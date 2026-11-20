"""runner/limits.py: design caps pinned, tighten-only, below the proxy's limits; budget."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from proveflow.proxy.session import MAX_CALLS, SESSION_TIMEOUT_S
from proveflow.runner import limits
from proveflow.runner.limits import RunBudget, TrialLimits
from runnerchecks import assert_budget_refuses_a_trial_it_cannot_cover


def test_design_caps_are_pinned() -> None:
    assert TrialLimits().model_dump() == {
        "max_turns": 16,
        "max_tool_calls": 32,
        "max_tokens_per_request": 1024,
        "max_tokens_in": 120_000,
        "max_tokens_out": 8_000,
        "wall_clock_s": 300.0,
    }
    assert limits.RUN_TOKEN_BUDGET == 500_000
    assert TrialLimits().max_trial_tokens == 128_000


def test_runner_caps_fire_before_the_proxy() -> None:
    assert limits.MAX_TOOL_CALLS < MAX_CALLS
    assert limits.WALL_CLOCK_S < SESSION_TIMEOUT_S


@pytest.mark.parametrize(
    "field", ["max_turns", "max_tool_calls", "max_tokens_per_request", "max_tokens_in",
              "max_tokens_out", "wall_clock_s"],
)  # fmt: skip
def test_caps_are_tighten_only(field: str) -> None:
    default = TrialLimits().model_dump()[field]
    TrialLimits.model_validate({field: default})
    TrialLimits.model_validate({field: default / 2 if isinstance(default, float) else default // 2})
    with pytest.raises(ValidationError):
        TrialLimits.model_validate({field: default + 1})
    with pytest.raises(ValidationError):
        TrialLimits.model_validate({field: 0})


def test_budget_refuses_a_trial_it_cannot_cover() -> None:
    assert_budget_refuses_a_trial_it_cannot_cover()


def test_budget_is_tighten_only() -> None:
    RunBudget(total=limits.RUN_TOKEN_BUDGET)
    for bad in (0, limits.RUN_TOKEN_BUDGET + 1):
        with pytest.raises(ValueError, match="tighten-only"):
            RunBudget(total=bad)
    with pytest.raises(ValueError, match="negative"):
        RunBudget().spend(-1)
