"""A release tag must equal the STATIC package version (Phase 9, Haris's ruling, 2026-11-26)."""

from __future__ import annotations

from pathlib import Path

import shipchecks


def test_a_tag_must_equal_the_package_version(tmp_path: Path) -> None:
    shipchecks.assert_a_tag_must_equal_the_package_version(tmp_path)
