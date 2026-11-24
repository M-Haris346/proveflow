"""Phase 7.3a offline: the plan file and its refusals, the paid CLI's refusals, the preflight, the
offline corpus, exposure, the calibration and the estimate (tests/planchecks.py). No twin, no
provider, no key; scripted or synthetic everywhere."""

from __future__ import annotations

from pathlib import Path

import pytest

import planchecks


def test_a_plan_without_a_cap_is_refused(tmp_path: Path) -> None:
    planchecks.assert_a_plan_without_a_cap_is_refused(tmp_path)


def test_a_cap_over_the_ceiling_is_refused(tmp_path: Path) -> None:
    planchecks.assert_a_cap_over_the_ceiling_is_refused(tmp_path)


def test_a_cap_below_one_reservation_is_refused(tmp_path: Path) -> None:
    planchecks.assert_a_cap_below_one_reservation_is_refused(tmp_path)


def test_a_plan_without_limits_is_refused(tmp_path: Path) -> None:
    planchecks.assert_a_plan_without_limits_is_refused(tmp_path)


def test_another_template_is_refused(tmp_path: Path) -> None:
    planchecks.assert_another_template_is_refused(tmp_path)


def test_the_committed_plans_are_the_ruled_ones() -> None:
    planchecks.assert_the_committed_plans_are_the_ruled_ones()


def test_the_calibration_is_the_evidence_runs() -> None:
    planchecks.assert_the_calibration_is_the_evidence_runs()


def test_the_estimate_arithmetic(tmp_path: Path) -> None:
    planchecks.assert_the_estimate_arithmetic(tmp_path)


def test_run_refuses_a_provider_that_differs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    planchecks.assert_run_refuses_a_provider_that_differs(tmp_path, monkeypatch)


def test_run_refuses_without_the_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    planchecks.assert_run_refuses_without_the_key(tmp_path, monkeypatch)


def test_run_refuses_another_plans_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    planchecks.assert_run_refuses_another_plans_state(tmp_path, monkeypatch)


def test_run_refuses_a_root_under_docs_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    planchecks.assert_run_refuses_a_root_under_docs_results(tmp_path, monkeypatch)


def test_run_spends_nothing_without_yes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    planchecks.assert_run_spends_nothing_without_yes(tmp_path, monkeypatch)


def test_dry_run_refuses_a_root_under_docs_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    planchecks.assert_dry_run_refuses_a_root_under_docs_results(tmp_path, monkeypatch)


def test_a_dry_run_state_is_never_resumed_as_paid(tmp_path: Path) -> None:
    planchecks.assert_a_dry_run_state_is_never_resumed_as_paid(tmp_path)


def test_the_preflight_spends_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    planchecks.assert_the_preflight_spends_nothing(tmp_path, monkeypatch)


def test_the_campaign_corpus_never_fetches(tmp_path: Path) -> None:
    planchecks.assert_the_campaign_corpus_never_fetches(tmp_path)
