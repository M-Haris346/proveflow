"""Read-only JSON config loading that never crashes and never echoes file content.

Error details carry only positions / OS error names, never bytes from the file —
a config file is full of secrets, and an error message is an output.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from proveflow.core.client import ConfigStatus

logger = logging.getLogger(__name__)

MAX_CONFIG_BYTES = 32 * 1024 * 1024


@dataclass(frozen=True)
class LoadResult:
    status: ConfigStatus
    data: dict[str, Any] | None = None
    detail: str | None = None


def read_bytes(path: Path) -> bytes:
    """Open read-only. Separate function so tests can simulate OS errors."""
    with path.open("rb") as fh:
        return fh.read(MAX_CONFIG_BYTES + 1)


def load_json_config(path: Path) -> LoadResult:
    try:
        if not path.exists():
            return LoadResult(ConfigStatus.NOT_FOUND)
        if path.is_dir():
            return LoadResult(ConfigStatus.UNREADABLE, detail="path is a directory")
        raw = read_bytes(path)
    except OSError as exc:
        reason = exc.strerror or type(exc).__name__
        logger.info("config unreadable: %s (%s)", path, type(exc).__name__)
        return LoadResult(ConfigStatus.UNREADABLE, detail=f"{type(exc).__name__}: {reason}")
    if len(raw) > MAX_CONFIG_BYTES:
        return LoadResult(
            ConfigStatus.PARSE_ERROR, detail=f"file larger than {MAX_CONFIG_BYTES} bytes"
        )
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        return LoadResult(ConfigStatus.PARSE_ERROR, detail=f"not valid UTF-8 at byte {exc.start}")
    if not text.strip():
        return LoadResult(ConfigStatus.PARSE_ERROR, detail="empty file")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        # exc.msg is a fixed parser message; never include exc.doc (the file text).
        return LoadResult(
            ConfigStatus.PARSE_ERROR,
            detail=f"invalid JSON: {exc.msg} at line {exc.lineno} column {exc.colno}",
        )
    except RecursionError:
        return LoadResult(ConfigStatus.PARSE_ERROR, detail="invalid JSON: nesting too deep")
    if not isinstance(data, dict):
        return LoadResult(
            ConfigStatus.PARSE_ERROR, detail=f"top level is {type(data).__name__}, expected object"
        )
    return LoadResult(ConfigStatus.FOUND, data=data)
