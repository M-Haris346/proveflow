"""runner/manual.py (Q5): without --yes nothing is spent and nothing is created. No test ever
runs the --yes path to a provider: the one test that passes --yes is refused (existing
--out-dir) before any twin, proxy or HTTP client exists, and run_trial is an aborting spy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from proveflow.runner import manual
from runnerchecks import (
    FIXTURES,
    assert_existing_out_dir_is_refused_cleanly,
    assert_no_spend_without_yes,
    manual_config,
)


def test_no_spend_without_yes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    assert_no_spend_without_yes(tmp_path, monkeypatch, capsys)


def test_an_existing_out_dir_is_refused_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    assert_existing_out_dir_is_refused_cleanly(tmp_path, monkeypatch, capsys)


def test_claim_out_dir_creates_a_new_directory(tmp_path: Path) -> None:
    target = tmp_path / "a" / "run1"
    assert manual.claim_out_dir(target) is None
    assert target.is_dir()
    assert manual.claim_out_dir(target) is not None


def test_unknown_provider_is_an_error(tmp_path: Path, capsys: Any) -> None:
    argv = ["--scenario", str(FIXTURES / "clean_utility" / "scenario.json"),
            "--config", str(manual_config(tmp_path)), "--provider", "nope",
            "--out-dir", str(tmp_path / "o")]  # fmt: skip
    assert manual.main(argv) == 1
    assert "no [[provider]] named 'nope'" in capsys.readouterr().err
