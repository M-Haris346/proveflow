"""Discovered MCP client configurations (read-only; secrets redacted at read time)."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import Field

from proveflow.core._base import FrozenModel
from proveflow.core.redact import RedactedText, RedactedValue


class ClientKind(StrEnum):
    CLAUDE_DESKTOP = "claude_desktop"
    CLAUDE_CODE = "claude_code"
    CURSOR = "cursor"
    VSCODE = "vscode"
    WINDSURF = "windsurf"
    EXPLICIT_FILE = "explicit_file"


class ConfigScope(StrEnum):
    USER = "user"
    PROJECT = "project"
    LOCAL = "local"  # Claude Code per-project private scope (CLIENT_CONFIGS.md §2)
    EXPLICIT = "explicit"


class ConfigStatus(StrEnum):
    FOUND = "found"
    NOT_FOUND = "not_found"
    PARSE_ERROR = "parse_error"
    UNREADABLE = "unreadable"
    UNSUPPORTED = "unsupported"


class TransportKind(StrEnum):
    STDIO = "stdio"
    HTTP = "http"
    SSE = "sse"
    WS = "ws"
    UNKNOWN = "unknown"


class ServerSpec(FrozenModel):
    """One configured MCP server. Every env/header value is redacted at read time;
    args, url, command, and envFile path are redacted by pattern (docs/REDACTION.md)."""

    name: str
    transport: TransportKind
    declared_type: str | None = None
    command: RedactedText | None = None
    args: tuple[RedactedText, ...] = ()
    url: RedactedText | None = None
    env: dict[str, RedactedValue] = Field(default_factory=dict)
    headers: dict[str, RedactedValue] = Field(default_factory=dict)
    env_file: RedactedText | None = None
    auth_hint: bool = False
    ignored_keys: tuple[str, ...] = ()
    source_file: Path
    scope: ConfigScope = ConfigScope.USER
    project: str | None = None
    # Variable NAMES referenced in launch values (never defaults/values); see
    # discover/variables.py. Non-empty => proveflow does not launch the server.
    variables: tuple[str, ...] = ()


class ClientConfig(FrozenModel):
    """One discovered MCP client config location (one file, or one scope inside a file)."""

    kind: ClientKind
    scope: ConfigScope
    path: Path | None
    status: ConfigStatus = ConfigStatus.FOUND
    detail: str | None = None
    project: str | None = None
    servers: tuple[ServerSpec, ...] = ()
    entry_errors: tuple[str, ...] = ()
