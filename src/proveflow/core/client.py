"""Discovered MCP client configurations (read-only; secrets redacted at read time)."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import Field

from proveflow.core._base import FrozenModel
from proveflow.core.redact import RedactedValue


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
    EXPLICIT = "explicit"


class TransportKind(StrEnum):
    STDIO = "stdio"
    HTTP = "http"


class ServerSpec(FrozenModel):
    """One configured MCP server. Env/header values are redacted at read time."""

    name: str
    transport: TransportKind
    command: str | None = None
    args: tuple[str, ...] = ()
    url: str | None = None
    env: dict[str, RedactedValue] = Field(default_factory=dict)
    headers: dict[str, RedactedValue] = Field(default_factory=dict)
    source_file: Path


class ClientConfig(FrozenModel):
    """One discovered MCP client config file."""

    kind: ClientKind
    scope: ConfigScope
    path: Path
    servers: tuple[ServerSpec, ...] = ()
