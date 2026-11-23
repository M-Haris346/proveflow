"""Named checks for the campaign LOOP and its STATE FILE (Phase 6 step 2): claims about the loop's
arithmetic, its classification and its state file, run with SCRIPTED attempts. A scripted
attempt starts no twin and no proxy: it writes a REAL transcript (TranscriptWriter, hash
chained, read back by the campaign's own transcript_usage) with the scripted usage and returns
a real AgentOutcome and a real Verdict, exactly what the campaign reads from a TrialResult
(campaign.AttemptResult). Claims about a REAL trial live in campaignchecks.py, on real twins and
real proxies. Also here: the AST scan of every trial_end reason the runner can write."""

from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import Any

from campaignchecks import PER_OK, TOTAL
from runnerchecks import AUTHORED, fixture_scenario

OK = ("final_answer", 100, 10)  # a completed attempt, 110 tokens
RL = ("rate_limited", 100, 10)  # a 429-ended attempt after one turn, 110 tokens


class ScriptedResult:
    def __init__(self, outcome: Any, verdict: Any) -> None:
        self.outcome = outcome
        self.verdict = verdict


class ScriptedAttempts:
    """Each call pops one step (reason, tokens_in, tokens_out[, retry_after_header]) and writes
    that attempt's transcript; ``calls`` counts the attempts actually started."""

    def __init__(self, out: Path, steps: list[tuple[Any, ...]]) -> None:
        self.out = out
        self.steps = list(steps)
        self.calls = 0

    async def __call__(self, key: str, trial_id: str, budget: Any) -> Any:
        from proveflow.core.trials import Verdict
        from proveflow.runner.agent import AgentOutcome
        from proveflow.runner.transcript import TranscriptWriter

        self.calls += 1
        if not self.steps:
            raise AssertionError("the scripted attempts ran out (a test bug)")
        reason, tin, tout, *rest = self.steps.pop(0)
        w = TranscriptWriter(self.out / f"{trial_id}.transcript.jsonl")
        w.emit("trial_start", trial_id=trial_id, scenario_id="scripted", provider={},
               parameters={}, limits={}, budget_remaining=budget.remaining, servers=[])  # fmt: skip
        if tin or tout:
            w.emit("llm_response", turn=1, status=200, body={}, tokens_in=tin, tokens_out=tout)
        w.emit("trial_end", reason=reason, tokens_in=tin, tokens_out=tout, cassettes=[])
        w.close()
        outcome = AgentOutcome(reason, None, tin, tout, 1, 0,
                               retry_after_header=rest[0] if rest else None)  # fmt: skip
        verdict = Verdict(trial_id=trial_id, utility=False, compromised=False, tokens_in=tin,
                          tokens_out=tout, latency_ms=0.0)  # fmt: skip
        return ScriptedResult(outcome, verdict)


class CampaignRaised(Exception):
    """What the campaign raised, with the scripted attempt function that ran."""

    def __init__(self, raised: BaseException, fn: ScriptedAttempts) -> None:
        super().__init__(repr(raised))
        self.raised = raised
        self.fn = fn


def scripted_campaign(tmp_path: Path, steps: list[tuple[Any, ...]], plan: list[str],
                      sleeps: list[float]) -> tuple[ScriptedAttempts, Any]:  # fmt: skip
    """Run (or resume) the campaign in ``tmp_path`` with scripted attempts: (fn, state), or
    ``CampaignRaised`` wrapping what the campaign raised."""
    import anyio

    from proveflow.runner.campaign import run_campaign

    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    fn = ScriptedAttempts(out, steps)

    async def sleep(s: float) -> None:
        sleeps.append(s)

    state_path = tmp_path / "c1.campaign.json"

    async def go() -> Any:
        return await run_campaign(plan, campaign_id="c1", state_path=state_path, out_dir=out,
                                  budget_total=TOTAL, attempt=fn, sleep=sleep)  # fmt: skip

    try:
        return fn, anyio.run(go)
    except AssertionError:
        raise
    except Exception as exc:
        raise CampaignRaised(exc, fn) from exc


