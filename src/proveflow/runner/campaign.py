"""Campaign state: 429 backoff and resume (Phase 6 step 2; D3, D4). Offline machinery only: the
campaign ENGINE (scheduling flows x models, Wilson aggregation) is Phase 7.

A campaign runs an ordered plan of trial keys. Each run of one trial is an ATTEMPT, a
``runner.trial.run_trial`` call with its own trial id ``<key>-a<n>`` and its own transcript.

* EVERY OUTCOME IS CLASSIFIED, by allowlist (``classify``): an attempt's reason is in exactly
  one of ``COMPLETED_REASONS``, ``FAILED_REASONS`` or ``{RATE_LIMITED}``, and any other reason
  STOPS the campaign (``UnclassifiedOutcome``), never defaults to a result. The three sets
  equal, by exact set equality, every trial_end reason the runner can write, found by an AST
  scan of runner/agent.py and runner/trial.py (``campaignloopchecks.assert_every_trial_end_
  reason_is_classified``). That claim covers ``Attempt.reason`` only, the reason the RUNNER
  wrote. An attempt that RAISED wrote none: it is recorded failed with ``Attempt.exception``
  (``exception_name``) instead, a separate field, never classified and never a reason.
  - COMPLETED: ``final_answer`` and every ``limit:*``. A limit-ended trial is a RESULT: it ran
    under declared caps recorded in its ``trial_start``, its transcript and every cassette are
    complete, and the oracle's verdict over what happened is valid (a compromise before the cap
    is real; none means none WITHIN the caps, the condition every trial carries; R3 reports
    ``not_evaluable`` without a final answer, never "not fired"). Its cost: an agent that would
    have been compromised after the cap counts as not compromised, and ``limit:wall_clock``
    depends on provider latency, so which trials it cuts does not reproduce. Phase 7 reports
    limit-ended trials per reason (docs/BACKLOG.md).
  - FAILED: the provider/response errors, and ``running``, ``AgentOutcome``'s initial value
    (nothing concluded). It never reaches trial_end today (measured: an exception escaping
    the agent loop leaves NO trial_end, ``campaignchecks.assert_running_never_reaches_trial_
    end``); it is classified a failure anyway, because "unreachable today" is luck.
* D3, 429 at the campaign level: an HTTP 429 ENDS the attempt (trial_end reason
  ``rate_limited``; never retried inside a trial). The campaign waits, then starts a NEW
  attempt. The wait after the k-th consecutive 429-ended attempt of one trial is
  ``max(backoff_s(k), retry_after)`` (``wait_for``): the provider's ``Retry-After`` is honoured
  in its NUMERIC form only (RFC 9110 s10.2.3, delay-seconds = 1*DIGIT, seconds), and only when
  sane (<= ``RETRY_AFTER_MAX_S``); the HTTP-date form, garbage, or an absent header leave
  proveflow's own schedule unchanged. Honouring it is never SHORTER than the schedule, so it
  needs no provider-specific documentation. Why honour it: a 429-ended attempt already PAID
  for its earlier turns, and retrying before the provider is ready pays for them again. Which
  of the two decided the wait, and the header text, are recorded on the attempt in the state
  file. After ``MAX_RATE_LIMITED_ATTEMPTS`` consecutive ones (counted per RUN) it stops
  (``RateLimitExhausted``), with the state saved and the key's LIFETIME count in the message
  (``summary``); the budget is the real backstop across resumes.
* D4, TWO LEDGERS, never derived from each other:
  - BUDGET: every attempt's provider-reported usage (F10, read from its transcript) counts,
    whatever its outcome. ``budget_spent`` is the ONE function that sums it; each attempt's
    budget is rebuilt from the STATE FILE's per-attempt usage (``budget_of``). A spend over
    the total (reachable: the per-trial caps are checked BEFORE each request, so a trial's
    last response can overshoot its reservation) fails closed (``BudgetOverspent``).
  - RESULTS: each COMPLETED trial counted once (``results``); at most one completed attempt
    per key (validator). **THE RESULTS LEDGER IS THE ONLY SOURCE OF COUNTED TRIALS.** A
    transcript's verdict is NOT evidence that a trial counted: ``run_trial`` gives a verdict
    (compromised=false) to a rate-limited or failed attempt too, so an aggregation that read
    verdicts off transcripts would count every attempt that measured nothing as a safe trial
    and dilute the ASR. Aggregate from ``results(state)`` only.
* The state file is SEPARATE from the transcripts (transcripts are evidence and are never
  edited). It is written atomically (a sibling temp file, then ``Path.replace``) with the
  sha256 of its canonical content; a state file that does not parse, validate, hash or match
  the campaign it is opened for FAILS CLOSED (``CorruptCampaignState``): nothing runs.
* Unknown spend is charged at its maximum, never at zero, by ONE function
  (``unknown_spend_charge``: the trial's full reservation, ``limits.max_trial_tokens``): for an
  attempt still ``started`` on resume (the process died) whose transcript is unreadable, and
  for an attempt that raised before its transcript existed.
* Any other failed attempt (a FAILED reason, an exception such as an invalid trial) STOPS the
  campaign (``AttemptFailed``): fail closed, a human looks. Resume retries it. (Phase 7: one
  bad response then halts a long run; a bounded skip-and-record is a deferred decision,
  docs/BACKLOG.md.)
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any, Literal, Protocol

import anyio
from pydantic import Field, ValidationError, model_validator

from proveflow.core._base import FrozenModel
from proveflow.proxy.cassette import canonical
from proveflow.runner.limits import BudgetExhausted, RunBudget, TrialLimits
from proveflow.runner.transcript import LlmResponse, load_transcript

log = logging.getLogger(__name__)

STATE_SCHEMA = 1
TRIAL_KEY_PATTERN = r"^[a-z0-9][a-z0-9_]{0,40}$"
# DESIGN values, not measurements (provider limits are not modelled):
BACKOFF_BASE_S = 2.0  # first wait after a 429-ended attempt
BACKOFF_CAP_S = 60.0  # no single scheduled wait is longer
MAX_RATE_LIMITED_ATTEMPTS = 5  # consecutive 429-ended attempts of one trial (per run), then stop
RETRY_AFTER_MAX_S = 600  # a larger Retry-After is treated as absurd: the schedule decides

# THE classification (exact set equality with what the runner can write, by AST scan).
RATE_LIMITED = "rate_limited"
COMPLETED_REASONS = frozenset({"final_answer", "limit:max_turns", "limit:max_tool_calls",
                               "limit:max_tokens_in", "limit:max_tokens_out",
                               "limit:wall_clock"})  # fmt: skip
FAILED_REASONS = frozenset({"provider_error", "usage_missing", "malformed_response",
                            "replay_mismatch", "running"})  # fmt: skip

AttemptStatus = Literal["started", "completed", "rate_limited", "failed", "interrupted"]
Classified = Literal["completed", "rate_limited", "failed"]


class CorruptCampaignState(RuntimeError):
    """The state file cannot be trusted; the campaign does not run (fail closed)."""


class RateLimitExhausted(RuntimeError):
    """Too many consecutive 429-ended attempts of one trial; the state is saved."""


class AttemptFailed(RuntimeError):
    """An attempt failed for a reason other than a 429; the state is saved."""


class UnclassifiedOutcome(AttemptFailed):
    """An attempt ended with a reason in none of the three sets; the state is saved."""


class BudgetOverspent(BudgetExhausted):
    """The state file's attempts spent more than the campaign's total (fail closed)."""


def classify(reason: str) -> Classified:
    """Allowlist: a reason in none of the three sets raises, it is never a result."""
    if reason in COMPLETED_REASONS:
        return "completed"
    if reason == RATE_LIMITED:
        return "rate_limited"
    if reason in FAILED_REASONS:
        return "failed"
    raise UnclassifiedOutcome(f"unclassified trial_end reason {reason!r}")


class Attempt(FrozenModel):
    trial_key: str = Field(pattern=TRIAL_KEY_PATTERN)
    number: int = Field(ge=1)
    status: AttemptStatus
    # TWO different things, kept in two fields (never one ambiguous "reason"):
    # ``reason``: the trial_end reason exactly as the RUNNER wrote it (what the AST scan
    #   covers): completed/rate_limited -> it classifies to that status (validator); failed ->
    #   a FAILED reason, or the UNCLASSIFIED reason that stopped the campaign.
    # ``exception``: ``exception_name`` of what the attempt RAISED (it wrote no trial_end
    #   reason); never classified, because there is no runner reason to classify.
    reason: str | None = None
    exception: str | None = None
    tokens_in: int = Field(default=0, ge=0)
    tokens_out: int = Field(default=0, ge=0)
    usage_source: Literal["none", "transcript", "reservation"] = "none"
    verdict: dict[str, Any] | None = None  # completed only
    # rate_limited only: the wait that followed, what decided it, and the header text
    wait_s: float | None = Field(default=None, ge=0)
    wait_source: Literal["schedule", "retry_after"] | None = None
    retry_after_header: str | None = None

    @property
    def attempt_id(self) -> str:
        return attempt_id(self.trial_key, self.number)

    @model_validator(mode="after")
    def _consistent(self) -> Attempt:
        if (self.status == "completed") != (self.verdict is not None):
            raise ValueError("exactly a completed attempt carries a verdict")
        if (self.status == "started") != (self.usage_source == "none"):
            raise ValueError("a started attempt has no usage yet; a finished one has a source")
        if self.status == "started" and (self.tokens_in or self.tokens_out):
            raise ValueError("a started attempt has no usage yet")
        if (self.wait_s is None) != (self.wait_source is None):
            raise ValueError("a wait and what decided it go together")
        if self.status != "rate_limited" and (self.wait_s is not None or self.retry_after_header):
            raise ValueError("only a rate-limited attempt records a wait or a Retry-After")
        if self.reason is not None and self.exception is not None:
            raise ValueError("an attempt has a runner reason OR an exception, never both")
        if self.status in ("started", "interrupted") and (self.reason or self.exception):
            raise ValueError("a started or interrupted attempt has no reason and no exception")
        self._check_result_reason()
        if self.status == "failed":
            if (self.reason is None) == (self.exception is None):
                raise ValueError("a failed attempt has exactly one of a reason or an exception")
            if self.reason in COMPLETED_REASONS or self.reason == RATE_LIMITED:
                raise ValueError("a failed attempt's reason is not a result or a 429")
        return self

    def _check_result_reason(self) -> None:
        """The VALIDATION layer of the results ledger, independent of ``classify`` (the
        CLASSIFICATION layer): whatever classified it, a completed attempt's reason is a
        COMPLETED reason and a rate-limited one's is rate_limited. So the state file cannot
        hold a result with an unclassified reason even if ``classify`` is wrong. Neither layer
        subsumes the other (campaignloopchecks, one mutation per layer plus the layering)."""
        if self.status == "completed" and self.reason not in COMPLETED_REASONS:
            raise ValueError("a completed attempt's reason is a COMPLETED reason")
        if self.status == "rate_limited" and self.reason != RATE_LIMITED:
            raise ValueError("a rate-limited attempt's reason is rate_limited")


ModelSide = Literal["scripted", "replay", "provider"]


class CellSpec(FrozenModel):
    """One campaign cell (Phase 7.1, runner/engine.py): which payload, carrier, goal and model
    a trial key runs. ``source_dataset`` is the ONLY grouping axis aggregation uses;
    ``attack_family`` is deliberately absent (a per-source taxonomy, never a cross-source axis:
    docs/METHODOLOGY.md threat 13)."""

    source_dataset: str
    record_id: str
    carrier: str
    goal_kind: str
    model: str


class SourceDraw(FrozenModel):
    population: int = Field(ge=0)  # records of this source available to the sampler
    drawn: int = Field(ge=0)  # records drawn (the sampling fraction is drawn / population)


class SamplingRecord(FrozenModel):
    """The stratified draw (Phase 7.1): EQUAL per source, deterministic from ``seed``."""

    seed: int
    per_source_n: int = Field(ge=1)
    per_source: dict[str, SourceDraw]


class CampaignState(FrozenModel):
    schema_version: Literal[1] = 1  # STATE_SCHEMA
    campaign_id: str = Field(pattern=TRIAL_KEY_PATTERN)
    budget_total: int = Field(ge=1)
    plan: tuple[str, ...] = Field(min_length=1)
    attempts: tuple[Attempt, ...] = ()
    # Phase 7.1 (runner/engine.py); absent for a bare run_campaign. A campaign whose model side
    # is not recorded cannot be REPORTED (runner/report.py fails closed on None).
    model_side: ModelSide | None = None
    cells: dict[str, CellSpec] = Field(default_factory=dict)
    sampling: SamplingRecord | None = None

    @model_validator(mode="after")
    def _consistent(self) -> CampaignState:
        if len(set(self.plan)) != len(self.plan):
            raise ValueError("duplicate trial key in the plan")
        seen: dict[str, int] = {}
        done: set[str] = set()
        for i, a in enumerate(self.attempts):
            if a.trial_key not in self.plan:
                raise ValueError(f"attempt for {a.trial_key!r}, which is not in the plan")
            if a.number != seen.get(a.trial_key, 0) + 1:
                raise ValueError(f"attempt numbers of {a.trial_key!r} are not 1, 2, ...")
            seen[a.trial_key] = a.number
            if a.trial_key in done:
                raise ValueError(f"an attempt after {a.trial_key!r} completed")
            if a.status == "completed":
                done.add(a.trial_key)  # RESULTS: one completed attempt per key
            if a.status == "started" and i != len(self.attempts) - 1:
                raise ValueError("only the last attempt can still be 'started'")
        if self.cells and set(self.cells) != set(self.plan):
            raise ValueError("the cells are not exactly the plan's trial keys")
        return self


def attempt_id(trial_key: str, number: int) -> str:
    """The attempt's trial id for ``run_trial`` (its transcript is ``<id>.transcript.jsonl``)."""
    return f"{trial_key}-a{number}"


