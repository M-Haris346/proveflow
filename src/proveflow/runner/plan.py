"""The campaign PLAN FILE (Phase 7.3a). ONE file feeds the scripted dry run AND the paid run, so
the dry run proves something about the paid run (D5, Haris's F2 ruling, 2026-11-24).

* What may differ between the two runs: ONLY the model side (scripted / provider) and the ROOT
  directory. The state file records the model side, and ``runner.campaign._open`` refuses a state
  file of the other side (campaign.py:434-439), so the dry run's state can never be resumed as
  the paid one. That refusal is correct and stays.
* ``campaign_id_of(plan)`` is ``<name>_<plan sha256[:12]>``: a state file written for any other
  plan has another campaign id, and ``_open`` refuses it. The sha256 is over the plan's canonical
  JSON (``proxy.cassette.canonical``), so whitespace in the file does not change it.
* REFUSALS (``PlanError``; each pinned by a named check in tests/planchecks.py and a mutation):
  the cap is missing; the cap is above the ``RunBudget`` ceiling; the cap is below ONE trial's
  reservation (``limits.max_trial_tokens``), so not even one trial could start; the limits are
  missing (they are never defaulted: a plan states the caps it reserves with, and the engine
  passes them to every trial, engine.trial_attempt_for); the template's sha256 differs from the
  pinned one; the provider entry of the config differs from the plan's (name, base_url, model,
  send_seed).
* Token figures are the PROVIDER's (F10). The calibration constants below are MEASURED from the
  committed evidence run and re-measured by a test
  (``planchecks.assert_the_calibration_is_the_evidence_runs``); they convert a scripted dry
  run's MEASURED request bytes into an ESTIMATE of tokens. N = 2 requests, one conversation: an
  estimate, never a measurement of the attacked model.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationError, model_validator

from proveflow.config import ProviderConfig
from proveflow.core._base import FrozenModel
from proveflow.core.attacks import Carrier, Goal
from proveflow.proxy.cassette import canonical
from proveflow.runner.limits import RUN_TOKEN_BUDGET, TrialLimits
from proveflow.runner.report import Delivery
from proveflow.runner.scenario import Scenario

PLAN_SCHEMA = 1
NAME_PATTERN = r"^[a-z0-9][a-z0-9_]{0,27}$"  # + "_" + 12 hex stays within TRIAL_KEY_PATTERN

# MEASURED (evidence/provider-runs/groq-gpt-oss-120b-2026-11-21/transcript.jsonl): each
# llm_request body's size by ``request_bytes``, and the provider-reported usage of the response
# that followed it. Re-measured from the file by planchecks.
EVIDENCE_RUN = "evidence/provider-runs/groq-gpt-oss-120b-2026-11-21"
EVIDENCE_REQUEST_BYTES = (9868, 10688)
EVIDENCE_PROMPT_TOKENS = (1525, 1655)
EVIDENCE_COMPLETION_TOKENS = (43, 125)


class PlanError(ValueError):
    """The plan cannot be run as written (fail closed; nothing is created)."""


def request_bytes(body: dict[str, Any]) -> int:
    """THE size of one chat request body, as both the calibration and the dry run measure it:
    compact JSON, UTF-8, non-ASCII kept."""
    return len(json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def bytes_per_token() -> float:
    """Measured calibration: total request bytes / total prompt tokens of the evidence run."""
    return sum(EVIDENCE_REQUEST_BYTES) / sum(EVIDENCE_PROMPT_TOKENS)


def completion_tokens_per_turn() -> float:
    return sum(EVIDENCE_COMPLETION_TOKENS) / len(EVIDENCE_COMPLETION_TOKENS)


class PlanProvider(FrozenModel):
    name: str
    base_url: str
    model: str = Field(min_length=1)
    send_seed: bool


class PlanPrice(FrozenModel):
    """The PUBLISHED price, as read from the provider's own pages (docs/PROVIDERS.md). Printed by
    the preflight with its URLs and read date, never a remembered number."""

    urls: tuple[str, ...] = Field(min_length=1)
    read_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    page_date: str | None  # None: the pages carry no date of their own
    input_usd_per_mtok: str = Field(pattern=r"^\d+(\.\d+)?$")  # decimal text, not a float
    output_usd_per_mtok: str = Field(pattern=r"^\d+(\.\d+)?$")


class CampaignPlan(FrozenModel):
    schema_version: Literal[1] = 1  # PLAN_SCHEMA
    name: str = Field(pattern=NAME_PATTERN)
    template: str = Field(min_length=1)  # path relative to the plan file
    template_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    # forced: the task REQUIRES the attacked tool (a FAVOURABLE condition: resistance under
    # guaranteed delivery). incidental: it does not (exposure then measures reachability).
    delivery: Delivery
    provider: PlanProvider
    per_source_n: int = Field(ge=1)
    sampler_seed: int
    carrier: Carrier
    goal: Goal
    budget_total: int = Field(ge=1, le=RUN_TOKEN_BUDGET)
    limits: TrialLimits  # REQUIRED: never defaulted
    temperature: float = Field(ge=0.0, le=2.0)
    trial_seed: int
    price: PlanPrice

    @model_validator(mode="after")
    def _one_trial_fits(self) -> CampaignPlan:
        if self.budget_total < self.limits.max_trial_tokens:
            raise ValueError(
                f"budget_total {self.budget_total} is below one trial's reservation "
                f"{self.limits.max_trial_tokens} (limits.max_trial_tokens): no trial could start"
            )
        return self


def plan_sha256(plan: CampaignPlan) -> str:
    return hashlib.sha256(canonical(plan.model_dump(mode="json")).encode("utf-8")).hexdigest()


def campaign_id_of(plan: CampaignPlan) -> str:
    return f"{plan.name}_{plan_sha256(plan)[:12]}"


def load_plan(path: Path) -> CampaignPlan:
    """Fail closed with every problem named (field paths only, never a value)."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise PlanError(f"{path.name}: unreadable ({type(exc).__name__})") from None
    try:
        return CampaignPlan.model_validate(raw)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or '(plan)'}: {err['msg']}"
            for err in exc.errors(include_input=False, include_url=False)
        )
        raise PlanError(f"{path.name}: {problems}") from None


