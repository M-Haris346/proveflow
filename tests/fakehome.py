"""Build fake client-config layouts under tmp_path (never the real home directory).

Every fixture secret contains the marker ``PLANTED``; leak tests assert the marker
never appears in any output.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from proveflow.discover.hostenv import HostEnv, OsKind

FIXTURES = Path(__file__).parent / "fixtures" / "configs"
MARKER = "PLANTED"
LOCAL_PROJECT_KEY = "D:/work/demo"


@dataclass(frozen=True)
class FakeSetup:
    host: HostEnv
    project: Path
    files: tuple[Path, ...]


def _copy(name: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURES / name, dest)
    return dest


def claude_desktop_path(host: HostEnv) -> Path:
    if host.os is OsKind.WINDOWS:
        assert host.appdata is not None
        return host.appdata / "Claude" / "claude_desktop_config.json"
    if host.os is OsKind.MACOS:
        return (
            host.home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
        )
    return host.home / ".config" / "Claude" / "claude_desktop_config.json"


def windsurf_new_path(host: HostEnv) -> Path:
    if host.os is OsKind.WINDOWS:
        assert host.appdata is not None
        return host.appdata / "devin" / "mcp_config.json"
    return (host.xdg_config_home or host.home / ".config") / "devin" / "mcp_config.json"


def make_host(tmp_path: Path, os_kind: OsKind = OsKind.WINDOWS) -> HostEnv:
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    appdata = home / "AppData" / "Roaming" if os_kind is OsKind.WINDOWS else None
    return HostEnv(os=os_kind, home=home, appdata=appdata, xdg_config_home=None)


def full_setup(tmp_path: Path, os_kind: OsKind = OsKind.WINDOWS) -> FakeSetup:
    """Every supported client config present, with secrets planted everywhere."""
    host = make_host(tmp_path, os_kind)
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    files = [
        _copy("claude_desktop_config.json", claude_desktop_path(host)),
        _copy("dot_mcp.json", project / ".mcp.json"),
        _copy("cursor_mcp.json", host.home / ".cursor" / "mcp.json"),
        _copy("cursor_mcp.json", project / ".cursor" / "mcp.json"),
        _copy("vscode_mcp.json", project / ".vscode" / "mcp.json"),
        _copy("windsurf_mcp_config.json", windsurf_new_path(host)),
        _copy("windsurf_mcp_config.json", host.home / ".codeium" / "windsurf" / "mcp_config.json"),
    ]
    # ~/.claude.json: point the local-scope project entry at this test's project dir
    # (written with backslashes/case changes on Windows to exercise key normalization).
    data = json.loads((FIXTURES / "claude.json").read_text(encoding="utf-8"))
    local_key = str(project).upper() if os_kind is OsKind.WINDOWS else str(project)
    data["projects"][local_key] = data["projects"].pop(LOCAL_PROJECT_KEY)
    claude_json = host.home / ".claude.json"
    claude_json.write_text(json.dumps(data, indent=2), encoding="utf-8")
    files.append(claude_json)
    return FakeSetup(host=host, project=project, files=tuple(files))
