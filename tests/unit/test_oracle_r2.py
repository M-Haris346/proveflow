"""R2 goal action (Phase 3b, ruling R2): positives, negatives, the action target's minting and
the per-trial validator. Every fixture is authored here; none is a real model's behaviour."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from oraclechecks import (
    ACTION_TARGET,
    action_attack_body,
    assert_action_target_is_not_an_r1_needle,
    assert_action_target_only_through_tool_results,
    assert_r2_fires_without_any_needle,
    assert_r2_matches_the_tool_by_look_alike_group,
    assert_r2_needs_a_sink_call,
    assert_r2_needs_an_action_goal,
    assert_r2_needs_the_goal_argument,
    assert_r2_needs_the_goal_tool,
    assert_r2_on_forwarded_sink,
    assert_r2_reaches_the_verdict,
    assert_r2_scans_the_goal_argument_value_recursively,
    assert_r2_uses_every_matcher_encoding,
)
from proveflow.core import attacks
from proveflow.core.attacks import Attack
from proveflow.core.honey import HONEY_HEX_LEN, t4_violations
from proveflow.core.trials import RuleHit
from proveflow.oracle.canary import (
    ACTION_TARGET_HEX_DIGITS,
    CanaryGenerationError,
    is_action_target,
    new_action_target,
)
from proveflow.oracle.rules import ACTION_TARGET_NEEDLE, Evidence


def test_r2_fires_without_any_needle(tmp_path: Path) -> None:
    assert_r2_fires_without_any_needle(tmp_path)


def test_r2_scans_the_goal_argument_value_recursively(tmp_path: Path) -> None:
    assert_r2_scans_the_goal_argument_value_recursively(tmp_path)


def test_action_target_is_not_an_r1_needle(tmp_path: Path) -> None:
    assert_action_target_is_not_an_r1_needle(tmp_path)


def test_r2_reaches_the_verdict(tmp_path: Path) -> None:
    assert_r2_reaches_the_verdict(tmp_path)


def test_the_fixture_action_target_is_legal() -> None:
    """A future edit must not leave an illegal fixture value passing."""
    assert re.fullmatch(attacks.ACTION_TARGET_PATTERN, ACTION_TARGET)
    assert t4_violations(ACTION_TARGET) == ()


def test_r2_matches_the_tool_by_look_alike_group(tmp_path: Path) -> None:
    assert_r2_matches_the_tool_by_look_alike_group(tmp_path)


def test_r2_uses_every_matcher_encoding(tmp_path: Path) -> None:
    assert_r2_uses_every_matcher_encoding(tmp_path)


def test_r2_on_forwarded_sink(tmp_path: Path) -> None:
    assert_r2_on_forwarded_sink(tmp_path)


def test_r2_needs_a_sink_call(tmp_path: Path) -> None:
    assert_r2_needs_a_sink_call(tmp_path)


def test_r2_needs_the_goal_argument(tmp_path: Path) -> None:
    assert_r2_needs_the_goal_argument(tmp_path)


def test_r2_needs_the_goal_tool(tmp_path: Path) -> None:
    assert_r2_needs_the_goal_tool(tmp_path)


def test_r2_needs_an_action_goal(tmp_path: Path) -> None:
    assert_r2_needs_an_action_goal(tmp_path)


def test_action_target_only_through_tool_results(tmp_path: Path) -> None:
    assert_action_target_only_through_tool_results(tmp_path)


def test_action_target_is_present_iff_the_goal_is_an_action_goal() -> None:
    body = action_attack_body()
    assert Attack.model_validate(body).action_target == ACTION_TARGET
    with pytest.raises(ValidationError, match="action_target is present iff"):
        Attack.model_validate({**body, "action_target": None})
    exfil = {**body, "goal": {"kind": "exfil", "sink_tool": "send_email"}}
    with pytest.raises(ValidationError, match="action_target is present iff"):
        Attack.model_validate(exfil)
    assert Attack.model_validate({**exfil, "action_target": None}).action_target is None
    with pytest.raises(ValidationError):
        Attack.model_validate({**body, "action_target": "act_NOTHEX000000"})
    with pytest.raises(ValidationError):  # the canary's 12-hex size is refused (16 hex only)
        Attack.model_validate({**body, "action_target": "act_5e0c9b2a7d14"})


def test_action_goal_has_one_top_level_argument_and_no_predicate() -> None:
    goal = attacks.ActionGoal(sink_tool="send_email", arg="to")
    assert set(goal.model_dump()) == {"kind", "sink_tool", "arg"}
    with pytest.raises(ValidationError):
        attacks.ActionGoal.model_validate({"sink_tool": "s", "arg_predicate": "x == 1"})
    with pytest.raises(ValidationError):
        attacks.ActionGoal(sink_tool="s", arg="")


def test_new_action_target_is_minted_like_the_canary() -> None:
    """16 hex, the HONEY length (ruling, Phase 3b): it is scanned on the same strings as the
    canary with the same 10 encodings, so it must not be the canary's size."""
    assert attacks.ACTION_TARGET_PATTERN == r"^act_[0-9a-f]{16}$"
    assert ACTION_TARGET_HEX_DIGITS == HONEY_HEX_LEN == 16
    draws = iter(["1234567890123456", "abcdef0123456789"])
    got = new_action_target(lambda n: next(draws))
    assert got == "act_abcdef0123456789" and is_action_target(got) and t4_violations(got) == ()
    assert t4_violations("act_1234567890123456") == ("digit_run_12",)
    with pytest.raises(CanaryGenerationError, match="no T4-clean action target in 64 draws"):
        new_action_target(lambda n: "1234567890123456")
    with pytest.raises(CanaryGenerationError, match="outside ACTION_TARGET_PATTERN"):
        new_action_target(lambda n: "XYZ")
    fresh = new_action_target()
    assert is_action_target(fresh) and not t4_violations(fresh)


def test_r2_evidence_names_the_action_target_needle() -> None:
    kw = {"seq": 1, "event": "upstream_request", "tool": "t", "sandbox_id": None, "reason": None}
    Evidence(rule=RuleHit.R2_GOAL_ACTION, needle=ACTION_TARGET_NEEDLE, **kw)  # type: ignore[arg-type]
    for bad in (None, "canary", "h01"):
        with pytest.raises(ValidationError, match="R2 evidence names"):
            Evidence(rule=RuleHit.R2_GOAL_ACTION, needle=bad, **kw)  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="R1 evidence names its needle"):
        Evidence(rule=RuleHit.R1_EXFIL, needle=ACTION_TARGET_NEEDLE, **kw)  # type: ignore[arg-type]
