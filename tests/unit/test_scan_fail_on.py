"""`proveflow scan --fail-on` (Phase 9): exit 3 ONLY for matched flows; an error is never a
finding and never a pass (Haris's rulings 3 and B, 2026-11-26; tests/shipchecks.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

import shipchecks


def test_fail_on_exits_3_only_for_matched_flows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shipchecks.assert_fail_on_exits_3_only_for_matched_flows(tmp_path, monkeypatch)


@pytest.mark.parametrize("case", shipchecks.ERROR_CASES)
def test_an_error_is_never_a_finding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    shipchecks.assert_an_error_is_never_a_finding(tmp_path, monkeypatch, case)


def test_absent_and_unsupported_configs_are_not_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shipchecks.assert_absent_and_unsupported_configs_are_not_errors(tmp_path, monkeypatch)


def test_scan_names_an_unread_config_without_fail_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shipchecks.assert_scan_names_an_unread_config_without_fail_on(tmp_path, monkeypatch)
