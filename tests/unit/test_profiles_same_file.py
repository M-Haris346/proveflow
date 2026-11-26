"""The same-file collapse (Phase 9 fix of a MEASURED Find defect; tests/samefilechecks.py):
two scopes of ONE client that name one file are read once, and the report says so."""

from __future__ import annotations

from pathlib import Path

import samefilechecks


def test_one_file_is_read_once(tmp_path: Path) -> None:
    samefilechecks.assert_one_file_is_read_once(tmp_path)


def test_the_collapse_is_said(tmp_path: Path) -> None:
    samefilechecks.assert_the_collapse_is_said(tmp_path)


def test_case_and_links_resolve_to_one_file(tmp_path: Path) -> None:
    print(samefilechecks.assert_case_and_links_resolve_to_one_file(tmp_path))


def test_two_clients_are_never_collapsed(tmp_path: Path) -> None:
    samefilechecks.assert_two_clients_are_never_collapsed(tmp_path)