# --- every trial_end reason is classified (AST scan, exact set equality) ----------------------

RUNNER_SOURCES = ("src/proveflow/runner/agent.py", "src/proveflow/runner/trial.py")


def _str(node: Any) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _helper_stops(agent: ast.Module) -> set[int]:
    """The ``_Stop`` calls inside stop_limit / stop_error that have the exact resolvable shape:
    stop_limit's is f"limit:{<first param>}", stop_error's is its first param."""
    out: set[int] = set()
    for fn in ast.walk(agent):
        if not (isinstance(fn, ast.FunctionDef) and fn.name in ("stop_limit", "stop_error")):
            continue
        param = fn.args.args[0].arg if fn.args.args else None
        for call in ast.walk(fn):
            if not (isinstance(call, ast.Call) and getattr(call.func, "id", None) == "_Stop"):
                continue
            arg = call.args[0] if call.args else None
            if fn.name == "stop_limit":
                ok = (isinstance(arg, ast.JoinedStr) and len(arg.values) == 2
                      and _str(arg.values[0]) == "limit:"
                      and isinstance(arg.values[1], ast.FormattedValue)
                      and getattr(arg.values[1].value, "id", None) == param)  # fmt: skip
            else:
                ok = isinstance(arg, ast.Name) and arg.id == param
            if ok:
                out.add(id(call))
    return out


def _stop_init_assigns(agent: ast.Module) -> set[int]:
    """``self.reason = <first param>`` in ``class _Stop.__init__``: the constructor storing the
    value of each ``_Stop(...)`` call, which the scan resolves at those call sites. Only this
    exact shape (found by the scan itself at agent.py:79, not listed beforehand)."""
    out: set[int] = set()
    for cls in ast.walk(agent):
        if not (isinstance(cls, ast.ClassDef) and cls.name == "_Stop"):
            continue
        for fn in cls.body:
            if not (isinstance(fn, ast.FunctionDef) and fn.name == "__init__"):
                continue
            params = [a.arg for a in fn.args.args]
            for node in ast.walk(fn):
                if (isinstance(node, ast.Assign) and len(params) >= 2
                        and isinstance(node.value, ast.Name) and node.value.id == params[1]
                        and all(isinstance(t, ast.Attribute) and t.attr == "reason"
                                and getattr(t.value, "id", None) == params[0]
                                for t in node.targets)):  # fmt: skip
                    out.add(id(node))
    return out


