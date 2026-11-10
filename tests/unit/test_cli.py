"""CLI skeleton tests: --version works, every stub exits 2 with an honest message."""

from __future__ import annotations

import re

import pytest
from typer.testing import CliRunner

from proveflow import __version__
from proveflow.cli import NOT_IMPLEMENTED_EXIT_CODE, app

runner = CliRunner()

ANSI_ESCAPES = re.compile(r"\x1b\[[0-9;]*m")


def plain(output: str) -> str:
    """Strip ANSI color codes and collapse whitespace/newlines from Rich output."""
    return " ".join(ANSI_ESCAPES.sub("", output).split())


STUBS = {
    "discover": "Phase 1",
    "scan": "Phase 1",
    "prove": "Phase 7",
    "fix": "Phase 8",
    "verify": "Phase 8",
    "replay": "Phase 5",
}


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert f"proveflow {__version__}" in plain(result.output)


def test_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in STUBS:
        assert command in result.output


@pytest.mark.parametrize(("command", "phase"), STUBS.items())
def test_stub_exits_2_with_honest_message(command: str, phase: str) -> None:
    result = runner.invoke(app, [command])
    assert result.exit_code == NOT_IMPLEMENTED_EXIT_CODE
    output = plain(result.output)
    assert "not implemented yet" in output
    assert phase in output
