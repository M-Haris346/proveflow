"""Shared helpers and NAMED checks for ``proveflow twin`` (Phase 4 step 11), used by
tests/unit/test_cli_twin.py and tests/mutation/test_twin_cli_mutation.py.

Synthetic input only: a scan report built from the fake-home fixture configs, with
introspection results made from STORED tool metadata (data/eval); nothing is launched, no
network. Output paths live in the test's TWIN_ROOT (``proxyhelpers.proxy_twin_root``).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from fakehome import full_setup
from proveflow.cli import app
from proveflow.config import ProveflowConfig
from proveflow.discover import run_discovery
from proveflow.introspect.cache import spec_key
from proveflow.proxy import policy as policy_module
from proveflow.report.json_out import to_json
from proveflow.report.models import IntrospectionResult, IntrospectionStatus, RawTool, ScanReport
from proveflow.scan import build_scan
from twinchecks import stored_tools

runner = CliRunner()
PROFILE = "claude_desktop"  # brave-search, filesystem, gmail in the fixture configs
STORED_FOR = {"brave-search": "fetch", "filesystem": "filesystem", "gmail": "pg-mcp-guard"}


def _result(server: str) -> IntrospectionResult:
    tools = tuple(
        RawTool(name=t.name, description=t.description, input_schema=t.input_schema)  # type: ignore[attr-defined]
        for t in stored_tools(STORED_FOR.get(server, "fetch"))
    )
    return IntrospectionResult(
        status=IntrospectionStatus.OK, protocol_version="2025-11-25", era="handshake", tools=tools
    )


def make_scan(tmp_path: Path, *, introspect: bool = True) -> tuple[Path, ScanReport]:
    s = full_setup(tmp_path / "home")
    configs = run_discovery(s.host, s.project)
    stdio = [sp for c in configs for sp in c.servers if sp.transport == "stdio"]
    results = {spec_key(sp): _result(sp.name) for sp in stdio} if introspect else None
    report = build_scan(configs, s.host, s.project, ProveflowConfig(), results)
    path = tmp_path / "scan.json"
    path.write_text(to_json(report), encoding="utf-8")
    return path, report


def out_dir() -> Path:
    return policy_module.TWIN_ROOT / "run1"


def invoke(*args: str) -> Any:
    return runner.invoke(app, ["twin", *args])


def run_default(scan: Path) -> Any:
    return invoke("--from", str(scan), "--profile", PROFILE, "--out-dir", str(out_dir()))


def files(d: Path) -> dict[str, str]:
    if not d.exists():
        return {}
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(d.iterdir())}


def assert_no_launch_scan_refused(tmp_path: Path) -> None:
    """Named check: a --no-launch scan is refused and nothing is written."""
    scan, _ = make_scan(tmp_path, introspect=False)
    result = run_default(scan)
    if result.exit_code != 1 or "--no-launch" not in result.stderr or files(out_dir()):
        raise AssertionError("a --no-launch scan was not refused")


def assert_out_dir_outside_twin_root_refused(tmp_path: Path) -> None:
    """Named check: an --out-dir outside TWIN_ROOT is refused before anything is written."""
    scan, _ = make_scan(tmp_path)
    outside = tmp_path / "elsewhere"
    result = invoke("--from", str(scan), "--profile", PROFILE, "--out-dir", str(outside))
    if result.exit_code != 1 or outside.exists():
        raise AssertionError("an out-dir outside TWIN_ROOT was accepted")


def assert_existing_target_refuses_whole_run(tmp_path: Path, existing: str) -> None:
    """Named check: one existing target file refuses the run; nothing else is written."""
    scan, _ = make_scan(tmp_path)
    out_dir().mkdir(parents=True)
    (out_dir() / existing).write_text("x", encoding="utf-8")
    result = run_default(scan)
    if result.exit_code != 1 or set(files(out_dir())) != {existing}:
        raise AssertionError(f"existing {existing} did not refuse the whole run")
