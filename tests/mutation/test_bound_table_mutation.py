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
    assert_sighting_location_matches_the_table,
    load_counter,
)
from proveflow.oracle import matcher, rules


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
             lambda m: m.setattr(matcher, "SPLIT_VALUE_ENCODINGS",
                                 ("raw", "casefold", "ws_zw")))  # fmt: skip


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
    # BOTH conditions the docstring names (Phase 6 ruling): the canary's size AND the canary's
    # encodings on the target. Before Phase 6 only the first was set, and the test passed
    # because the second happened to hold; the measured breach is 2.0152.
    counter.NEEDLE_HEX["action_target"] = 12
    what, kinds = counter.SCAN_LOCATIONS["goal_argument"]
    widened = {**kinds, "action_target": counter.ALL_ENCODINGS}
    counter.SCAN_LOCATIONS["goal_argument"] = (what, widened)
    base = 1024 * 1024 * 91 / 2**48
    assert f"{counter.location_bound(1024 * 1024, 32, 'goal_argument') / base:.4f}" == "2.0152"
    with pytest.raises(AssertionError, match="over the R-N1b limit at goal_argument"):
        assert_every_location_under_the_threshold(counter, 1024 * 1024, 32)


def _split_set_sightings(events: Any, needles: Any) -> list[Any]:
    """Mutant: the action target's forwarded-call sighting matched with R2's split set."""
    real = [n for n in needles if n.id != rules.ACTION_TARGET_NEEDLE]
    out = _REAL_SIGHTINGS(events, real)
    for n in (n for n in needles if n.id == rules.ACTION_TARGET_NEEDLE):
        for e in events:
            if isinstance(e, rules.UpstreamRequest) and not e.sink:
                hits = matcher.match_split_value(n.value, e.arguments).hits
                if hits:
                    found = tuple(rules.EncodingHit(path=h.path, encoding=h.encoding)
                                  for h in hits)  # fmt: skip
                    out.append(rules.NeedleSighting(seq=e.seq, tool=e.tool, needle=n.id,
                                                    hits=found))  # fmt: skip
    return out


_REAL_SIGHTINGS = rules.forwarded_sightings


def test_a_sighting_scan_changed_without_the_table_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The figure that justifies the 16-hex length must describe the scan the oracle does."""
    (tmp_path / "ok").mkdir()
    (tmp_path / "mut").mkdir()
    real = load_counter()
    assert_sighting_location_matches_the_table(tmp_path / "ok", real)
    monkeypatch.setattr(rules, "forwarded_sightings", _split_set_sightings)
    with pytest.raises(AssertionError, match="the sighting table does not match"):
        assert_sighting_location_matches_the_table(tmp_path / "mut", real)