def verify_template_bytes(plan: CampaignPlan, data: bytes) -> None:
    got = hashlib.sha256(data).hexdigest()
    if got != plan.template_sha256:
        raise PlanError(
            f"template {plan.template} has sha256 {got[:12]}..., the plan pins "
            f"{plan.template_sha256[:12]}...; refusing to run another template"
        )


def load_template(plan: CampaignPlan, plan_path: Path) -> Scenario:
    """The template the plan pins, refused unless its bytes have the pinned sha256."""
    path = plan_path.parent / plan.template
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise PlanError(f"template {plan.template}: unreadable ({type(exc).__name__})") from None
    verify_template_bytes(plan, data)
    template = Scenario.model_validate_json(data)
    if template.attack is None or template.attack_server is None:
        raise PlanError(f"template {plan.template} has no attack server: not a campaign template")
    if plan.goal.kind != template.attack.goal.kind:
        raise PlanError(
            f"the plan's goal kind {plan.goal.kind!r} is not the template's "
            f"{template.attack.goal.kind!r}"
        )
    return template


def check_provider(plan: CampaignPlan, provider: ProviderConfig) -> None:
    """The config's provider entry must be EXACTLY the plan's: same name, endpoint, model and
    seed behaviour. The key's variable name comes from the config and is never in the plan."""
    want = plan.provider
    mine = (want.name, want.base_url, want.model, want.send_seed)
    theirs = (provider.name, provider.base_url, provider.model, provider.send_seed)
    for field, a, b in zip(("name", "base_url", "model", "send_seed"), mine, theirs, strict=True):
        if a != b:
            raise PlanError(f"the config's provider {field} differs from the plan's: refusing")
