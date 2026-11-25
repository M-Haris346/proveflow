"""Mutations of paired verify (Phase 8): one weakening per rule, each killed by its named check
(tests/verifychecks.py). The 3-cell verify runs share ONE unmutated run (the module fixture,
which is itself the passing check); each mutant then runs the check again and must fail."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

import planchecks
import verifychecks
from proveflow.runner import routing, trial, verify
from proveflow.stats import paired


@pytest.fixture(scope="module")
def ok_m1(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Any]]:
    tmp = tmp_path_factory.mktemp("okm1")
    with pytest.MonkeyPatch.context() as mp:
        yield verifychecks.assert_the_mitigation_blocks_the_flow(
            tmp / "run", mp, plan_path=planchecks.small_fs_plan(tmp),
            records=planchecks.synthetic_corpus(tmp), mitigation="m1")  # fmt: skip


def _blocked_check(tmp_path: Path, mp: pytest.MonkeyPatch, mitigation: str) -> None:
    verifychecks.assert_the_mitigation_blocks_the_flow(
        tmp_path / "run", mp, plan_path=planchecks.small_fs_plan(tmp_path),
        records=planchecks.synthetic_corpus(tmp_path), mitigation=mitigation)  # fmt: skip


def _no_gate(table: Any, mitigation: Any) -> Any:
    return table.with_gate(routing.Gate(mitigation.kind))


def test_a_hide_that_hides_nothing_fails_the_flow_blocked_check(
    ok_m1: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutant (twin M1): the sink's server stays offered and its calls are sent."""
    monkeypatch.setattr(trial, "apply_mitigation", _no_gate)
    with pytest.raises(AssertionError, match=r"m1 on .*'labels': \['rate_not_zero'\]"):
        _blocked_check(tmp_path, monkeypatch, "m1")


def test_a_deny_that_denies_nothing_fails_the_flow_blocked_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutant (twin M3): the sink tool's calls are not denied. The unmutated M3 check runs
    first (M3 has no shared fixture)."""
    _blocked_check(tmp_path / "ok", monkeypatch, "m3")
    with monkeypatch.context() as m:
        m.setattr(trial, "apply_mitigation", _no_gate)
        with pytest.raises(AssertionError, match=r"m3 on .*'labels': \['rate_not_zero'\]"):
            _blocked_check(tmp_path / "mut", m, "m3")


def test_a_lost_mitigation_record_fails_the_mechanism_check(
    ok_m1: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutant: the transcript's trial_start no longer records what was applied."""
    monkeypatch.setattr(trial, "record_of", lambda m: {})
    with pytest.raises(AssertionError, match="trial_start records"):
        _blocked_check(tmp_path, monkeypatch, "m1")


def _label_mutant(drop: set[str]) -> Callable[[Any], tuple[Any, ...]]:
    real = verify.classify

    def classify(row: Any) -> tuple[Any, ...]:
        got = tuple(x for x in real(row) if x.value not in drop)
        return got or (verify.Label.FLOW_BLOCKED,)

    return classify


@pytest.mark.parametrize(("drop", "message"), [
    ({"capability_removed"}, r"classify\(capability removed\)"),
    ({"delivery_removed", "delivery_reduced"}, r"classify\(delivery removed\)"),
    ({"utility_reduced", "capability_removed"}, r"classify\(capability removed\)"),
])  # fmt: skip
def test_a_label_rule_that_ignores_a_figure_fails_the_label_check(
    monkeypatch: pytest.MonkeyPatch, drop: set[str], message: str
) -> None:
    """Mutants: classify ignores utility (capability), exposure (delivery) or utility loss."""
    verifychecks.assert_the_label_rule_matches_the_ruling()
    monkeypatch.setattr(verify, "classify", _label_mutant(drop))
    with pytest.raises(AssertionError, match=message):
        verifychecks.assert_the_label_rule_matches_the_ruling()


def test_a_one_sided_mcnemar_fails_the_reference_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mutant: the p-value is the one-sided tail (no factor 2)."""
    verifychecks.assert_mcnemar_matches_hand_values()
    real = paired.mcnemar_exact
    monkeypatch.setattr(paired, "mcnemar_exact", lambda b, c: min(1.0, real(b, c) / 2))
    with pytest.raises(AssertionError, match=r"mcnemar_exact\(10, 0\)"):
        verifychecks.assert_mcnemar_matches_hand_values()


def test_a_report_without_the_control_note_accepted_fails_the_refusal_check(
    ok_m1: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutant: the CONTROL note is no longer required."""
    verifychecks.assert_the_report_refuses_what_the_counts_do_not_say(ok_m1)
    monkeypatch.setattr(verify, "REQUIRED_NOTES", (verify.TWIN_NOTE,))
    with pytest.raises(AssertionError, match="no CONTROL note was accepted"):
        verifychecks.assert_the_report_refuses_what_the_counts_do_not_say(ok_m1)


def test_pairing_halves_on_different_cells_fails_the_pairing_check(
    ok_m1: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutant: the same-cells premise always holds."""
    verifychecks.assert_unpaired_halves_are_refused(ok_m1)
    monkeypatch.setattr(verify, "same_cells", lambda a, b: True)
    with pytest.raises(AssertionError, match="different cells were accepted"):
        verifychecks.assert_unpaired_halves_are_refused(ok_m1)


def test_an_m3_row_without_the_twin_substitution_fails_the_row_check(
    ok_m1: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutant: M3's rows carry its bare name, so a row reads as verified against the client."""
    verifychecks.assert_m3_rows_say_the_twin_denied(ok_m1)
    monkeypatch.setattr(verify, "row_tag", lambda kind: "M3")
    with pytest.raises(AssertionError, match="does not say the twin denied the call"):
        verifychecks.assert_m3_rows_say_the_twin_denied(ok_m1)
