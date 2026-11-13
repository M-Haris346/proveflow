"""UpstreamGate per method (D4/D5): the write-path check, independent of the handler."""

from __future__ import annotations

import mcp_types
import pytest

from proveflow.proxy.gate import UPSTREAM_ALLOWED, GateBlocked, UpstreamGate
from proxyhelpers import FORWARDED, TWIN_ROLES, TWIN_TOOLS, twin_policy

GATE = UpstreamGate(twin_policy())
GATE.set_advertised(TWIN_TOOLS)
GATE_FORWARD = FORWARDED & TWIN_TOOLS  # policy-forward AND advertised upstream


def request(method: str, params: dict[str, object] | None = None) -> mcp_types.JSONRPCRequest:
    return mcp_types.JSONRPCRequest(jsonrpc="2.0", id=1, method=method, params=params)


def test_allowlist_is_exactly_d4() -> None:
    assert UPSTREAM_ALLOWED == {
        "initialize",
        "notifications/initialized",
        "tools/list",
        "tools/call",
        "ping",
        "notifications/cancelled",
    }


@pytest.mark.parametrize(
    "method", ["initialize", "tools/list", "ping", "notifications/initialized"]
)
def test_allowed_methods_pass(method: str) -> None:
    GATE.check(request(method))


@pytest.mark.parametrize(
    "method",
    [
        "resources/list",
        "resources/read",
        "resources/templates/list",
        "resources/subscribe",
        "prompts/list",
        "prompts/get",
        "completion/complete",
        "logging/setLevel",
        "sampling/createMessage",
        "roots/list",
        "elicitation/create",
        "server/discover",
        "subscriptions/listen",
        "tasks/get",
        "",
    ],
)
def test_everything_else_is_blocked(method: str) -> None:
    with pytest.raises(GateBlocked, match="allowlist"):
        GATE.check(request(method))


def test_cancelled_notification_passes() -> None:
    GATE.check(
        mcp_types.JSONRPCNotification(
            jsonrpc="2.0", method="notifications/cancelled", params={"requestId": 1}
        )
    )


@pytest.mark.parametrize("name", sorted(GATE_FORWARD))
def test_tools_call_for_forward_tool_passes(name: str) -> None:
    GATE.check(request("tools/call", {"name": name, "arguments": {}}))


@pytest.mark.parametrize(
    "name", [*sorted(set(TWIN_ROLES) - GATE_FORWARD), "unknown", "*", "", "SEND_EMAIL"]
)
def test_tools_call_for_any_other_name_is_blocked(name: str) -> None:
    with pytest.raises(GateBlocked, match="forward=True"):
        GATE.check(request("tools/call", {"name": name}))


def test_policy_forward_but_not_advertised_is_blocked() -> None:
    assert "ghost" in FORWARDED and "ghost" not in TWIN_TOOLS
    with pytest.raises(GateBlocked):
        GATE.check(request("tools/call", {"name": "ghost"}))


def test_no_tools_call_before_upstream_list_is_known() -> None:
    gate = UpstreamGate(twin_policy())
    for name in sorted(FORWARDED):
        with pytest.raises(GateBlocked):
            gate.check(request("tools/call", {"name": name}))
    gate.check(request("tools/list"))  # the list itself may go out


def test_advertised_set_only_once() -> None:
    gate = UpstreamGate(twin_policy())
    gate.set_advertised(frozenset({"query_db"}))
    with pytest.raises(RuntimeError):
        gate.set_advertised(TWIN_TOOLS)
    with pytest.raises(GateBlocked):
        gate.check(request("tools/call", {"name": "read_page"}))
    gate.check(request("tools/call", {"name": "query_db"}))


@pytest.mark.parametrize("params", [None, {}, {"name": None}, {"name": ["read_page"]}])
def test_tools_call_without_a_string_name_is_blocked(params: dict[str, object] | None) -> None:
    with pytest.raises(GateBlocked):
        GATE.check(request("tools/call", params))


def test_error_responses_pass_and_empty_results_pass() -> None:
    GATE.check(
        mcp_types.JSONRPCError(
            jsonrpc="2.0", id=1, error=mcp_types.ErrorData(code=-32601, message="no")
        )
    )
    GATE.check(mcp_types.JSONRPCResponse(jsonrpc="2.0", id=1, result={}))


def test_non_empty_result_to_upstream_is_blocked() -> None:
    """The proxy never answers an upstream request (e.g. sampling) with data."""
    with pytest.raises(GateBlocked, match="non-empty result"):
        GATE.check(mcp_types.JSONRPCResponse(jsonrpc="2.0", id=1, result={"content": "relayed"}))


def test_empty_policy_blocks_every_tools_call() -> None:
    gate = UpstreamGate({})
    gate.set_advertised(TWIN_TOOLS)
    with pytest.raises(GateBlocked):
        gate.check(request("tools/call", {"name": "read_page"}))
