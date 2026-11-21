"""Named checks for the runner (Phase 5), shared by unit, safety and mutation tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import mcp_types

from proveflow.proxy.cassette import canonical, digest
from proveflow.runner import transcript as transcript_module
from proveflow.runner.routing import RoutingError, RoutingTable
from proveflow.runner.transcript import (
    TranscriptError,
    TranscriptWriter,
    load_transcript,
)


def write_minimal_transcript(path: Path, *, cassettes: list[dict[str, Any]] | None = None) -> Path:
    w = TranscriptWriter(path)
    w.emit("trial_start", trial_id="t1", scenario_id="s1",
           provider={"name": "replay", "base_url": "https://example.invalid/v1", "model": "m"},
           parameters={"temperature": 0.0, "max_tokens": 16, "seed": None, "seed_sent": False},
           limits={}, budget_remaining=1000, servers=[])  # fmt: skip
    w.emit(
        "llm_request", turn=1, body={"model": "m", "messages": [{"role": "user", "content": "hi"}]}
    )
    w.emit("llm_response", turn=1, status=200,
           body={"choices": [{"message": {"role": "assistant", "content": "done"}}]},
           tokens_in=3, tokens_out=1)  # fmt: skip
    w.emit("final_answer", text="done")
    w.emit("trial_end", reason="final_answer", tokens_in=3, tokens_out=1, cassettes=cassettes or [])
    w.close()
    return path


def assert_altered_record_breaks_the_chain(tmp_path: Path) -> None:
    """Named check (D3): altering any recorded request or response, even with its own sha256
    recomputed, breaks the transcript's chain and the loader refuses it."""
    path = write_minimal_transcript(tmp_path / "t.jsonl")
    load_transcript(path)
    lines = path.read_bytes().splitlines()
    for index in (1, 2):  # the llm_request and the llm_response
        body = json.loads(lines[index])
        body["body"] = {"tampered": True}
        for recompute in (False, True):  # False: only the digest comparison catches it
            if recompute:
                body["sha256"] = digest(body)
            bad = list(lines)
            bad[index] = canonical(body).encode()
            tampered = tmp_path / f"tampered-{index}-{recompute}.jsonl"
            tampered.write_bytes(b"\n".join(bad) + b"\n")
            try:
                load_transcript(tampered)
            except TranscriptError:
                continue
            raise AssertionError(f"altered event {index} was accepted (recompute={recompute})")


def assert_mismatched_cassette_ref_refused(tmp_path: Path, cassette: Path) -> None:
    """Named check (D3): a transcript referencing a cassette whose final hash differs is
    refused by ``verify_cassette_refs``."""
    from proveflow.proxy.cassette import load_cassette

    final = load_cassette(cassette)[-1].sha256
    good = write_minimal_transcript(
        tmp_path / "good.jsonl",
        cassettes=[
            {"session_id": "s", "server": "x", "file": cassette.name, "final_sha256": final}
        ],
    )
    transcript_module.verify_cassette_refs(load_transcript(good), cassette.parent)
    wrong = "f" * 64 if final != "f" * 64 else "e" * 64
    bad = write_minimal_transcript(
        tmp_path / "bad.jsonl",
        cassettes=[
            {"session_id": "s", "server": "x", "file": cassette.name, "final_sha256": wrong}
        ],
    )
    try:
        transcript_module.verify_cassette_refs(load_transcript(bad), cassette.parent)
    except TranscriptError:
        return
    raise AssertionError("a transcript referencing a mismatched cassette was accepted")


def tool(name: str, desc: str = "d") -> mcp_types.Tool:
    return mcp_types.Tool(name=name, description=desc, input_schema={"type": "object"})


def assert_cross_server_collision_refused() -> None:
    """Named check (D4): the same name, or a look-alike, on two servers refuses to start and
    names both."""
    for a, b in (("fetch", "fetch"), ("send_email", "send_" + chr(0x200B) + "email"),
                 ("Fetch", "fetch")):  # fmt: skip
        try:
            RoutingTable.build([("web", "s-web", [tool(a)]), ("mail", "s-mail", [tool(b)])])
        except RoutingError as exc:
            if repr(a) not in str(exc) and repr(b) not in str(exc):
                raise AssertionError(f"refusal does not name the tools: {exc}") from None
            continue
        raise AssertionError(f"collision {a!r}/{b!r} across servers was routed")


# --- D7: every committed transcript is clean ---------------------------------------------

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "runner"
_BS = chr(92)
EVIDENCE = Path(__file__).resolve().parents[1] / "evidence" / "provider-runs"
LIST = "[]"  # a list position in a JSON path
EVENT_KINDS = ("trial_start", "llm_request", "llm_response", "tool_call", "tool_result",
               "final_answer", "limit_hit", "error", "trial_end")  # fmt: skip

