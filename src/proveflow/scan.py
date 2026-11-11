"""Scan pipeline: configs → profiles → roles (+ overrides) → ranked flows.

Introspection results (optional) come from ``introspect.runner`` and are passed in, so this
module never imports the MCP SDK. Servers without an OK introspection fall back to
server-level (low-confidence) roles.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from proveflow import __version__
from proveflow.config import ProveflowConfig, RoleOverride
from proveflow.core.client import ClientConfig, ServerSpec, TransportKind
from proveflow.core.flows import Flow
from proveflow.core.tools import ToolSpec
from proveflow.discover.hostenv import HostEnv
from proveflow.discover.profiles import Profile, build_profiles
from proveflow.flows.graph import apply_override, flows_for_profile, rank_flows
from proveflow.flows.pinning import check_pinning
from proveflow.flows.roles import classify_tool
from proveflow.flows.server_roles import SERVER_TOOL_NAME, classify_server
from proveflow.introspect.cache import spec_key
from proveflow.report.models import (
    Finding,
    IntrospectionResult,
    IntrospectionStatus,
    ProfileReport,
    ScanReport,
    ServerReport,
)

COMMON_LIMITATIONS: tuple[str, ...] = (
    "Static analysis only: every flow is THEORETICAL until proven in a twin (Phase 7). "
    "No flow listed does not mean the setup is safe.",
    "Every configured server is treated as connected to its client (over-approximation): "
    "client-side approval and disabled flags are not modeled.",
    "Secrets in args/URLs are redacted by pattern (docs/REDACTION.md); a short unflagged "
    "positional secret can be missed. Env and header values are always fully redacted.",
)
NO_LAUNCH_LIMITATION = (
    "--no-launch: tools are unknown; roles are inferred from server names/commands only "
    "(granularity=server, low confidence)."
)
INTROSPECT_LIMITATION = (
    "Introspection ran each consented stdio server's own code for tools/list only (never "
    "tools/call), with a minimal environment; servers not introspected fall back to "
    "server-level, low-confidence roles. Tool roles come from untuned heuristics; their "
    "precision/recall is reported separately."
)


def stdio_specs(profiles: Sequence[Profile]) -> list[ServerSpec]:
    """Unique stdio servers across profiles, in deterministic order."""
    seen: dict[str, ServerSpec] = {}
    for profile in profiles:
        for member in profile.members:
            if member.spec.transport is TransportKind.STDIO:
                seen.setdefault(spec_key(member.spec), member.spec)
    return [seen[k] for k in sorted(seen)]


def pinning_findings(profiles: Sequence[Profile]) -> tuple[Finding, ...]:
    """PF-UNPINNED notes, one per configured server (deduplicated across profiles)."""
    found: dict[str, Finding] = {}
    for profile in profiles:
        for member in profile.members:
            check = check_pinning(member.spec)
            if check is None or check.status == "pinned":
                continue
            found.setdefault(
                spec_key(member.spec),
                Finding(
                    rule_id="PF-UNPINNED",
                    server=member.spec.name,
                    source_file=member.spec.source_file,
                    status=check.status,
                    launcher=check.launcher,
                    package=check.package,
                    reason=check.reason,
                ),
            )
    return tuple(sorted(found.values(), key=lambda f: (str(f.source_file), f.server)))


def _default_status(spec: ServerSpec) -> IntrospectionStatus:
    if spec.transport is TransportKind.STDIO:
        return IntrospectionStatus.SKIPPED_NO_LAUNCH
    if spec.auth_hint:
        return IntrospectionStatus.AUTH_REQUIRED
    return IntrospectionStatus.REMOTE_NOT_INTROSPECTED


def _override_label(o: RoleOverride) -> str:
    return f"{o.server}/{o.tool if o.tool is not None else SERVER_TOOL_NAME}"


def _tools_for(
    key: str,
    spec: ServerSpec,
    result: IntrospectionResult | None,
    overrides: Sequence[RoleOverride],
    used: set[int],
) -> list[ToolSpec]:
    if result is None or result.status is not IntrospectionStatus.OK:
        tool = classify_server(key, spec)
        for i, o in enumerate(overrides):
            if o.server == key and o.tool is None:
                tool = apply_override(tool, o.roles, o.sink_severity)
                used.add(i)
        return [tool]
    tools: list[ToolSpec] = []
    for raw in sorted(result.tools, key=lambda t: t.name):
        tool = classify_tool(raw.name, key, raw.description, raw.input_schema)
        tool_level = [i for i, o in enumerate(overrides) if o.server == key and o.tool == raw.name]
        server_level = [i for i, o in enumerate(overrides) if o.server == key and o.tool is None]
        # A tool-level override wins; a server-level override covers every other tool.
        for i in tool_level or server_level:
            o = overrides[i]
            tool = apply_override(tool, o.roles, o.sink_severity)
            used.add(i)
        tools.append(tool)
    return tools


def build_scan(
    configs: list[ClientConfig],
    host: HostEnv,
    project: Path,
    config: ProveflowConfig,
    introspection: Mapping[str, IntrospectionResult] | None = None,
) -> ScanReport:
    profiles = build_profiles(configs, host, project)
    used: set[int] = set()
    profile_reports: list[ProfileReport] = []
    all_flows: list[Flow] = []
    for profile in profiles:
        server_reports: list[ServerReport] = []
        tools: list[ToolSpec] = []
        for member in profile.members:
            result = introspection.get(spec_key(member.spec)) if introspection is not None else None
            member_tools = _tools_for(member.key, member.spec, result, config.override, used)
            tools.extend(member_tools)
            server_reports.append(
                ServerReport(
                    key=member.key,
                    spec=member.spec,
                    introspection=result.status if result else _default_status(member.spec),
                    protocol_version=result.protocol_version if result else None,
                    era=result.era if result else None,
                    detail=result.detail if result else None,
                    changes=result.changes if result else (),
                    baseline=result.baseline if result else None,
                    stderr_tail=result.stderr_tail if result else None,
                    tools=tuple(member_tools),
                )
            )
        all_flows.extend(flows_for_profile(profile.id, tools))
        profile_reports.append(
            ProfileReport(
                id=profile.id,
                client=profile.client,
                servers=tuple(server_reports),
                shadowed=profile.shadowed,
                notes=profile.notes,
            )
        )
    unused = sorted(
        _override_label(o)
        + (
            " (tool not introspected)"
            if o.tool is not None and introspection is not None
            else " (tool-level overrides need introspection)"
            if o.tool is not None
            else " (no match)"
        )
        for i, o in enumerate(config.override)
        if i not in used
    )
    mode = "introspect" if introspection is not None else "no_launch"
    return ScanReport(
        proveflow_version=__version__,
        project=str(project),
        mode=mode,
        profiles=tuple(profile_reports),
        flows=tuple(rank_flows(all_flows)),
        findings=pinning_findings(profiles),
        unused_overrides=tuple(unused),
        limitations=(
            COMMON_LIMITATIONS[:1]
            + ((INTROSPECT_LIMITATION,) if introspection is not None else (NO_LAUNCH_LIMITATION,))
            + COMMON_LIMITATIONS[1:]
        ),
    )
