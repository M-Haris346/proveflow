"""The installers (Phase 9), each run against a STUB uv on PATH: nothing is downloaded and
nothing is installed (tests/shipchecks.py). install.ps1 is the Windows installer and runs only
where Windows PowerShell exists; install.sh runs wherever `sh` exists (Git Bash on Windows)."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

import shipchecks


@pytest.mark.skipif(shutil.which("sh") is None, reason="no sh on this machine")
def test_install_sh_installs_exactly_its_route(tmp_path: Path) -> None:
    shipchecks.assert_the_installer_installs_exactly_its_route(tmp_path, "sh")


@pytest.mark.skipif(sys.platform != "win32", reason="install.ps1 is the Windows installer")
def test_install_ps1_installs_exactly_its_route(tmp_path: Path) -> None:
    shipchecks.assert_the_installer_installs_exactly_its_route(tmp_path, "ps1")
