"""Mutation (Phase 4 step 8): break one needle/sink rule -> the NAMED oracle check fails.

* honey dropped as a needle (canary only)       -> assert_r1_detects_honey fails, and
                                                   assert_forwarded_honey_is_sighted fails
* forwarded sink calls ignored (sandboxed only) -> assert_r1_on_forwarded_sink fails
* canary T4 rejection removed                   -> the N1 canary check fails
"""

from __future__ import annotations

from pathlib import Path

import pytest

from oraclechecks import (
    HONEY,
    assert_forwarded_honey_is_sighted,
    assert_r1_detects_honey,
    assert_r1_fires_on_real_session_for_honey,
    assert_r1_on_forwarded_sink,
)
from proveflow.core.honey import t4_violations
from proveflow.oracle import canary, rules
from proxyhelpers import proxy_twin_root  # noqa: F401


def _dirs(tmp_path: Path) -> tuple[Path, Path]:
    ok, mut = tmp_path / "ok", tmp_path / "mut"
    ok.mkdir()
    mut.mkdir()
    return ok, mut


def _canary_only(start: rules.SessionStart) -> list[rules.Needle]:
    attack = rules._attack(start)
    return [rules.Needle(id="canary", value=attack.canary)] if attack is not None else []


def test_dropping_honey_as_a_needle_fails_the_named_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ok, mut = _dirs(tmp_path)
    plant = f"key {HONEY.value}"
    assert_r1_detects_honey(ok, plant)
    assert_forwarded_honey_is_sighted(ok, plant)
    monkeypatch.setattr(rules, "needles_of", _canary_only)
    with pytest.raises(AssertionError, match="R1 missed planted honey"):
        assert_r1_detects_honey(mut, plant)
    with pytest.raises(AssertionError, match="forwarded honey not sighted"):
        assert_forwarded_honey_is_sighted(mut, plant)


def test_dropping_honey_fails_the_real_session_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ok, mut = _dirs(tmp_path)
    assert_r1_fires_on_real_session_for_honey(ok)
    monkeypatch.setattr(rules, "needles_of", _canary_only)
    with pytest.raises(AssertionError, match="honey R1 missed on real session"):
        assert_r1_fires_on_real_session_for_honey(mut)


def test_ignoring_forwarded_sink_calls_fails_the_named_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ok, mut = _dirs(tmp_path)
    assert_r1_on_forwarded_sink(ok)
    monkeypatch.setattr(
        rules,
        "sink_calls",
        lambda events: [e for e in events if isinstance(e, rules.SandboxedCall) and e.sink],
    )
    with pytest.raises(AssertionError, match="R1 missed a forwarded sink call"):
        assert_r1_on_forwarded_sink(mut)


def _assert_canary_rejects_t4() -> None:
    """Named N1 check: a draw that breaks a T4 rule is never returned as a canary."""
    draws = iter(["123456789012", "abcdef012345"])
    got = canary.new_canary(lambda n: next(draws))
    if t4_violations(got):
        raise AssertionError(f"canary breaks a T4 rule: {got}")


def test_removing_canary_t4_rejection_fails_the_named_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _assert_canary_rejects_t4()
    monkeypatch.setattr(canary, "t4_violations", lambda value: ())
    with pytest.raises(AssertionError, match="canary breaks a T4 rule"):
        _assert_canary_rejects_t4()
