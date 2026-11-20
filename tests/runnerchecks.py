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
# Chain hashes are public integrity values, not secrets: the envelope hashes and each
# referenced cassette's final hash.
_ENVELOPE_HASHES = frozenset({"sha256", "prev_sha256", "final_sha256"})


def committed_transcripts() -> list[Path]:
    return sorted(FIXTURES.rglob("transcript.jsonl"))


def _strings(value: Any, key: str = "") -> list[tuple[str, str]]:
    if isinstance(value, str):
        return [(key, value)]
    if isinstance(value, dict):
        return [
            s
            for k, v in value.items()
            for s in (_strings(v, k) if k not in _ENVELOPE_HASHES else [])
        ] + [(key, k) for k in value]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v, key)]
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
        for key, text in _strings(e.model_dump(mode="json")):
            where = f"{path.parent.name} seq {e.seq} {e.kind}.{key}"
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

    return Scenario.model_validate_json((FIXTURES / name / "scenario.json").read_text("utf-8"))


def staged_recording(tmp_path: Path, name: str, *, timings: bool = True) -> Path:
    """Copy a committed transcript into tmp_path; optionally add a SYNTHETIC timings
    sidecar bound to it (committed fixtures carry no machine timings)."""
    import shutil

    rec = tmp_path / "recorded"
    rec.mkdir(exist_ok=True)
    path = rec / f"{name}.transcript.jsonl"
    shutil.copyfile(FIXTURES / name / "transcript.jsonl", path)
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
