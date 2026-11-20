"""runner/manual.py (Q5): without --yes nothing is spent and nothing is created. No test ever
runs the --yes path (it would call a provider)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from proveflow.runner import manual
from runnerchecks import FIXTURES, assert_no_spend_without_yes, manual_config


def test_no_spend_without_yes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    assert_no_spend_without_yes(tmp_path, monkeypatch, capsys)


def test_unknown_provider_is_an_error(tmp_path: Path, capsys: Any) -> None:
    argv = ["--scenario", str(FIXTURES / "clean_utility" / "scenario.json"),
            "--config", str(manual_config(tmp_path)), "--provider", "nope",
            "--out-dir", str(tmp_path / "o")]  # fmt: skip
    assert manual.main(argv) == 1
    assert "no [[provider]] named 'nope'" in capsys.readouterr().err
