"""The Action's main limitation, as numbers (Haris's Ruling A, 2026-11-26): the Action scans
with --no-launch, so it sees config names and command lines only. Each Action fixture is
scanned both ways; only the repo's own fake MCP server is launched (tests/shipchecks.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

import shipchecks


def test_the_action_is_blind_where_measured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shipchecks.assert_the_action_is_blind_where_measured(tmp_path, monkeypatch)
