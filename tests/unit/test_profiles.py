"""Agent profiles: Claude Code precedence, duplicate handling, profile isolation."""

from __future__ import annotations

from pathlib import Path

from fakehome import full_setup
from proveflow.config import ProveflowConfig
from proveflow.core.client import ConfigScope
from proveflow.discover import run_discovery
from proveflow.discover.hostenv import HostEnv, OsKind
from proveflow.discover.profiles import build_profiles
from proveflow.discover.readers import normalize_project_key
from proveflow.scan import build_scan


def test_claude_code_precedence_local_project_user_no_merge(tmp_path: Path) -> None:
    s = full_setup(tmp_path)
    profiles = build_profiles(run_discovery(s.host, s.project), s.host, s.project)
    cc = next(p for p in profiles if p.id.startswith("claude_code@"))
    members = {m.key: m.spec for m in cc.members}
    assert set(members) == {"fetch", "github", "memory", "postgres", "slack"}
    # slack: local entry wins over user entry, whole entry (no field merge)
    slack = members["slack"]
    assert slack.scope is ConfigScope.LOCAL
    assert slack.command is not None and str(slack.command) == "node"
    assert set(slack.env) == {"X"}
    # fetch: local wins over project
    assert members["fetch"].scope is ConfigScope.LOCAL
    assert members["fetch"].args[0].parts == ("mcp-server-fetch",)
    assert sorted(cc.shadowed) == [
        "fetch [project] shadowed by local",
        "slack [user] shadowed by local",
    ]


def test_other_projects_local_scope_not_in_profile(tmp_path: Path) -> None:
    s = full_setup(tmp_path)
    profiles = build_profiles(run_discovery(s.host, s.project), s.host, s.project)
    cc = next(p for p in profiles if p.id.startswith("claude_code@"))
    assert "linear" not in {m.key for m in cc.members}


def test_cursor_duplicates_kept_and_disambiguated(tmp_path: Path) -> None:
    s = full_setup(tmp_path)
    profiles = build_profiles(run_discovery(s.host, s.project), s.host, s.project)
    cursor = next(p for p in profiles if p.id.startswith("cursor@"))
    assert {m.key for m in cursor.members} == {
        "notion [user]",
        "notion [project]",
        "remote-example [user]",
        "remote-example [project]",
    }


def test_project_key_normalization() -> None:
    win = HostEnv(os=OsKind.WINDOWS, home=Path("C:/h"))
    lin = HostEnv(os=OsKind.LINUX, home=Path("/h"))
    assert normalize_project_key("C:\\Work\\Demo\\", win) == normalize_project_key(
        "c:/work/demo", win
    )
    assert normalize_project_key("/Work/Demo", lin) != normalize_project_key("/work/demo", lin)


def test_no_flow_crosses_profiles(tmp_path: Path) -> None:
    s = full_setup(tmp_path)
    report = build_scan(run_discovery(s.host, s.project), s.host, s.project, ProveflowConfig())
    keys = {p.id: {srv.key for srv in p.servers} for p in report.profiles}
    assert report.flows
    for f in report.flows:
        refs = [r for r in (f.source, f.private, f.sink) if r is not None]
        assert {r.server for r in refs} <= keys[f.profile]
