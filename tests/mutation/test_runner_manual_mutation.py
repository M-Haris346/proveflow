"""Mutations: remove the --yes spend gate -> the NAMED no-spend check fails; weaken the
existing --out-dir refusal -> the NAMED refusal check fails. The trial function is a spy
that aborts, so nothing is ever sent."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from proveflow.runner import manual
from runnerchecks import assert_existing_out_dir_is_refused_cleanly, assert_no_spend_without_yes


def test_removing_the_yes_gate_fails_the_named_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    ok, mut = tmp_path / "ok", tmp_path / "mut"
    ok.mkdir()
    mut.mkdir()
    with monkeypatch.context() as m:
        assert_no_spend_without_yes(ok, m, capsys)
    monkeypatch.setattr(manual, "require_consent", lambda args, line: None)
    with pytest.raises(AssertionError, match="spent without --yes"):
        assert_no_spend_without_yes(mut, monkeypatch, capsys)


def _raw_mkdir(path: Path) -> str | None:
    """Mutant: the code before the fix (manual.py:78), a bare mkdir."""
    path.mkdir(parents=True, exist_ok=False)
    return None


def _mkdir_exist_ok(path: Path) -> str | None:
    """Mutant: an existing --out-dir is accepted and reused."""
    path.mkdir(parents=True, exist_ok=True)
    return None


@pytest.mark.parametrize(("mutant", "message"), [
    (_raw_mkdir, "raw traceback instead of a refusal"),
    (_mkdir_exist_ok, "a trial started over an existing --out-dir"),
])  # fmt: skip
def test_weakening_the_out_dir_refusal_fails_the_named_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any, mutant: Any, message: str
) -> None:
    ok, mut = tmp_path / "ok", tmp_path / "mut"
    ok.mkdir()
    mut.mkdir()
    with monkeypatch.context() as m:
        assert_existing_out_dir_is_refused_cleanly(ok, m, capsys)
    monkeypatch.setattr(manual, "claim_out_dir", mutant)
    with pytest.raises(AssertionError, match=message):
        assert_existing_out_dir_is_refused_cleanly(mut, monkeypatch, capsys)
