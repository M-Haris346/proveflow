"""The fix writer (Phase 8): layout and manifest, never an overwrite, no partial output."""

from __future__ import annotations

from pathlib import Path

import fixchecks


def test_the_writer_never_overwrites_and_leaves_no_partial_output(tmp_path: Path) -> None:
    fixchecks.assert_the_writer_never_overwrites_and_leaves_no_partial_output(tmp_path)
