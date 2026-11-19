"""Flow grouping (ARCHITECTURE §5.3): key, id, order, derived fields and the report
validator. Synthetic tools and the fixture home only (never a real machine)."""

from __future__ import annotations

import json
import random
import re
import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from fakehome import claude_desktop_path, full_setup, make_host
from proveflow.config import ProveflowConfig, load_config
from proveflow.core.flows import Flow, FlowClass, group_attributes, group_key
from proveflow.core.tools import Granularity, SinkSeverity, ToolRole, ToolSpec
from proveflow.discover import run_discovery
from proveflow.flows.graph import (
    apply_override,
    flows_for_profile,
    group_flows,
    group_rank_key,
    rank_flows,
    rank_key,
)
from proveflow.report.models import ScanReport
from proveflow.report.sarif import build_sarif
from proveflow.scan import build_scan
from widths import TEST_COLUMNS

S, P, K = ToolRole.UNTRUSTED_SOURCE, ToolRole.PRIVATE_DATA, ToolRole.SINK


def tool(server: str, name: str, roles: list[ToolRole],
         severity: SinkSeverity | None = None) -> ToolSpec:  # fmt: skip
    return apply_override(ToolSpec(name=name, server=server), roles, severity)


TRIPLE = [tool("web", "fetch", [S]), tool("db", "query", [P]), tool("mail", "send", [K])]


def _report(flows: list[Flow]) -> ScanReport:
    ranked = rank_flows(flows)
    return ScanReport(proveflow_version="t", project="p", mode="no_launch",
                      discovered_servers=0, profiles=(), flows=tuple(ranked),
                      groups=tuple(group_flows(ranked)), limitations=())  # fmt: skip


def test_cross_profile_flows_collapse_into_one_group() -> None:
    flows = flows_for_profile("A", TRIPLE) + flows_for_profile("B", TRIPLE)
    exfil = [g for g in group_flows(flows) if g.flow_class is FlowClass.EXFIL]
    assert len(exfil) == 1
    [g] = exfil
    assert g.profiles == ("A", "B") and len(g.member_ids) == 2
    assert (g.source_server, g.private_server, g.sink_server) == ("web", "db", "mail")
    assert g.cross_server is True


def test_derived_action_and_leak_stay_separate_groups() -> None:
    groups = group_flows(flows_for_profile("A", TRIPLE))
    keys = {(g.flow_class, g.source_server, g.private_server, g.sink_server) for g in groups}
    assert keys == {
        (FlowClass.EXFIL, "web", "db", "mail"),
        (FlowClass.ACTION, "web", None, "mail"),
        (FlowClass.LEAK, None, "db", "mail"),
    }
    assert len({g.id for g in groups}) == 3


def test_mixed_granularity_shares_a_group() -> None:
    server_level = [tool("web", "*", [S]), tool("db", "*", [P]), tool("mail", "*", [K])]
    flows = flows_for_profile("A", TRIPLE) + flows_for_profile("B", server_level)
    for g in group_flows(flows):
        assert g.granularities == (Granularity.SERVER, Granularity.TOOL)
        assert len(g.member_ids) == 2


def test_single_server_collapses_to_at_most_one_group_per_class() -> None:
    tools = [tool("solo", f"src{i}", [S]) for i in range(3)]
    tools += [tool("solo", f"prv{i}", [P]) for i in range(3)]
    tools += [tool("solo", f"snk{i}", [K]) for i in range(3)]
    flows = flows_for_profile("A", tools)
    groups = group_flows(flows)
    assert len(flows) == 3 * 3 * 3 + 3 * 3 + 3 * 3  # every tool path is still a flow
    assert len(groups) == 3 and all(g.cross_server is False for g in groups)
    assert sum(len(g.member_ids) for g in groups) == len(flows)


