"""Mutation: put back a finite, path-sized width -> the NAMED width checks fail."""

from __future__ import annotations

from pathlib import Path

import pytest

from widths import assert_long_command_prompt_is_exact, assert_render_width_is_pinned


def test_the_old_400_column_width_fails_the_named_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ok, mut = tmp_path / "ok", tmp_path / "mut"
    ok.mkdir()
    mut.mkdir()
    assert_render_width_is_pinned()
    with monkeypatch.context() as m:
        assert_long_command_prompt_is_exact(ok, m)
    monkeypatch.setenv("COLUMNS", "400")  # the pre-fix value from tests/conftest.py
    with pytest.raises(AssertionError, match="not the pinned width"):
        assert_render_width_is_pinned()
    with pytest.raises(AssertionError, match="wrapped or altered"):
        assert_long_command_prompt_is_exact(mut, monkeypatch)
