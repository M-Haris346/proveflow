"""Every discovered server is accounted for (THREAT_MODEL T16): in a profile, or in
``ScanReport.skipped`` with a reason. Fixture configs only; nothing is ever launched."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError
from rich.console import Console
from typer.testing import CliRunner

import proveflow.cli as cli
from fakehome import full_setup, make_host
from proveflow.config import ProveflowConfig
from proveflow.core.client import ClientConfig, ClientKind, ConfigScope, ServerSpec, TransportKind
from proveflow.discover import run_discovery
from proveflow.discover.hostenv import HostEnv
from proveflow.discover.profiles import partition_profiles
from proveflow.discover.readers import read_explicit
from proveflow.introspect.cache import spec_key
from proveflow.introspect.runner import Consent, introspect_specs
from proveflow.report.models import IntrospectionStatus, ScanReport, SkipReason
from proveflow.report.sarif import build_sarif
from proveflow.report.terminal import render_scan
from proveflow.scan import build_scan
from widths import TEST_COLUMNS

runner = CliRunner()


def _assert_accounted(report: ScanReport, configs: list[ClientConfig]) -> None:
    discovered = sum(len(c.servers) for c in configs)
    assert report.discovered_servers == discovered
    assert discovered == report.analyzed_servers + len(report.skipped)


def _members(report: ScanReport) -> dict[str, IntrospectionStatus]:
    return {s.key: s.introspection for p in report.profiles for s in p.servers}


def _other_project_only(tmp_path: Path) -> tuple[HostEnv, Path, Path]:
    """The author's case: ~/.claude.json has ONE local-scope server, for another project."""
    host = make_host(tmp_path)
    project = tmp_path / "project"
    other = tmp_path / "other-project"
    project.mkdir()
    other.mkdir()
    data = {"projects": {str(other): {"mcpServers": {"x": {"command": "node", "args": ["s.js"]}}}}}
    (host.home / ".claude.json").write_text(json.dumps(data), encoding="utf-8")
    return host, project, other


def _explicit(tmp_path: Path, servers: dict[str, object]) -> tuple[list[ClientConfig], Path]:
    path = tmp_path / "servers.json"
    path.write_text(json.dumps({"mcpServers": servers}), encoding="utf-8")
    project = tmp_path / "p"
    project.mkdir(exist_ok=True)
    return read_explicit(path), project


def _introspected_scan(
    tmp_path: Path, configs: list[ClientConfig], project: Path, answer: Consent
) -> ScanReport:
    specs = [s for c in configs for s in c.servers]
    results = introspect_specs(specs, consent=lambda _s: answer, timeout=10)
    return build_scan(configs, make_host(tmp_path), project, ProveflowConfig(), results)


# --- out_of_project (the author's case) -------------------------------------------


def test_out_of_project_local_entry_is_skipped_not_dropped(tmp_path: Path) -> None:
    host, project, other = _other_project_only(tmp_path)
    configs = run_discovery(host, project)
    report = build_scan(configs, host, project, ProveflowConfig())
    assert report.profiles == ()
    [sk] = report.skipped
    assert (sk.server_ref, sk.client, sk.scope, sk.reason) == (
        "x",
        ClientKind.CLAUDE_CODE,
        ConfigScope.LOCAL,
        SkipReason.OUT_OF_PROJECT,
    )
    assert sk.project == str(other)
    assert any("1 of 1 discovered server(s) were not analyzed" in lim for lim in report.limitations)
    _assert_accounted(report, configs)


def test_local_entry_without_project_key_is_out_of_project(tmp_path: Path) -> None:
    host = make_host(tmp_path)
    spec = ServerSpec(
        name="y",
        transport=TransportKind.STDIO,
        source_file=host.home / ".claude.json",
        scope=ConfigScope.LOCAL,
    )
    cfg = ClientConfig(
        kind=ClientKind.CLAUDE_CODE, scope=ConfigScope.LOCAL, path=spec.source_file, servers=(spec,)
    )
    profiles, skipped = partition_profiles([cfg], host, tmp_path)
    assert profiles == []
    assert [(s.server_ref, s.reason) for s in skipped] == [("y", SkipReason.OUT_OF_PROJECT)]


