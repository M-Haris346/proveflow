"""Trials, verdicts, and run metadata (everything a number must be reported with)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from proveflow.core._base import FrozenModel
from proveflow.core.attacks import Attack


class RuleHit(StrEnum):
    R1_EXFIL = "r1_exfil"
    R2_GOAL_ACTION = "r2_goal_action"
    R3_ANSWER_HIJACK = "r3_answer_hijack"
    R4_SUSPICIOUS = "r4_suspicious"  # review only, never counted as compromise


class Trial(FrozenModel):
    """One (flow, attack | None, model, mitigation, seed) execution.

    ``attack is None`` marks the clean paired trial run with the same seed.
    """

    id: str
    flow_id: str
    attack: Attack | None = None
    model: str
    mitigation_id: str | None = None
    seed: int


class Verdict(FrozenModel):
    """Deterministic oracle output for one trial."""

    trial_id: str
    utility: bool
    compromised: bool
    rule_hits: tuple[RuleHit, ...] = ()
    blocked_by_mitigation: bool = False
    tokens_in: int = Field(ge=0)
    tokens_out: int = Field(ge=0)
    latency_ms: float = Field(ge=0.0)


class RunMeta(FrozenModel):
    """Reporting context: every published number must carry all of this."""

    run_id: str
    model: str
    provider: str
    provider_version: str | None = None
    temperature: float
    seed_policy: str
    corpus_revision: str | None = None
    proveflow_version: str
    hardware: str
    started_at: datetime
    finished_at: datetime | None = None
