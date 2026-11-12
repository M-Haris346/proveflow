"""Checkpoint-4a review fixes, with REAL processes (fake MCP server).

P0-2 project-scoped servers are not covered by --yes; P0-3 variables block launch;
P1-4 baseline is explicit; P1-6 SDK auto-mode fallback behaviour; P1-7 pattern layer.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

import proveflow.cli as cli
from fakehome import FAKE_SERVER, fake_servers_file, logged_methods, make_host
from proveflow.discover import run_discovery
from proveflow.discover.readers import read_explicit
from proveflow.introspect.cache import spec_key
from proveflow.introspect.runner import introspect_specs
from proveflow.report.models import IntrospectionStatus

runner = CliRunner()
TIMEOUT = "30"


def _project_with_mcp_json(tmp_path: Path, args_extra: list[str] | None = None) -> Path:
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)
    entry = {
        "command": sys.executable,
        "args": [str(FAKE_SERVER), "--mode", "legacy", "--log", str(tmp_path / "proj.log"),
                 *(args_extra or [])],
        "env": {"API_KEY": "PLANTEDprojectEnv0001"},
    }  # fmt: skip
    (project / ".mcp.json").write_text(json.dumps({"mcpServers": {"proj": entry}}), "utf-8")
    return project


def _scan(
    tmp_path: Path, project: Path, *extra: str, monkeypatch: pytest.MonkeyPatch, input: str = ""
) -> tuple[dict[str, object], object]:
    host = make_host(tmp_path)
    monkeypatch.setattr(cli, "_host", lambda: host)
    result = runner.invoke(
        cli.app,
        ["scan", "--json", "--project", str(project), "--cache-dir", str(tmp_path / "cache"),
         "--timeout", TIMEOUT, *extra],
        input=input,
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    stdout = result.stdout[result.stdout.index("{") :]
    return json.loads(stdout), result


def _servers(data: dict[str, object]) -> dict[str, dict[str, object]]:
    return {
        srv["key"]: srv
        for prof in data["profiles"]  # type: ignore[attr-defined]
        for srv in prof["servers"]
    }


# --- P0-2 --------------------------------------------------------------------------


def test_yes_does_not_launch_project_scoped_servers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project_with_mcp_json(tmp_path)
    data, _ = _scan(tmp_path, project, "--yes", monkeypatch=monkeypatch)
    srv = _servers(data)["proj"]
    assert srv["introspection"] == "consent_required"
    assert "--yes-project" in str(srv["detail"])
    assert not (tmp_path / "proj.log").exists()  # never started


def test_yes_project_launches_project_scoped_servers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project_with_mcp_json(tmp_path)
    data, _ = _scan(tmp_path, project, "--yes-project", monkeypatch=monkeypatch)
    assert _servers(data)["proj"]["introspection"] == "ok"
    assert (tmp_path / "proj.log").exists()


def test_consent_prompt_text_is_exact_and_redacted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project_with_mcp_json(tmp_path, ["--token", "PLANTEDargSecret0001"])
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    data, result = _scan(tmp_path, project, "--yes", monkeypatch=monkeypatch, input="n\n")
    stderr = result.stderr  # type: ignore[attr-defined]
    configs = run_discovery(make_host(tmp_path), project)
    spec = next(sp for c in configs for sp in c.servers if sp.name == "proj")
    expected = cli.consent_prompt_text(spec)
    assert expected in stderr
    assert "WARNING: this server is defined in the scanned project" in expected
    assert "own code will run on this machine with its configured environment" in expected
    assert "API_KEY (values hidden)" in expected
    assert "<redacted:sha256-" in expected  # the --token value
    assert "PLANTED" not in stderr
    assert _servers(data)["proj"]["introspection"] == "declined"


# --- P0-3 --------------------------------------------------------------------------


def test_unresolved_variables_block_launch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    servers = tmp_path / "s.json"
    servers.write_text(
        json.dumps(
            {"mcpServers": {"v": {"command": sys.executable,
                                  "args": [str(FAKE_SERVER), "--log", str(tmp_path / "v.log"),
                                           "--mode", "${MODE}"]}}}
        ),
        "utf-8",
    )  # fmt: skip
    project = tmp_path / "p"
    project.mkdir()
    data, _ = _scan(tmp_path, project, "--yes", "--servers", str(servers), monkeypatch=monkeypatch)
    srv = _servers(data)["v"]
    assert srv["introspection"] == "unresolved_variables"
    assert not (tmp_path / "v.log").exists()
    assert all(t["name"] == "*" for t in srv["tools"])  # server-level fallback


# --- P1-4 --------------------------------------------------------------------------


def test_baseline_states(tmp_path: Path) -> None:
    from proveflow.introspect.cache import ToolCache

    servers = fake_servers_file(tmp_path, {"m": "legacy"})
    [cfg] = read_explicit(servers)
    [spec] = cfg.servers
    key = spec_key(spec)

    def run(cache: ToolCache | None) -> str | None:
        res = introspect_specs([spec], consent=lambda s: "yes", timeout=30, cache=cache)
        return res[key].baseline

    assert run(None) == "cache_disabled"
    assert run(ToolCache(tmp_path / "c", write=False)) == "first_seen"  # nothing stored
    assert run(ToolCache(tmp_path / "c")) == "first_seen"
    assert run(ToolCache(tmp_path / "c")) == "compared"


# --- P1-6 --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mode", "status", "methods"),
    [
        ("discover_error", IntrospectionStatus.OK,
         ["server/discover", "initialize", "notifications/initialized", "tools/list"]),
        ("discover_silent", IntrospectionStatus.TIMEOUT, ["server/discover"]),
        # exit_unknown: now relaunched once with legacy -> see test_review_round3.py
        ("exit_unknown", IntrospectionStatus.OK,
         ["server/discover", "initialize", "notifications/initialized", "tools/list"]),
    ],
)  # fmt: skip
def test_sdk_auto_mode_fallback_behaviour(
    tmp_path: Path, mode: str, status: IntrospectionStatus, methods: list[str]
) -> None:
    """Documents the ACTUAL SDK 2.3.0 behaviour (mcp/client/_probe.py:52-114): any MCPError
    on server/discover falls back to initialize; silence only times out; an exit fails."""
    servers = fake_servers_file(tmp_path, {"s": mode})
    [cfg] = read_explicit(servers)
    [spec] = cfg.servers
    res = introspect_specs([spec], consent=lambda s: "yes", timeout=6)[spec_key(spec)]
    assert res.status is status, res.detail
    assert logged_methods(tmp_path, "s") == methods


# --- P1-7 --------------------------------------------------------------------------


def test_pattern_layer_catches_secret_never_seen_in_config(tmp_path: Path) -> None:
    servers = fake_servers_file(tmp_path, {"d": "diskecho"})
    [cfg] = read_explicit(servers)
    [spec] = cfg.servers
    res = introspect_specs([spec], consent=lambda s: "yes", timeout=30)[spec_key(spec)]
    assert res.status is IntrospectionStatus.OK
    assert "PLANTED" not in res.model_dump_json()
    assert res.pattern_redactions >= 1