def test_derived_fields_worst_severity_max_confidence() -> None:
    a = [tool("web", "fetch", [S]), tool("mail", "draft", [K], SinkSeverity.LOCAL_WRITE)]
    b = [tool("web", "fetch", [S]), tool("mail", "send", [K], SinkSeverity.NETWORK_EGRESS)]
    [g] = group_flows(flows_for_profile("A", a) + flows_for_profile("B", b))
    assert g.worst_sink_severity is SinkSeverity.NETWORK_EGRESS
    assert g.max_confidence == 1.0 and g.profiles == ("A", "B")


def test_group_ids_stable_across_tmp_dirs_while_flow_ids_differ() -> None:
    ids, flow_ids = [], []
    for _ in range(2):
        with tempfile.TemporaryDirectory() as d:
            s = full_setup(Path(d))
            rep = build_scan(run_discovery(s.host, s.project), s.host, s.project,
                             ProveflowConfig())  # fmt: skip
            ids.append([g.id for g in rep.groups])
            flow_ids.append({f.id for f in rep.flows})
    assert ids[0] == ids[1] and ids[0]
    assert flow_ids[0] != flow_ids[1]  # flow ids embed the (path-bearing) profile id


def test_order_is_deterministic_on_raw_unranked_input() -> None:
    tools = [*TRIPLE, tool("web", "browse", [S]), tool("db", "dump", [P]),
             tool("chat", "post", [K], SinkSeverity.REMOTE_WRITE)]  # fmt: skip
    flows = flows_for_profile("A", tools) + flows_for_profile("B", tools[:3])
    expected = group_flows(rank_flows(flows))
    for seed in range(5):
        raw = list(flows)
        random.Random(seed).shuffle(raw)  # noqa: S311 - raw, unranked test input
        got = group_flows(raw)
        assert got == expected
    assert expected == sorted(expected, key=group_rank_key)
    by_id = {f.id: f for f in flows}
    for g in expected:  # members in rank_key order
        members = [by_id[m] for m in g.member_ids]
        assert members == sorted(members, key=rank_key)


def test_pipe_in_server_names_cannot_collide_and_scan_does_not_raise(tmp_path: Path) -> None:
    """Under a '|'-join, (exfil, 'a|b', 'c', 'd') and (exfil, 'a', 'b|c', 'd') would hash the
    same input; group_id uses a JSON array instead."""
    host = make_host(tmp_path)
    project = tmp_path / "proj"
    project.mkdir()
    servers = tmp_path / "servers.json"
    names = ["a|b", "c", "d", "a", "b|c"]
    servers.write_text(json.dumps({"mcpServers": {n: {"command": "node"} for n in names}}),
                       encoding="utf-8")  # fmt: skip
    toml = tmp_path / "proveflow.toml"
    roles = {"a|b": "untrusted_source", "a": "untrusted_source", "c": "private_data",
             "b|c": "private_data", "d": "sink"}  # fmt: skip
    toml.write_text("".join(f'[[override]]\nserver = "{n}"\nroles = ["{r}"]\n\n'
                            for n, r in roles.items()), encoding="utf-8")  # fmt: skip
    rep = build_scan(run_discovery(host, project, servers), host, project, load_config(toml))
    keys = {g.key: g.id for g in rep.groups}
    k1, k2 = (FlowClass.EXFIL, "a|b", "c", "d"), (FlowClass.EXFIL, "a", "b|c", "d")
    assert "|".join(["exfil", "a|b", "c", "d"]) == "|".join(["exfil", "a", "b|c", "d"])
    assert k1 in keys and k2 in keys and keys[k1] != keys[k2]


