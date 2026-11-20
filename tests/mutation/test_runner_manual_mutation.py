"""Mutation: remove the --yes spend gate -> the NAMED no-spend check fails. The trial
function is a spy that aborts, so nothing is ever sent."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from proveflow.runner import manual
from runnerchecks import assert_no_spend_without_yes


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
