"""Phase 7.3a on REAL twins and proxies, the model side SCRIPTED (nothing paid, no network, no
key): the dry-run command on the forced plan survives a kill and a resume with each key
counted once (tests/planchecks.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

import planchecks


def test_the_dry_run_kills_and_resumes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    planchecks.assert_the_dry_run_kills_and_resumes(tmp_path, monkeypatch)
