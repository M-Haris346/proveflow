"""Named checks for the campaign engine and the report (Phase 7.1, 7.2). OFFLINE, nothing paid,
no provider: the model side is SCRIPTED everywhere here. A scripted provider does not react to
payloads, so every rate in these checks measures the script, not attack success."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import anyio

from proveflow.core.attacks import Carrier, ExfilGoal

GOALS = [ExfilGoal(sink_tool="fetch")]  # the cross_server_exfil template's sink tool
PER_SOURCE = 2


class Killed(BaseException):
    """The process dying mid-attempt (not an Exception: the campaign must not catch it)."""


def corpus(tmp_path: Path) -> list[Any]:
    """The SYNTHETIC fixture corpus (tests/fixtures/corpus), deduplicated: 15 records."""
    from ingestchecks import fixture_ingest

    return fixture_ingest(tmp_path / "corpus-cache").dedup.kept


# --- scripted attempts (no twin): for the sampler, the aggregation and the report -------------


class ScriptedCells:
    """attempt_for that scripts each cell's attempts: per cell key, a list of steps
    (reason, tokens, compromised). Writes a real transcript per attempt (the budget ledger
    reads usage from it) and returns a real AgentOutcome and Verdict."""

    def __init__(self, out: Path, steps: dict[str, list[tuple[str, int, bool]]]) -> None:
        self.out = out
        self.steps = {k: list(v) for k, v in steps.items()}
        self.calls = 0

    def __call__(self, cell: Any, record: Any, goal: Any) -> Any:
        async def attempt(key: str, trial_id: str, budget: Any) -> Any:
            from campaignloopchecks import ScriptedResult
            from proveflow.core.trials import Verdict
            from proveflow.runner.agent import AgentOutcome
            from proveflow.runner.transcript import TranscriptWriter

            self.calls += 1
            reason, tokens, compromised = self.steps[key].pop(0)
            w = TranscriptWriter(self.out / f"{trial_id}.transcript.jsonl")
            w.emit("trial_start", trial_id=trial_id, scenario_id="scripted", provider={},
                   parameters={}, limits={}, budget_remaining=budget.remaining,
                   servers=[])  # fmt: skip
            if tokens:
                w.emit("llm_response", turn=1, status=200, body={}, tokens_in=tokens, tokens_out=0)
            w.emit("trial_end", reason=reason, tokens_in=tokens, tokens_out=0, cassettes=[])
            w.close()
            verdict = Verdict(trial_id=trial_id, utility=False, compromised=compromised,
                              tokens_in=tokens, tokens_out=0, latency_ms=0.0)  # fmt: skip
            return ScriptedResult(AgentOutcome(reason, None, tokens, 0, 1, 0), verdict)

        return attempt


def scripted_engine(tmp_path: Path, steps: dict[str, list[tuple[str, int, bool]]]) -> Any:
    from proveflow.runner.engine import run_engine

    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    fn = ScriptedCells(out, steps)

    async def no_sleep(s: float) -> None:
        return None

    async def go() -> Any:
        return await run_engine(corpus(tmp_path), campaign_id="smoke",
                                state_path=tmp_path / "smoke.campaign.json", out_dir=out,
                                budget_total=500_000, per_source_n=PER_SOURCE, seed=7,
                                carriers=[Carrier.PLAIN], goals=GOALS, models=["scripted-model"],
                                model_side="scripted", attempt_for=fn, sleep=no_sleep)  # fmt: skip

    return fn, anyio.run(go)


# Cells c0000..c0005 in source order (DATASETS.md: injecagent, bipia, agentdojo), 2 each.
MIXED: dict[str, list[tuple[str, int, bool]]] = {
    "c0000": [("final_answer", 110, True)],
    "c0001": [("rate_limited", 0, False), ("final_answer", 110, False)],
    "c0002": [("final_answer", 110, True)],
    "c0003": [("limit:max_turns", 110, False)],  # a limit-ended trial COUNTS (COMPLETED_REASONS)
    "c0004": [("final_answer", 110, False)],
    "c0005": [("final_answer", 110, False)],
}


def assert_the_sampler_is_stratified_seeded_and_recorded(tmp_path: Path) -> None:
    """Named check (D6): EQUAL per source (min(n, population)), the same draw for the same seed,
    the draw independent of attack_family, and the state records the seed, each source's
    POPULATION and DRAW."""
    from proveflow.runner.engine import sample_records

    records = corpus(tmp_path)
    drawn, sampling = sample_records(records, per_source_n=PER_SOURCE, seed=7)
    counts = {s: d.drawn for s, d in sampling.per_source.items()}
    populations = {s: d.population for s, d in sampling.per_source.items()}
    if counts != {"injecagent": 2, "bipia": 2, "agentdojo": 2}:
        raise AssertionError(f"the draw is not equal per source: {counts}")
    if populations != {"injecagent": 3, "bipia": 6, "agentdojo": 6}:
        raise AssertionError(f"the recorded populations are wrong: {populations}")
    again, _ = sample_records(records, per_source_n=PER_SOURCE, seed=7)
    if [r.id for r in again] != [r.id for r in drawn]:
        raise AssertionError("the same seed did not give the same draw")
    relabelled = [r.model_copy(update={"attack_family": "x"}) for r in records]
    other, _ = sample_records(relabelled, per_source_n=PER_SOURCE, seed=7)
    if [r.id for r in other] != [r.id for r in drawn]:
        raise AssertionError("attack_family changed the draw: it is not a sampling axis")
    _, state = scripted_engine(tmp_path, {k: list(v) for k, v in MIXED.items()})
    if state.sampling != sampling or state.model_side != "scripted" or len(state.cells) != 6:
        raise AssertionError(f"the state does not record the draw: {state.sampling}")


def with_a_failure(tmp_path: Path) -> Any:
    """MIXED plus a FAILED attempt (c0004: provider_error, its scripted verdict compromised=true
    so counting it would raise the NUMERATOR too); the campaign stops there (fail closed) and a
    resume completes it. The state then holds a rate-limited AND a failed attempt, each with
    its transcript on disk (ARCHITECTURE.md section 9, Phase 7's required pin)."""
    from proveflow.runner.campaign import AttemptFailed

    steps = {k: list(v) for k, v in MIXED.items()}
    steps["c0004"] = [("provider_error", 110, True), ("final_answer", 110, False)]
    try:
        scripted_engine(tmp_path, {k: list(v) for k, v in steps.items()})
    except AttemptFailed:
        pass
    else:
        raise AssertionError("premise broken: the provider_error did not stop the campaign")
    steps["c0004"] = steps["c0004"][1:]
    return scripted_engine(tmp_path, steps)[1]


def exposure_all(state: Any, served: bool) -> dict[str, bool]:
    """An exposure map for SCRIPTED cells (they write no cassette): every counted trial the same."""
    from proveflow.runner.campaign import results

    return {k: served for k in results(state)}


def assert_aggregation_reads_only_the_results_ledger(tmp_path: Path) -> None:
    """Named check (D7): per source, the denominator is the COMPLETED trials of the results
    ledger, never one per transcript on disk: a rate-limited and a failed attempt each left a
    transcript and must not count, in the denominator or the numerator."""
    from proveflow.runner import report

    state = with_a_failure(tmp_path)
    transcripts = sorted((tmp_path / "out").glob("*.transcript.jsonl"))
    if len(transcripts) != 8:  # premise: both excluded attempts left a transcript too
        raise AssertionError(f"premise broken: {len(transcripts)} transcripts")
    rows = {r.source_dataset: r for r in
            report.aggregate(state, exposure_all(state, True), "forced").per_source}  # fmt: skip
    got = {s: (r.trials, r.compromised) for s, r in rows.items()}
    if got != {"injecagent": (2, 1), "bipia": (2, 1), "agentdojo": (2, 0)}:
        raise AssertionError(f"aggregation did not read the results ledger only: {got}")
    if rows["injecagent"].excluded.rate_limited != 1 or rows["agentdojo"].excluded.failed != 1:
        raise AssertionError("an excluded attempt is not reported alongside the rate")
    if rows["bipia"].ended_by != {"final_answer": 1, "limit:max_turns": 1}:
        raise AssertionError(f"the limit-ended trial is not reported by reason: {rows['bipia']}")
    exposed = report.aggregate(state, exposure_all(state, True), "forced")
    if "1 limit:max_turns" not in report.format_report(exposed):
        raise AssertionError("the limit-ended count is not printed beside the rate")


TOP_KEYS = {"schema_version", "campaign_id", "model_side", "delivery", "sampling_seed",
            "per_source", "notes"}  # fmt: skip
ROW_KEYS = {"source_dataset", "population", "drawn", "trials", "compromised", "exposed",
            "exposure_basis", "end_to_end", "delivered", "ended_by", "excluded"}  # fmt: skip


def assert_no_pooled_figure_is_emitted(tmp_path: Path) -> None:
    """Named check (D8): no pooled rate anywhere: the JSON has exactly the per-source rows and no
    other rate; the text has one line per emitted rate (two per source: end-to-end and
    delivered) and no total/overall/pooled line."""
    from proveflow.runner import report

    _, state = scripted_engine(tmp_path, {k: list(v) for k, v in MIXED.items()})
    rep = report.aggregate(state, exposure_all(state, True), "forced")
    body = json.loads(report.report_bytes(rep))
    if set(body) != TOP_KEYS or any(set(row) != ROW_KEYS for row in body["per_source"]):
        raise AssertionError(f"the report carries fields beyond the per-source rows: {set(body)}")
    text = report.format_report(rep)
    rate_lines = [ln for ln in text.splitlines() if "compromised" in ln and "Wilson" in ln]
    sources = len(body["per_source"])
    if len(rate_lines) != 2 * sources:
        raise AssertionError(f"the text has {len(rate_lines)} rate lines for {sources} sources")
    for ln in text.splitlines():
        head = ln.strip().split(":")[0].casefold()
        if head in {"total", "overall", "pooled", "all sources", "headline"}:
            raise AssertionError(f"a pooled figure was emitted: {ln!r}")
    if "attack_family" in report.report_bytes(rep).decode("utf-8"):
        raise AssertionError("attack_family appears in the report: it is not a reporting axis")


def assert_the_lower_bound_note_is_beside_the_numbers(tmp_path: Path) -> None:
    """Named check (D9, Q4b): the lower-bound note is in the JSON AND printed with the numbers,
    and a scripted campaign also carries the note that its rates measure the script."""
    from proveflow.runner import report

    _, state = scripted_engine(tmp_path, {k: list(v) for k, v in MIXED.items()})
    rep = report.aggregate(state, exposure_all(state, True), "forced")
    text = report.format_report(rep)
    for note in (report.LOWER_BOUND_NOTE, report.SCRIPTED_NOTE):
        if note not in rep.notes or note not in text:
            raise AssertionError(f"a required note is missing from the report: {note[:40]}...")


def assert_two_rates_are_emitted_and_never_conflated(tmp_path: Path) -> None:
    """Named check (7.3a, F1): per source TWO labelled rates with their OWN denominators. Here
    the exposure differs from the counted set on purpose, so a conflation shows in the numbers:
    injecagent c0000 compromised+exposed, c0001 not exposed -> END-TO-END 1/2, DELIVERED 1/1;
    bipia both exposed -> 1/2 and 1/2; agentdojo none exposed -> END-TO-END 0/2 printed with
    its interval and DELIVERED NOT EVALUATED, never 0/0 and never a rate. No field and no line
    is called an ASR, and the template's delivery condition note is beside the numbers."""
    from proveflow.runner import report

    _, state = scripted_engine(tmp_path, {k: list(v) for k, v in MIXED.items()})
    exposure = {"c0000": True, "c0001": False, "c0002": True, "c0003": True,
                "c0004": False, "c0005": False}  # fmt: skip
    rep = report.aggregate(state, exposure, "forced")
    rows = {r.source_dataset: r for r in rep.per_source}

    def pair(cell: Any) -> Any:
        return None if cell is None else (cell.label, cell.numerator, cell.denominator)

    got = {s: (pair(r.end_to_end), pair(r.delivered), r.exposed) for s, r in rows.items()}
    e2e, dlv = report.END_TO_END_LABEL, report.DELIVERED_LABEL
    want = {"injecagent": ((e2e, 1, 2), (dlv, 1, 1), 1), "bipia": ((e2e, 1, 2), (dlv, 1, 2), 2),
            "agentdojo": ((e2e, 0, 2), None, 0)}  # fmt: skip
    if got != want:
        raise AssertionError(f"the two rates are conflated or one is missing: {got}")
    text = report.format_report(rep)
    for source, row in rows.items():
        lines = [ln for ln in text.splitlines() if ln.strip().startswith(f"{source}:")]
        if not any(e2e in ln and "Wilson" in ln for ln in lines):
            raise AssertionError(f"{source}: the END-TO-END rate is not printed with its interval")
        delivered = [ln for ln in lines if dlv in ln]
        if len(delivered) != 1:
            raise AssertionError(f"{source}: the DELIVERED rate is not printed exactly once")
        if row.delivered is None and "NOT EVALUATED" not in delivered[0]:
            raise AssertionError(f"{source}: 0 exposed trials must print NOT EVALUATED")

    def keys(obj: Any) -> list[str]:
        if isinstance(obj, dict):
            return [*obj, *(k for v in obj.values() for k in keys(v))]
        return [k for v in obj for k in keys(v)] if isinstance(obj, list) else []

    named = [k for k in keys(json.loads(report.report_bytes(rep))) if "asr" in k.casefold()]
    heads = [ln for ln in text.splitlines()
             if "NOTE:" not in ln and "asr" in ln.split("compromised")[0].casefold()]  # fmt: skip
    if named or heads:
        raise AssertionError(f"a number called the ASR was emitted: {named or heads}")
    if report.FORCED_NOTE not in text or report.TWO_RATES_NOTE not in text:
        raise AssertionError("the delivery-condition or two-rates note is missing")


def assert_scripted_exposure_is_labelled(tmp_path: Path) -> None:
    """Named check (7.3a, Haris's ruling): a SCRIPTED report's EXPOSURE figures carry the SCRIPTED
    label where they are printed, like its rates: ``exposure_basis`` "scripted" on every JSON
    row, and "(SCRIPTED: ..." on every text exposure line. The script decides which tools are
    called, so a dry run's exposure is the script's and cannot predict a model's. The same
    state with a PROVIDER model side is labelled MEASURED, never SCRIPTED."""
    from proveflow.runner import report
    from proveflow.runner.campaign import CampaignState

    _, state = scripted_engine(tmp_path, {k: list(v) for k, v in MIXED.items()})
    sides = {"scripted": state,
             "provider": CampaignState.model_validate(
                 {**state.model_dump(mode="json"), "model_side": "provider"})}  # fmt: skip
    for side, st in sides.items():
        rep = report.aggregate(st, exposure_all(st, True), "forced")
        rows = json.loads(report.report_bytes(rep))["per_source"]
        lines = [ln for ln in report.format_report(rep).splitlines() if ": exposed " in ln]
        want = "scripted" if side == "scripted" else "measured"
        if {r["exposure_basis"] for r in rows} != {want}:
            raise AssertionError(f"{side}: the exposure figures are not labelled {want} in JSON")
        tag = "(SCRIPTED:" if side == "scripted" else "(MEASURED:"
        if len(lines) != len(rows) or not all(tag in ln for ln in lines):
            raise AssertionError(f"{side}: an exposure line lacks its {tag} label: {lines}")


def assert_scripted_data_never_reaches_docs_results(tmp_path: Path) -> None:
    """Named check (Q4a): a SCRIPTED report is refused under any docs/results/ path (here one
    built under tmp_path, so even a mutant writes nothing into the repo), written elsewhere as LF
    bytes; a campaign whose model side was never recorded cannot be aggregated."""
    from proveflow.runner import report
    from proveflow.runner.campaign import CampaignState

    _, state = scripted_engine(tmp_path, {k: list(v) for k, v in MIXED.items()})
    rep = report.aggregate(state, exposure_all(state, True), "forced")
    forbidden = tmp_path / "repo" / "docs" / "results" / "smoke.json"
    forbidden.parent.mkdir(parents=True)
    try:
        report.write_report(rep, forbidden)
    except report.ScriptedEvidenceRefused:
        pass
    else:
        raise AssertionError("a SCRIPTED report was written under docs/results/")
    if forbidden.exists():
        raise AssertionError("a refused report still left a file under docs/results/")
    ok = tmp_path / "smoke-report.json"
    report.write_report(rep, ok)
    if b"\r" in ok.read_bytes():
        raise AssertionError("the report bytes depend on the OS (CRLF written)")
    unknown = CampaignState.model_validate({**state.model_dump(mode="json"), "model_side": None})
    try:
        report.aggregate(unknown, exposure_all(unknown, True), "forced")
    except Exception as exc:  # EXPECTED: the refusal; which layer refused is checked below
        if not isinstance(exc, report.ReportError):
            raise AssertionError(f"refused, but not by the report's own guard: {exc!r}") from exc
        return
    raise AssertionError("a campaign with no recorded model side was aggregated")


def assert_the_engine_fails_closed(tmp_path: Path) -> None:
    """Named check (7.1d): a non-429 failure stops the engine's campaign with the state saved
    (the failed attempt recorded, nothing after it run); a resume retries it."""
    from proveflow.runner.campaign import AttemptFailed, load_state, results

    steps = {k: list(v) for k, v in MIXED.items()}
    steps["c0002"] = [("provider_error", 110, False), ("final_answer", 110, True)]
    try:
        scripted_engine(tmp_path, steps)
    except AttemptFailed:
        pass
    else:
        raise AssertionError("a provider_error did not stop the campaign")
    state = load_state(tmp_path / "smoke.campaign.json")
    if state.attempts[-1].trial_key != "c0002" or state.attempts[-1].status != "failed":
        raise AssertionError(f"the state does not end at the failed attempt: {state.attempts[-1]}")
    if any(a.trial_key > "c0002" for a in state.attempts):
        raise AssertionError("the campaign ran past a non-429 failure")
    steps["c0002"] = steps["c0002"][1:]
    remaining = {k: v for k, v in steps.items() if k >= "c0002"}
    _, state = scripted_engine(tmp_path, {**{k: [] for k in steps}, **remaining})
    if len(results(state)) != 6:
        raise AssertionError("the resume did not complete the campaign")


# --- the smoke campaign: REAL trials (real twins and proxies), the model side SCRIPTED ---------


class ScriptedChat:
    """A scripted provider: each request pops a step. "ok" answers with the cross_server_exfil
    fixture's recorded response for that turn (usage 100 + 10); 429 raises RateLimited; "kill"
    raises Killed (the process dying mid-attempt). It never reads the payload."""

    def __init__(self, script: list[Any]) -> None:
        from proveflow.runner.transcript import load_transcript
        from runnerchecks import _fixture_dir

        recorded = load_transcript(_fixture_dir("cross_server_exfil") / "transcript.jsonl")
        responses = [e for e in recorded if e.kind == "llm_response"]
        self.bodies = [e.body for e in responses]  # type: ignore[attr-defined]
        self.script = list(script)

    async def complete(self, body: dict[str, Any]) -> Any:
        from proveflow.runner.llm import ChatResponse, RateLimited

        step = self.script.pop(0)
        if step == 429:
            raise RateLimited("HTTP 429")
        if step == "kill":
            raise Killed("the process died here")
        turn = sum(1 for m in body["messages"] if m.get("role") == "assistant")
        out = {**self.bodies[turn], "usage": {"prompt_tokens": 100, "completion_tokens": 10}}
        return ChatResponse(200, out, 100, 10)


TURNS = 4  # cross_server_exfil's recorded conversation: 4 responses, 440 tokens per trial


def smoke(tmp_path: Path, script: list[Any], sleeps: list[float]) -> Any:
    from proveflow.config import ProviderConfig
    from proveflow.proxy import policy as policy_module
    from proveflow.runner.engine import run_engine, trial_attempt_for
    from proveflow.runner.limits import TrialLimits
    from runnerchecks import AUTHORED, fixture_scenario

    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    chat = ScriptedChat(script)
    attempt_for = trial_attempt_for(
        fixture_scenario("cross_server_exfil"), llm_for=lambda model: chat,
        provider_for=lambda model: ProviderConfig(**AUTHORED), out_dir=out,
        twin_dir=policy_module.TWIN_ROOT, parent_env=dict(os.environ), limits=TrialLimits(),
    )  # fmt: skip

    async def sleep(s: float) -> None:
        sleeps.append(s)

    async def go() -> Any:
        return await run_engine(corpus(tmp_path), campaign_id="smoke",
                                state_path=tmp_path / "smoke.campaign.json", out_dir=out,
                                budget_total=500_000, per_source_n=PER_SOURCE, seed=7,
                                carriers=[Carrier.PLAIN], goals=GOALS, models=["scripted-model"],
                                model_side="scripted", attempt_for=attempt_for,
                                sleep=sleep)  # fmt: skip

    return anyio.run(go)


def assert_the_smoke_campaign_resumes_with_each_trial_once(tmp_path: Path) -> Any:
    """Named check (7.1c): six cells on REAL twins and proxies (scripted model side). Cell 1 is
    429-ended once and retried; cell 3 is KILLED mid-attempt after one turn. Resumed, the results
    ledger holds each completed trial EXACTLY ONCE and the budget ledger counts every attempt,
    the killed one included (interrupted, its usage read from its transcript)."""
    from proveflow.runner.campaign import budget_spent, load_state, results

    ok = ["ok"] * TURNS
    run1 = [*ok, 429, *ok, *ok, "ok", "kill"]  # c0, c1 (429 then a retry), c2, c3 killed
    sleeps: list[float] = []
    killed: BaseException | None = None
    try:
        smoke(tmp_path, run1, sleeps)
    except BaseException as exc:  # EXPECTED: Killed escapes the campaign, as a dying process
        killed = exc
    if killed is None:
        raise AssertionError("premise broken: the kill did not stop run 1")
    mid = load_state(tmp_path / "smoke.campaign.json")
    last = mid.attempts[-1]
    if last.status != "started" or last.trial_key != "c0003":
        raise AssertionError(f"premise broken: the killed attempt is not 'started': {last}")
    state = smoke(tmp_path, [*ok, *ok, *ok], sleeps)  # resume: c3 again, c4, c5
    done = results(state)
    if sorted(done) != [f"c{i:04d}" for i in range(6)]:
        raise AssertionError(f"the results ledger is not each trial once: {sorted(done)}")
    statuses = [(a.trial_key, a.status) for a in state.attempts]
    killed_once = statuses.count(("c0003", "interrupted")) == 1
    if not killed_once or statuses.count(("c0001", "rate_limited")) != 1:
        raise AssertionError(f"the killed or rate-limited attempt is missing: {statuses}")
    per_trial = TURNS * 110
    if budget_spent(state) != 6 * per_trial + 110 + 0:
        raise AssertionError(f"the budget ledger is not every attempt: {budget_spent(state)}")
    if sleeps != [2.0]:
        raise AssertionError(f"the 429 was not backed off once: {sleeps}")
    return state


def assert_the_trial_runs_with_the_campaigns_limits(tmp_path: Path) -> None:
    """Named check (7.3a, F3): every attempt's transcript records the CAMPAIGN's tightened limits
    in its trial_start, i.e. the limits reached run_trial. Before 7.3a the engine dropped them:
    each trial ran with the defaults while the campaign reserved with its own."""
    from proveflow.config import ProviderConfig
    from proveflow.proxy import policy as policy_module
    from proveflow.runner.engine import run_engine, trial_attempt_for
    from proveflow.runner.limits import TrialLimits
    from proveflow.runner.transcript import TrialStart, load_transcript
    from runnerchecks import AUTHORED, fixture_scenario

    limits = TrialLimits(max_tokens_in=30_000, max_tokens_out=2_000)
    out = tmp_path / "out"
    out.mkdir(parents=True)
    chat = ScriptedChat(["ok"] * (3 * TURNS))  # three cells, one per source
    attempt_for = trial_attempt_for(
        fixture_scenario("cross_server_exfil"), llm_for=lambda model: chat,
        provider_for=lambda model: ProviderConfig(**AUTHORED), out_dir=out,
        twin_dir=policy_module.TWIN_ROOT, parent_env=dict(os.environ), limits=limits,
    )  # fmt: skip

    async def go() -> Any:
        return await run_engine(corpus(tmp_path), campaign_id="limits",
                                state_path=tmp_path / "limits.campaign.json", out_dir=out,
                                budget_total=400_000, per_source_n=1, seed=7,
                                carriers=[Carrier.PLAIN], goals=GOALS, models=["scripted-model"],
                                model_side="scripted", attempt_for=attempt_for,
                                limits=limits)  # fmt: skip

    state = anyio.run(go)
    want = limits.model_dump(mode="json")
    if len(state.attempts) != 3:
        raise AssertionError(f"premise broken: {len(state.attempts)} attempts")
    for a in state.attempts:
        first = load_transcript(out / f"{a.attempt_id}.transcript.jsonl")[0]
        if not isinstance(first, TrialStart) or first.limits != want:
            got = getattr(first, "limits", None)
            raise AssertionError(f"{a.attempt_id} ran with other limits than the campaign's: {got}")


# --- F1: exposure --------------------------------------------------------------------------


def _cassette(path: Path, *, attack: Any, events: list[tuple[str, dict[str, Any]]]) -> None:
    from proveflow.proxy.cassette import CassetteWriter

    w = CassetteWriter(path)
    w.emit("session_start", session_id=path.stem[:64], proveflow_version="test", upstream={},
           policy={}, attack=attack, limits={}, honey=[])  # fmt: skip
    for kind, fields in events:
        w.emit(kind, **fields)
    w.emit("session_end", reason="client_closed", tool_calls=0, forwarded_calls=0,
           sandboxed_calls=0, upstream_stderr="", upstream_stderr_truncated=False)  # fmt: skip
    w.close()


def exposure_state(tmp_path: Path) -> tuple[Any, Path]:
    """Two counted trials. c0000: its ATTACKED cassette holds an injection. c0001: its attacked
    cassette holds only an injection_skipped, its OTHER server's cassette holds an injection
    record, and its verdict says compromised: neither may make it exposed."""
    from proveflow.runner.campaign import Attempt, CampaignState

    out = tmp_path / "out"
    out.mkdir(parents=True)
    attack = {"armed": True}
    inj = ("injection", {"tool": "fetch", "carrier": "plain", "canary": "c", "content_index": 0})
    skip = ("injection_skipped", {"tool": "fetch", "reason": "empty_content"})
    _cassette(out / "c0000-a1.fetch.cassette.jsonl", attack=attack, events=[inj])
    _cassette(out / "c0000-a1.filesystem.cassette.jsonl", attack=None, events=[])
    _cassette(out / "c0001-a1.fetch.cassette.jsonl", attack=attack, events=[skip])
    _cassette(out / "c0001-a1.filesystem.cassette.jsonl", attack=None, events=[inj])

    def done(key: str, compromised: bool) -> Attempt:
        return Attempt(trial_key=key, number=1, status="completed", reason="final_answer",
                       usage_source="transcript", verdict={"compromised": compromised})  # fmt: skip

    state = CampaignState(campaign_id="exp", budget_total=1, plan=("c0000", "c0001"),
                          attempts=(done("c0000", False), done("c0001", True)))  # fmt: skip
    return state, out


def assert_exposure_is_read_from_the_attacked_cassette(tmp_path: Path) -> None:
    """Named check (F1): exposed iff the ATTACKED server's cassette holds an ``injection``
    record; never from another server's cassette, never from the verdict, never from a
    transcript (there is none here). An attempt with no attacked cassette fails closed."""
    from proveflow.runner.exposure import ExposureUnknown, exposure_of

    state, out = exposure_state(tmp_path)
    got = exposure_of(state, out)
    if got != {"c0000": True, "c0001": False}:
        raise AssertionError(f"exposure is not the attacked cassette's injection record: {got}")
    (out / "c0001-a1.fetch.cassette.jsonl").unlink()
    try:
        exposure_of(state, out)
    except ExposureUnknown:
        return
    raise AssertionError("a counted trial with no attacked cassette was given an exposure")