def test_same_name_different_command_servers_merge(tmp_path: Path) -> None:
    """Known limitation (ARCHITECTURE §5.3): the key is the profile's server KEY, so two
    profiles' "github" entries with different commands share one group."""
    host = make_host(tmp_path)
    project = tmp_path / "proj"
    project.mkdir()
    desktop = claude_desktop_path(host)
    desktop.parent.mkdir(parents=True, exist_ok=True)
    desktop.write_text(json.dumps({"mcpServers": {"github": {"command": "npx",
                       "args": ["-y", "@example/github-a"]}}}), encoding="utf-8")  # fmt: skip
    cursor = host.home / ".cursor" / "mcp.json"
    cursor.parent.mkdir(parents=True, exist_ok=True)
    cursor.write_text(json.dumps({"mcpServers": {"github": {"command": "docker",
                      "args": ["run", "example/github-b"]}}}), encoding="utf-8")  # fmt: skip
    toml = tmp_path / "proveflow.toml"
    toml.write_text('[[override]]\nserver = "github"\nroles = ["untrusted_source", '
                    '"private_data", "sink"]\n', encoding="utf-8")  # fmt: skip
    rep = build_scan(run_discovery(host, project), host, project, load_config(toml))
    commands = {str(s.spec.command) for p in rep.profiles for s in p.servers}
    assert commands == {"npx", "docker"}  # two different servers...
    [g] = [g for g in rep.groups if g.flow_class is FlowClass.EXFIL]
    assert len(g.profiles) == 2 and len(g.member_ids) == 2  # ...merged into one group


# --- report validator ------------------------------------------------------------------


def _valid() -> ScanReport:
    return _report(flows_for_profile("A", TRIPLE) + flows_for_profile("B", TRIPLE))


def _with_groups(rep: ScanReport, groups: list[dict[str, object]]) -> None:
    data = rep.model_dump()
    data["groups"] = groups
    ScanReport.model_validate(data)


def test_validator_rejects_flow_in_no_group() -> None:
    rep = _valid()
    groups = [dict(g) for g in rep.model_dump()["groups"]]
    groups[0]["member_ids"] = groups[0]["member_ids"][:1]
    with pytest.raises(ValidationError):
        _with_groups(rep, groups)


def test_validator_rejects_unknown_member() -> None:
    rep = _valid()
    groups = [dict(g) for g in rep.model_dump()["groups"]]
    groups[0]["member_ids"] = [*groups[0]["member_ids"], "F-00000000"]
    with pytest.raises(ValidationError, match="is not a flow"):
        _with_groups(rep, groups)


def test_validator_rejects_flow_in_two_groups() -> None:
    rep = _valid()
    groups = [dict(g) for g in rep.model_dump()["groups"]]
    groups[1]["member_ids"] = [*groups[1]["member_ids"], groups[0]["member_ids"][0]]
    with pytest.raises(ValidationError):
        _with_groups(rep, groups)


def test_validator_rejects_duplicate_group_ids() -> None:
    rep = _valid()
    groups = [dict(g) for g in rep.model_dump()["groups"]]
    groups.append(dict(groups[0]))
    with pytest.raises(ValidationError, match="duplicate group ids"):
        _with_groups(rep, groups)


@pytest.mark.parametrize(("field", "value"), [("max_confidence", 0.1),
                                              ("cross_server", False),
                                              ("worst_sink_severity", "local_write"),
                                              ("profiles", ["A"])])  # fmt: skip
def test_validator_rejects_derived_field_mismatch(field: str, value: object) -> None:
    rep = _valid()
    groups = [dict(g) for g in rep.model_dump()["groups"]]
    groups[0][field] = value
    with pytest.raises(ValidationError, match="does not match its members"):
        _with_groups(rep, groups)


def test_validator_rejects_wrong_id() -> None:
    rep = _valid()
    groups = [dict(g) for g in rep.model_dump()["groups"]]
    groups[0]["id"] = "G-deadbeef"
    with pytest.raises(ValidationError, match="does not match its key"):
        _with_groups(rep, groups)


def test_validator_rejects_member_with_wrong_key_even_when_derived_fields_match() -> None:
    """Move one flow into another group and recompute BOTH groups' derived fields from their
    new members, so only the member-key check can fire."""
    rep = _valid()
    flows = {f.id: f for f in rep.flows}
    groups = [dict(g) for g in rep.model_dump()["groups"]]
    src = next(i for i, g in enumerate(groups) if len(g["member_ids"]) > 1)
    dst = next(i for i in range(len(groups)) if i != src)
    moved = groups[src]["member_ids"][-1]
    groups[src]["member_ids"] = list(groups[src]["member_ids"][:-1])
    groups[dst]["member_ids"] = [*groups[dst]["member_ids"], moved]
    for g in (groups[src], groups[dst]):
        g.update(group_attributes([flows[m] for m in g["member_ids"]]))
    expected = f"group {groups[dst]['id']}: member {moved} has a different key"
    with pytest.raises(ValidationError, match=re.escape(expected)):
        _with_groups(rep, groups)


