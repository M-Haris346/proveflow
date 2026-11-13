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


EXTRA_RULES: tuple[tuple[str, str, str, str, str], ...] = (
    (
        "PF-TOOLCHANGE",
        "tool_change",
        "note",
        "Tool description or schema changed since the last scan",
        "A server's tools/list differs from the cached previous run (tool added, removed, or "
        "description/schema changed). This can be a legitimate update or a rug-pull; review it.",
    ),
    (
        "PF-UNPINNED",
        "unpinned_launch",
        "note",
        "Server fetched at launch by npx/uvx/pipx without an exact version",
        "The server package is resolved at every launch (no version, a dist-tag such as "
        "@latest, or a range), so its code can change without any config change. Pin an exact "
        "version. Static check of the config only; see docs/PINNING.md.",
    ),
)
_EXTRA_INDEX = {rid: len(_RULES) + i for i, (rid, *_rest) in enumerate(EXTRA_RULES)}


def spec_ident(srv: Any) -> str:
    return f"{srv.spec.source_file}|{srv.spec.name}"


def _extra_result(rule_id: str, text: str, source: Path, props: dict[str, Any]) -> dict[str, Any]:
    rule = next(r for r in EXTRA_RULES if r[0] == rule_id)
    locations = (
        [{"physicalLocation": {"artifactLocation": {"uri": source.as_uri()}}}]
        if source.is_absolute()
        else []
    )
    return {
        "ruleId": rule_id,
        "ruleIndex": _EXTRA_INDEX[rule_id],
        "level": rule[2],
        "message": {"text": text},
        "locations": locations,
        "properties": props,
    }


def build_sarif(report: ScanReport) -> dict[str, Any]:
    files: dict[tuple[str, str], Path] = {}
    for prof in report.profiles:
        for srv in prof.servers:
            files[(prof.id, srv.key)] = srv.spec.source_file

    group_of = {mid: g.id for g in report.groups for mid in g.member_ids}
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
                    # one SARIF result per FLOW; the group is a property (one result per
                    # group is deferred: ARCHITECTURE §5.3 "Flow grouping")
                    "groupId": group_of[f.id],
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
    seen_change: set[tuple[str, str, str]] = set()
    for prof in report.profiles:
        for srv in prof.servers:
            for change in srv.changes:
                ident = (spec_ident(srv), change.tool, change.kind.value)
                if ident in seen_change:
                    continue
                seen_change.add(ident)
                results.append(
                    _extra_result(
                        "PF-TOOLCHANGE",
                        f"tool {srv.key}/{change.tool}: {change.kind.value} since the last "
                        "cached tools/list (possible rug-pull; review before trusting)",
                        srv.spec.source_file,
                        {"server": srv.key, "tool": change.tool, "change": change.kind.value},
                    )
                )
    for fnd in report.findings:
        results.append(
            _extra_result(
                fnd.rule_id,
                f"server {fnd.server}: {fnd.launcher} package "
                f"{fnd.package or '(not determined)'} is {fnd.status}: {fnd.reason}",
                fnd.source_file,
                {"server": fnd.server, "launcher": fnd.launcher, "status": fnd.status},
            )
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
    ] + [
        {
            "id": rid,
            "name": name,
            "shortDescription": {"text": short},
            "fullDescription": {"text": full},
            "defaultConfiguration": {"level": level},
        }
        for rid, name, level, short, full in EXTRA_RULES
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
                "properties": {
                    "proveflowMode": report.mode,
                    # Accounting (THREAT_MODEL T16): discovered = analyzed + skipped. An empty
                    # results list with skipped servers is not a clean result. The other
                    # project's path (SkippedServer.project) is left out of SARIF on purpose.
                    "proveflowDiscoveredServers": report.discovered_servers,
                    "proveflowAnalyzedServers": report.analyzed_servers,
                    "proveflowSkippedServers": [
                        {
                            "server": sk.server_ref,
                            "client": sk.client.value,
                            "scope": sk.scope.value,
                            "reason": sk.reason.value,
                            "detail": sk.detail,
                        }
                        for sk in report.skipped
                    ],
                    # Per server: was a tools/list baseline available? Makes an empty
                    # PF-TOOLCHANGE list unambiguous (first run vs compared vs no cache).
                    "proveflowServerBaselines": sorted(
                        (
                            {
                                "profile": prof.id,
                                "server": srv.key,
                                "introspection": srv.introspection.value,
                                "baseline": srv.baseline,
                                "patternRedactions": srv.pattern_redactions,
                            }
                            for prof in report.profiles
                            for srv in prof.servers
                        ),
                        key=lambda d: (str(d["profile"]), str(d["server"])),
                    ),
                },
            }
        ],
    }


def write_sarif(report: ScanReport, path: Path) -> None:
    path.write_text(to_json(build_sarif(report)), encoding="utf-8", newline="\n")