# --- waiting -------------------------------------------------------------------------------


def backoff_s(k: int) -> float:
    """proveflow's own wait after the k-th consecutive 429-ended attempt: 2, 4, 8, ... capped."""
    if k < 1:
        raise ValueError("k starts at 1")
    return float(min(BACKOFF_BASE_S * 2 ** (k - 1), BACKOFF_CAP_S))


_DELAY_SECONDS = re.compile(r"[0-9]+")  # RFC 9110 s10.2.3: delay-seconds = 1*DIGIT


def retry_after_s(header: str | None) -> float | None:
    """The NUMERIC Retry-After (delay-seconds, RFC 9110 s10.2.3), or None: absent, the
    HTTP-date form (ignored), anything else unparseable, or above ``RETRY_AFTER_MAX_S``."""
    if header is None or not _DELAY_SECONDS.fullmatch(header.strip()):
        return None
    seconds = int(header.strip())
    return float(seconds) if seconds <= RETRY_AFTER_MAX_S else None


def wait_for(k: int, header: str | None) -> tuple[float, Literal["schedule", "retry_after"]]:
    """The wait after the k-th consecutive 429-ended attempt: ``max(backoff_s(k), retry_after)``,
    never shorter than the schedule, and which of the two decided it."""
    own, theirs = backoff_s(k), retry_after_s(header)
    if theirs is not None and theirs > own:
        return theirs, "retry_after"
    return own, "schedule"


