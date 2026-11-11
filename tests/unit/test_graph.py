"""Flow graph with hand-built tool sets: exact flows, ranking, stable IDs."""

from __future__ import annotations

from proveflow.core.flows import FlowClass
from proveflow.core.tools import (
    Granularity,
    RoleEvidence,
    RoleSource,
    SinkSeverity,
    ToolRole,
    ToolSpec,
)
from proveflow.flows.graph import flows_for_profile, rank_flows

S, P, K = ToolRole.UNTRUSTED_SOURCE, ToolRole.PRIVATE_DATA, ToolRole.SINK


def tool(
    server: str,
    name: str,
    roles: dict[ToolRole, float],
    sev: SinkSeverity = SinkSeverity.NETWORK_EGRESS,
    gran: Granularity = Granularity.TOOL,
) -> ToolSpec:
    return ToolSpec(
        name=name,
        server=server,
        roles=tuple(
            RoleEvidence(
                role=r,
                source=RoleSource.HEURISTIC,
                reason="test",
                weight=w,
                granularity=gran,
                sink_severity=sev if r is K else None,
            )
            for r, w in roles.items()
        ),
    )


def labels(flows: list) -> set[tuple[str, str, str, str]]:  # type: ignore[type-arg]
    return {
        (
            f.flow_class.value,
            f.source.label if f.source else "-",
            f.private.label if f.private else "-",
            f.sink.label,
        )
        for f in flows
    }


def test_exact_flows_three_servers() -> None:
    tools = [
        tool("mail", "read_inbox", {S: 0.7, P: 0.7}),
        tool("db", "query", {P: 0.9}),
        tool("slack", "post", {K: 0.8}),
    ]
    got = labels(flows_for_profile("prof", tools))
    assert got == {
        ("exfil", "mail/read_inbox", "mail/read_inbox", "slack/post"),
        ("exfil", "mail/read_inbox", "db/query", "slack/post"),
        ("action", "mail/read_inbox", "-", "slack/post"),
        ("leak", "-", "mail/read_inbox", "slack/post"),
        ("leak", "-", "db/query", "slack/post"),
    }


def test_single_tool_never_flows_to_itself() -> None:
    tools = [tool("x", "do_everything", {S: 0.9, P: 0.9, K: 0.9})]
    assert flows_for_profile("prof", tools) == []


def test_server_level_pseudo_tool_may_flow_within_server() -> None:
    tools = [tool("gmail", "*", {S: 0.35, P: 0.35, K: 0.35}, gran=Granularity.SERVER)]
    flows = flows_for_profile("prof", tools)
    assert {f.flow_class for f in flows} == {FlowClass.EXFIL, FlowClass.ACTION, FlowClass.LEAK}
    assert all(not f.cross_server for f in flows)
    assert all(f.granularity is Granularity.SERVER for f in flows)
    assert all(f.sink.tool is None for f in flows)


def test_confidence_is_min_endpoint_score() -> None:
    tools = [tool("a", "src", {S: 0.6}), tool("b", "snk", {K: 0.9})]
    [f] = flows_for_profile("prof", tools)
    assert f.confidence == 0.6


def test_ranking_order() -> None:
    tools = [
        tool("a", "src", {S: 0.9}),
        tool("a", "local_snk", {K: 0.9}, SinkSeverity.LOCAL_WRITE),
        tool("b", "net_snk", {K: 0.5}, SinkSeverity.NETWORK_EGRESS),
        tool("b", "priv", {P: 0.9}),
    ]
    ranked = rank_flows(flows_for_profile("prof", tools))
    # cross-server flows all come first
    cross = [f.cross_server for f in ranked]
    assert cross == sorted(cross, reverse=True)
    first = ranked[0]
    assert first.cross_server
    assert first.sink_severity is SinkSeverity.NETWORK_EGRESS
    assert first.flow_class is FlowClass.EXFIL
    assert ranked[-1].sink_severity is SinkSeverity.LOCAL_WRITE
    assert not ranked[-1].cross_server


def test_ids_stable_when_unrelated_tool_added() -> None:
    base = [tool("a", "src", {S: 0.9}), tool("b", "snk", {K: 0.9})]
    before = {f.id: labels([f]) for f in flows_for_profile("prof", base)}
    after_flows = flows_for_profile("prof", [*base, tool("c", "unrelated", {})])
    after = {f.id: labels([f]) for f in after_flows}
    assert before == after


def test_ids_differ_across_profiles() -> None:
    base = [tool("a", "src", {S: 0.9}), tool("b", "snk", {K: 0.9})]
    [f1] = flows_for_profile("p1", base)
    [f2] = flows_for_profile("p2", base)
    assert f1.id != f2.id
    assert f1.id.startswith("F-")
    assert len(f1.id) == 10