def test_max_confidence_is_the_highest_member_confidence() -> None:
    """One member from overrides (confidence 1.0), one from heuristics (< 1.0): the group
    must carry the max, not the min (the builder and validator share group_attributes, so
    this pins the semantics independently)."""
    from proveflow.flows.roles import classify_tool

    override = [tool("web", "fetch_page", [S]), tool("mail", "send_email", [K])]
    heuristic = [
        classify_tool("fetch_page", "web", "Fetch a web page", {"properties": {"url": {}}}),
        classify_tool("send_email", "mail", "Send an email", {"properties": {"to": {}}}),
    ]
    flows = flows_for_profile("A", override) + flows_for_profile("B", heuristic)
    action = [f for f in flows if f.flow_class is FlowClass.ACTION
              and f.source and f.source.server == "web" and f.sink.server == "mail"]  # fmt: skip
    confs = sorted({f.confidence for f in action})
    msg = f"member confidences: {confs}"
    assert len(confs) == 2 and confs[0] < confs[1] == 1.0, msg
    [g] = [g for g in group_flows(flows) if g.flow_class is FlowClass.ACTION
           and g.source_server == "web" and g.sink_server == "mail"]  # fmt: skip
    assert g.max_confidence == confs[1], msg
    assert g.max_confidence != confs[0], msg


# --- outputs -----------------------------------------------------------------------------


def test_sarif_has_one_result_per_flow_with_its_group_id(tmp_path: Path) -> None:
    s = full_setup(tmp_path)
    rep = build_scan(run_discovery(s.host, s.project), s.host, s.project, ProveflowConfig())
    results = [r for r in build_sarif(rep)["runs"][0]["results"]
               if r["ruleId"] in ("PF-EXFIL", "PF-ACTION", "PF-LEAK")]  # fmt: skip
    assert len(results) == len(rep.flows)
    group_of = {m: g.id for g in rep.groups for m in g.member_ids}
    by_flow = {f.id: f for f in rep.flows}
    for r in results:
        fid = r["properties"]["flowId"]
        assert r["properties"]["groupId"] == group_of[fid]
        assert group_key(by_flow[fid]) == next(g.key for g in rep.groups if g.id == group_of[fid])


def test_json_schema_2_and_every_flow_in_exactly_one_group(tmp_path: Path) -> None:
    s = full_setup(tmp_path)
    rep = build_scan(run_discovery(s.host, s.project), s.host, s.project, ProveflowConfig())
    data = json.loads(rep.model_dump_json())
    assert data["schema_version"] == 2
    members = [m for g in data["groups"] for m in g["member_ids"]]
    assert sorted(members) == sorted(f["id"] for f in data["flows"])


def test_terminal_shows_one_row_per_group_with_server_marker(tmp_path: Path) -> None:
    from rich.console import Console

    from proveflow.report.terminal import render_scan

    s = full_setup(tmp_path)
    rep = build_scan(run_discovery(s.host, s.project), s.host, s.project, ProveflowConfig())
    console = Console(record=True, width=TEST_COLUMNS)
    render_scan(rep, console, limit=3)
    text = console.export_text()
    title = f"Toxic flows: {len(rep.groups)} groups ({len(rep.flows)} flows), all THEORETICAL"
    assert title in text
    for col in ("worst sink kind", "max conf", "#flows", "#profiles"):
        assert col in text
    assert rep.groups[0].id in text and rep.groups[3].id not in text  # --limit counts groups
    assert f"... {len(rep.groups) - 3} more groups" in text
    assert "(server)" in text  # fixture flows are all server-level
