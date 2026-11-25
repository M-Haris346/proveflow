"""The patch renderers (Phase 8): M1 pointers and coverage, the M3 rule form and its refusals,
and the out-of-phase kinds (tests/fixchecks.py)."""

from __future__ import annotations

from pathlib import Path

import fixchecks


def test_m1_pointers_are_the_readers_keys() -> None:
    fixchecks.assert_m1_pointers_are_the_readers_keys()


def test_m1_removes_every_entry_that_would_connect(tmp_path: Path) -> None:
    fixchecks.assert_m1_removes_every_entry_that_would_connect(tmp_path)


def test_m3_rule_form_is_the_cited_one(tmp_path: Path) -> None:
    fixchecks.assert_m3_rule_form_is_the_cited_one(tmp_path)


def test_m3_is_refused_for_cursor() -> None:
    fixchecks.assert_m3_is_refused_for_cursor()


def test_out_of_phase_kinds_are_refused(tmp_path: Path) -> None:
    fixchecks.assert_out_of_phase_kinds_are_refused(tmp_path)