# --- the two ledgers -----------------------------------------------------------------------


def budget_spent(state: CampaignState) -> int:
    """THE budget ledger: the usage of EVERY attempt in the state file, whatever its outcome."""
    return sum(a.tokens_in + a.tokens_out for a in state.attempts)


def budget_of(state: CampaignState) -> RunBudget:
    """The budget an attempt runs with, rebuilt from the state file (never from memory).
    ``RunBudget.spend`` itself never refuses an overshoot (its ``remaining`` would go
    negative), so an overspent state fails closed HERE, named."""
    spent = budget_spent(state)
    if spent > state.budget_total:
        raise BudgetOverspent(
            f"the state file's attempts spent {spent} tokens, over the campaign's total "
            f"{state.budget_total}; refusing to start further attempts"
        )
    budget = RunBudget(total=state.budget_total)
    budget.spend(spent)
    return budget


def results(state: CampaignState) -> dict[str, Attempt]:
    """THE results ledger, the ONLY source of counted trials: each completed trial once, by
    key, in plan order. Never aggregate verdicts read off transcripts (module docstring)."""
    done = {a.trial_key: a for a in state.attempts if a.status == "completed"}
    return {k: done[k] for k in state.plan if k in done}


class KeySummary(FrozenModel):
    attempts: int
    rate_limited: int  # LIFETIME, across every run of this campaign
    failed: int
    completed: bool


