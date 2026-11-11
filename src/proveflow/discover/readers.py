"""Client config readers. Every reader cites its docs/CLIENT_CONFIGS.md row.

Readers open files read-only (ADR-005), never crash on bad input, and return one
``ClientConfig`` per location with an explicit status. Rows marked [research] in
CLIENT_CONFIGS.md are reported as UNSUPPORTED, never guessed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from proveflow.core.client import ClientConfig, ClientKind, ConfigScope, ConfigStatus
from proveflow.discover._common import parse_servers
from proveflow.discover._io import load_json_config
from proveflow.discover.hostenv import HostEnv, OsKind

_URL = ("url",)
_URL_WINDSURF = ("serverUrl", "url")


def _read_simple(
    kind: ClientKind,
    scope: ConfigScope,
    path: Path,
    *,
    key: str,
    url_keys: tuple[str, ...],
    project: str | None = None,
) -> ClientConfig:
    loaded = load_json_config(path)
    if loaded.status is not ConfigStatus.FOUND or loaded.data is None:
        return ClientConfig(
            kind=kind,
            scope=scope,
            path=path,
            status=loaded.status,
            detail=loaded.detail,
            project=project,
        )
    servers, errors = parse_servers(
        loaded.data.get(key),
        key_name=key,
        url_keys=url_keys,
        source_file=path,
        scope=scope,
        project=project,
    )
    detail = None if key in loaded.data else f"no {key!r} key in file"
    return ClientConfig(
        kind=kind,
        scope=scope,
        path=path,
        detail=detail,
        project=project,
        servers=servers,
        entry_errors=errors,
    )


def read_claude_desktop(host: HostEnv) -> list[ClientConfig]:
    """Claude Desktop — CLIENT_CONFIGS.md §1 (Windows ``%APPDATA%\\Claude``, macOS
    ``~/Library/Application Support/Claude``, Linux ``~/.config/Claude``;
    file ``claude_desktop_config.json``, key ``mcpServers``)."""
    kind, scope = ClientKind.CLAUDE_DESKTOP, ConfigScope.USER
    if host.os is OsKind.WINDOWS:
        if host.appdata is None:
            return [
                ClientConfig(
                    kind=kind,
                    scope=scope,
                    path=None,
                    status=ConfigStatus.UNSUPPORTED,
                    detail="APPDATA is not set; cannot locate %APPDATA%\\Claude",
                )
            ]
        base = host.appdata / "Claude"
    elif host.os is OsKind.MACOS:
        base = host.home / "Library" / "Application Support" / "Claude"
    else:
        base = host.home / ".config" / "Claude"
    path = base / "claude_desktop_config.json"
    return [_read_simple(kind, scope, path, key="mcpServers", url_keys=_URL)]


def normalize_project_key(path_text: str, host: HostEnv) -> str:
    """Compare-key for Claude Code ``projects`` entries. The key format is not
    documented (CLIENT_CONFIGS.md research note), so slashes are unified, trailing
    slashes dropped, and case folded on Windows."""
    text = path_text.replace("\\", "/").rstrip("/")
    return text.casefold() if host.os is OsKind.WINDOWS else text


def read_claude_code(host: HostEnv, project: Path) -> list[ClientConfig]:
    """Claude Code — CLIENT_CONFIGS.md §2. User scope: ``~/.claude.json`` top-level
    ``mcpServers``; local scope: ``~/.claude.json`` ``projects["<path>"].mcpServers``;
    project scope: ``.mcp.json`` in the project root. Only these keys are read; the
    rest of ``~/.claude.json`` is never inspected or logged."""
    kind = ClientKind.CLAUDE_CODE
    out: list[ClientConfig] = []
    user_path = host.home / ".claude.json"
    loaded = load_json_config(user_path)
    if loaded.status is not ConfigStatus.FOUND or loaded.data is None:
        out.append(
            ClientConfig(
                kind=kind,
                scope=ConfigScope.USER,
                path=user_path,
                status=loaded.status,
                detail=loaded.detail,
            )
        )
    else:
        data = loaded.data
        servers, errors = parse_servers(
            data.get("mcpServers"),
            key_name="mcpServers",
            url_keys=_URL,
            source_file=user_path,
            scope=ConfigScope.USER,
        )
        out.append(
            ClientConfig(
                kind=kind,
                scope=ConfigScope.USER,
                path=user_path,
                servers=servers,
                entry_errors=errors,
            )
        )
        out.extend(_claude_code_local_scopes(data.get("projects"), user_path))
    project_path = project / ".mcp.json"
    out.append(
        _read_simple(
            kind,
            ConfigScope.PROJECT,
            project_path,
            key="mcpServers",
            url_keys=_URL,
            project=str(project),
        )
    )
    return out


def _claude_code_local_scopes(projects: Any, user_path: Path) -> list[ClientConfig]:
    if not isinstance(projects, dict):
        return []
    out: list[ClientConfig] = []
    for key in sorted(projects):
        entry = projects[key]
        if not isinstance(entry, dict):
            continue
        mapping = entry.get("mcpServers")
        if not mapping:
            continue
        servers, errors = parse_servers(
            mapping,
            key_name=f"projects[{key!r}].mcpServers",
            url_keys=_URL,
            source_file=user_path,
            scope=ConfigScope.LOCAL,
            project=key,
        )
        out.append(
            ClientConfig(
                kind=ClientKind.CLAUDE_CODE,
                scope=ConfigScope.LOCAL,
                path=user_path,
                project=key,
                servers=servers,
                entry_errors=errors,
            )
        )
    return out


def read_cursor(host: HostEnv, project: Path) -> list[ClientConfig]:
    """Cursor — CLIENT_CONFIGS.md §3. Global ``~/.cursor/mcp.json``, project
    ``.cursor/mcp.json``; key ``mcpServers``; ``envFile`` recorded, never opened."""
    kind = ClientKind.CURSOR
    return [
        _read_simple(
            kind,
            ConfigScope.USER,
            host.home / ".cursor" / "mcp.json",
            key="mcpServers",
            url_keys=_URL,
        ),
        _read_simple(
            kind,
            ConfigScope.PROJECT,
            project / ".cursor" / "mcp.json",
            key="mcpServers",
            url_keys=_URL,
            project=str(project),
        ),
    ]


def read_vscode(host: HostEnv, project: Path) -> list[ClientConfig]:
    """VS Code — CLIENT_CONFIGS.md §4. Workspace ``.vscode/mcp.json`` with top-level
    key ``servers`` (NOT ``mcpServers``). The user-profile path is marked [research]
    and is reported UNSUPPORTED; the experimental workspace ``.mcp.json`` format is
    not verified either and is reported UNSUPPORTED. Strict JSON: the VS Code docs
    fetched 2026-11-10 do not state that comments are allowed."""
    kind = ClientKind.VSCODE
    del host  # user path not verified; nothing host-dependent is read
    return [
        _read_simple(
            kind,
            ConfigScope.PROJECT,
            project / ".vscode" / "mcp.json",
            key="servers",
            url_keys=_URL,
            project=str(project),
        ),
        ClientConfig(
            kind=kind,
            scope=ConfigScope.USER,
            path=None,
            status=ConfigStatus.UNSUPPORTED,
            detail="user-profile mcp.json path not verified in official docs [research]",
        ),
        ClientConfig(
            kind=kind,
            scope=ConfigScope.PROJECT,
            path=project / ".mcp.json",
            status=ConfigStatus.UNSUPPORTED,
            detail="VS Code experimental workspace .mcp.json format not verified [research]",
            project=str(project),
        ),
    ]


def read_windsurf(host: HostEnv) -> list[ClientConfig]:
    """Windsurf / Devin — CLIENT_CONFIGS.md §5. New config: Windows
    ``%APPDATA%/devin/mcp_config.json``, macOS/Linux ``$XDG_CONFIG_HOME/devin`` or
    ``~/.config/devin``; legacy ``~/.codeium/windsurf[-next]/mcp_config.json``.
    Key ``mcpServers``; remote URL in ``serverUrl`` (or ``url``)."""
    kind, scope = ClientKind.WINDSURF, ConfigScope.USER
    out: list[ClientConfig] = []
    if host.os is OsKind.WINDOWS:
        if host.appdata is None:
            out.append(
                ClientConfig(
                    kind=kind,
                    scope=scope,
                    path=None,
                    status=ConfigStatus.UNSUPPORTED,
                    detail="APPDATA is not set; cannot locate %APPDATA%/devin",
                )
            )
        else:
            new_path = host.appdata / "devin" / "mcp_config.json"
            out.append(
                _read_simple(kind, scope, new_path, key="mcpServers", url_keys=_URL_WINDSURF)
            )
    else:
        base = host.xdg_config_home or (host.home / ".config")
        out.append(
            _read_simple(
                kind,
                scope,
                base / "devin" / "mcp_config.json",
                key="mcpServers",
                url_keys=_URL_WINDSURF,
            )
        )
    for legacy in ("windsurf", "windsurf-next"):
        out.append(
            _read_simple(
                kind,
                scope,
                host.home / ".codeium" / legacy / "mcp_config.json",
                key="mcpServers",
                url_keys=_URL_WINDSURF,
            )
        )
    return out


def read_explicit(path: Path) -> list[ClientConfig]:
    """``--servers FILE``: accepts the ``mcpServers`` shape (Claude/Cursor/Windsurf)
    or the ``servers`` shape (VS Code); URL in ``url`` or ``serverUrl``."""
    kind, scope = ClientKind.EXPLICIT_FILE, ConfigScope.EXPLICIT
    loaded = load_json_config(path)
    if loaded.status is not ConfigStatus.FOUND or loaded.data is None:
        return [
            ClientConfig(
                kind=kind, scope=scope, path=path, status=loaded.status, detail=loaded.detail
            )
        ]
    key = "mcpServers" if "mcpServers" in loaded.data else "servers"
    return [_read_simple(kind, scope, path, key=key, url_keys=_URL_WINDSURF)]
