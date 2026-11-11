"""Tool-level and server-level role heuristics."""

from __future__ import annotations

from pathlib import Path

import pytest

from proveflow.core.client import ConfigScope, ServerSpec, TransportKind
from proveflow.core.redact import RedactedText, RedactedValue
from proveflow.core.tools import Granularity, SinkSeverity, ToolRole
from proveflow.flows.roles import (
    ROLE_THRESHOLD,
    assigned_roles,
    classify_tool,
    role_score,
    sink_severity,
    tokenize,
)
from proveflow.flows.server_roles import SERVER_WEIGHT, classify_server

S, P, K = ToolRole.UNTRUSTED_SOURCE, ToolRole.PRIVATE_DATA, ToolRole.SINK


def test_tokenize() -> None:
    assert tokenize("sendEmailMessages") == ["send", "email", "message"]
    assert tokenize("list_issues") == ["list", "issue"]
    assert tokenize("browser-navigate") == ["browser", "navigate"]
    assert tokenize("address") == ["address"]


@pytest.mark.parametrize(
    ("name", "expected", "severity"),
    [
        ("send_email", {K}, SinkSeverity.NETWORK_EGRESS),
        ("read_email", {S, P}, None),
        ("read_file", {P}, None),
        ("write_file", {K}, SinkSeverity.LOCAL_WRITE),
        ("create_issue", {K}, SinkSeverity.REMOTE_WRITE),
        ("list_issues", {S}, None),
        ("fetch", {S}, None),
        ("execute_command", {K}, SinkSeverity.NETWORK_EGRESS),
        ("query_database", {P}, None),
        ("get_current_time", set(), None),
    ],
)
def test_tool_name_roles(name: str, expected: set[ToolRole], severity: SinkSeverity | None) -> None:
    tool = classify_tool(name, "srv")
    assert assigned_roles(tool) == expected
    assert sink_severity(tool.roles) == severity
    for ev in tool.roles:
        assert ev.reason
        assert ev.granularity is Granularity.TOOL


def test_url_param_makes_source_with_weak_sink_signal() -> None:
    tool = classify_tool(
        "get_page", "web", "Fetches a web page", {"type": "object", "properties": {"url": {}}}
    )
    assert S in assigned_roles(tool)


def test_description_alone_needs_two_signals() -> None:
    one = classify_tool("do_it", "srv", "Sends things")
    assert assigned_roles(one) == set()
    two = classify_tool("do_it", "srv", "Send an email via webhook")
    assert K in assigned_roles(two)


def test_noisy_or_and_threshold() -> None:
    tool = classify_tool("send_email", "srv", "Send an email", {"properties": {"to": {}}})
    score = role_score(tool.roles, K)
    assert score > 0.75
    assert score >= ROLE_THRESHOLD


def _spec(name: str, args: tuple[RedactedText, ...] = ()) -> ServerSpec:
    return ServerSpec(
        name=name,
        transport=TransportKind.STDIO,
        command=RedactedText.plain("npx"),
        args=args,
        source_file=Path("C:/x.json"),
        scope=ConfigScope.USER,
    )


def test_server_level_github() -> None:
    tool = classify_server(
        "gh", _spec("gh", (RedactedText.plain("@modelcontextprotocol/server-github"),))
    )
    assert tool.name == "*"
    assert assigned_roles(tool) == {S, P, K}
    assert all(e.granularity is Granularity.SERVER for e in tool.roles)
    assert all(e.weight <= SERVER_WEIGHT for e in tool.roles)


def test_server_level_unknown_has_no_roles() -> None:
    assert classify_server("time", _spec("time")).roles == ()


def test_server_level_ignores_redacted_segments() -> None:
    secret_arg = RedactedText(parts=("--token=", RedactedValue.from_secret("slack")))
    tool = classify_server("x", _spec("x", (secret_arg,)))
    assert tool.roles == ()
