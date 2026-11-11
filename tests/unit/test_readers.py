"""Reader tests for every client in docs/CLIENT_CONFIGS.md."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fakehome import FIXTURES, claude_desktop_path, full_setup, make_host
from proveflow.core.client import ClientConfig, ClientKind, ConfigScope, ConfigStatus, TransportKind
from proveflow.discover import _io, run_discovery
from proveflow.discover.hostenv import HostEnv, OsKind
from proveflow.discover.readers import (
    read_claude_desktop,
    read_explicit,
    read_vscode,
    read_windsurf,
)


def by(configs: list[ClientConfig], kind: ClientKind, scope: ConfigScope) -> list[ClientConfig]:
    return [c for c in configs if c.kind is kind and c.scope is scope]


def test_full_windows_setup_statuses(tmp_path: Path) -> None:
    s = full_setup(tmp_path)
    configs = run_discovery(s.host, s.project)
    desktop = by(configs, ClientKind.CLAUDE_DESKTOP, ConfigScope.USER)
    assert [c.status for c in desktop] == [ConfigStatus.FOUND]
    assert {sp.name for sp in desktop[0].servers} == {"filesystem", "brave-search", "gmail"}

    cc_user = by(configs, ClientKind.CLAUDE_CODE, ConfigScope.USER)[0]
    assert {sp.name for sp in cc_user.servers} == {"github", "slack", "postgres"}
    cc_local = by(configs, ClientKind.CLAUDE_CODE, ConfigScope.LOCAL)
    # empty project entries are skipped; two projects have servers
    assert len(cc_local) == 2
    cc_proj = by(configs, ClientKind.CLAUDE_CODE, ConfigScope.PROJECT)[0]
    assert {sp.name for sp in cc_proj.servers} == {"fetch", "memory"}

    assert [c.status for c in by(configs, ClientKind.CURSOR, ConfigScope.USER)] == [
        ConfigStatus.FOUND
    ]
    vs = by(configs, ClientKind.VSCODE, ConfigScope.PROJECT)
    assert {c.status for c in vs} == {ConfigStatus.FOUND, ConfigStatus.UNSUPPORTED}
    vs_user = by(configs, ClientKind.VSCODE, ConfigScope.USER)[0]
    assert vs_user.status is ConfigStatus.UNSUPPORTED
    assert vs_user.path is None
    assert "[research]" in (vs_user.detail or "")

    ws = by(configs, ClientKind.WINDSURF, ConfigScope.USER)
    assert [c.status for c in ws] == [
        ConfigStatus.FOUND,
        ConfigStatus.FOUND,
        ConfigStatus.NOT_FOUND,
    ]


def test_nothing_installed_all_not_found(tmp_path: Path) -> None:
    host = make_host(tmp_path)
    project = tmp_path / "p"
    project.mkdir()
    configs = run_discovery(host, project)
    statuses = {c.status for c in configs}
    assert statuses <= {ConfigStatus.NOT_FOUND, ConfigStatus.UNSUPPORTED}


@pytest.mark.parametrize("os_kind", [OsKind.MACOS, OsKind.LINUX])
def test_claude_desktop_posix_paths(tmp_path: Path, os_kind: OsKind) -> None:
    host = make_host(tmp_path, os_kind)
    path = claude_desktop_path(host)
    path.parent.mkdir(parents=True)
    path.write_text((FIXTURES / "claude_desktop_config.json").read_text(), encoding="utf-8")
    [cfg] = read_claude_desktop(host)
    assert cfg.status is ConfigStatus.FOUND
    assert cfg.path == path


def test_windows_without_appdata_is_unsupported(tmp_path: Path) -> None:
    host = HostEnv(os=OsKind.WINDOWS, home=tmp_path, appdata=None)
    [cfg] = read_claude_desktop(host)
    assert cfg.status is ConfigStatus.UNSUPPORTED
    assert read_windsurf(host)[0].status is ConfigStatus.UNSUPPORTED


def test_windsurf_xdg_override(tmp_path: Path) -> None:
    xdg = tmp_path / "xdg"
    host = HostEnv(os=OsKind.LINUX, home=tmp_path / "home", xdg_config_home=xdg)
    target = xdg / "devin" / "mcp_config.json"
    target.parent.mkdir(parents=True)
    target.write_text((FIXTURES / "windsurf_mcp_config.json").read_text(), encoding="utf-8")
    cfg = read_windsurf(host)[0]
    assert cfg.path == target
    assert cfg.status is ConfigStatus.FOUND


def test_windsurf_server_url_field(tmp_path: Path) -> None:
    s = full_setup(tmp_path)
    cfg = read_windsurf(s.host)[0]
    remote = next(sp for sp in cfg.servers if sp.name == "remote-http-mcp")
    assert remote.transport is TransportKind.HTTP
    assert remote.url is not None
    assert str(remote.url).endswith("@example.com/mcp")
    assert remote.auth_hint


def test_vscode_uses_servers_key_not_mcpservers(tmp_path: Path) -> None:
    project = tmp_path / "p"
    (project / ".vscode").mkdir(parents=True)
    # A Claude-style file in the VS Code location: found, but zero servers + detail.
    (project / ".vscode" / "mcp.json").write_text(
        (FIXTURES / "dot_mcp.json").read_text(), encoding="utf-8"
    )
    cfg = read_vscode(make_host(tmp_path), project)[0]
    assert cfg.status is ConfigStatus.FOUND
    assert cfg.servers == ()
    assert cfg.detail == "no 'servers' key in file"


def test_claude_code_only_mcp_keys_are_read(tmp_path: Path) -> None:
    s = full_setup(tmp_path)
    configs = run_discovery(s.host, s.project)
    dumped = json.dumps([c.model_dump(mode="json") for c in configs])
    assert "someUnrelatedSetting" not in dumped
    assert "PLANTED" not in dumped


def test_claude_code_transport_auth_and_ignored_keys(tmp_path: Path) -> None:
    s = full_setup(tmp_path)
    configs = run_discovery(s.host, s.project)
    other = next(
        c
        for c in by(configs, ClientKind.CLAUDE_CODE, ConfigScope.LOCAL)
        if c.project == "D:/work/other"
    )
    [linear] = other.servers
    assert linear.transport is TransportKind.SSE
    assert linear.auth_hint
    assert linear.ignored_keys == ("oauth",)


def test_env_and_header_values_fully_redacted(tmp_path: Path) -> None:
    s = full_setup(tmp_path)
    configs = run_discovery(s.host, s.project)
    cursor = by(configs, ClientKind.CURSOR, ConfigScope.USER)[0]
    notion = next(sp for sp in cursor.servers if sp.name == "notion")
    assert set(notion.env) == {"API_KEY"}
    assert notion.env["API_KEY"].length == len("PLANTEDcursorEnv00001")
    assert notion.env_file is not None
    assert str(notion.env_file) == ".env"


def test_env_file_is_never_opened(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    s = full_setup(tmp_path)
    (s.host.home / ".cursor" / ".env").write_text("API_KEY=PLANTEDdotenv0001\n", encoding="utf-8")
    opened: list[Path] = []
    real = _io.read_bytes

    def spy(path: Path) -> bytes:
        opened.append(path)
        return real(path)

    monkeypatch.setattr(_io, "read_bytes", spy)
    run_discovery(s.host, s.project)
    assert opened
    assert not any(p.name == ".env" for p in opened)


def test_bad_entries_skipped_without_leaking(tmp_path: Path) -> None:
    [cfg] = read_explicit(FIXTURES / "bad_entries.json")
    assert cfg.status is ConfigStatus.FOUND
    assert [sp.name for sp in cfg.servers] == ["good"]
    assert len(cfg.entry_errors) == 4
    joined = " ".join(cfg.entry_errors)
    assert "PLANTED" not in joined
    assert "'args' must be a list of strings" in joined


@pytest.mark.parametrize(
    ("name", "status"),
    [
        ("malformed.json", ConfigStatus.PARSE_ERROR),
        ("empty.json", ConfigStatus.PARSE_ERROR),
        ("toplevel_array.json", ConfigStatus.PARSE_ERROR),
        ("does-not-exist.json", ConfigStatus.NOT_FOUND),
    ],
)
def test_explicit_file_bad_inputs(name: str, status: ConfigStatus) -> None:
    [cfg] = read_explicit(FIXTURES / name)
    assert cfg.status is status
    assert cfg.servers == ()


def test_explicit_file_accepts_both_shapes(tmp_path: Path) -> None:
    [a] = read_explicit(FIXTURES / "vscode_mcp.json")
    [b] = read_explicit(FIXTURES / "cursor_mcp.json")
    assert {sp.name for sp in a.servers} == {"playwright", "context7"}
    assert {sp.name for sp in b.servers} == {"notion", "remote-example"}


def test_bad_desktop_file_does_not_hide_other_clients(tmp_path: Path) -> None:
    s = full_setup(tmp_path)
    claude_desktop_path(s.host).write_text("{ not json", encoding="utf-8")
    configs = run_discovery(s.host, s.project)
    assert (
        by(configs, ClientKind.CLAUDE_DESKTOP, ConfigScope.USER)[0].status
        is ConfigStatus.PARSE_ERROR
    )
    assert by(configs, ClientKind.CURSOR, ConfigScope.USER)[0].status is ConfigStatus.FOUND
