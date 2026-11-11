"""SARIF 2.1.0 output for scan findings (validated in tests against the pinned
official OASIS schemas, tests/fixtures/sarif/SOURCE.md)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from proveflow.core.flows import Flow, FlowClass
from proveflow.report.json_out import to_json
from proveflow.report.models import ScanReport

SARIF_SCHEMA_URI = (
    "https://docs.oasis-open.org/sarif/sarif/v2.1.0/errata01/os/schemas/sarif-schema-2.1.0.json"
)

_RULES: tuple[tuple[str, FlowClass, str, str, str], ...] = (
    (
        "PF-EXFIL",
        FlowClass.EXFIL,
        "error",
        "Untrusted source + private data + sink in one agent profile",
        "Content from an attacker-controllable tool can instruct the agent to read private "
        "data with one tool and send it out through a sink tool. Static finding "
        "(THEORETICAL): not proven exploitable.",
    ),
    (
        "PF-ACTION",
        FlowClass.ACTION,
        "warning",
        "Untrusted source + sink in one agent profile",
        "Content from an attacker-controllable tool can instruct the agent to call a sink "
        "tool with attacker-chosen arguments. Static finding (THEORETICAL).",
    ),
    (
        "PF-LEAK",
        FlowClass.LEAK,
        "note",
        "Private data + sink in one agent profile (no untrusted source)",
        "Informational: private data can reach a sink if the agent is misused. "
        "Static finding (THEORETICAL).",
    ),
)
_RULE_INDEX = {cls: i for i, (_, cls, _, _, _) in enumerate(_RULES)}


def _message(f: Flow) -> str:
    path = " -> ".join(r.label for r in (f.source, f.private, f.sink) if r is not None)
    scope = "cross-server" if f.cross_server else "same-server"
    gran = " (server-level guess, tools unknown)" if f.granularity == "server" else ""
    return (
        f"{f.flow_class.value} flow {f.id} in profile {f.profile}: {path} [{scope}, sink "
        f"{f.sink_severity.value}, confidence {f.confidence:.2f}{gran}]. THEORETICAL."
    )


def build_sarif(report: ScanReport) -> dict[str, Any]:
    files: dict[tuple[str, str], Path] = {}
    for prof in report.profiles:
        for srv in prof.servers:
            files[(prof.id, srv.key)] = srv.spec.source_file

    results: list[dict[str, Any]] = []
    for f in report.flows:
        rule_id, _, level, _, _ = _RULES[_RULE_INDEX[f.flow_class]]
        ordered = [f.sink] + [r for r in (f.source, f.private) if r is not None]
        uris: list[str] = []
        for ref in ordered:
            path = files.get((f.profile, ref.server))
            if path is not None and path.is_absolute():
                uri = path.as_uri()
                if uri not in uris:
                    uris.append(uri)
        results.append(
            {
                "ruleId": rule_id,
                "ruleIndex": _RULE_INDEX[f.flow_class],
                "level": level,
                "message": {"text": _message(f)},
                "locations": [{"physicalLocation": {"artifactLocation": {"uri": u}}} for u in uris],
                "partialFingerprints": {"proveflowFlowId/v1": f.id},
                "properties": {
                    "flowId": f.id,
                    "profile": f.profile,
                    "flowClass": f.flow_class.value,
                    "crossServer": f.cross_server,
                    "sinkSeverity": f.sink_severity.value,
                    "confidence": f.confidence,
                    "granularity": f.granularity.value,
                    "verdict": f.verdict.value,
                },
            }
        )
    rules = [
        {
            "id": rid,
            "name": cls.value,
            "shortDescription": {"text": short},
            "fullDescription": {"text": full},
            "defaultConfiguration": {"level": level},
        }
        for rid, cls, level, short, full in _RULES
    ]
    return {
        "$schema": SARIF_SCHEMA_URI,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "proveflow",
                        "version": report.proveflow_version,
                        "rules": rules,
                    }
                },
                "results": results,
            }
        ],
    }


def write_sarif(report: ScanReport, path: Path) -> None:
    path.write_text(to_json(build_sarif(report)), encoding="utf-8", newline="\n")
