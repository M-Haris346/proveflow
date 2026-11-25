"""SAFETY (CLAUDE.md: "Never edit a user's client config. Fixes are written as separate patch
files for review"): `proveflow fix` changes no config's bytes or mtime, writes only its
out-dir, and no planted secret reaches any output (tests/fixchecks.py)."""

from __future__ import annotations

from pathlib import Path

import fixchecks


def test_fix_never_touches_a_config(tmp_path: Path) -> None:
    fixchecks.assert_fix_never_touches_a_config(tmp_path)
