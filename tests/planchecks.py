"""Named checks for the Phase 7.3a campaign path: the plan file and its refusals, the paid CLI's
refusals, the preflight, the offline corpus, the calibration, the estimate's arithmetic and the
dry run with a kill and a resume (F3's and exposure's checks are in tests/enginechecks.py, with
the engine and the report). OFFLINE and nothing paid: the
model side is SCRIPTED everywhere, no key exists, tests/netguard refuses every non-loopback
host. The corpus is the SYNTHETIC fixture corpus (raw datasets are never committed, and CI has
no local corpus cache), patched in where a command would read the local cache."""

from __future__ import annotations

import contextlib
import io
import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import anyio
import pytest

REPO = Path(__file__).resolve().parents[1]
CAMPAIGNS = REPO / "campaigns"
FORCED_PLAN = CAMPAIGNS / "groq_forced.plan.json"
KEY_ENV = "PROVEFLOW_PLANCHECKS_KEY"  # a test variable name; its value is a dummy, never a key


class Tripwire(AssertionError):
    """A refused command got past its refusals (it would have created or sent something)."""


# --- helpers -------------------------------------------------------------------------------


def plan_body(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = json.loads(FORCED_PLAN.read_text(encoding="utf-8"))
    body.update(over)
    return body


def write_plan(tmp_path: Path, body: dict[str, Any], name: str = "t.plan.json") -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    shutil.copytree(CAMPAIGNS / "templates", tmp_path / "templates", dirs_exist_ok=True)
    path = tmp_path / name
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def small_plan(tmp_path: Path, per_source_n: int = 1) -> Path:
    """The forced plan with a draw the synthetic corpus can serve (populations 3, 6, 6)."""
    return write_plan(tmp_path, plan_body(per_source_n=per_source_n))


FS_PLAN = CAMPAIGNS / "groq_fs_forced.plan.json"


def small_fs_plan(tmp_path: Path, per_source_n: int = 1) -> Path:
    """The Phase 8 plan (fs_notes_exfil: the injection is in the file, the sink is fetch) with a
    draw the synthetic corpus can serve."""
    body: dict[str, Any] = json.loads(FS_PLAN.read_text(encoding="utf-8"))
    body["per_source_n"] = per_source_n
    return write_plan(tmp_path, body)


def write_config(tmp_path: Path, **over: Any) -> Path:
    provider = {"name": "groq", "base_url": "https://api.groq.com/openai/v1",
                "model": "openai/gpt-oss-120b", "api_key_env": KEY_ENV,
                "send_seed": True}  # fmt: skip
    provider.update(over)

    def value(v: Any) -> str:
        return "true" if v is True else "false" if v is False else json.dumps(v)

    lines = ["[[provider]]", *(f"{k} = {value(v)}" for k, v in provider.items())]
    path = tmp_path / "proveflow.toml"
    path.write_text(chr(10).join(lines) + chr(10), encoding="utf-8")
    return path


def synthetic_corpus(tmp_path: Path) -> list[Any]:
    from enginechecks import corpus

    return corpus(tmp_path / "corpus")


def arm(mp: pytest.MonkeyPatch) -> None:
    """Everything a refused command must never reach raises Tripwire."""
    from proveflow.runner import llm, paid

    def trip(*a: Any, **k: Any) -> Any:
        raise Tripwire("a refused command got past its refusals")

    mp.setattr(paid, "cached_records", trip)
    mp.setattr(paid, "run_engine", trip)
    mp.setattr(llm, "HttpChatClient", trip)


def expect_refused(run: Callable[[], Any], reason: str) -> None:
    from proveflow.runner.paid import Refused

    try:
        run()
    except Refused as exc:
        if reason not in exc.reason:
            raise AssertionError(f"refused for another reason: {exc.reason!r}") from None
        return
    except Tripwire as exc:
        raise AssertionError(f"not refused: {exc}") from None
    raise AssertionError("not refused: the command returned")


def _plan_error(path: Path) -> str:
    from proveflow.runner.plan import PlanError, load_plan

    try:
        load_plan(path)
    except PlanError as exc:
        return str(exc)
    raise AssertionError("the plan was accepted")


# --- the plan file -------------------------------------------------------------------------


def assert_a_plan_without_a_cap_is_refused(tmp_path: Path) -> None:
    """Named check: a plan with no ``budget_total`` is refused (the cap is never defaulted)."""
    body = plan_body()
    del body["budget_total"]
    if "budget_total" not in _plan_error(write_plan(tmp_path, body)):
        raise AssertionError("the missing cap is not named")


def assert_a_cap_over_the_ceiling_is_refused(tmp_path: Path) -> None:
    """Named check: a cap above RunBudget's ceiling (500,000, tighten-only) is refused."""
    from proveflow.runner.limits import RUN_TOKEN_BUDGET

    error = _plan_error(write_plan(tmp_path, plan_body(budget_total=RUN_TOKEN_BUDGET + 1)))
    if "budget_total" not in error:
        raise AssertionError(f"the over-ceiling cap is not named: {error}")


def assert_a_cap_below_one_reservation_is_refused(tmp_path: Path) -> None:
    """Named check: a cap below ONE trial's reservation (limits.max_trial_tokens) is refused,
    so a plan in which no trial could start never runs."""
    body = plan_body()
    reservation = body["limits"]["max_tokens_in"] + body["limits"]["max_tokens_out"]
    error = _plan_error(write_plan(tmp_path, plan_body(budget_total=reservation - 1)))
    if "below one trial's reservation" not in error:
        raise AssertionError(f"the too-small cap is not refused as such: {error}")


def assert_a_plan_without_limits_is_refused(tmp_path: Path) -> None:
    """Named check: the limits are REQUIRED (never defaulted, F3)."""
    body = plan_body()
    del body["limits"]
    if "limits" not in _plan_error(write_plan(tmp_path, body)):
        raise AssertionError("the missing limits are not named")


def assert_another_template_is_refused(tmp_path: Path) -> None:
    """Named check: a template whose bytes differ from the pinned sha256 is refused."""
    from proveflow.runner.plan import PlanError, load_plan, load_template

    path = small_plan(tmp_path)
    template = tmp_path / "templates" / "fetch_summary_exfil.json"
    template.write_bytes(template.read_bytes() + b" ")
    try:
        load_template(load_plan(path), path)
    except PlanError as exc:
        if "refusing to run another template" not in str(exc):
            raise AssertionError(f"refused for another reason: {exc}") from None
        return
    raise AssertionError("a template with another sha256 was accepted")


def assert_the_committed_plans_are_the_ruled_ones() -> None:
    """Named check: both committed plans load, pin their templates, and carry Haris's rulings:
    30 cells' worth of draw (10 per source), cap 400,000, 32,000 per trial (30,000 + 2,000),
    the evidence run's provider and model, one carrier and one goal; the forced plan's template
    REQUIRES the attacked tool and the incidental one is byte-identical to the fixture."""
    from proveflow.runner.plan import load_plan, load_template

    fixture = REPO / "tests" / "fixtures" / "runner" / "cross_server_exfil" / "scenario.json"
    for name, delivery in (("groq_forced", "forced"), ("groq_incidental", "incidental"),
                           ("groq_fs_forced", "forced")):  # fmt: skip
        path = CAMPAIGNS / f"{name}.plan.json"
        plan = load_plan(path)
        template = load_template(plan, path)
        got = (plan.delivery, plan.per_source_n, plan.budget_total, plan.limits.max_tokens_in,
               plan.limits.max_tokens_out, plan.provider.model, plan.provider.base_url)  # fmt: skip
        want = (delivery, 10, 400_000, 30_000, 2_000, "openai/gpt-oss-120b",
                "https://api.groq.com/openai/v1")  # fmt: skip
        if got != want:
            raise AssertionError(f"{name}: not the ruled plan: {got}")
        from proveflow.runner.scripted import scripted_calls

        required = {tool for tool, _ in scripted_calls(template)}  # the utility's tool calls
        attacked = {t.name for s in template.servers if s.name == template.attack_server
                    for t in s.tools}  # fmt: skip
        if (delivery == "forced") != bool(required & attacked):
            raise AssertionError(f"{name}: the utility's required tools {required} do not match "
                                 f"the {delivery} delivery condition")  # fmt: skip
    incidental = CAMPAIGNS / "templates" / "cross_server_exfil.json"
    if incidental.read_bytes() != fixture.read_bytes():
        raise AssertionError("the incidental template is not the cross_server_exfil fixture")
    # Phase 8 (Haris's ruling): fs_notes_exfil is cross_server_exfil with EXACTLY four changes.
    want = json.loads(incidental.read_text(encoding="utf-8"))
    want["id"] = "fs_notes_exfil"
    want["flow_id"] = ("filesystem->filesystem->fetch (exfil; forced delivery: the injection "
                       "arrives in the file the task reads)")  # fmt: skip
    want["attack_server"] = "filesystem"
    fs = next(s for s in want["servers"] if s["name"] == "filesystem")
    next(t for t in fs["tools"] if t["name"] == "read_text_file")["roles"].append(
        {"role": "untrusted_source", "source": "override", "reason": "Phase 8 template (ruled): "
         "the file's content is attacker-controlled", "weight": 1.0, "granularity": "tool",
         "sink_severity": None})  # fmt: skip
    got = json.loads((CAMPAIGNS / "templates" / "fs_notes_exfil.json").read_text(encoding="utf-8"))
    if got != want:
        raise AssertionError("fs_notes_exfil is not cross_server_exfil plus the four ruled changes")


def assert_the_calibration_is_the_evidence_runs() -> None:
    """Named check: the bytes-per-token constants are the committed evidence run's own figures,
    re-measured here from its transcript (requests by ``request_bytes``, the provider-reported
    usage of the response after each)."""
    from proveflow.runner import plan

    path = REPO / plan.EVIDENCE_RUN / "transcript.jsonl"
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    sizes = tuple(plan.request_bytes(e["body"]) for e in events if e["kind"] == "llm_request")
    resp = [e for e in events if e["kind"] == "llm_response"]
    tin = tuple(e["tokens_in"] for e in resp)
    tout = tuple(e["tokens_out"] for e in resp)
    got = (
        plan.EVIDENCE_REQUEST_BYTES,
        plan.EVIDENCE_PROMPT_TOKENS,
        plan.EVIDENCE_COMPLETION_TOKENS,
    )
    if got != (sizes, tin, tout):
        raise AssertionError(
            f"the calibration is not the evidence run's: {got} vs {(sizes, tin, tout)}"
        )


def assert_the_estimate_arithmetic(tmp_path: Path) -> None:
    """Named check: the preflight's estimate is the measured bytes over the measured
    bytes-per-token, the evidence run's completion tokens per turn, times the cells and the
    published price, and the fit and runaway lines follow from the cap and the reservation."""
    from decimal import Decimal

    from proveflow.runner.paid import estimate
    from proveflow.runner.plan import load_plan

    plan = load_plan(small_plan(tmp_path))
    e = estimate(plan, [{"turn": 0, "bytes": 6464}, {"turn": 1, "bytes": 12928}], cells=30)
    got = (e["tokens_in_per_trial"], e["tokens_out_per_trial"], e["total_in"], e["total_out"],
           e["usd_in"], e["usd_out"], e["usd_hard_max"], e["fits"],
           e["runaway_trials"])  # fmt: skip
    want = (3000, 168, 90_000, 5_040, Decimal("0.0135"), Decimal("0.003024"), Decimal("0.24"),
            True, 12)  # fmt: skip
    if got != want:
        raise AssertionError(f"the estimate arithmetic is wrong: {got}")


# --- the paid CLI's refusals ---------------------------------------------------------------


def _run_args(tmp_path: Path, plan: Path, *extra: str, state: Path | None = None) -> list[str]:
    from proveflow.runner.plan import campaign_id_of, load_plan

    cid = campaign_id_of(load_plan(plan))
    state = state or tmp_path / "runs" / f"{cid}.campaign.json"
    return ["run", str(plan), "--config", str(write_config(tmp_path)), "--state", str(state),
            *extra]  # fmt: skip


def assert_run_refuses_a_provider_that_differs(tmp_path: Path, mp: pytest.MonkeyPatch) -> None:
    """Named check: the config's provider must be EXACTLY the plan's: a different base_url,
    model or send_seed is refused before anything is created."""
    from proveflow.runner import paid

    arm(mp)
    mp.setenv(KEY_ENV, "dummy-not-a-key")
    plan = small_plan(tmp_path)
    for field, value in (("base_url", "https://example.invalid/v1"), ("model", "other-model"),
                         ("send_seed", False)):  # fmt: skip
        args = _run_args(tmp_path, plan, "--yes")
        write_config(tmp_path, **{field: value})
        expect_refused(lambda a=args: paid.main(a), f"provider {field} differs")


def assert_run_refuses_without_the_key(tmp_path: Path, mp: pytest.MonkeyPatch) -> None:
    """Named check: with the key's variable unset, run refuses before any twin or HTTP client."""
    from proveflow.runner import paid

    arm(mp)
    mp.delenv(KEY_ENV, raising=False)
    args = _run_args(tmp_path, small_plan(tmp_path), "--yes")
    expect_refused(lambda: paid.main(args), f"{KEY_ENV} is not set")


def assert_run_refuses_another_plans_state(tmp_path: Path, mp: pytest.MonkeyPatch) -> None:
    """Named check: --state must be THIS plan's state file (named by its campaign id)."""
    from proveflow.runner import paid

    arm(mp)
    mp.setenv(KEY_ENV, "dummy-not-a-key")
    plan = small_plan(tmp_path)
    args = _run_args(tmp_path, plan, "--yes", state=tmp_path / "runs" / "other.campaign.json")
    expect_refused(lambda: paid.main(args), "is not this plan's state file")


def assert_run_refuses_a_root_under_docs_results(tmp_path: Path, mp: pytest.MonkeyPatch) -> None:
    """Named check: a paid run never writes under docs/results/ (the report goes there by hand,
    after review)."""
    from proveflow.runner import paid
    from proveflow.runner.plan import campaign_id_of, load_plan

    arm(mp)
    mp.setenv(KEY_ENV, "dummy-not-a-key")
    plan = small_plan(tmp_path)
    cid = campaign_id_of(load_plan(plan))
    state = tmp_path / "docs" / "results" / f"{cid}.campaign.json"
    args = _run_args(tmp_path, plan, "--yes", state=state)
    expect_refused(lambda: paid.main(args), "under docs/results/")


def assert_run_spends_nothing_without_yes(tmp_path: Path, mp: pytest.MonkeyPatch) -> None:
    """Named check: without --yes, run prints the maximum spend and exits 2, creating nothing."""
    from proveflow.runner import paid

    arm(mp)
    mp.setenv(KEY_ENV, "dummy-not-a-key")
    args = _run_args(tmp_path, small_plan(tmp_path))
    try:
        code = paid.main(args)
    except Tripwire:
        raise AssertionError("run without --yes went on to the campaign") from None
    if code != paid.EXIT_REFUSED or (tmp_path / "runs").exists():
        raise AssertionError(f"run without --yes did not stop cleanly: exit {code}")


def assert_dry_run_refuses_a_root_under_docs_results(
    tmp_path: Path, mp: pytest.MonkeyPatch
) -> None:
    """Named check: a dry run (SCRIPTED) never writes under docs/results/."""
    from proveflow.runner import paid

    arm(mp)
    root = tmp_path / "docs" / "results" / "dry"
    args = ["dry-run", str(small_plan(tmp_path)), "--root", str(root)]
    expect_refused(lambda: paid.main(args), "under docs/results/")


def assert_a_dry_run_state_is_never_resumed_as_paid(tmp_path: Path) -> None:
    """Named check (F2): the dry run's state file can never become the paid run's: resuming a
    SCRIPTED campaign's state with model side ``provider`` is refused (campaign._open)."""
    from enginechecks import MIXED, ScriptedCells, corpus
    from proveflow.core.attacks import Carrier, ExfilGoal
    from proveflow.runner.campaign import CorruptCampaignState
    from proveflow.runner.engine import run_engine

    out = tmp_path / "out"
    out.mkdir()
    records = corpus(tmp_path)

    async def go(side: Any, steps: Any) -> Any:
        return await run_engine(records, campaign_id="same", state_path=tmp_path / "s.json",
                                out_dir=out, budget_total=500_000, per_source_n=2, seed=7,
                                carriers=[Carrier.PLAIN], goals=[ExfilGoal(sink_tool="fetch")],
                                models=["m"], model_side=side,
                                attempt_for=ScriptedCells(out, steps))  # fmt: skip

    anyio.run(go, "scripted", {k: list(v) for k, v in MIXED.items()})
    try:
        anyio.run(go, "provider", {k: [] for k in MIXED})
    except CorruptCampaignState as exc:
        if "belongs to another campaign" not in str(exc):
            raise AssertionError(f"refused for another reason: {exc}") from None
        return
    raise AssertionError("a SCRIPTED state was resumed as a PROVIDER campaign")


def assert_the_preflight_spends_nothing(tmp_path: Path, mp: pytest.MonkeyPatch) -> Any:
    """Named check: the preflight creates no twin, no proxy, no trial and no HTTP client, and
    prints the plan, the draw, the cells, the measured bytes, the estimate with its arithmetic,
    the price with its URLs and read date, and the cap."""
    from proveflow.proxy import server
    from proveflow.runner import llm, paid, trial
    from proveflow.runner.plan import campaign_id_of, load_plan, plan_sha256

    plan_path = small_plan(tmp_path, per_source_n=2)
    plan = load_plan(plan_path)
    records = synthetic_corpus(tmp_path)

    def trip(*a: Any, **k: Any) -> Any:
        raise Tripwire("the preflight reached a component that runs or sends something")

    for module, name in ((paid, "run_engine"), (trial, "run_trial"), (server, "serve"),
                         (llm, "HttpChatClient")):  # fmt: skip
        mp.setattr(module, name, trip)
    mp.setattr(paid, "cached_records", lambda cache: records)
    root = tmp_path / "dry"
    root.mkdir()
    cid = campaign_id_of(plan)
    measure = {"campaign_id": cid, "plan_sha256": plan_sha256(plan),
               "requests": [{"turn": 0, "bytes": 9892}, {"turn": 1, "bytes": 10823}]}  # fmt: skip
    paid.measure_path_of(root, cid).write_text(json.dumps(measure), encoding="utf-8")
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            code = paid.main(["preflight", str(plan_path), "--dry-run-root", str(root)])
    except Tripwire as exc:
        raise AssertionError(f"the preflight is not side-effect free: {exc}") from None
    text = buf.getvalue()
    for needle in ("cells: 6", "MEASURED", "ESTIMATED SPEND", "HARD MAXIMUM", plan.price.urls[0],
                   f"read {plan.price.read_date}", "cap 400000", "spent nothing"):  # fmt: skip
        if needle not in text:
            raise AssertionError(f"the preflight does not print {needle!r}")
    if code != 0:
        raise AssertionError(f"the preflight exited {code}")
    return text


def assert_the_campaign_corpus_never_fetches(tmp_path: Path) -> None:
    """Named check: with an empty cache, the campaign's corpus loader REFUSES (CorpusNotCached)
    instead of fetching."""
    from proveflow.runner.offline_corpus import CorpusNotCached, cached_records

    try:
        cached_records(tmp_path / "empty-cache")
    except CorpusNotCached:
        return
    except Exception as exc:
        raise AssertionError(f"did not refuse with CorpusNotCached: {exc!r}") from None
    raise AssertionError("an empty cache produced records")


# --- the dry run, end to end, with a kill and a resume -------------------------------------


def assert_the_dry_run_kills_and_resumes(tmp_path: Path, mp: pytest.MonkeyPatch) -> Any:
    """Named check (deliverable 3): the dry-run COMMAND on the forced plan (3 cells here, real
    twins and proxies, scripted model side) is killed mid-attempt, then resumed by running the
    same command again: each key counted once, the killed attempt interrupted and charged from
    its transcript, the report written under the root (never docs/results/) with both rates and
    exposure read from the cassettes, and the measurement file kept across the kill."""
    from proveflow.runner import paid
    from proveflow.runner.campaign import budget_spent, load_state, results
    from proveflow.runner.plan import campaign_id_of, load_plan
    from proveflow.runner.scripted import ScriptedKill

    plan_path = small_plan(tmp_path)
    cid = campaign_id_of(load_plan(plan_path))
    records = synthetic_corpus(tmp_path)
    mp.setattr(paid, "cached_records", lambda cache: records)
    root = tmp_path / "dry"
    args = ["dry-run", str(plan_path), "--root", str(root)]
    killed: BaseException | None = None
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            paid.main([*args, "--kill-at-request", "4"])  # c0001's second request
    except BaseException as exc:  # EXPECTED: the kill, possibly wrapped by the harness's groups
        killed = exc
    is_kill = isinstance(killed, ScriptedKill) or (
        isinstance(killed, BaseExceptionGroup) and killed.subgroup(ScriptedKill) is not None
    )
    if not is_kill:
        raise AssertionError(f"premise broken: the scripted kill did not stop the run: {killed!r}")
    mid = load_state(paid.state_path_of(root, cid))
    if mid.attempts[-1].status != "started" or mid.attempts[-1].trial_key != "c0001":
        raise AssertionError(f"premise broken: the killed attempt is not 'started': {mid.attempts}")
    with contextlib.redirect_stdout(io.StringIO()):
        paid.main(args)
    state = load_state(paid.state_path_of(root, cid))
    statuses = [(a.attempt_id, a.status) for a in state.attempts]
    if sorted(results(state)) != ["c0000", "c0001", "c0002"]:
        raise AssertionError(f"each key is not counted once: {statuses}")
    if ("c0001-a1", "interrupted") not in statuses or budget_spent(state) != 3 * 220 + 110:
        raise AssertionError(f"the killed attempt is not charged: {statuses} {budget_spent(state)}")
    rep = json.loads(paid.report_path_of(root, cid).read_text(encoding="utf-8"))
    if [r["exposed"] for r in rep["per_source"]] != [1, 1, 1] or rep["model_side"] != "scripted":
        raise AssertionError(f"the report's exposure is not the cassettes': {rep['per_source']}")
    if any(r["delivered"] is None or r["end_to_end"] is None for r in rep["per_source"]):
        raise AssertionError("the dry run's report does not carry both rates")
    measured = json.loads(paid.measure_path_of(root, cid).read_text(encoding="utf-8"))
    if len(measured["requests"]) != 3 + 4:  # run 1 measured 3 before the kill; the resume 4
        raise AssertionError(
            f"the measurement did not survive the kill: {len(measured['requests'])}"
        )
    return state