# The ONLY values the D7 shape scan skips, as EXACT JSON paths (event kind, then keys; a
# list position is LIST). Compared by exact-set equality in tests/safety/test_transcript_layers.py,
# so adding a path is a visible diff. Not a pattern, not a prefix, not a key name.
# * the chain hashes: every event's envelope ``sha256`` / ``prev_sha256``, and each referenced
#   cassette's ``final_sha256``: public integrity values;
# * ``llm_response.body.id`` (R1): the provider's opaque completion id, the field that lets a
#   transcript be correlated with the provider's own logs in an audit. It is high-entropy, so
#   the shape scan would flag it. Nothing proveflow SENDS can land at this path: the API key
#   travels only in an HTTP header, and headers are never recorded. An error body
#   (``llm_response.body.error.message``) is a different path and stays scanned.
# * the provider's TOOL-CALL id (ruling after the first real run, Groq 2026-11-21): the same
#   class as the completion id, a provider-minted correlation identifier, not a secret. Real
#   Groq mints ``fc_<uuid>``, which the shape scan flags; the made-up id an earlier probe used
#   did not, which is why a guessed response shape is not evidence. It is MINTED at
#   TOOL_CALL_ID_MINTED and ECHOED by the runner at TOOL_CALL_ID_ECHOES. The echo paths are
#   values proveflow CONSTRUCTS, weaker ground than a recorded response field, so their
#   exclusion holds only together with ``tool_call_id_echo_problems`` (part of every D7 scan
#   below): each echoed value must equal an id an EARLIER llm_response minted.
TOOL_CALL_ID_MINTED = ("llm_response", "body", "choices", LIST, "message", "tool_calls", LIST, "id")
TOOL_CALL_ID_ECHOES = frozenset({
    ("llm_request", "body", "messages", LIST, "tool_calls", LIST, "id"),
    ("llm_request", "body", "messages", LIST, "tool_call_id"),
    ("tool_call", "call_id"),
    ("tool_result", "call_id"),
})  # fmt: skip
STRUCTURAL_PATHS = frozenset(
    {(kind, "sha256") for kind in EVENT_KINDS}
    | {(kind, "prev_sha256") for kind in EVENT_KINDS}
    | {("trial_end", "cassettes", LIST, "final_sha256"), ("llm_response", "body", "id")}
    | {TOOL_CALL_ID_MINTED}
    | TOOL_CALL_ID_ECHOES
)
UNMINTED = "carries a tool_call_id no response minted"


def _values_at(value: Any, path: tuple[str, ...], targets: frozenset[tuple[str, ...]]
               ) -> list[tuple[tuple[str, ...], Any]]:  # fmt: skip
    """Every value (of any type) sitting at one of the exact ``targets`` paths."""
    if path in targets:
        return [(path, value)]
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in _values_at(v, (*path, str(k)), targets)]
    if isinstance(value, list):
        return [s for v in value for s in _values_at(v, (*path, LIST), targets)]
    return []


def tool_call_id_echo_problems(events: list[Any]) -> list[str]:
    """The runner may only ECHO tool-call ids the provider minted: every value at a
    TOOL_CALL_ID_ECHOES path must equal a value at TOOL_CALL_ID_MINTED in an llm_response
    EARLIER in the same transcript. An id no response produced is a bug, and the D7 path
    exclusion must not hide it."""
    minted: set[Any] = set()
    problems: list[str] = []
    for e in events:
        body = e.model_dump(mode="json")
        echoes = [s for k, v in body.items()
                  for s in _values_at(v, (e.kind, k), TOOL_CALL_ID_ECHOES)]  # fmt: skip
        for json_path, value in echoes:
            if not isinstance(value, str) or value not in minted:
                who = "request" if e.kind == "llm_request" else e.kind
                problems.append(f"seq {e.seq} {'.'.join(json_path)}: {who} {UNMINTED}")
        minted |= {v for k, x in body.items()
                   for _, v in _values_at(x, (e.kind, k), frozenset({TOOL_CALL_ID_MINTED}))
                   if isinstance(v, str)}  # fmt: skip
    return problems


def committed_transcripts() -> list[Path]:
    return sorted(FIXTURES.rglob("transcript.jsonl"))


def _strings(value: Any, path: tuple[str, ...]) -> list[tuple[tuple[str, ...], str]]:
    """Every string value and dict key with its JSON path; a path in STRUCTURAL_PATHS is
    skipped (its value only; nothing below or beside it)."""
    if path in STRUCTURAL_PATHS:
        return []
    if isinstance(value, str):
        return [(path, value)]
    if isinstance(value, dict):
        out = [(path, str(k)) for k in value]
        for k, v in value.items():
            out += _strings(v, (*path, str(k)))
        return out
    if isinstance(value, list):
        return [s for v in value for s in _strings(v, (*path, LIST))]
    return []


def trial_needle_values(scenario_path: Path) -> set[str]:
    """The trial's own needles by EXACT value (Q1): the scenario's canary, and every honey
    value of every twin the scenario generates. Never a pattern."""
    from proveflow.runner.scenario import Scenario
    from proveflow.twin.generator import generate_twin

    sc = Scenario.model_validate_json(scenario_path.read_text(encoding="utf-8"))
    values = {sc.attack.canary} if sc.attack else set()
    for s in sc.servers:
        values |= {h.value for h in generate_twin(s.name, s.tools, seed=s.seed).honey}
    return values


def transcript_problems(path: Path) -> list[str]:
    """Every reason a committed transcript is not clean (D7)."""
    import getpass
    import re
    import socket

    from proveflow.core.honey import t4_violations
    from proveflow.core.redact_rules import secret_spans
    from twinchecks import PROVIDER_PREFIXES

    problems: list[str] = []
    events = load_transcript(path)  # chain, canonical form, models
    needles = trial_needle_values(path.parent / "scenario.json")
    machine = [n for n in (getpass.getuser(), socket.gethostname()) if len(n) >= 3]
    path_like = re.compile(
        r"(?<![A-Za-z0-9])[A-Za-z]:[" + re.escape(_BS) + r"/](?!/)"
        r"|/home/|/Users/|"
        + re.escape(_BS + "Users" + _BS)
        + r"|AppData|pytest-of-|proveflow-twin-"
    )
    for e in events:
        body = e.model_dump(mode="json")
        strings = [s for k, v in body.items() for s in _strings(v, (e.kind, k))]
        for json_path, text in strings:
            where = f"{path.parent.name} seq {e.seq} {'.'.join(json_path)}"
            if path_like.search(text):
                problems.append(f"{where}: absolute path or temp dir")
            if any(m.lower() in text.lower() for m in machine):
                problems.append(f"{where}: user or host name")
            if t4_violations(text):
                problems.append(f"{where}: T4 {t4_violations(text)}")
            low = text.lower()
            for p in PROVIDER_PREFIXES:
                if re.search(r"(?<![a-z0-9])" + re.escape(p.lower()), low):
                    problems.append(f"{where}: provider prefix {p!r}")
            for a, b in secret_spans(text):
                span = residue = text[a:b]
                for v in needles:
                    residue = residue.replace(v, "")
                # Allowed ONLY when the span holds a needle (exact value) and nothing
                # secret-shaped is left once every needle is removed (Q1: never a pattern).
                if residue == span or secret_spans(residue):
                    problems.append(f"{where}: secret-shaped text {span[:12]!r}...")
    # The request-side tool-call id exclusion is earned here, never assumed.
    problems += [f"{path.parent.name} {p}" for p in tool_call_id_echo_problems(events)]
    return problems


