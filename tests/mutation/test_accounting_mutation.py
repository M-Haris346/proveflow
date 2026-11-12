"""Mutation: re-introduce the silent drop (profiles built, skipped list discarded).
The ScanReport accounting validator must refuse the report (THREAT_MODEL T16)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

import proveflow.scan as scan_module
from fakehome import full_setup
from proveflow.config import ProveflowConfig
from proveflow.discover import run_discovery
from proveflow.discover.profiles import partition_profiles


def test_dropping_skipped_servers_fails_loudly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = full_setup(tmp_path)

    def silent_drop(*args, **kwargs):  # type: ignore[no-untyped-def]
        profiles, _skipped = partition_profiles(*args, **kwargs)
        return profiles, []

    monkeypatch.setattr(scan_module, "partition_profiles", silent_drop)
    configs = run_discovery(s.host, s.project)
    with pytest.raises(ValidationError, match="server accounting mismatch"):
        scan_module.build_scan(configs, s.host, s.project, ProveflowConfig())
