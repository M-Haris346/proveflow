"""Mutations of the Phase 7.3a campaign path: each mutant is the defect its named check exists to
catch (tests/planchecks.py), and each named check must fail on it. Every refusal has one."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic import Field, model_validator

import planchecks as pc
from proveflow.runner import campaign, offline_corpus, paid, plan
from proveflow.runner.limits import TrialLimits


def _ok_then(check: Callable[..., Any], tmp_path: Path, mp: pytest.MonkeyPatch,
             patch: Callable[[pytest.MonkeyPatch], None], message: str,
             with_mp: bool = False) -> None:  # fmt: skip
    (tmp_path / "ok").mkdir()
    (tmp_path / "mut").mkdir()
    with pytest.MonkeyPatch.context() as ok_mp:
        check(tmp_path / "ok", ok_mp) if with_mp else check(tmp_path / "ok")
    patch(mp)
    with pytest.raises(AssertionError, match=message):
        check(tmp_path / "mut", mp) if with_mp else check(tmp_path / "mut")


# --- the plan file -------------------------------------------------------------------------


class _DefaultCap(plan.CampaignPlan):
    budget_total: int = 400_000  # MUTANT: the cap is defaulted


class _NoCeiling(plan.CampaignPlan):
    budget_total: int = Field(ge=1)  # MUTANT: no RunBudget ceiling


class _NoReservationCheck(plan.CampaignPlan):
    @model_validator(mode="after")
    def _one_trial_fits(self) -> _NoReservationCheck:  # MUTANT: the validator is gone
        return self


class _DefaultLimits(plan.CampaignPlan):
    limits: TrialLimits = TrialLimits()  # MUTANT: the limits are defaulted (F3's defect)


@pytest.mark.parametrize(("check", "mutant"), [
    (pc.assert_a_plan_without_a_cap_is_refused, _DefaultCap),
    (pc.assert_a_cap_over_the_ceiling_is_refused, _NoCeiling),
    (pc.assert_a_cap_below_one_reservation_is_refused, _NoReservationCheck),
    (pc.assert_a_plan_without_limits_is_refused, _DefaultLimits),
])  # fmt: skip
def test_each_plan_refusal_fails_its_check_when_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, check: Any, mutant: Any
) -> None:
    _ok_then(check, tmp_path, monkeypatch,
             lambda m: m.setattr(plan, "CampaignPlan", mutant),
             "the plan was accepted")  # fmt: skip


def test_skipping_the_template_hash_fails_the_template_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ok_then(pc.assert_another_template_is_refused, tmp_path, monkeypatch,
             lambda m: m.setattr(plan, "verify_template_bytes", lambda p, d: None),
             "another sha256 was accepted")  # fmt: skip


def test_a_wrong_calibration_constant_fails_the_calibration_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pc.assert_the_calibration_is_the_evidence_runs()
    monkeypatch.setattr(plan, "EVIDENCE_PROMPT_TOKENS", (1525, 1656))
    with pytest.raises(AssertionError, match="not the evidence run's"):
        pc.assert_the_calibration_is_the_evidence_runs()


def test_an_estimate_without_output_tokens_fails_the_arithmetic_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ok_then(pc.assert_the_estimate_arithmetic, tmp_path, monkeypatch,
             lambda m: m.setattr(paid, "completion_tokens_per_turn", lambda: 0.0),
             "arithmetic is wrong")  # fmt: skip


# --- the paid CLI's refusals ---------------------------------------------------------------


@pytest.mark.parametrize(("check", "name", "value", "message"), [
    (pc.assert_run_refuses_a_provider_that_differs, "check_provider", lambda p, c: None,
     "not refused"),
    (pc.assert_run_refuses_without_the_key, "key_is_set", lambda p: True, "not refused"),
    (pc.assert_run_refuses_another_plans_state, "state_matches", lambda s, c: True,
     "not refused"),
    (pc.assert_run_refuses_a_root_under_docs_results, "under_docs_results", lambda p: False,
     "not refused"),
    (pc.assert_dry_run_refuses_a_root_under_docs_results, "under_docs_results",
     lambda p: False, "not refused"),
    (pc.assert_run_spends_nothing_without_yes, "confirmed", lambda a: True,
     "went on to the campaign"),
])  # fmt: skip
def test_each_cli_refusal_fails_its_check_when_removed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    check: Any,
    name: str,
    value: Any,
    message: str,
) -> None:
    _ok_then(check, tmp_path, monkeypatch, lambda m: m.setattr(paid, name, value), message,
             with_mp=True)  # fmt: skip


def test_a_preflight_that_runs_the_engine_fails_the_spends_nothing_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = paid.cmd_preflight

    def runs_first(args: Any) -> int:  # MUTANT: a "preflight" that starts the campaign
        paid.run_engine()
        return original(args)

    _ok_then(pc.assert_the_preflight_spends_nothing, tmp_path, monkeypatch,
             lambda m: m.setitem(paid.COMMANDS, "preflight", runs_first),
             "not side-effect free", with_mp=True)  # fmt: skip


def test_a_fetching_corpus_loader_fails_the_never_fetches_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MUTANT: a missing cache file is 'fetched' (here: bytes appear) instead of refused."""
    _ok_then(pc.assert_the_campaign_corpus_never_fetches, tmp_path, monkeypatch,
             lambda m: m.setattr(offline_corpus, "_refuse", lambda url: b""),
             "did not refuse with CorpusNotCached")  # fmt: skip


def test_ignoring_the_model_side_fails_the_dry_run_state_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MUTANT: the state file's model side is not compared on resume (F2's guard gone)."""
    original = campaign._open

    def ignoring(state_path: Path, *args: Any) -> Any:
        *rest, spec = args
        if state_path.exists():
            spec = {**spec, "model_side": campaign.load_state(state_path).model_side}
        return original(state_path, *rest, spec)

    _ok_then(pc.assert_a_dry_run_state_is_never_resumed_as_paid, tmp_path, monkeypatch,
             lambda m: m.setattr(campaign, "_open", ignoring),
             "was resumed as a PROVIDER")  # fmt: skip
