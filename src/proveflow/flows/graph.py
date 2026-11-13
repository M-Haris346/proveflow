"""Flow graph: every ordered (source, private?, sink) path inside each agent profile.

Classes (ARCHITECTURE §3): exfil = source + private + sink, action = source + sink,
leak = private + sink (informational). Ranking (§5.3): cross-server first, then sink
severity (network egress > remote write > local write), then class, then confidence,
then a lexicographic tiebreak — so the same input always yields the same order and
the same IDs.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass

from proveflow.core.flows import (
    Flow,
    FlowClass,
    FlowGroup,
    GroupKey,
    ToolRef,
    group_attributes,
    group_id,
    group_key,
)
from proveflow.core.tools import (
    Granularity,
    RoleEvidence,
    RoleSource,
    SinkSeverity,
    ToolRole,
    ToolSpec,
)
from proveflow.flows.roles import role_score, sink_severity
from proveflow.flows.server_roles import SERVER_TOOL_NAME

_CLASS_RANK = {FlowClass.EXFIL: 0, FlowClass.ACTION: 1, FlowClass.LEAK: 2}


@dataclass(frozen=True)
class _Node:
    ref: ToolRef
    score: float
    server_level: bool
    severity: SinkSeverity | None


def _score(tool: ToolSpec, role: ToolRole) -> float:
    evs = [e for e in tool.roles if e.role is role]
    if any(e.granularity is Granularity.SERVER for e in evs):
        # Server-level evidence never adds up past a single weight: it is a guess.
        return max(e.weight for e in evs)
    return role_score(evs, role)


def _nodes(tools: Sequence[ToolSpec], role: ToolRole) -> list[_Node]:
    out: list[_Node] = []
    for t in tools:
        evs = [e for e in t.roles if e.role is role]
        if not evs:
            continue
        server_level = t.name == SERVER_TOOL_NAME and any(
            e.granularity is Granularity.SERVER for e in evs
        )
        ref = ToolRef(server=t.server, tool=None if t.name == SERVER_TOOL_NAME else t.name)
        out.append(_Node(ref, _score(t, role), server_level, sink_severity(evs)))
    return sorted(out, key=lambda n: n.ref.label)


def flow_id(profile: str, cls: FlowClass, refs: Sequence[ToolRef | None]) -> str:
    key = "|".join([profile, cls.value, *(r.label if r else "-" for r in refs)])
    return "F-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]


def _flow(profile: str, cls: FlowClass, src: _Node | None, prv: _Node | None, snk: _Node) -> Flow:
    parts = [n for n in (src, prv, snk) if n is not None]
    return Flow(
        id=flow_id(profile, cls, [src.ref if src else None, prv.ref if prv else None, snk.ref]),
        profile=profile,
        flow_class=cls,
        source=src.ref if src else None,
        private=prv.ref if prv else None,
        sink=snk.ref,
        cross_server=len({n.ref.server for n in parts}) > 1,
        sink_severity=snk.severity or SinkSeverity.NETWORK_EGRESS,
        confidence=round(min(n.score for n in parts), 4),
        granularity=Granularity.SERVER if any(n.server_level for n in parts) else Granularity.TOOL,
    )


def _distinct(*nodes: _Node) -> bool:
    """Tool-level: a path may not be one tool in every position. Server-level pseudo
    tools ("*") stand for many tools, so a same-server path is allowed."""
    refs = {n.ref for n in nodes}
    return len(refs) > 1 or all(n.server_level for n in nodes)


def flows_for_profile(profile: str, tools: Sequence[ToolSpec]) -> list[Flow]:
    sources = _nodes(tools, ToolRole.UNTRUSTED_SOURCE)
    privates = _nodes(tools, ToolRole.PRIVATE_DATA)
    sinks = _nodes(tools, ToolRole.SINK)
    out: list[Flow] = []
    for k in sinks:
        for s in sources:
            for p in privates:
                if _distinct(s, p, k):
                    out.append(_flow(profile, FlowClass.EXFIL, s, p, k))
            if _distinct(s, k):
                out.append(_flow(profile, FlowClass.ACTION, s, None, k))
        for p in privates:
            if _distinct(p, k):
                out.append(_flow(profile, FlowClass.LEAK, None, p, k))
    return out


def rank_key(f: Flow) -> tuple[object, ...]:
    return (
        not f.cross_server,
        f.sink_severity.rank,
        _CLASS_RANK[f.flow_class],
        -f.confidence,
        f.profile,
        f.source.label if f.source else "",
        f.private.label if f.private else "",
        f.sink.label,
    )


def rank_flows(flows: Sequence[Flow]) -> list[Flow]:
    return sorted(flows, key=rank_key)


# --- flow grouping (ARCHITECTURE §5.3) -----------------------------------------------------


def group_rank_key(g: FlowGroup) -> tuple[object, ...]:
    """rank_key's criteria on group attributes (no profile; '' for a missing server)."""
    return (
        not g.cross_server,
        g.worst_sink_severity.rank,
        _CLASS_RANK[g.flow_class],
        -g.max_confidence,
        g.source_server or "",
        g.private_server or "",
        g.sink_server,
    )


def group_flows(flows: Sequence[Flow]) -> list[FlowGroup]:
    """Group flows by (class, source server, private server, sink server) across profiles.
    Members are sorted by rank_key here (input order does not matter); groups are sorted by
    group_rank_key. Every flow lands in exactly one group."""
    buckets: dict[GroupKey, list[Flow]] = {}
    for f in flows:
        buckets.setdefault(group_key(f), []).append(f)
    groups: list[FlowGroup] = []
    for key, members in buckets.items():
        ranked = sorted(members, key=rank_key)
        cls, src, prv, snk = key
        groups.append(
            FlowGroup(
                id=group_id(key),
                flow_class=cls,
                source_server=src,
                private_server=prv,
                sink_server=snk,
                member_ids=tuple(f.id for f in ranked),
                **group_attributes(ranked),
            )
        )
    return sorted(groups, key=group_rank_key)


def apply_override(
    tool: ToolSpec, roles: Sequence[ToolRole], severity: SinkSeverity | None
) -> ToolSpec:
    gran = Granularity.SERVER if tool.name == SERVER_TOOL_NAME else Granularity.TOOL
    evidence = tuple(
        RoleEvidence(
            role=r,
            source=RoleSource.OVERRIDE,
            reason="override in proveflow.toml",
            weight=1.0,
            granularity=gran,
            sink_severity=(severity or SinkSeverity.NETWORK_EGRESS) if r is ToolRole.SINK else None,
        )
        for r in sorted(set(roles))
    )
    return tool.model_copy(update={"roles": evidence})
