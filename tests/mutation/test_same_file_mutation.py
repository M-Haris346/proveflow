"""Mutations of the same-file collapse (Phase 9 fix of a MEASURED Find defect): one weakening
per rule, each killed by its named check (tests/samefilechecks.py). Each test runs the check
unmutated first, then under the mutant."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

import samefilechecks
from proveflow import scan
from proveflow.discover import profiles


def _ok_then(tmp_path: Path, mp: pytest.MonkeyPatch, check: Callable[[Path], object],
             patch: Callable[[pytest.MonkeyPatch], None], message: str) -> None:  # fmt: skip
    check(tmp_path / "ok")
    with mp.context() as m:
        patch(m)
        with pytest.raises(AssertionError, match=message):
            check(tmp_path / "mut")


def _no_dedupe(configs: list[object]) -> tuple[list[object], list[object]]:
    return list(configs), []


def test_removing_the_dedupe_fails_the_read_once_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutant: src/proveflow/discover/profiles.py line 200, `configs, collapses =
    collapse_same_file(configs)`, and scan.py line 144's count, read every config (no dedupe):
    the measured defect returns, 4 entries, 16 flows and 16 groups."""

    def patch(m: pytest.MonkeyPatch) -> None:
        m.setattr(profiles, "collapse_same_file", _no_dedupe)
        m.setattr(scan, "collapse_same_file", _no_dedupe)

    _ok_then(tmp_path, monkeypatch, samefilechecks.assert_one_file_is_read_once, patch,
             r"\(entries, flows, groups, discovered\) = \(4, 16, 16, 4\)")  # fmt: skip


def test_a_silent_collapse_fails_the_note_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutant: src/proveflow/discover/profiles.py line 242, `profiles =
    _with_collapse_notes(profiles, collapses)` adds no note: the numbers are right but the
    report does not say a config was collapsed."""
    _ok_then(tmp_path, monkeypatch, samefilechecks.assert_the_collapse_is_said,
             lambda m: m.setattr(profiles, "_with_collapse_notes", lambda ps, cs: ps),
             "the collapse is silent")  # fmt: skip


def test_raw_string_paths_fail_the_resolution_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutant: src/proveflow/discover/profiles.py line 133, `return
    os.path.normcase(os.path.realpath(path))` becomes the raw string: a differently cased path
    (Windows) or a junction/symlink to the home is no longer the same file."""
    _ok_then(tmp_path, monkeypatch, samefilechecks.assert_case_and_links_resolve_to_one_file,
             lambda m: m.setattr(profiles, "canonical_path", lambda p: str(p)),
             r"want \(2, 3, 3, 2\)|was not resolved")  # fmt: skip