def test_cli_scan_author_case_says_no_servers_analyzed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Interactive-less `scan` (default introspect mode, no --yes): table and JSON both
    show the skipped server; the table never shows a bare '0 flows'."""
    from proveflow.introspect import transport

    async def refuse(*_a: object, **_k: object) -> None:
        raise AssertionError("nothing may be spawned")

    host, project, _ = _other_project_only(tmp_path)
    monkeypatch.setattr(cli, "_host", lambda: host)
    monkeypatch.setattr(transport, "spawn", refuse)
    base = ["scan", "--project", str(project), "--cache-dir", str(tmp_path / "c")]

    table = runner.invoke(cli.app, base)
    assert table.exit_code == 0, table.output
    out = " ".join(table.stdout.split())  # Rich may wrap long lines
    assert "No servers analyzed: 1 discovered, 1 skipped" in out
    assert "out_of_project" in out
    assert "Toxic flows" not in out

    js = runner.invoke(cli.app, [*base, "--json"])
    data = json.loads(js.stdout)
    assert data["discovered_servers"] == 1
    assert data["profiles"] == []
    assert [s["reason"] for s in data["skipped"]] == ["out_of_project"]
    assert not list((tmp_path / "c").rglob("*.json"))  # nothing introspected, nothing cached


# --- shadowed -----------------------------------------------------------------------


def test_shadowed_entries_are_skipped_with_reason(tmp_path: Path) -> None:
    s = full_setup(tmp_path)
    configs = run_discovery(s.host, s.project)
    report = build_scan(configs, s.host, s.project, ProveflowConfig())
    shadowed = {(k.server_ref, k.scope) for k in report.skipped if k.reason is SkipReason.SHADOWED}
    assert shadowed == {("fetch", ConfigScope.PROJECT), ("slack", ConfigScope.USER)}
    out_of_project = {k.server_ref for k in report.skipped if k.reason is SkipReason.OUT_OF_PROJECT}
    assert out_of_project == {"linear"}
    _assert_accounted(report, configs)


# --- servers kept in a profile with an introspection status (never dropped) ----------


def test_remote_transport_stays_in_profile(tmp_path: Path) -> None:
    remote = {"type": "http", "url": "https://example.invalid/mcp"}
    configs, project = _explicit(tmp_path, {"r": remote})
    report = _introspected_scan(tmp_path, configs, project, "yes")
    assert _members(report) == {"r": IntrospectionStatus.REMOTE_NOT_INTROSPECTED}
    assert report.skipped == ()
    _assert_accounted(report, configs)


def test_unresolved_variables_stays_in_profile(tmp_path: Path) -> None:
    configs, project = _explicit(tmp_path, {"v": {"command": sys.executable, "args": ["${MODE}"]}})

    def never(_s: ServerSpec) -> Consent:
        raise AssertionError("no prompt for a server that is never launched")

    specs = [s for c in configs for s in c.servers]
    results = introspect_specs(specs, consent=never, timeout=10)
    report = build_scan(configs, make_host(tmp_path), project, ProveflowConfig(), results)
    assert _members(report) == {"v": IntrospectionStatus.UNRESOLVED_VARIABLES}
    _assert_accounted(report, configs)


def test_consent_denied_stays_in_profile(tmp_path: Path) -> None:
    configs, project = _explicit(tmp_path, {"d": {"command": sys.executable, "args": ["-c", "0"]}})
    report = _introspected_scan(tmp_path, configs, project, "no")
    assert _members(report) == {"d": IntrospectionStatus.DECLINED}
    _assert_accounted(report, configs)


def test_non_interactive_no_consent_stays_in_profile(tmp_path: Path) -> None:
    configs, project = _explicit(tmp_path, {"n": {"command": sys.executable, "args": ["-c", "0"]}})
    report = _introspected_scan(tmp_path, configs, project, "unavailable")
    assert _members(report) == {"n": IntrospectionStatus.CONSENT_REQUIRED}
    _assert_accounted(report, configs)


def test_launch_failed_stays_in_profile(tmp_path: Path) -> None:
    configs, project = _explicit(tmp_path, {"f": {"command": "proveflow-test-no-such-binary-7f3a"}})
    report = _introspected_scan(tmp_path, configs, project, "yes")
    assert _members(report) == {"f": IntrospectionStatus.FAILED}
    _assert_accounted(report, configs)


# --- the invariant itself -------------------------------------------------------------


@pytest.mark.parametrize("no_launch", [True, False])
def test_discovered_equals_analyzed_plus_skipped(tmp_path: Path, no_launch: bool) -> None:
    s = full_setup(tmp_path)
    configs = run_discovery(s.host, s.project)
    introspection = None if no_launch else {}  # introspect mode, nothing consented
    report = build_scan(configs, s.host, s.project, ProveflowConfig(), introspection)
    _assert_accounted(report, configs)
    assert report.discovered_servers > 0 and report.skipped


def test_report_that_drops_a_server_is_refused(tmp_path: Path) -> None:
    s = full_setup(tmp_path)
    report = build_scan(run_discovery(s.host, s.project), s.host, s.project, ProveflowConfig())
    data = report.model_dump()
    data["discovered_servers"] += 1
    with pytest.raises(ValidationError, match="server accounting mismatch"):
        ScanReport.model_validate(data)


# --- rendering ------------------------------------------------------------------------


def test_terminal_shows_skipped_table_and_counts(tmp_path: Path) -> None:
    s = full_setup(tmp_path)
    report = build_scan(run_discovery(s.host, s.project), s.host, s.project, ProveflowConfig())
    console = Console(record=True, width=TEST_COLUMNS)
    render_scan(report, console, limit=5)
    text = console.export_text()
    assert f"Skipped servers ({len(report.skipped)}, NOT analyzed)" in text
    assert (
        f"Servers: {report.discovered_servers} discovered, {report.analyzed_servers} analyzed, "
        f"{len(report.skipped)} skipped"
    ) in text
    assert "Toxic flows" in text  # profiles exist, so flows are shown


def test_sarif_run_properties_list_skipped_without_other_project_path(tmp_path: Path) -> None:
    host, project, other = _other_project_only(tmp_path)
    report = build_scan(run_discovery(host, project), host, project, ProveflowConfig())
    props = build_sarif(report)["runs"][0]["properties"]
    assert props["proveflowDiscoveredServers"] == 1
    assert props["proveflowAnalyzedServers"] == 0
    assert [(p["server"], p["reason"]) for p in props["proveflowSkippedServers"]] == [
        ("x", "out_of_project")
    ]
    assert other.name not in json.dumps(build_sarif(report))


def test_spec_key_unique_per_member(tmp_path: Path) -> None:
    """Sanity for the accounting: no member is counted twice across profiles."""
    s = full_setup(tmp_path)
    report = build_scan(run_discovery(s.host, s.project), s.host, s.project, ProveflowConfig())
    keys = [(p.id, spec_key(m.spec)) for p in report.profiles for m in p.servers]
    assert len(keys) == len(set(keys))