def summary(state: CampaignState) -> dict[str, KeySummary]:
    """Per key, across the campaign's whole life: so a human resuming for the fourth time sees
    that a key burned twenty attempts and nothing completed."""
    out: dict[str, KeySummary] = {}
    for key in state.plan:
        mine = [a for a in state.attempts if a.trial_key == key]
        out[key] = KeySummary(
            attempts=len(mine),
            rate_limited=sum(a.status == "rate_limited" for a in mine),
            failed=sum(a.status in ("failed", "interrupted") for a in mine),
            completed=any(a.status == "completed" for a in mine),
        )
    return out


def unknown_spend_charge(limits: TrialLimits) -> tuple[int, int]:
    """THE charge for spend that cannot be read: the trial's FULL reservation,
    ``limits.max_trial_tokens``, split as (max_tokens_in, max_tokens_out) because an attempt
    records in and out separately. The identity sum == max_trial_tokens is pinned by test."""
    return limits.max_tokens_in, limits.max_tokens_out


# --- the state file ------------------------------------------------------------------------


def _digest(body: dict[str, Any]) -> str:
    return hashlib.sha256(canonical(body).encode("utf-8")).hexdigest()


def save_state(path: Path, state: CampaignState) -> None:
    body = state.model_dump(mode="json")
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"sha256": _digest(body), "state": body}, indent=2), "utf-8")
    tmp.replace(path)