def assert_committed_transcripts_are_clean() -> None:
    """Named check (D7): every committed transcript passes the redaction check (beyond the
    trial's own needles, by exact value), T4, no provider prefix, no path or machine detail."""
    paths = committed_transcripts()
    if not paths:
        raise AssertionError("no committed transcripts found; check is vacuous")
    problems = [p for path in paths for p in transcript_problems(path)]
    if problems:
        raise AssertionError("committed transcript not clean: " + "; ".join(problems[:10]))


# --- replay helpers + end-to-end named checks ----------------------------------------------

AUTHORED = {"name": "authored", "base_url": "https://example.invalid/v1", "model": "authored",
            "api_key_env": "PF_AUTHORED_UNUSED", "send_seed": False}  # fmt: skip
SYNTHETIC_TIMINGS_NOTE = "SYNTHETIC test timings (written by the test, not measured)"


def fixture_scenario(name: str) -> Any:
    from proveflow.runner.scenario import Scenario

    return Scenario.model_validate_json((_fixture_dir(name) / "scenario.json").read_text("utf-8"))


def staged_recording(tmp_path: Path, name: str, *, timings: bool = True) -> Path:
    """Copy a committed transcript into tmp_path; optionally add a SYNTHETIC timings
    sidecar bound to it (committed fixtures carry no machine timings)."""
    import shutil

    rec = tmp_path / "recorded"
    rec.mkdir(exist_ok=True)
    path = rec / f"{name}.transcript.jsonl"
    shutil.copyfile(_fixture_dir(name) / "transcript.jsonl", path)
    if timings:
        last = load_transcript(path)[-1].sha256
        (rec / f"{name}.timings.json").write_text(json.dumps(
            {"_note": SYNTHETIC_TIMINGS_NOTE, "transcript_sha256": last, "latency_ms": 42.0}
        ), encoding="utf-8")  # fmt: skip
    return path


def replay(tmp_path: Path, name: str, **kwargs: Any) -> Any:
    import os

    import anyio

    from proveflow.config import ProviderConfig
    from proveflow.proxy import policy as policy_module
    from proveflow.runner.trial import replay_trial

    recorded = staged_recording(tmp_path, name, timings=kwargs.pop("timings", True))
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)

    async def go() -> Any:
        return await replay_trial(
            kwargs.pop("scenario", fixture_scenario(name)), recorded=recorded, trial_id=name,
            provider=ProviderConfig(**AUTHORED), temperature=0.0, seed=0, out_dir=out,
            twin_dir=policy_module.TWIN_ROOT, parent_env=dict(os.environ), **kwargs,
        )  # fmt: skip

    return anyio.run(go)


def assert_calls_landed_in_their_own_cassettes(result: Any) -> None:
    """Named check (D4): one agent, two real proxies: every tool call the transcript records
    for server S is a tools/call in S's cassette and in no other cassette."""
    from proveflow.proxy.cassette import load_cassette

    events = load_transcript(result.transcript)
    by_server: dict[str, list[str]] = {}
    for path in result.cassettes:
        server = path.name.split(".")[1]
        by_server[server] = [
            e.message["params"]["name"] for e in load_cassette(path)
            if e.kind == "agent_request" and e.message.get("method") == "tools/call"
        ]  # fmt: skip
    expected: dict[str, list[str]] = {s: [] for s in by_server}
    for e in events:
        if e.kind == "tool_call":
            expected.setdefault(e.server, []).append(e.tool)
    if len(by_server) < 2:
        raise AssertionError("check is vacuous: fewer than two proxies")
    if by_server != expected:
        raise AssertionError(
            f"calls did not land in their own cassettes: {by_server} != {expected}"
        )


def runner_authored_leaks(transcript: Path, attack: Any) -> list[str]:
    """INDEPENDENT of runner.validity (so a removed runtime guard is still caught): the attack
    payload or canary in any system/user message the runner sent."""
    out: list[str] = []
    for e in load_transcript(transcript):
        if e.kind != "llm_request":
            continue
        for m in e.body.get("messages", []):
            if m.get("role") in ("system", "user"):
                text = json.dumps(m.get("content"))
                for label, v in (("payload", attack.payload.text), ("canary", attack.canary)):
                    if v in text or json.dumps(v)[1:-1] in text:
                        out.append(f"turn {e.turn}: {label} in a {m['role']} message")
    return out


def assert_injection_only_through_tool_results(tmp_path: Path) -> None:
    """Named check (F9): in the attacked trial, the payload and the canary appear in NO
    message the runner authored, and reach the model only inside tool results."""
    from proveflow.runner.llm import ReplayMismatch
    from proveflow.runner.validity import InvalidTrial

    scenario = fixture_scenario("cross_server_exfil")
    try:
        result = replay(tmp_path, "cross_server_exfil")
        transcript = result.transcript
    except (InvalidTrial, ReplayMismatch):
        transcript = tmp_path / "out" / "cross_server_exfil.transcript.jsonl"
    leaks = runner_authored_leaks(transcript, scenario.attack)
    if leaks:
        raise AssertionError("attack text in a runner-authored message: " + "; ".join(leaks))
    results = [e for e in load_transcript(transcript) if e.kind == "tool_result"]
    if not any(scenario.attack.canary in e.content for e in results):
        raise AssertionError("check is vacuous: the payload never arrived through a tool")


