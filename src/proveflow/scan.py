"""Static scan pipeline: configs → profiles → roles (+ overrides) → ranked flows."""

from __future__ import annotations

from pathlib import Path

from proveflow import __version__
from proveflow.config import ProveflowConfig, RoleOverride
from proveflow.core.client import ClientConfig, ServerSpec, TransportKind
from proveflow.core.tools import ToolSpec
from proveflow.discover.hostenv import HostEnv
from proveflow.discover.profiles import build_profiles
from proveflow.flows.graph import apply_override, flows_for_profile, rank_flows
from proveflow.flows.server_roles import SERVER_TOOL_NAME, classify_server
from proveflow.report.models import (
    IntrospectionStatus,
    ProfileReport,
    ScanReport,
    ServerReport,
)

LIMITATIONS: tuple[str, ...] = (
    "Static analysis only: every flow is THEORETICAL until proven in a twin (Phase 7). "
    "No flow listed does not mean the setup is safe.",
    "--no-launch: tools are unknown; roles are inferred from server names/commands only "
    "(granularity=server, low confidence).",
    "Every configured server is treated as connected to its client (over-approximation): "
    "client-side approval and disabled flags are not modeled.",
    "Secrets in args/URLs are redacted by pattern (docs/REDACTION.md); a short unflagged "
    "positional secret can be missed. Env and header values are always fully redacted.",
)


def _introspection_status(spec: ServerSpec) -> IntrospectionStatus:
    if spec.transport is TransportKind.STDIO:
        return IntrospectionStatus.SKIPPED_NO_LAUNCH
    if spec.auth_hint:
        return IntrospectionStatus.AUTH_REQUIRED
    return IntrospectionStatus.REMOTE_NOT_INTROSPECTED


def _override_label(o: RoleOverride) -> str:
    return f"{o.server}/{o.tool if o.tool is not None else SERVER_TOOL_NAME}"


def build_scan(
    configs: list[ClientConfig], host: HostEnv, project: Path, config: ProveflowConfig
) -> ScanReport:
    profiles = build_profiles(configs, host, project)
    used: set[int] = set()
    profile_reports: list[ProfileReport] = []
    all_flows = []
    for profile in profiles:
        server_reports: list[ServerReport] = []
        tools: list[ToolSpec] = []
        for member in profile.members:
            tool = classify_server(member.key, member.spec)
            for i, o in enumerate(config.override):
                if o.server == member.key and o.tool is None:
                    tool = apply_override(tool, o.roles, o.sink_severity)
                    used.add(i)
            tools.append(tool)
            server_reports.append(
                ServerReport(
                    key=member.key,
                    spec=member.spec,
                    introspection=_introspection_status(member.spec),
                    tools=(tool,),
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
        + (" (tool-level overrides need introspection)" if o.tool is not None else " (no match)")
        for i, o in enumerate(config.override)
        if i not in used
    )
    return ScanReport(
        proveflow_version=__version__,
        project=str(project),
        mode="no_launch",
        profiles=tuple(profile_reports),
        flows=tuple(rank_flows(all_flows)),
        unused_overrides=tuple(unused),
        limitations=LIMITATIONS,
    )
