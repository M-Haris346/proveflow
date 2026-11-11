"""Per-user tool cache for rug-pull detection (description/schema changes between runs).

Location (never the project directory; ``--cache-dir`` overrides), conventions cited in
docs/PROCESS_KILL.md §Cache location:
- Windows: ``%LOCALAPPDATA%\\proveflow\\cache`` (FOLDERID_LocalAppData, Microsoft Learn)
- macOS:   ``~/Library/Caches/proveflow`` (Apple File System Programming Guide)
- Linux:   ``$XDG_CACHE_HOME/proveflow`` if absolute, else ``~/.cache/proveflow``
           (XDG Base Directory Specification 0.8)

Only names and sha256 hashes are stored: no descriptions, no schemas, no values.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Sequence
from pathlib import Path

from proveflow.core.client import ServerSpec
from proveflow.discover.hostenv import HostEnv, OsKind
from proveflow.report.models import RawTool, ToolChange, ToolChangeKind

CACHE_SCHEMA_VERSION = 1


def default_cache_dir(host: HostEnv) -> Path | None:
    if host.os is OsKind.WINDOWS:
        return host.localappdata / "proveflow" / "cache" if host.localappdata else None
    if host.os is OsKind.MACOS:
        return host.home / "Library" / "Caches" / "proveflow"
    xdg = host.xdg_cache_home
    base = xdg if xdg is not None and xdg.is_absolute() else host.home / ".cache"
    return base / "proveflow"


def spec_key(spec: ServerSpec) -> str:
    """Stable id of a configured server (redacted spec only)."""
    return hashlib.sha256(spec.model_dump_json().encode("utf-8")).hexdigest()[:32]


def _sha(value: object) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def tool_hashes(tools: Sequence[RawTool]) -> dict[str, dict[str, str]]:
    return {
        t.name: {"description": _sha(t.description), "schema": _sha(t.input_schema)} for t in tools
    }


class ToolCache:
    def __init__(self, root: Path, *, write: bool = True) -> None:
        self.root = root
        self.write = write

    def _path(self, key: str) -> Path:
        return self.root / "tools" / f"{key}.json"

    def load(self, key: str) -> dict[str, dict[str, str]] | None:
        path = self._path(key)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        tools = data.get("tools") if isinstance(data, dict) else None
        return tools if isinstance(tools, dict) else None

    def compare_and_store(
        self, key: str, tools: Sequence[RawTool]
    ) -> tuple[tuple[ToolChange, ...], bool]:
        """Return (changes vs previous run, first_seen) and store the new hashes."""
        new = tool_hashes(tools)
        old = self.load(key)
        changes: list[ToolChange] = []
        if old is not None:
            for name in sorted(set(new) | set(old)):
                if name not in old:
                    changes.append(ToolChange(kind=ToolChangeKind.ADDED, tool=name))
                elif name not in new:
                    changes.append(ToolChange(kind=ToolChangeKind.REMOVED, tool=name))
                else:
                    if old[name].get("description") != new[name]["description"]:
                        changes.append(
                            ToolChange(kind=ToolChangeKind.DESCRIPTION_CHANGED, tool=name)
                        )
                    if old[name].get("schema") != new[name]["schema"]:
                        changes.append(ToolChange(kind=ToolChangeKind.SCHEMA_CHANGED, tool=name))
        if self.write:
            path = self._path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            body = {"schema_version": CACHE_SCHEMA_VERSION, "tools": new}
            tmp.write_text(
                json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
            )
            os.replace(tmp, path)
        return tuple(changes), old is None
