"""proveflow.toml overrides beat heuristics; bad config never echoes values."""

from __future__ import annotations

from pathlib import Path

import pytest

from fakehome import full_setup
from proveflow.config import ConfigError, ProveflowConfig, RoleOverride, load_config
from proveflow.core.tools import RoleSource, SinkSeverity, ToolRole
from proveflow.discover import run_discovery
from proveflow.scan import build_scan


def test_load_valid(tmp_path: Path) -> None:
    p = tmp_path / "proveflow.toml"
    p.write_text(
        '[[override]]\nserver = "fetch"\nroles = []\n\n'
        '[[override]]\nserver = "memory"\nroles = ["sink"]\nsink_severity = "local_write"\n',
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert cfg.override[0] == RoleOverride(server="fetch", roles=())
    assert cfg.override[1].sink_severity is SinkSeverity.LOCAL_WRITE


def test_invalid_toml(tmp_path: Path) -> None:
    p = tmp_path / "proveflow.toml"
    p.write_text('[[override]\nserver = "PLANTEDtoml0001', encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_config(p)
    assert "invalid TOML" in str(exc.value)


def test_validation_error_does_not_echo_input(tmp_path: Path) -> None:
    p = tmp_path / "proveflow.toml"
    p.write_text('[[override]]\nserver = "x"\nroles = ["PLANTEDrole0001"]\n', encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_config(p)
    assert "PLANTED" not in str(exc.value)
    assert "override.0.roles.0" in str(exc.value)


def test_override_beats_heuristic_and_unused_reported(tmp_path: Path) -> None:
    s = full_setup(tmp_path)
    configs = run_discovery(s.host, s.project)
    cfg = ProveflowConfig(
        override=(
            RoleOverride(server="fetch", roles=()),
            RoleOverride(server="memory", roles=(ToolRole.SINK,)),
            RoleOverride(server="memory", tool="create_entities", roles=(ToolRole.SINK,)),
            RoleOverride(server="nope", roles=()),
        )
    )
    report = build_scan(configs, s.host, s.project, cfg)
    cc = next(p for p in report.profiles if p.id.startswith("claude_code@"))
    fetch = next(srv for srv in cc.servers if srv.key == "fetch")
    assert fetch.tools[0].roles == ()
    memory = next(srv for srv in cc.servers if srv.key == "memory")
    assert {e.role for e in memory.tools[0].roles} == {ToolRole.SINK}
    assert all(e.source is RoleSource.OVERRIDE and e.weight == 1.0 for e in memory.tools[0].roles)
    for f in report.flows:
        if f.profile == cc.id:
            assert "fetch" not in {r.server for r in (f.source, f.private, f.sink) if r}
    assert report.unused_overrides == (
        "memory/create_entities (tool-level overrides need introspection)",
        "nope/* (no match)",
    )