def scanned_trial_end_reasons(sources: dict[str, str] | None = None) -> tuple[set[str], list[str]]:
    """Every reason the runner can write to trial_end, by AST scan of runner/agent.py and
    runner/trial.py (or ``sources``, for mutation tests): (reasons, unresolved sites).

    Agent sites: ``stop_limit(<lit>, ...)`` -> "limit:<lit>"; ``stop_error(<lit>, ...)`` ->
    <lit>; ``_Stop(<lit>)``; ``AgentOutcome(<lit>, ...)`` (the initial value); and
    ``<x>.reason = <lit>``. The helpers' own ``_Stop`` calls are resolved through their call
    sites ONLY in their exact shape (``_helper_stops``); ``<x>.reason = stop.reason`` is the
    _Stop value. Trial sites: every ``emit("trial_end", reason=...)`` is a literal or
    ``outcome.reason``; an AgentOutcome built in trial.py is unresolved. Anything else is
    UNRESOLVED, and an unresolved site fails the check."""
    root = Path(__file__).resolve().parents[1]
    texts = {p: (sources or {}).get(p) or (root / p).read_text(encoding="utf-8")
             for p in RUNNER_SOURCES}  # fmt: skip
    agent, trial = (ast.parse(texts[p]) for p in RUNNER_SOURCES)
    resolved_by_helper = _helper_stops(agent)
    resolved_by_helper |= _stop_init_assigns(agent)
    reasons: set[str] = set()
    unresolved: list[str] = []

    def take(value: str | None, site: str) -> None:
        if value is None:
            unresolved.append(site)
        else:
            reasons.add(value)

    for node in ast.walk(agent):
        where = f"agent.py:{getattr(node, 'lineno', '?')}"
        if isinstance(node, ast.Call):
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            first = node.args[0] if node.args else None
            if name in ("stop_limit", "stop_error"):
                lit = _str(first)
                prefix = "limit:" if name == "stop_limit" else ""
                take(None if lit is None else prefix + lit, f"{where} {name}(<not a literal>)")
            elif name == "_Stop" and id(node) not in resolved_by_helper:
                take(_str(first), f"{where} _Stop(<not a literal>)")
            elif name == "AgentOutcome":
                kw = next((k.value for k in node.keywords if k.arg == "reason"), None)
                take(_str(first if first is not None else kw), f"{where} AgentOutcome(?)")
        elif isinstance(node, ast.Assign) and id(node) not in resolved_by_helper:
            for target in node.targets:
                if not (isinstance(target, ast.Attribute) and target.attr == "reason"):
                    continue
                v = node.value
                from_stop = (isinstance(v, ast.Attribute) and v.attr == "reason"
                             and getattr(v.value, "id", None) == "stop")  # fmt: skip
                if not from_stop:
                    take(_str(v), f"{where} .reason = <not a literal>")
    for node in ast.walk(trial):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "id", None) == "AgentOutcome":
            unresolved.append(f"trial.py:{node.lineno} AgentOutcome built outside the agent")
        if (
            getattr(node.func, "attr", None) == "emit"
            and node.args
            and _str(node.args[0]) == ("trial_end")
        ):
            kw = next((k.value for k in node.keywords if k.arg == "reason"), None)
            from_outcome = (isinstance(kw, ast.Attribute) and kw.attr == "reason"
                            and getattr(kw.value, "id", None) == "outcome")  # fmt: skip
            if not from_outcome:
                take(_str(kw), f"trial.py:{node.lineno} trial_end reason=<unresolved>")
    return reasons, unresolved


def assert_every_trial_end_reason_is_classified(sources: dict[str, str] | None = None) -> None:
    """Named check: the reasons the runner can write (AST scan) EQUAL, by exact set equality,
    COMPLETED_REASONS | FAILED_REASONS | {RATE_LIMITED}; no site is unresolved; the three sets
    are disjoint; "running" is scanned and classified a failure. "Every outcome is classified"
    is then checked, not trusted."""
    from proveflow.runner import campaign as c

    reasons, unresolved = scanned_trial_end_reasons(sources)
    if unresolved:
        raise AssertionError(f"trial_end reason sites the scan cannot resolve: {unresolved}")
    sets = (c.COMPLETED_REASONS, c.FAILED_REASONS, frozenset({c.RATE_LIMITED}))
    classified: frozenset[str] = frozenset().union(*sets)
    if sum(len(s) for s in sets) != len(classified):
        raise AssertionError("the classification sets overlap")
    if reasons != classified:
        raise AssertionError(
            f"unclassified trial_end reasons: {sorted(reasons - classified)}; classified but "
            f"never written: {sorted(classified - reasons)}"
        )
    if "running" not in reasons or "running" not in c.FAILED_REASONS:
        raise AssertionError("the 'running' sentinel is not scanned and classified a failure")


