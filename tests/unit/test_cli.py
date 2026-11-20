"""CLI tests: --version, honest stubs, real discover/scan on a fake home."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

import proveflow.cli as cli
from fakehome import full_setup
from proveflow import __version__
from proveflow.cli import NOT_IMPLEMENTED_EXIT_CODE, app

runner = CliRunner()

ANSI_ESCAPES = re.compile(r"\x1b\[[0-9;]*m")


def plain(output: str) -> str:
    """Strip ANSI color codes and collapse whitespace/newlines from Rich output."""
    return " ".join(ANSI_ESCAPES.sub("", output).split())


STUBS = {
    "prove": "Phase 7",
    "fix": "Phase 8",
    "verify": "Phase 8",
    "replay": "Phase 7",
}


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert f"proveflow {__version__}" in plain(result.output)


def test_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in [*STUBS, "discover", "scan"]:
        assert command in result.output


@pytest.mark.parametrize(("command", "phase"), STUBS.items())
def test_stub_exits_2_with_honest_message(command: str, phase: str) -> None:
    result = runner.invoke(app, [command])
    assert result.exit_code == NOT_IMPLEMENTED_EXIT_CODE
    output = plain(result.output)
    assert "not implemented yet" in output
    assert phase in output


def test_tracebacks_never_show_locals() -> None:
    assert app.pretty_exceptions_show_locals is False


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    s = full_setup(tmp_path)
    monkeypatch.setattr(cli, "_host", lambda: s.host)
    return s


def test_discover_table(setup) -> None:  # type: ignore[no-untyped-def]
    result = runner.invoke(app, ["discover", "--project", str(setup.project)])
    assert result.exit_code == 0, result.output
    out = plain(result.output)
    assert "claude_desktop" in out
    assert "unsupported" in out
    assert "<redacted:sha256-" in out
    assert "PLANTED" not in result.output


def test_discover_json(setup) -> None:  # type: ignore[no-untyped-def]
    result = runner.invoke(app, ["discover", "--json", "--project", str(setup.project)])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["schema_version"] == 1
    assert any(c["kind"] == "windsurf" for c in data["configs"])
    assert "PLANTED" not in result.output


def test_scan_json_and_sarif(setup, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    sarif = tmp_path / "scan.sarif"
    result = runner.invoke(
        app,
        ["scan", "--no-launch", "--json", "--sarif", str(sarif), "--project", str(setup.project)],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["mode"] == "no_launch"
    assert data["flows"]
    assert all(f["verdict"] == "THEORETICAL" for f in data["flows"])
    assert sarif.is_file()


def test_scan_table_limit(setup) -> None:  # type: ignore[no-untyped-def]
    result = runner.invoke(
        app, ["scan", "--no-launch", "--limit", "3", "--project", str(setup.project)]
    )
    assert result.exit_code == 0, result.output
    out = plain(result.output)
    assert "more groups" in out  # --limit counts flow groups (schema 2)
    assert "THEORETICAL" in out
    assert "limitation:" in out


def test_scan_bad_config_exits_1(setup, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    bad = tmp_path / "bad.toml"
    bad.write_text("[[override]]\nroles = 3\n", encoding="utf-8")
    result = runner.invoke(
        app, ["scan", "--no-launch", "--config", str(bad), "--project", str(setup.project)]
    )
    assert result.exit_code == 1
    assert "error:" in plain(result.output)


def test_scan_reads_project_toml_by_default(setup) -> None:  # type: ignore[no-untyped-def]
    (setup.project / "proveflow.toml").write_text(
        '[[override]]\nserver = "nope"\nroles = []\n', encoding="utf-8"
    )
    result = runner.invoke(app, ["scan", "--no-launch", "--json", "--project", str(setup.project)])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["unused_overrides"] == ["nope/* (no match)"]


def test_scan_default_non_interactive_launches_nothing(
    setup, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    """No --yes and no TTY: every stdio server is reported consent_required, none spawned."""
    from proveflow.introspect import transport

    async def refuse(*_a: object, **_k: object) -> None:
        raise AssertionError("must not spawn without consent")

    monkeypatch.setattr(transport, "spawn", refuse)
    result = runner.invoke(
        app, ["scan", "--json", "--project", str(setup.project), "--cache-dir", str(tmp_path / "c")]
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["mode"] == "introspect"
    statuses = {
        srv["introspection"]
        for prof in data["profiles"]
        for srv in prof["servers"]
        if srv["spec"]["transport"] == "stdio"
    }
    assert statuses == {"consent_required"}


class _Stream:
    def __init__(self, tty: bool) -> None:
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


@pytest.mark.parametrize(
    ("stdin", "stdout", "stderr", "expected"),
    [
        (True, False, True, True),  # scan --json > file: stdout redirected, still prompts
        (True, True, True, True),
        (True, True, False, False),  # stderr redirected: prompt would be invisible
        (False, True, True, False),  # stdin redirected: nobody can answer
    ],
)
def test_interactive_depends_on_stdin_and_stderr_only(
    monkeypatch: pytest.MonkeyPatch, stdin: bool, stdout: bool, stderr: bool, expected: bool
) -> None:
    import sys

    monkeypatch.setattr(sys, "stdin", _Stream(stdin))
    monkeypatch.setattr(sys, "stdout", _Stream(stdout))
    monkeypatch.setattr(sys, "stderr", _Stream(stderr))
    assert cli._interactive() is expected


def test_interactive_false_for_stream_without_isatty(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    monkeypatch.setattr(sys, "stdin", object())
    assert cli._interactive() is False
