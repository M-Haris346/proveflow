"""Review round 3, with REAL processes (fake MCP server).

- discover fallback: relaunch once with legacy only when the connection closed after just
  server/discover; silent servers are not relaunched; --protocol legacy works for them
- pattern_redactions is reported per server in JSON, terminal and SARIF (T11 claim)
- the known pattern-layer false positive is pinned
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

import proveflow.cli as cli
from fakehome import fake_servers_file, logged_methods, make_host
from proveflow.discover.readers import read_explicit
from proveflow.introspect.cache import spec_key
from proveflow.introspect.runner import introspect_specs
from proveflow.introspect.scrub import Scrubber
from proveflow.report.models import IntrospectionStatus

runner = CliRunner()
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _one(tmp_path: Path, mode: str, *, protocol: str = "auto", timeout: float = 30) -> object:
    servers = fake_servers_file(tmp_path, {"s": mode})
    [cfg] = read_explicit(servers)
    [spec] = cfg.servers
    return introspect_specs(
        [spec],
        consent=lambda s: "yes",
        timeout=timeout,
        protocol=protocol,  # type: ignore[arg-type]
    )[spec_key(spec)]


def test_connection_closed_after_discover_relaunches_once_with_legacy(tmp_path: Path) -> None:
    res = _one(tmp_path, "exit_unknown")
    assert res.status is IntrospectionStatus.OK  # type: ignore[attr-defined]
    assert res.era == "handshake"  # type: ignore[attr-defined]
    assert "relaunched once with --protocol legacy" in (res.detail or "")  # type: ignore[attr-defined]
    # first launch: discover (then exit); second launch: handshake only
    assert logged_methods(tmp_path, "s") == [
        "server/discover", "initialize", "notifications/initialized", "tools/list",
    ]  # fmt: skip


def test_silent_discover_is_not_relaunched_and_hints_protocol_legacy(tmp_path: Path) -> None:
    res = _one(tmp_path, "discover_silent", timeout=5)
    assert res.status is IntrospectionStatus.TIMEOUT  # type: ignore[attr-defined]
    assert "--protocol legacy" in (res.detail or "")  # type: ignore[attr-defined]
    assert "relaunched" not in (res.detail or "")  # type: ignore[attr-defined]
    assert logged_methods(tmp_path, "s") == ["server/discover"]


def test_protocol_legacy_handles_silent_discover_servers(tmp_path: Path) -> None:
    res = _one(tmp_path, "discover_silent", protocol="legacy")
    assert res.status is IntrospectionStatus.OK  # type: ignore[attr-defined]
    assert logged_methods(tmp_path, "s") == [
        "initialize", "notifications/initialized", "tools/list",
    ]  # fmt: skip


def test_legacy_mode_does_not_relaunch(tmp_path: Path) -> None:
    res = _one(tmp_path, "exit_unknown", protocol="legacy")
    assert res.status is IntrospectionStatus.OK  # type: ignore[attr-defined]
    assert res.detail is None  # type: ignore[attr-defined]
    assert logged_methods(tmp_path, "s") == [
        "initialize", "notifications/initialized", "tools/list",
    ]  # fmt: skip


def test_protocol_option_rejects_unknown_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = make_host(tmp_path)
    monkeypatch.setattr(cli, "_host", lambda: host)
    result = runner.invoke(cli.app, ["scan", "--protocol", "modern", "--project", str(tmp_path)])
    assert result.exit_code == 1
    assert "--protocol must be" in result.output


def test_pattern_redactions_reported_in_json_terminal_and_sarif(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    servers = fake_servers_file(tmp_path, {"disk": "diskecho", "plain": "legacy"})
    host = make_host(tmp_path)
    monkeypatch.setattr(cli, "_host", lambda: host)
    project = tmp_path / "p"
    project.mkdir()
    sarif = tmp_path / "o.sarif"
    common = ["--project", str(project), "--servers", str(servers), "--yes",
              "--cache-dir", str(tmp_path / "c"), "--timeout", "30"]  # fmt: skip
    result = runner.invoke(cli.app, ["scan", "--json", "--sarif", str(sarif), *common])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    by = {s["key"]: s for p in data["profiles"] for s in p["servers"]}
    assert by["disk"]["pattern_redactions"] >= 1
    assert by["plain"]["pattern_redactions"] == 0
    props = json.loads(sarif.read_text(encoding="utf-8"))["runs"][0]["properties"]
    sarif_by = {b["server"]: b for b in props["proveflowServerBaselines"]}
    assert sarif_by["disk"]["patternRedactions"] >= 1
    assert sarif_by["plain"]["patternRedactions"] == 0
    table = runner.invoke(cli.app, ["scan", *common])
    assert table.exit_code == 0
    text = ANSI.sub("", table.output)
    assert "redacted" in text
    row = next(line for line in text.splitlines() if "│ disk " in line)
    assert re.search(r"│ *[1-9][0-9]* *│", row), row
    assert "PLANTED" not in result.output + table.output + sarif.read_text(encoding="utf-8")


def test_known_false_positive_name_key_equals_value_is_redacted() -> None:
    """Pinned known false positive (THREAT_MODEL T11): the pattern layer redacts the value
    of any `NAME=value` text whose NAME contains a secret word (R-ARG-ENVSTYLE), so a
    harmless description fragment like 'env_keys=A,B' loses 'A,B'. It is counted."""
    scrubber = Scrubber(secrets=[])
    out = scrubber.text("env_keys=A,B")
    assert out.startswith("env_keys=<redacted:sha256-")
    assert "A,B" not in out
    assert scrubber.pattern_redactions == 1
