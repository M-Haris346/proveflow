"""Host environment used to resolve client config paths.

Injected everywhere so tests build fake home layouts under ``tmp_path`` and never
touch the real home directory. Only the CLI calls ``HostEnv.current()``.

Interpretation note (docs/CLIENT_CONFIGS.md): the docs write ``~``; proveflow reads
it as ``Path.home()`` (USERPROFILE on Windows).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class OsKind(StrEnum):
    WINDOWS = "windows"
    MACOS = "macos"
    LINUX = "linux"


@dataclass(frozen=True)
class HostEnv:
    os: OsKind
    home: Path
    appdata: Path | None = None
    xdg_config_home: Path | None = None

    @classmethod
    def current(cls) -> HostEnv:
        if sys.platform == "win32":
            kind = OsKind.WINDOWS
        elif sys.platform == "darwin":
            kind = OsKind.MACOS
        else:
            kind = OsKind.LINUX
        appdata = os.environ.get("APPDATA")
        xdg = os.environ.get("XDG_CONFIG_HOME")
        return cls(
            os=kind,
            home=Path.home(),
            appdata=Path(appdata) if appdata else None,
            xdg_config_home=Path(xdg) if xdg else None,
        )