def load_state(path: Path) -> CampaignState:
    """Fail closed: any defect raises ``CorruptCampaignState`` and nothing runs."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise CorruptCampaignState(f"{path.name}: unreadable ({type(exc).__name__})") from None
    if not isinstance(raw, dict) or set(raw) != {"sha256", "state"}:
        raise CorruptCampaignState(f"{path.name}: not a campaign state file")
    body = raw["state"]
    if not isinstance(body, dict) or raw["sha256"] != _digest(body):
        raise CorruptCampaignState(f"{path.name}: sha256 does not match its content")
    try:
        return CampaignState.model_validate(body)
    except ValidationError as exc:
        raise CorruptCampaignState(f"{path.name}: invalid ({exc.error_count()} errors)") from None


def transcript_usage(path: Path) -> tuple[int, int] | None:
    """(tokens in, tokens out) the provider reported in one attempt's transcript (F10), or None
    when it is missing or unreadable."""
    try:
        events = load_transcript(path)
    except Exception:  # a torn or missing transcript: the caller charges the reservation
        return None
    responses = [e for e in events if isinstance(e, LlmResponse)]
    return (sum(e.tokens_in or 0 for e in responses), sum(e.tokens_out or 0 for e in responses))


def _usage(
    path: Path, limits: TrialLimits
) -> tuple[int, int, Literal["transcript", "reservation"]]:
    usage = transcript_usage(path)
    if usage is None:
        tin, tout = unknown_spend_charge(limits)
        return tin, tout, "reservation"
    return usage[0], usage[1], "transcript"


# --- the loop ------------------------------------------------------------------------------


class AttemptResult(Protocol):
    """What the campaign reads from one attempt (``runner.trial.TrialResult`` satisfies it)."""

    @property
    def outcome(self) -> Any: ...  # .reason, .retry_after_header

    @property
    def verdict(self) -> Any: ...  # .model_dump(mode="json")


AttemptFn = Callable[[str, str, RunBudget], Awaitable[AttemptResult]]
SleepFn = Callable[[float], Awaitable[None]]


def _open(state_path: Path, campaign_id: str, plan: Sequence[str], budget_total: int,
          out_dir: Path, limits: TrialLimits, spec: dict[str, Any]) -> CampaignState:  # fmt: skip
    fresh = CampaignState(campaign_id=campaign_id, budget_total=budget_total, plan=tuple(plan),
                          **spec)  # fmt: skip
    if not state_path.exists():
        save_state(state_path, fresh)
        return fresh
    state = load_state(state_path)
    mine = (state.campaign_id, state.plan, state.budget_total, state.model_side, state.cells,
            state.sampling)  # fmt: skip
    theirs = (fresh.campaign_id, fresh.plan, fresh.budget_total, fresh.model_side, fresh.cells,
              fresh.sampling)  # fmt: skip
    if mine != theirs:
        raise CorruptCampaignState(f"{state_path.name} belongs to another campaign or plan")
    if state.attempts and state.attempts[-1].status == "started":
        last = state.attempts[-1]
        tin, tout, source = _usage(out_dir / f"{last.attempt_id}.transcript.jsonl", limits)
        final = Attempt.model_validate({**last.model_dump(mode="json"), "status": "interrupted",
                                        "tokens_in": tin, "tokens_out": tout,
                                        "usage_source": source})  # fmt: skip
        state = CampaignState.model_validate(
            {**state.model_dump(mode="json"),
             "attempts": [a.model_dump(mode="json") for a in (*state.attempts[:-1], final)]}
        )  # fmt: skip
        save_state(state_path, state)
    return state


def exception_name(exc: BaseException) -> str:
    """``Attempt.exception`` for an attempt that RAISED: its type, and for an exception group (the
    proxy harness's nested task groups wrap what escapes a trial, three deep, measured) its
    LEAF types, flattened: ``ExceptionGroup[RuntimeError]``, so the state file says what
    actually failed."""
    if isinstance(exc, BaseExceptionGroup):
        return f"{type(exc).__name__}[{','.join(sorted(set(_leaf_types(exc))))}]"
    return type(exc).__name__


def _leaf_types(exc: BaseException) -> list[str]:
    if isinstance(exc, BaseExceptionGroup):
        return [name for e in exc.exceptions for name in _leaf_types(e)]
    return [type(exc).__name__]


def _finish(started: Attempt, out_dir: Path, status: AttemptStatus, reason: str | None,
            limits: TrialLimits, **extra: Any) -> Attempt:  # fmt: skip
    """``reason``: the runner's trial_end reason (None when the attempt raised; then the
    caller passes ``exception=``)."""
    tin, tout, source = _usage(out_dir / f"{started.attempt_id}.transcript.jsonl", limits)
    return Attempt.model_validate({**started.model_dump(mode="json"), "status": status,
                                   "reason": reason, "tokens_in": tin, "tokens_out": tout,
                                   "usage_source": source, **extra})  # fmt: skip


async def run_campaign(
    plan: Sequence[str],
    *,
    campaign_id: str,
    state_path: Path,
    out_dir: Path,
    budget_total: int,
    attempt: AttemptFn,
    limits: TrialLimits | None = None,
    sleep: SleepFn = anyio.sleep,
    model_side: ModelSide | None = None,
    cells: dict[str, CellSpec] | None = None,
    sampling: SamplingRecord | None = None,
) -> CampaignState:
    """Run (or resume) the plan. ``attempt(key, attempt_id, budget)`` runs ONE attempt (in
    production a ``run_trial`` with that trial id and budget). Raises ``BudgetExhausted``
    (``BudgetOverspent``), ``RateLimitExhausted``, ``AttemptFailed`` (``UnclassifiedOutcome``)
    or ``CorruptCampaignState``; the state file is saved before any of them."""
    limits = limits or TrialLimits()
    spec = {"model_side": model_side, "cells": cells or {}, "sampling": sampling}
    state = _open(state_path, campaign_id, plan, budget_total, out_dir, limits, spec)

    def record(a: Attempt) -> None:
        nonlocal state
        kept = state.attempts[:-1] if a.status != "started" else state.attempts
        state = CampaignState.model_validate(
            {**state.model_dump(mode="json"),
             "attempts": [x.model_dump(mode="json") for x in (*kept, a)]}
        )  # fmt: skip
        save_state(state_path, state)

    for key in plan:
        consecutive = 0  # per run: a resume starts its own count (summary() has the lifetime)
        while key not in results(state):
            budget = budget_of(state)  # D4: from the state file's per-attempt usage
            budget.reserve(limits)  # BudgetExhausted: nothing started, state already saved
            number = sum(1 for a in state.attempts if a.trial_key == key) + 1
            started = Attempt(trial_key=key, number=number, status="started")
            record(started)
            try:
                result = await attempt(key, started.attempt_id, budget)
            except Exception as exc:  # an invalid trial, a harness failure: no result
                name = exception_name(exc)
                record(_finish(started, out_dir, "failed", None, limits, exception=name))
                raise AttemptFailed(f"{started.attempt_id}: {name}") from exc
            reason = result.outcome.reason
            try:
                kind = classify(reason)
            except UnclassifiedOutcome:
                record(_finish(started, out_dir, "failed", reason, limits))
                raise
            if kind == "rate_limited":
                consecutive += 1
                header = result.outcome.retry_after_header
                if consecutive >= MAX_RATE_LIMITED_ATTEMPTS:
                    record(_finish(started, out_dir, "rate_limited", reason, limits,
                                   retry_after_header=header))  # fmt: skip
                    life = summary(state)[key]
                    raise RateLimitExhausted(
                        f"{key}: {consecutive} consecutive 429-ended attempts in this run; "
                        f"{life.rate_limited} rate-limited of {life.attempts} attempts over "
                        f"the campaign's life, {'one' if life.completed else 'none'} completed; "
                        "resume later"
                    )
                wait, source = wait_for(consecutive, header)
                record(_finish(started, out_dir, "rate_limited", reason, limits, wait_s=wait,
                               wait_source=source, retry_after_header=header))  # fmt: skip
                log.info("rate limited; backing off", extra={
                    "attempt": started.attempt_id, "wait_s": wait, "wait_source": source,
                    "lifetime_rate_limited": summary(state)[key].rate_limited})  # fmt: skip
                await sleep(wait)
            elif kind == "failed":
                record(_finish(started, out_dir, "failed", reason, limits))
                raise AttemptFailed(f"{started.attempt_id}: {reason}")
            else:
                record(_finish(started, out_dir, "completed", reason, limits,
                               verdict=result.verdict.model_dump(mode="json")))  # fmt: skip
    return state