def assert_running_never_reaches_trial_end(tmp_path: Path) -> None:
    """Named check (MEASURED, on a REAL trial: real twins, real proxies): an exception that
    escapes the agent loop (an LLM client raising something that is not a ProviderError)
    propagates out of run_trial and leaves NO trial_end, so the initial reason "running" is
    never written. Through the campaign that attempt is recorded failed, named with the
    exception's types (``ExceptionGroup[RuntimeError]``: the harness's task group wraps the
    escape, measured), and is never a result."""
    import anyio

    from proveflow.config import ProviderConfig
    from proveflow.proxy import policy as policy_module
    from proveflow.runner.campaign import AttemptFailed, load_state, results, run_campaign
    from proveflow.runner.transcript import load_transcript
    from proveflow.runner.trial import run_trial

    class Boom:
        async def complete(self, body: dict[str, Any]) -> Any:
            raise RuntimeError("boom")

    out = tmp_path / "out"
    out.mkdir()

    async def attempt(key: str, trial_id: str, budget: Any) -> Any:
        return await run_trial(
            fixture_scenario("clean_utility"), trial_id=trial_id, llm=Boom(),
            provider=ProviderConfig(**AUTHORED), temperature=0.0, seed=0, out_dir=out,
            twin_dir=policy_module.TWIN_ROOT, budget=budget, parent_env=dict(os.environ),
        )  # fmt: skip

    async def go() -> Any:
        return await run_campaign(["t1"], campaign_id="c1", state_path=tmp_path / "s.json",
                                  out_dir=out, budget_total=TOTAL, attempt=attempt)  # fmt: skip

    from campaignchecks import with_story

    try:
        with_story(out, lambda: anyio.run(go))
    except AttemptFailed as exc:
        # MEASURED: the escape arrives wrapped by the proxy harness's nested task groups
        def leaves(e: BaseException | None) -> list[BaseException]:
            if isinstance(e, BaseExceptionGroup):
                return [leaf for inner in e.exceptions for leaf in leaves(inner)]
            return [e] if e is not None else []

        found = leaves(exc.__cause__)
        if not any(isinstance(e, RuntimeError) and str(e) == "boom" for e in found):
            raise AssertionError(f"the escape was not the client's exception: {exc!r}") from None
    else:
        raise AssertionError("an exception escaping the agent loop did not stop the attempt")
    kinds = [e.kind for e in load_transcript(out / "t1-a1.transcript.jsonl")]
    if "trial_end" in kinds or kinds[:1] != ["trial_start"]:
        raise AssertionError(f"a trial_end was written after an escape: {kinds}")
    state = load_state(tmp_path / "s.json")
    got = [(a.status, a.reason, a.exception) for a in state.attempts]
    if got != [("failed", None, "ExceptionGroup[RuntimeError]")] or results(state):
        raise AssertionError(f"the escaped attempt was not recorded as a failure: {got}")


def assert_an_unclassified_reason_stops_the_campaign(tmp_path: Path) -> None:
    """Named check (the allowlist at run time): an attempt ending with a reason in none of the
    three sets STOPS the campaign (UnclassifiedOutcome, the reason named), is recorded FAILED
    with its usage, and is never a result."""
    from proveflow.runner.campaign import UnclassifiedOutcome, budget_spent, load_state, results

    try:
        scripted_campaign(tmp_path, [("gave_up", 100, 10)], ["t1"], [])
    except CampaignRaised as exc:
        if not isinstance(exc.raised, UnclassifiedOutcome) or "gave_up" not in str(exc.raised):
            raise AssertionError(f"the stop is not an unclassified-outcome stop: {exc}") from None
    else:
        raise AssertionError("an unclassified reason did not stop the campaign")
    state = load_state(tmp_path / "c1.campaign.json")
    if [(a.status, a.reason) for a in state.attempts] != [("failed", "gave_up")]:
        raise AssertionError(f"an unclassified reason was recorded as {state.attempts}")
    if results(state) or budget_spent(state) != PER_OK:
        raise AssertionError("an unclassified attempt was counted as a result, or not charged")