# --- caps and budget (D6) ------------------------------------------------------------------


def capped_trial(tmp_path: Path, limits: Any, *, completion_tokens: int | None = None) -> Any:
    """Replay the attacked fixture under ``limits``. With ``completion_tokens`` the real
    HttpChatClient is driven through httpx2.MockTransport (socket-free, R-B1) serving the
    fixture's RECORDED response bodies with that usage, so the out-token cap can be reached
    (a tighter out cap clamps max_tokens, which strict replay would rightly call a mismatch)."""
    import os

    import anyio
    import httpx2

    from proveflow.config import ProviderConfig
    from proveflow.proxy import policy as policy_module
    from proveflow.runner.limits import RunBudget
    from proveflow.runner.llm import HttpChatClient, ReplayChatClient
    from proveflow.runner.trial import run_trial

    recorded = staged_recording(tmp_path, "cross_server_exfil")
    out = tmp_path / "out"
    out.mkdir()
    llm: Any = ReplayChatClient(load_transcript(recorded))
    if completion_tokens is not None:
        bodies = [e.body for e in load_transcript(recorded) if e.kind == "llm_response"]

        def handler(request: httpx2.Request) -> httpx2.Response:
            body = dict(bodies.pop(0))
            body["usage"] = {"prompt_tokens": 10, "completion_tokens": completion_tokens}
            return httpx2.Response(200, json=body)

        llm = HttpChatClient(ProviderConfig(**AUTHORED), environ={"PF_AUTHORED_UNUSED": "x"},
                             transport=httpx2.MockTransport(handler))  # fmt: skip

    async def go() -> Any:
        return await run_trial(
            fixture_scenario("cross_server_exfil"), trial_id="capped", llm=llm,
            provider=ProviderConfig(**AUTHORED), temperature=0.0, seed=0, out_dir=out,
            twin_dir=policy_module.TWIN_ROOT, budget=RunBudget(), parent_env=dict(os.environ),
            limits=limits,
        )  # fmt: skip

    return anyio.run(go)


def assert_cap_fires(
    tmp_path: Path, limits: Any, limit: str, completion_tokens: int | None = None
) -> None:
    """Named check (D6): the cap stops the trial and is recorded as a limit_hit."""
    r = capped_trial(tmp_path, limits, completion_tokens=completion_tokens)
    hits = [e.limit for e in load_transcript(r.transcript) if e.kind == "limit_hit"]
    if r.outcome.reason != f"limit:{limit}" or hits != [limit]:
        raise AssertionError(f"cap {limit} did not fire: {r.outcome.reason}, {hits}")


def assert_budget_refuses_a_trial_it_cannot_cover() -> None:
    """Named check (D6): reserve refuses when the remaining budget is below one trial's
    MAXIMUM, before any spend; a trial is never started on a partial budget."""
    from proveflow.runner.limits import BudgetExhausted, RunBudget, TrialLimits

    lim = TrialLimits(max_tokens_in=100, max_tokens_out=20)
    budget = RunBudget(total=239)
    budget.reserve(lim)
    budget.spend(120)
    try:
        budget.reserve(lim)  # 119 left < 120
    except BudgetExhausted:
        return
    raise AssertionError("budget allowed a trial it cannot cover")


# --- D1: the API key never reaches an artifact ----------------------------------------------

PLANTED_KEY = "gsk_PLANTEDproviderKey0123456789abcdef"


def run_with_planted_key(tmp_path: Path) -> list[Path]:
    import os

    import anyio
    import httpx2

    from proveflow.config import ProviderConfig
    from proveflow.oracle.matcher import match  # noqa: F401
    from proveflow.proxy import policy as policy_module
    from proveflow.runner.limits import RunBudget
    from proveflow.runner.llm import HttpChatClient
    from proveflow.runner.trial import run_trial

    """The attacked fixture through the REAL HttpChatClient (MockTransport, socket-free),
    the key planted in the environment. Returns every artifact the trial wrote."""
    recorded = staged_recording(tmp_path, "cross_server_exfil")
    bodies = [e.body for e in load_transcript(recorded) if e.kind == "llm_response"]  # type: ignore[attr-defined]

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.headers["Authorization"] == f"Bearer {PLANTED_KEY}"
        return httpx2.Response(200, json=bodies.pop(0))

    provider = ProviderConfig(**{**AUTHORED, "api_key_env": "PF_PLANTED_KEY"})
    client = HttpChatClient(provider, environ={"PF_PLANTED_KEY": PLANTED_KEY},
                            transport=httpx2.MockTransport(handler))  # fmt: skip
    out = tmp_path / "out"
    out.mkdir()

    async def go() -> object:
        return await run_trial(
            fixture_scenario("cross_server_exfil"), trial_id="keyed", llm=client,
            provider=provider, temperature=0.0, seed=0, out_dir=out,
            twin_dir=policy_module.TWIN_ROOT, budget=RunBudget(),
            parent_env={**os.environ, "PF_PLANTED_KEY": PLANTED_KEY},
        )  # fmt: skip

    result = anyio.run(go)
    report = out / "verdict.json"
    report.write_text(
        json.dumps(
            {
                "verdict": result.verdict.model_dump(mode="json"),  # type: ignore[attr-defined]
                "findings": result.findings.model_dump(mode="json"),
            }
        )
    )  # type: ignore[attr-defined]
    return sorted(p for p in out.iterdir() if p.is_file())


