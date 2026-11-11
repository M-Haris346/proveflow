"""SARIF output validates against the pinned official OASIS 2.1.0 schemas."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import validators

from fakehome import full_setup
from proveflow.config import ProveflowConfig
from proveflow.discover import run_discovery
from proveflow.report.sarif import SARIF_SCHEMA_URI, build_sarif, write_sarif
from proveflow.scan import build_scan

SCHEMAS = Path(__file__).resolve().parents[1] / "fixtures" / "sarif"
PINNED = {
    "sarif-schema-2.1.0-errata01.json": (
        "c3b4bb2d6093897483348925aaa73af03b3e3f4bd4ca38cef26dcb4212a2682e"
    ),
    "sarif-schema-2.1.0-os.json": (
        "ad6db49878699b091f3eeb765b6e29e92a34bad4da88664d000c923b549c3a25"
    ),
}


def _schema(name: str) -> dict[str, Any]:
    raw = (SCHEMAS / name).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == PINNED[name], f"{name} modified"
    data: dict[str, Any] = json.loads(raw)
    return data


def _validate(doc: dict[str, Any], name: str) -> None:
    schema = _schema(name)
    cls = validators.validator_for(schema)
    cls.check_schema(schema)
    errors = sorted(cls(schema).iter_errors(doc), key=lambda e: list(e.path))
    assert not errors, [f"{list(e.path)}: {e.message}" for e in errors[:5]]


@pytest.mark.parametrize("schema_name", sorted(PINNED))
def test_scan_sarif_validates(tmp_path: Path, schema_name: str) -> None:
    s = full_setup(tmp_path)
    report = build_scan(run_discovery(s.host, s.project), s.host, s.project, ProveflowConfig())
    assert report.flows
    out = tmp_path / "out.sarif"
    write_sarif(report, out)
    doc = json.loads(out.read_text(encoding="utf-8"))
    _validate(doc, schema_name)
    assert doc["$schema"] == SARIF_SCHEMA_URI
    assert doc["version"] == "2.1.0"
    results = doc["runs"][0]["results"]
    flow_results = [r for r in results if r["ruleId"] in {"PF-EXFIL", "PF-ACTION", "PF-LEAK"}]
    assert len(flow_results) == len(report.flows)
    unpinned = [r for r in results if r["ruleId"] == "PF-UNPINNED"]
    assert len(unpinned) == len(report.findings) > 0
    assert {r["ruleId"] for r in results} <= {"PF-EXFIL", "PF-ACTION", "PF-LEAK", "PF-UNPINNED"}
    assert all(r["locations"] for r in results)
    assert b"\r\n" not in out.read_bytes()


@pytest.mark.parametrize("schema_name", sorted(PINNED))
def test_empty_scan_sarif_validates(tmp_path: Path, schema_name: str) -> None:
    from fakehome import make_host

    host = make_host(tmp_path)
    project = tmp_path / "p"
    project.mkdir()
    report = build_scan(run_discovery(host, project), host, project, ProveflowConfig())
    assert report.flows == ()
    _validate(build_sarif(report), schema_name)


@pytest.mark.parametrize("schema_name", sorted(PINNED))
def test_toolchange_sarif_validates(tmp_path: Path, schema_name: str) -> None:
    from proveflow.introspect.cache import spec_key
    from proveflow.report.models import (
        IntrospectionResult,
        IntrospectionStatus,
        RawTool,
        ToolChange,
        ToolChangeKind,
    )

    s = full_setup(tmp_path)
    configs = run_discovery(s.host, s.project)
    stdio = [sp for c in configs for sp in c.servers if sp.transport == "stdio"]
    changed = IntrospectionResult(
        status=IntrospectionStatus.OK,
        protocol_version="2025-11-25",
        era="handshake",
        tools=(RawTool(name="send_email", description="Send an email"),),
        changes=(ToolChange(kind=ToolChangeKind.DESCRIPTION_CHANGED, tool="send_email"),),
    )
    report = build_scan(
        configs, s.host, s.project, ProveflowConfig(), {spec_key(sp): changed for sp in stdio}
    )
    doc = build_sarif(report)
    _validate(doc, schema_name)
    rule_ids = [r["ruleId"] for r in doc["runs"][0]["results"]]
    assert "PF-TOOLCHANGE" in rule_ids
    driver_rules = [r["id"] for r in doc["runs"][0]["tool"]["driver"]["rules"]]
    for result in doc["runs"][0]["results"]:
        assert driver_rules[result["ruleIndex"]] == result["ruleId"]
