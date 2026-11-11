"""THREAT_MODEL T8 / ADR-005: discover and scan never modify a client config."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from typer.testing import CliRunner

import proveflow.cli as cli
from fakehome import full_setup


def _fingerprint(paths: tuple[Path, ...]) -> dict[Path, tuple[str, int]]:
    return {p: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) for p in paths}


def test_configs_byte_identical_and_mtime_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = full_setup(tmp_path)
    before = _fingerprint(s.files)
    monkeypatch.setattr(cli, "_host", lambda: s.host)
    runner = CliRunner()
    for args in (
        ["discover", "--project", str(s.project)],
        ["discover", "--json", "--project", str(s.project)],
        ["scan", "--no-launch", "--sarif", str(tmp_path / "o.sarif"), "--project", str(s.project)],
    ):
        assert runner.invoke(cli.app, args).exit_code == 0
    assert _fingerprint(s.files) == before
    # no new files were created next to the configs either
    assert not (s.project / ".proveflow-cache").exists()