def assert_no_api_key_in_any_artifact(tmp_path: Path) -> None:
    """Named check (D1): the planted key appears in no transcript, cassette, timings file or
    report, in ANY of the matcher's 10 encodings."""
    from proveflow.oracle.matcher import match

    artifacts = run_with_planted_key(tmp_path)
    if len(artifacts) < 4:
        raise AssertionError(f"check is vacuous: artifacts {[a.name for a in artifacts]}")
    for path in artifacts:
        text = path.read_text(encoding="utf-8")
        if match(PLANTED_KEY, text).found or match(PLANTED_KEY, {"v": text}).found:
            raise AssertionError(f"API key found in {path.name}")


# --- Q5: the manual run never spends without --yes -----------------------------------------


class _Spent(Exception):
    pass


def manual_config(tmp_path: Path) -> Path:
    lines = ["[[provider]]", 'name = "groq"', 'base_url = "https://api.groq.com/openai/v1"',
             'model = "some-model"', 'api_key_env = "PF_MANUAL_KEY"', ""]  # fmt: skip
    path = tmp_path / "proveflow.toml"
    path.write_text(chr(10).join(lines), encoding="utf-8")
    return path


def assert_no_spend_without_yes(tmp_path: Path, monkeypatch: Any, capsys: Any) -> None:
    """Named check (Q5): without --yes the cost line is printed, the exit code is 2, no trial
    starts and no output directory is created. ``run_trial`` is a spy that aborts."""
    from proveflow.runner import manual, trial

    calls: list[object] = []

    async def spy(*args: Any, **kwargs: Any) -> Any:
        calls.append(args)
        raise _Spent

    monkeypatch.setattr(trial, "run_trial", spy)
    out = tmp_path / "out"
    argv = ["--scenario", str(FIXTURES / "clean_utility" / "scenario.json"),
            "--config", str(manual_config(tmp_path)), "--provider", "groq",
            "--out-dir", str(out)]  # fmt: skip
    code: object = 0
    try:
        manual.main(argv)
    except SystemExit as exc:
        code = exc.code
    except _Spent:
        code = "spent"
    err = capsys.readouterr().err
    if code != manual.EXIT_NOT_CONFIRMED or calls or out.exists():
        raise AssertionError(f"spent without --yes (exit {code}, calls {len(calls)})")
    if "up to 120000 tokens in + 8000 out = 128000" not in err or "some-model" not in err:
        raise AssertionError(f"cost line missing: {err!r}")


def assert_existing_out_dir_is_refused_cleanly(tmp_path: Path, monkeypatch: Any,
                                               capsys: Any) -> None:  # fmt: skip
    """Named check: --yes with an existing --out-dir prints one refusal line and exits 2. No
    traceback, no trial (``run_trial`` is a spy that aborts), and the old output untouched."""
    from proveflow.runner import manual, trial

    calls: list[object] = []

    async def spy(*args: Any, **kwargs: Any) -> Any:
        calls.append(args)
        raise _Spent

    monkeypatch.setattr(trial, "run_trial", spy)
    out = tmp_path / "run1"
    out.mkdir()
    (out / "earlier.transcript.jsonl").write_bytes(b"earlier run\n")
    argv = ["--scenario", str(FIXTURES / "clean_utility" / "scenario.json"),
            "--config", str(manual_config(tmp_path)), "--provider", "groq",
            "--out-dir", str(out), "--yes"]  # fmt: skip
    try:
        code: object = manual.main(argv)
    except _Spent:
        raise AssertionError("a trial started over an existing --out-dir") from None
    except FileExistsError as exc:
        raise AssertionError(f"raw traceback instead of a refusal: {exc!r}") from None
    err = capsys.readouterr().err
    if code != manual.EXIT_OUT_DIR_EXISTS or code != 2 or calls:
        raise AssertionError(f"existing --out-dir not refused (exit {code}, calls {len(calls)})")
    if "refusing to overwrite: --out-dir 'run1' already exists" not in err or "Traceback" in err:
        raise AssertionError(f"refusal line missing: {err!r}")
    if sorted(p.name for p in out.iterdir()) != ["earlier.transcript.jsonl"]:
        raise AssertionError("the earlier run's output was touched")
    if (out / "earlier.transcript.jsonl").read_bytes() != b"earlier run\n":
        raise AssertionError("the earlier run's output was changed")


# --- two independent layers: D7 catches SHAPES, the exact-key check catches THE KEY ----------


def exact_key_hits(files: list[Path], key: str) -> list[str]:
    """The exact-value key check: every file whose text contains ``key`` in ANY of the
    matcher's 10 encodings. It has no notion of JSON paths, so no D7 path exclusion can ever
    narrow it. This is the layer that protects a real key; it prints file names only."""
    from proveflow.oracle.matcher import match

    return [f.name for f in files
            if match(key, f.read_text(encoding="utf-8")).found
            or match(key, {"v": f.read_text(encoding="utf-8")}).found]  # fmt: skip


def transcript_with_key_at_body_id(tmp_path: Path, key: str) -> Path:
    """A crafted transcript whose only copy of ``key`` sits at llm_response.body.id, the
    path D7 skips (R1), plus a scenario.json so the D7 scan can run on it."""
    import shutil

    run = tmp_path / "crafted"
    run.mkdir()
    shutil.copyfile(FIXTURES / "clean_utility" / "scenario.json", run / "scenario.json")
    w = TranscriptWriter(run / "transcript.jsonl")
    w.emit("trial_start", trial_id="t", scenario_id="clean_utility",
           provider={"name": "p", "base_url": "https://example.invalid/v1", "model": "m"},
           parameters={"temperature": 0.0, "max_tokens": 8, "seed": None, "seed_sent": False},
           limits={}, budget_remaining=1, servers=[])  # fmt: skip
    w.emit("llm_request", turn=1, body={"model": "m", "messages": []})
    message = {"role": "assistant", "content": "ok"}
    w.emit("llm_response", turn=1, status=200, tokens_in=1, tokens_out=1,
           body={"id": key, "choices": [{"message": message}]})  # fmt: skip
    w.emit("final_answer", text="ok")
    w.emit("trial_end", reason="final_answer", tokens_in=1, tokens_out=1, cassettes=[])
    w.close()
    return run / "transcript.jsonl"


