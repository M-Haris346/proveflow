"""Mutations of THE bound table's guarantees (Phase 3b): a rule that scans a needle kind at a
location the table does not list, a table edited without the code, and a needle kind made
the canary's size where the canary is scanned, each make a NAMED check fail."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from boundchecks import (
    assert_every_location_under_the_threshold,
    assert_scan_locations_match_the_bound_table,
    load_counter,
)
from proveflow.oracle import answer, rules


def _ok_then(tmp_path: Path, mp: pytest.MonkeyPatch, patch: Any, counter: Any = None) -> None:
    (tmp_path / "ok").mkdir()
    (tmp_path / "mut").mkdir()
    real = load_counter()
    assert_scan_locations_match_the_bound_table(tmp_path / "ok", real)
    patch(mp)
    with pytest.raises(AssertionError, match="the bound table does not match what the oracle"):
        assert_scan_locations_match_the_bound_table(tmp_path / "mut", counter or real)


def test_widening_r3_without_the_table_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ok_then(tmp_path, monkeypatch,
             lambda m: m.setattr(answer, "R3_ENCODINGS", ("raw", "casefold", "ws_zw")))  # fmt: skip


_REAL_NEEDLES_OF = rules.needles_of


def _action_target_in_r1(start: Any) -> list[Any]:
    out = _REAL_NEEDLES_OF(start)
    attack = rules._attack(start)
    if attack is not None and attack.action_target is not None:
        out.append(rules.Needle(id="act", value=attack.action_target))
    return out


def test_a_needle_kind_added_to_a_location_without_the_table_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The action target scanned by R1 (every sink call's whole arguments) adds a term at the
    sink-argument location that the table does not have."""
    _ok_then(tmp_path, monkeypatch,
             lambda m: m.setattr(rules, "needles_of", _action_target_in_r1))  # fmt: skip


def test_a_table_edited_without_the_code_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    edited = load_counter()
    what, kinds = edited.SCAN_LOCATIONS["sink_argument"]
    edited.SCAN_LOCATIONS["sink_argument"] = (what, {**kinds, "marker": ("raw",)})
    _ok_then(tmp_path, monkeypatch, lambda m: None, counter=edited)


def test_a_12_hex_action_target_fails_the_threshold() -> None:
    """The bug this table exists to catch: the action target at the canary's size, scanned on
    the canary's strings with the same encodings, doubles the dominant term."""
    counter = load_counter()
    assert_every_location_under_the_threshold(counter, 1024 * 1024, 32)
    counter.NEEDLE_HEX["action_target"] = 12
    with pytest.raises(AssertionError, match="over the R-N1b limit at goal_argument"):
        assert_every_location_under_the_threshold(counter, 1024 * 1024, 32)
