"""Discovery: find MCP client configs on this machine, secrets redacted at read time."""

from __future__ import annotations

import logging
from pathlib import Path

from proveflow.core.client import ClientConfig
from proveflow.discover.hostenv import HostEnv, OsKind
from proveflow.discover.readers import (
    read_claude_code,
    read_claude_desktop,
    read_cursor,
    read_explicit,
    read_vscode,
    read_windsurf,
)

logger = logging.getLogger(__name__)

__all__ = ["HostEnv", "OsKind", "run_discovery"]


def run_discovery(
    host: HostEnv, project: Path, servers_file: Path | None = None
) -> list[ClientConfig]:
    """Read every supported client location. Never raises on bad config content."""
    configs: list[ClientConfig] = []
    configs += read_claude_desktop(host)
    configs += read_claude_code(host, project)
    configs += read_cursor(host, project)
    configs += read_vscode(host, project)
    configs += read_windsurf(host)
    if servers_file is not None:
        configs += read_explicit(servers_file)
    for cfg in configs:
        logger.debug(
            "config %s/%s at %s: %s, %d servers, %d entry errors",
            cfg.kind,
            cfg.scope,
            cfg.path,
            cfg.status,
            len(cfg.servers),
            len(cfg.entry_errors),
        )
    return configs