def assert_exact_key_check_sees_past_the_path_exclusion(tmp_path: Path) -> None:
    """Named check (R1): the planted key at llm_response.body.id is invisible to D7 BY
    DESIGN (the path is excluded) and still caught by the exact-key check."""
    key = PLANTED_KEY
    transcript = transcript_with_key_at_body_id(tmp_path, key)
    shape_problems = [p for p in transcript_problems(transcript) if "body.id" in p]
    if shape_problems:
        raise AssertionError(f"premise broken: D7 scanned an excluded path: {shape_problems}")
    if exact_key_hits([transcript], key) != [transcript.name]:
        raise AssertionError("exact-key check missed the key at an excluded D7 path")


def assert_error_body_stays_scanned(tmp_path: Path) -> None:
    """Named check (R1): a secret-shaped value in llm_response.body.error.message is flagged;
    only the exact path llm_response.body.id is excluded."""
    run = tmp_path / "errbody"
    run.mkdir()
    import shutil

    shutil.copyfile(FIXTURES / "clean_utility" / "scenario.json", run / "scenario.json")
    w = TranscriptWriter(run / "transcript.jsonl")
    w.emit("llm_response", turn=1, status=200, tokens_in=1, tokens_out=1,
           body={"error": {"message": f"bad key {PLANTED_KEY}"}})  # fmt: skip
    w.close()
    problems = [p for p in transcript_problems(run / "transcript.jsonl")
                if "llm_response.body.error.message" in p]  # fmt: skip
    if not problems:
        raise AssertionError("a secret-shaped value in body.error.message was not flagged")


# SYNTHETIC ids in the shape real Groq mints (fc_<uuid>); written by hand for these tests.
MINTED_ID = "fc_0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
NEVER_MINTED_ID = "fc_9f8e7d6c-5b4a-4c3d-8e2f-1a0b9c8d7e6f"


def transcript_with_echo(tmp_path: Path, echoed: str) -> Path:
    """A complete crafted transcript, a README and a scenario.json: one response mints
    MINTED_ID, tool_call/tool_result carry it, and the next request echoes ``echoed`` as the
    assistant's tool_calls[].id and the tool message's tool_call_id."""
    import shutil

    tmp_path.mkdir(parents=True)
    shutil.copyfile(FIXTURES / "clean_utility" / "scenario.json", tmp_path / "scenario.json")
    (tmp_path / "README.md").write_bytes(b"A crafted transcript for a test.\n")
    call = {"id": MINTED_ID, "type": "function",
            "function": {"name": "read_text_file", "arguments": "{}"}}  # fmt: skip
    echo = {**call, "id": echoed}
    w = TranscriptWriter(tmp_path / "transcript.jsonl")
    w.emit("trial_start", trial_id="t", scenario_id="clean_utility",
           provider={"name": "p", "base_url": "https://example.invalid/v1", "model": "m"},
           parameters={"temperature": 0.0, "max_tokens": 8, "seed": None, "seed_sent": False},
           limits={}, budget_remaining=1, servers=[])  # fmt: skip
    user = {"role": "user", "content": "go"}
    w.emit("llm_request", turn=1, body={"model": "m", "messages": [user]})
    w.emit("llm_response", turn=1, status=200, tokens_in=1, tokens_out=1,
           body={"choices": [{"message": {"role": "assistant", "content": None,
                                          "tool_calls": [call]}}]})  # fmt: skip
    w.emit("tool_call", turn=1, call_id=MINTED_ID, tool="read_text_file", server="filesystem",
           session_id="t.filesystem", arguments={})  # fmt: skip
    w.emit("tool_result", call_id=MINTED_ID, content="ok", is_error=False)
    w.emit("llm_request", turn=2, body={"model": "m", "messages": [
        user,
        {"role": "assistant", "content": None, "tool_calls": [echo]},
        {"role": "tool", "tool_call_id": echoed, "content": "ok"}]})  # fmt: skip
    w.emit("llm_response", turn=2, status=200, tokens_in=1, tokens_out=1,
           body={"choices": [{"message": {"role": "assistant", "content": "done"}}]})  # fmt: skip
    w.emit("final_answer", text="done")
    w.emit("trial_end", reason="final_answer", tokens_in=2, tokens_out=2, cassettes=[])
    w.close()
    return tmp_path / "transcript.jsonl"


def assert_unminted_tool_call_id_is_caught(tmp_path: Path) -> None:
    """Named check (ruling after the first real run): a request that echoes a tool-call id
    no response minted fails the EVIDENCE check, although D7 skips both request paths. Only
    the echo check can catch it: the shape layer is silent there by design."""
    from proveflow.core.redact_rules import secret_spans

    if not secret_spans(NEVER_MINTED_ID):
        raise AssertionError("premise broken: the synthetic id is not secret-shaped")
    good = evidence_problems(transcript_with_echo(tmp_path / "echo", MINTED_ID))
    if good:
        raise AssertionError(f"a correct echo was refused: {good}")
    bad = evidence_problems(transcript_with_echo(tmp_path / "unminted", NEVER_MINTED_ID))
    others = [p for p in bad if UNMINTED not in p]
    if others:
        raise AssertionError(f"premise broken: D7 flagged more than the echo: {others}")
    flagged = {p.split(": ")[0].split(" ")[-1] for p in bad if f"request {UNMINTED}" in p}
    expected = {".".join(p) for p in TOOL_CALL_ID_ECHOES if p[0] == "llm_request"}
    if flagged != expected:
        raise AssertionError(f"request {UNMINTED}, and the evidence check passed it "
                             f"(flagged {sorted(flagged)}, want {sorted(expected)})")  # fmt: skip