def assert_the_state_refuses_an_unclassified_result() -> None:
    """Named check (the VALIDATION layer of the results ledger, independent of classify): an
    Attempt built by hand, not by the loop, that claims a result with a reason that is not a
    COMPLETED reason, or a rate-limited status with another reason, is refused. The
    CLASSIFICATION layer is pinned by assert_an_unclassified_reason_stops_the_campaign."""
    from pydantic import ValidationError

    from proveflow.runner.campaign import Attempt

    base = {"trial_key": "t1", "number": 1, "usage_source": "transcript"}
    for label, fields in (
        ("a result", {"status": "completed", "reason": "gave_up", "verdict": {"x": 1}}),
        ("a result", {"status": "completed", "reason": "provider_error", "verdict": {"x": 1}}),
        ("a 429", {"status": "rate_limited", "reason": "gave_up"}),
        ("a result", {"status": "completed", "reason": "rate_limited", "verdict": {"x": 1}}),
    ):
        try:
            Attempt.model_validate({**base, **fields})
        except ValidationError:
            continue
        raise AssertionError(f"the state accepted {label} with reason {fields['reason']!r}")


RL0 = ("rate_limited", 0, 0)  # a 429 on the attempt's first request: nothing spent


def assert_backoff_between_rate_limited_attempts(tmp_path: Path) -> None:
    """Named check (D3, scripted since the cut): two 429-ended attempts (the first after one
    turn, 110 tokens; the second at its first request, 0), then one that completes (220). The
    campaign waits backoff_s(1) = 2 s and backoff_s(2) = 4 s, starts a NEW attempt each time,
    and only the completed attempt is a result; every attempt's usage is in the budget
    ledger."""
    from proveflow.runner.campaign import budget_spent, load_state, results

    sleeps: list[float] = []
    scripted_campaign(tmp_path, [RL, RL0, ("final_answer", 200, 20)], ["t1"], sleeps)
    state = load_state(tmp_path / "c1.campaign.json")
    if sleeps != [2.0, 4.0]:
        raise AssertionError(f"the campaign did not back off 2 s then 4 s: {sleeps}")
    got = [(a.number, a.status) for a in state.attempts]
    if got != [(1, "rate_limited"), (2, "rate_limited"), (3, "completed")]:
        raise AssertionError(f"each 429 did not end its attempt: {got}")
    if [a.number for a in results(state).values()] != [3]:
        raise AssertionError("a rate-limited attempt was counted as a result")
    if budget_spent(state) != PER_OK + 0 + 2 * PER_OK:
        raise AssertionError(
            f"the budget ledger is not every attempt's usage: {budget_spent(state)}"
        )


def assert_rate_limit_exhaustion_stops_and_resumes(tmp_path: Path) -> None:
    """Named check (D3, scripted since the cut): MAX_RATE_LIMITED_ATTEMPTS consecutive
    429-ended attempts stop the campaign with the state saved; a resume starts attempt
    MAX + 1 and completes."""
    from proveflow.runner.campaign import (
        MAX_RATE_LIMITED_ATTEMPTS,
        RateLimitExhausted,
        load_state,
        results,
    )

    sleeps: list[float] = []
    try:
        scripted_campaign(tmp_path, [RL0] * MAX_RATE_LIMITED_ATTEMPTS, ["t1"], sleeps)
    except CampaignRaised as exc:
        if not isinstance(exc.raised, RateLimitExhausted):
            raise AssertionError(f"consecutive 429s stopped for another reason: {exc}") from None
    else:
        raise AssertionError("consecutive 429s did not stop the campaign")
    if len(sleeps) != MAX_RATE_LIMITED_ATTEMPTS - 1:
        raise AssertionError(f"backoffs before the stop: {sleeps}")
    scripted_campaign(tmp_path, [OK], ["t1"], sleeps)
    done = results(load_state(tmp_path / "c1.campaign.json"))
    if [a.number for a in done.values()] != [MAX_RATE_LIMITED_ATTEMPTS + 1]:
        raise AssertionError(f"the resume did not complete a new attempt: {done}")


