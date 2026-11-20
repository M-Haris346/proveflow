"""Per-trial caps and the per-run token budget (Phase 5, D6). Fail closed, tighten-only.

These are DESIGN caps, not measurements. They are revisited after the first manual provider
run. Each default is also its ceiling (the ``ProxyLimits`` discipline): a caller may tighten
a cap, never raise it.

* MAX_TURNS 16: a cross-server flow needs about 3-5 tool round trips; 16 is ~3x headroom
  and ends a runaway loop early.
* MAX_TOOL_CALLS 32: about two per turn, and below the proxy's MAX_CALLS (200) so the
  runner's cap always fires first.
* MAX_TOKENS_PER_REQUEST 1024: an agent turn is a short tool call or a short answer.
* MAX_TOKENS_IN 120_000 per trial: tool schemas plus history are resent every turn,
  about 7.5k x 16.
* MAX_TOKENS_OUT 8_000 per trial: about 16 x the per-request maximum of 1024.
* WALL_CLOCK_S 300 per trial: half the proxy's SESSION_TIMEOUT_S (600), so the runner ends
  first and writes trial_end.
* RUN_TOKEN_BUDGET 500_000 per run: a trial starts only if the budget left covers that
  trial's MAXIMUM (tokens in + out); otherwise the runner refuses and says so. A campaign is
  never silently truncated.

Token counts are the PROVIDER's own usage figures (F10); proveflow counts nothing itself.
"""

from __future__ import annotations

from pydantic import Field

from proveflow.core._base import FrozenModel
from proveflow.proxy.session import MAX_CALLS, SESSION_TIMEOUT_S

MAX_TURNS = 16
MAX_TOOL_CALLS = 32
MAX_TOKENS_PER_REQUEST = 1024
MAX_TOKENS_IN = 120_000
MAX_TOKENS_OUT = 8_000
WALL_CLOCK_S = 300.0
RUN_TOKEN_BUDGET = 500_000

if not MAX_TOOL_CALLS < MAX_CALLS or not WALL_CLOCK_S < SESSION_TIMEOUT_S:  # pragma: no cover
    raise AssertionError("runner caps must fire before the proxy's limits")


class TrialLimits(FrozenModel):
    max_turns: int = Field(default=MAX_TURNS, ge=1, le=MAX_TURNS)
    max_tool_calls: int = Field(default=MAX_TOOL_CALLS, ge=1, le=MAX_TOOL_CALLS)
    max_tokens_per_request: int = Field(
        default=MAX_TOKENS_PER_REQUEST, ge=1, le=MAX_TOKENS_PER_REQUEST
    )
    max_tokens_in: int = Field(default=MAX_TOKENS_IN, ge=1, le=MAX_TOKENS_IN)
    max_tokens_out: int = Field(default=MAX_TOKENS_OUT, ge=1, le=MAX_TOKENS_OUT)
    wall_clock_s: float = Field(default=WALL_CLOCK_S, gt=0, le=WALL_CLOCK_S)

    @property
    def max_trial_tokens(self) -> int:
        return self.max_tokens_in + self.max_tokens_out


class BudgetExhausted(RuntimeError):
    """The run budget cannot cover another trial's maximum; no trial is started."""


class RunBudget:
    """Token budget for one run. ``reserve`` before a trial, ``spend`` after it."""

    def __init__(self, total: int = RUN_TOKEN_BUDGET) -> None:
        if not 1 <= total <= RUN_TOKEN_BUDGET:
            raise ValueError(f"run budget must be 1..{RUN_TOKEN_BUDGET} tokens (tighten-only)")
        self.total = total
        self.spent = 0

    @property
    def remaining(self) -> int:
        return self.total - self.spent

    def reserve(self, limits: TrialLimits) -> None:
        if self.remaining < limits.max_trial_tokens:
            raise BudgetExhausted(
                f"run budget left {self.remaining} tokens < this trial's maximum "
                f"{limits.max_trial_tokens}; refusing to start further trials"
            )

    def spend(self, tokens: int) -> None:
        if tokens < 0:
            raise ValueError("negative spend")
        self.spent += tokens