def assert_an_echo_before_its_mint_is_refused(tmp_path: Path) -> None:
    """Named check: the minting response must come EARLIER. The correct transcript with its
    turn-2 request moved before the turn-1 response carries an id nothing had minted yet."""
    events = load_transcript(transcript_with_echo(tmp_path / "order", MINTED_ID))
    kinds = [e.kind for e in events]
    if tool_call_id_echo_problems(events):
        raise AssertionError("premise broken: the correct order was refused")
    request2 = max(i for i, k in enumerate(kinds) if k == "llm_request")
    response1 = kinds.index("llm_response")
    early = [*events[:response1], events[request2], *events[response1:request2],
             *events[request2 + 1:]]  # fmt: skip
    if not [p for p in tool_call_id_echo_problems(early) if f"request {UNMINTED}" in p]:
        raise AssertionError("an echo before the response that minted it was accepted")


def assert_every_constructed_exclusion_is_echo_checked() -> None:
    """Named check: every D7-excluded path in an event proveflow CONSTRUCTS (anything but a
    recorded llm_response, and not a chain hash) is an echo path the echo check verifies.
    A constructed path excluded from D7 without that check would hide whatever lands there."""
    hashes = ({(k, "sha256") for k in EVENT_KINDS} | {(k, "prev_sha256") for k in EVENT_KINDS}
              | {("trial_end", "cassettes", LIST, "final_sha256")})  # fmt: skip
    constructed = {p for p in STRUCTURAL_PATHS - hashes if p[0] != "llm_response"}
    if constructed != set(TOOL_CALL_ID_ECHOES):
        raise AssertionError(f"D7-excluded constructed paths not echo-checked: "
                             f"{sorted(constructed - set(TOOL_CALL_ID_ECHOES))}")  # fmt: skip
    if TOOL_CALL_ID_MINTED not in STRUCTURAL_PATHS:
        raise AssertionError("the minting path is not excluded, the echoes are")


# --- R2: committed real-run transcripts are EVIDENCE, not replay fixtures ---------------------


def evidence_transcripts(root: Path = EVIDENCE) -> list[Path]:
    return sorted(root.rglob("transcript.jsonl")) if root.is_dir() else []


def evidence_problems(transcript: Path) -> list[str]:
    """The evidence check: the hash CHAIN (load_transcript: models, seq, chain, canonical
    form) and the D7 shape scan over the file. It NEVER resolves cassette references: a
    real run's cassettes hold absolute interpreter and twin paths and are not committed."""
    problems: list[str] = []
    try:
        events = load_transcript(transcript)
    except TranscriptError as exc:
        return [f"{transcript.parent.name}: {exc}"]
    from proveflow.runner.transcript import is_complete_transcript

    if not is_complete_transcript(events):
        problems.append(f"{transcript.parent.name}: not a complete transcript")
    if not (transcript.parent / "README.md").is_file():
        problems.append(f"{transcript.parent.name}: no README.md stating what this run is")
    return problems + transcript_problems(transcript)


def assert_evidence_runs_are_clean(root: Path = EVIDENCE) -> int:
    """Named check (R2): every committed real-run transcript passes chain + D7. Returns how
    many were checked (one since the first manual run, 2026-11-21)."""
    runs = evidence_transcripts(root)
    problems = [p for t in runs for p in evidence_problems(t)]
    if problems:
        raise AssertionError("evidence run not clean: " + "; ".join(problems[:10]))
    return len(runs)


EVIDENCE_REPLAY_TOOL = "replay_evidence"  # the dev-only module in tools/, by name only