def assert_corrupt_state_fails_closed(tmp_path: Path) -> None:
    """Named check (D4, scripted since the cut): a state file that does not parse, whose
    sha256 does not match (a LOWER spend written in with the hash left as it was), that does
    not validate, or that belongs to another plan makes the campaign refuse to run:
    CorruptCampaignState, and NO attempt starts (the attempt function is never called)."""
    import json

    from proveflow.runner import campaign as mod
    from proveflow.runner.campaign import CorruptCampaignState

    good = tmp_path / "good"
    good.mkdir()
    scripted_campaign(good, [OK], ["t1"], [])
    text = (good / "c1.campaign.json").read_text(encoding="utf-8")
    tampered = json.loads(text)
    tampered["state"]["attempts"][0]["tokens_in"] = 0  # a lower spend, hash left as it was
    invalid = json.loads(text)
    invalid["state"]["attempts"][0]["status"] = "started"
    invalid["sha256"] = mod._digest(invalid["state"])
    cases = {"truncated": text[: len(text) // 2], "tampered": json.dumps(tampered),
             "invalid": json.dumps(invalid), "other_plan": text}  # fmt: skip
    for name, content in cases.items():
        where = tmp_path / name
        where.mkdir()
        (where / "c1.campaign.json").write_text(content, encoding="utf-8")
        plan = ["t1", "t2"] if name == "other_plan" else ["t1"]
        try:
            scripted_campaign(where, [OK, OK], plan, [])
        except CampaignRaised as exc:
            if not isinstance(exc.raised, CorruptCampaignState):
                raise AssertionError(f"{name}: refused for another reason: {exc}") from None
            if exc.fn.calls:
                raise AssertionError(f"{name}: an attempt ran on a corrupt state") from None
            continue
        raise AssertionError(f"a {name} state file was accepted")


def assert_an_interrupted_attempt_is_charged(tmp_path: Path) -> None:
    """Named check (D4, scripted since the cut): an attempt still 'started' in the state file
    (the process died) is finalized on resume as 'interrupted' and charged what its transcript
    records, or, with no readable transcript, its FULL reservation (unknown_spend_charge,
    limits.max_trial_tokens), never zero."""
    from proveflow.runner.campaign import Attempt, CampaignState, load_state, save_state
    from proveflow.runner.limits import TrialLimits

    for label, keep_transcript in (("with", True), ("without", False)):
        work = tmp_path / label
        work.mkdir()
        try:  # leaves t1-a1's transcript (110 tokens)
            scripted_campaign(work, [("provider_error", 100, 10)], ["t1"], [])
        except CampaignRaised:
            pass
        if not keep_transcript:
            (work / "out" / "t1-a1.transcript.jsonl").unlink()
        died = Attempt(trial_key="t1", number=1, status="started")  # the process died here
        state = CampaignState(campaign_id="c1", budget_total=TOTAL, plan=("t1",), attempts=(died,))
        save_state(work / "c1.campaign.json", state)
        scripted_campaign(work, [OK], ["t1"], [])
        first = load_state(work / "c1.campaign.json").attempts[0]
        want = PER_OK if keep_transcript else TrialLimits().max_trial_tokens
        source = "transcript" if keep_transcript else "reservation"
        got = (first.status, first.tokens_in + first.tokens_out, first.usage_source)
        if got != ("interrupted", want, source):
            raise AssertionError(
                f"an interrupted attempt ({label} transcript) was charged "
                f"{first.tokens_in + first.tokens_out} from {first.usage_source}, want {want}"
            )


def assert_retry_after_extends_never_shortens(tmp_path: Path) -> None:
    """Named check (claim c: the ARITHMETIC, scripted): three 429-ended attempts, each its
    trial's FIRST backoff (schedule 2 s), carrying Retry-After 30, 1 and garbage, wait 30 (the
    header decided), 2 and 2 (the schedule decided); the state file records the wait, what
    decided it and the header text. (Header extraction is claim a, at the client; the wiring
    to the outcome is claim b, on one real trial: campaignchecks.)"""
    from proveflow.runner.campaign import load_state

    sleeps: list[float] = []
    steps = [(*RL, "30"), OK, (*RL, "1"), OK, (*RL, "soon, maybe"), OK]
    scripted_campaign(tmp_path, steps, ["t1", "t2", "t3"], sleeps)
    if sleeps != [30.0, 2.0, 2.0]:
        raise AssertionError(f"Retry-After did not extend-but-never-shorten the wait: {sleeps}")
    state = load_state(tmp_path / "c1.campaign.json")
    waits = [(a.wait_s, a.wait_source, a.retry_after_header) for a in state.attempts
             if a.wait_s is not None]  # fmt: skip
    want = [(30.0, "retry_after", "30"), (2.0, "schedule", "1"), (2.0, "schedule", "soon, maybe")]
    if waits != want:
        raise AssertionError(f"the state file does not explain the waits: {waits}")


def assert_the_lifetime_count_is_visible(tmp_path: Path) -> None:
    """Named check: the per-run consecutive count resets on resume, but the key's LIFETIME
    rate-limited count is surfaced (summary(), and the RateLimitExhausted message): after two
    exhausted runs a human sees 10 rate-limited of 10 attempts and none completed."""
    from proveflow.runner.campaign import (
        MAX_RATE_LIMITED_ATTEMPTS,
        RateLimitExhausted,
        load_state,
        summary,
    )

    n = MAX_RATE_LIMITED_ATTEMPTS
    messages: list[str] = []
    for _ in range(2):
        try:
            scripted_campaign(tmp_path, [RL] * n, ["t1"], [])
        except CampaignRaised as exc:
            if isinstance(exc.raised, RateLimitExhausted):
                messages.append(str(exc.raised))
    want = f"{2 * n} rate-limited of {2 * n} attempts over the campaign's life, none completed"
    if len(messages) != 2 or want not in messages[1]:
        raise AssertionError(f"the lifetime count is not visible on the second stop: {messages}")
    life = summary(load_state(tmp_path / "c1.campaign.json"))["t1"]
    if (life.attempts, life.rate_limited, life.completed) != (2 * n, 2 * n, False):
        raise AssertionError(f"summary() does not carry the lifetime count: {life}")


def assert_an_overspent_state_fails_closed(tmp_path: Path) -> None:
    """Named check: a state file whose attempts spent MORE than the campaign's total fails
    closed, named (BudgetOverspent), before any attempt starts; RunBudget.spend alone lets
    ``remaining`` go negative (unit test test_run_budget_spend_alone_goes_negative)."""
    from proveflow.runner.campaign import Attempt, BudgetOverspent, CampaignState, save_state

    over = Attempt(trial_key="t1", number=1, status="failed", reason="provider_error",
                   tokens_in=TOTAL, tokens_out=1, usage_source="transcript")  # fmt: skip
    state = CampaignState(campaign_id="c1", budget_total=TOTAL, plan=("t1",), attempts=(over,))
    save_state(tmp_path / "c1.campaign.json", state)
    try:
        scripted_campaign(tmp_path, [OK], ["t1"], [])
    except CampaignRaised as exc:
        if isinstance(exc.raised, BudgetOverspent) and exc.fn.calls == 0:
            return
        raise AssertionError(
            f"an overspent state did not fail closed before any attempt: {exc}"
        ) from None
    raise AssertionError("an overspent state file was accepted")


def assert_unknown_spend_is_the_full_reservation() -> None:
    """Named check: ONE function names the unknown-spend charge, and it equals the trial's
    reservation (``max_trial_tokens``, what RunBudget.reserve checks), which equals
    max_tokens_in + max_tokens_out, for the default caps and for tightened ones."""
    from proveflow.runner.campaign import unknown_spend_charge
    from proveflow.runner.limits import TrialLimits

    for limits in (TrialLimits(), TrialLimits(max_tokens_in=100, max_tokens_out=20),
                   TrialLimits(max_tokens_in=1, max_tokens_out=8_000)):  # fmt: skip
        tin, tout = unknown_spend_charge(limits)
        reservation = limits.max_trial_tokens
        if not tin + tout == reservation == limits.max_tokens_in + limits.max_tokens_out:
            raise AssertionError(f"the unknown-spend charge is not the full reservation: {limits}")