def evidence_replay_reach(root: Path) -> list[str]:
    """Every .py file under ``root`` that imports the dev-only evidence replay tool, or
    names its script file in a string (a subprocess or runpy call). The twin generator's
    output may change legitimately, so a committed replay of evidence would break and push
    toward weakening it or deleting real evidence; the tool is run by hand only."""
    import ast

    script = EVIDENCE_REPLAY_TOOL + ".py"
    hits: list[str] = []
    for path in sorted(root.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            mods: list[str] = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                mods = [node.module or ""] + [a.name for a in node.names]
            reached = any(m.split(".")[-1] == EVIDENCE_REPLAY_TOOL for m in mods) or (
                isinstance(node, ast.Constant) and isinstance(node.value, str)
                and script in node.value
            )  # fmt: skip
            if reached:
                hits.append(path.relative_to(root).as_posix())
    return sorted(set(hits))


def assert_no_test_reaches_the_evidence_replay(root: Path | None = None) -> None:
    """Named check: no test imports or runs the evidence replay tool, and it is not
    importable from the test path."""
    import importlib.util

    root = root or Path(__file__).resolve().parent
    if importlib.util.find_spec(EVIDENCE_REPLAY_TOOL) is not None:
        raise AssertionError("the evidence replay tool is importable from the tests")
    hits = evidence_replay_reach(root)
    if hits:
        raise AssertionError(f"a test reaches the evidence replay tool: {hits}")


def _fixture_dir(name: str) -> Path:
    """Replay fixtures are addressed by a plain directory name under FIXTURES only."""
    path = (FIXTURES / name).resolve()
    if "/" in name or chr(92) in name or name in ("", ".", "..") or path.parent != FIXTURES:
        raise ValueError(f"not a replay fixture name: {name!r}")
    if not (path / "transcript.jsonl").is_file():
        raise ValueError(f"no replay fixture named {name!r}")
    return path


# --- R4's ordering precondition: the agent never overlaps tool calls (Phase 3b) ------------


def _drive_agent(
    tmp_path: Path, tool_calls: list[dict[str, Any]]
) -> tuple[Any, list[Any], dict[str, int]]:
    """Run ``run_agent`` for one response carrying ``tool_calls`` then a final answer. The
    provider side is HttpChatClient over httpx2.MockTransport serving two hand-written bodies
    (socket-free); the proxies are fakes for sessions ``s-a`` (tool read_a) and ``s-b``
    (tool read_b) that count calls in flight and yield to the event loop inside every call,
    so concurrency, if any, shows. Returns (outcome, transcript event dicts, counters)."""
    import anyio
    import httpx2

    from proveflow.config import ProviderConfig
    from proveflow.runner.agent import run_agent
    from proveflow.runner.limits import TrialLimits
    from proveflow.runner.llm import HttpChatClient
    from proveflow.runner.routing import RoutingTable

    usage = {"prompt_tokens": 1, "completion_tokens": 1}
    assistant = {"role": "assistant", "content": None, "tool_calls": tool_calls}
    bodies = [
        {"choices": [{"message": assistant}], "usage": usage},
        {"choices": [{"message": {"role": "assistant", "content": "done"}}], "usage": usage},
    ]

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=bodies.pop(0))

    llm = HttpChatClient(ProviderConfig(**AUTHORED), environ={"PF_AUTHORED_UNUSED": "x"},
                         transport=httpx2.MockTransport(handler))  # fmt: skip
    state = {"in_flight": 0, "max": 0, "calls": 0}

    class _Client:
        async def call_tool(self, name: str, arguments: Any) -> Any:
            state["in_flight"] += 1
            state["calls"] += 1
            state["max"] = max(state["max"], state["in_flight"])
            for _ in range(3):
                await anyio.sleep(0)
            state["in_flight"] -= 1
            return mcp_types.CallToolResult(content=[mcp_types.TextContent(type="text", text="ok")])

    class _Proxy:
        client = _Client()

    routing = RoutingTable.build([("a", "s-a", [tool("read_a")]), ("b", "s-b", [tool("read_b")])])
    writer = TranscriptWriter(tmp_path / "agent.jsonl")

    async def go() -> Any:
        return await run_agent(
            llm=llm, model="m", temperature=0.0, seed=None, system_prompt="s", task="t",
            routing=routing, proxies={"s-a": _Proxy(), "s-b": _Proxy()},  # type: ignore[dict-item]
            limits=TrialLimits(), record=writer,
        )  # fmt: skip

    out = anyio.run(go)
    writer.close()
    events = [e.model_dump(mode="json") for e in load_transcript(tmp_path / "agent.jsonl")]
    return out, events, state


def _call(i: int, name: str, arguments: str = "{}") -> dict[str, Any]:
    return {"id": f"call_{i}", "type": "function",
            "function": {"name": name, "arguments": arguments}}  # fmt: skip


def assert_agent_never_overlaps_tool_calls(tmp_path: Path) -> None:
    """Named check: when the model asks for several tool calls in ONE response, the agent runs
    them one at a time, so no call starts before the previous one returned, and the transcript
    records each result before the next call. The oracle's R4 orders a trial's cassettes by
    this transcript and pairs the k-th call of a session with the k-th tools/call in its
    cassette (docs/ORACLE.md); concurrent calls would make that pairing a guess."""
    from proveflow.oracle.rules import transcript_calls

    calls = [_call(i, n) for i, n in enumerate(("read_a", "read_b", "read_a"), start=1)]
    out, events, state = _drive_agent(tmp_path, calls)
    if out.tool_calls != 3 or state["calls"] != 3:
        raise AssertionError(f"premise broken: {state['calls']} of 3 tool calls reached a proxy")
    if state["max"] != 1:
        raise AssertionError(f"overlapping tool calls: {state['max']} in flight at once")
    try:
        per = transcript_calls(events)
    except ValueError as exc:
        raise AssertionError(f"overlapping tool calls in the transcript: {exc}") from None
    order = {sid: [name for _, name in calls] for sid, calls in per.items()}
    if order != {"s-a": ["read_a", "read_a"], "s-b": ["read_b"]}:
        raise AssertionError(f"the transcript's per-session call order is wrong: {per}")


def assert_unsent_calls_name_no_session(tmp_path: Path) -> None:
    """Named check (the ``-`` sentinel): a tool call the runner never sends (an unknown tool,
    invalid JSON arguments, or arguments that are not an object) names server and session
    ``-`` in the transcript, reaches no proxy, and gets the runner's own error result; a
    sent call names its proxy. R4 pairs a session's tool_call events with that session's
    cassette one to one, so an unsent call naming a real session would break the pairing."""
    calls = [_call(1, "nope"), _call(2, "read_a", "{not json"), _call(3, "read_b", "[1, 2]"),
             _call(4, "read_a")]  # fmt: skip
    _, events, state = _drive_agent(tmp_path, calls)
    named = [(e["server"], e["session_id"]) for e in events if e["kind"] == "tool_call"]
    if named != [("-", "-"), ("-", "-"), ("-", "-"), ("a", "s-a")]:
        raise AssertionError(f"an unsent tool call names a proxy session: {named}")
    if state["calls"] != 1:
        raise AssertionError(f"{state['calls']} calls reached a proxy; only the valid one may")
    refused = [e["content"] for e in events if e["kind"] == "tool_result" and e["is_error"]]
    if len(refused) != 3 or not all(c.startswith("proveflow runner: ") for c in refused):
        raise AssertionError(f"unsent calls did not get the runner's error result: {refused}")
