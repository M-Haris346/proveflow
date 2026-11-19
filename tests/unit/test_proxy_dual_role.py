"""Unit: the dual-role set (N2), decide/gate with it, session honey (schema 3)."""

from __future__ import annotations

import json
from pathlib import Path

import mcp_types
import pytest
from pydantic import ValidationError

from proveflow.core.honey import HoneyKind, HoneyValue
from proveflow.core.tools import Granularity, ToolSpec
from proveflow.proxy import session as session_module
from proveflow.proxy.gate import GateBlocked, UpstreamGate
from proveflow.proxy.policy import (
    Decision,
    SandboxReason,
    build_policy,
    decide,
    dual_role_names,
    session_dual_role_names,
)
from proveflow.proxy.server import forwardable_dual_roles, proxy_roles
from proveflow.proxy.session import MAX_HONEY, ProxySession
from proveflow.twin import generator
from proxyhelpers import (  # noqa: F401
    PRIVATE,
    SINK,
    SOURCE,
    evidence,
    make_session,
    proxy_twin_root,
)
from twinchecks import sample_honey

DUAL = ("untrusted_source", "sink")
LOOK = "fet" + chr(0x200B) + "ch"  # look-alike of fetch (zero-width space)


def spec(name: str, *roles: object, granularity: Granularity = Granularity.TOOL) -> ToolSpec:
    return ToolSpec(
        name=name,
        server="twin",
        roles=tuple(evidence(r, granularity) for r in roles),  # type: ignore[arg-type]
    )


def test_session_dual_role_needs_source_and_sink_at_tool_granularity() -> None:
    tools = [
        spec("both", SOURCE, SINK),
        spec("sink", SINK),
        spec("source", SOURCE),
        spec("server_level", SOURCE, SINK, granularity=Granularity.SERVER),
        spec("*", SOURCE, SINK),
        spec("three", SOURCE, SINK, PRIVATE),
    ]
    assert session_dual_role_names(tools) == {"both", "three"}


@pytest.mark.parametrize(
    ("session_roles", "proxy", "expected"),
    [
        ((SOURCE, SINK), DUAL, True),
        ((SINK,), DUAL, False),  # session says pure sink
        ((SOURCE, SINK), ("sink",), False),  # proxy says pure sink
        ((SOURCE, SINK), ("untrusted_source",), False),  # proxy says no sink
        ((SOURCE,), DUAL, False),
        ((SINK,), ("sink",), False),  # pure sink on both sides
    ],
)
def test_dual_role_is_the_and_of_session_and_proxy(
    session_roles: tuple[object, ...], proxy: tuple[str, ...], expected: bool
) -> None:
    got = dual_role_names([spec("t", *session_roles)], {"t": proxy}, frozenset({"t"}))
    assert (got == {"t"}) is expected


def test_dual_role_requires_advertised_and_no_collision() -> None:
    tools = [spec("fetch", SOURCE, SINK), spec("get", SOURCE, SINK)]
    roles = {"fetch": DUAL, "get": DUAL}
    assert dual_role_names(tools, roles, frozenset({"get"})) == {"get"}
    lookalike = LOOK
    with_look = {**roles, lookalike: ("untrusted_source",)}
    assert dual_role_names(tools, with_look, frozenset(with_look)) == {"get"}
    session_look = [*tools, spec(lookalike, PRIVATE)]
    assert dual_role_names(session_look, roles, frozenset(roles)) == {"get"}


def test_dual_role_does_not_touch_tool_policy() -> None:
    """N2: decided outside ToolPolicy; build_policy still denies every sink."""
    policy = build_policy([spec("fetch", SOURCE, SINK)])
    assert policy["fetch"].forward is False
    assert policy["fetch"].inject is True


def test_decide_forwards_dual_role_only_when_listed_advertised_and_unique() -> None:
    policy = build_policy([spec("fetch", SOURCE, SINK), spec("send", SINK)])
    adv = frozenset({"fetch", "send"})
    sinks = frozenset({"fetch", "send"})
    assert decide(policy, adv, "fetch", proxy_sinks=sinks) == (
        Decision.SANDBOX,
        SandboxReason.POLICY_DENY,
    )
    dual = frozenset({"fetch"})
    assert decide(policy, adv, "fetch", proxy_sinks=sinks, dual_role=dual) == (
        Decision.FORWARD,
        None,
    )
    assert decide(policy, adv, "send", proxy_sinks=sinks, dual_role=dual)[0] is Decision.SANDBOX
    assert decide(policy, frozenset({"send"}), "fetch", dual_role=dual) == (
        Decision.SANDBOX,
        SandboxReason.NOT_ADVERTISED,
    )
    look = adv | {LOOK}
    assert decide(policy, look, "fetch", dual_role=dual) == (
        Decision.SANDBOX,
        SandboxReason.NAME_COLLISION,
    )
    assert decide(policy, adv, "unknown", dual_role=frozenset({"unknown"})) == (
        Decision.SANDBOX,
        SandboxReason.UNKNOWN_TOOL,
    )


def _call(name: str) -> mcp_types.JSONRPCRequest:
    return mcp_types.JSONRPCRequest(jsonrpc="2.0", id=1, method="tools/call", params={"name": name})


def test_gate_adds_only_advertised_non_colliding_dual_roles() -> None:
    policy = build_policy([spec("fetch", SOURCE, SINK), spec("send", SINK), spec("r", SOURCE)])
    off = UpstreamGate(policy)
    off.set_advertised(frozenset({"fetch", "send", "r"}), proxy_sinks=frozenset({"fetch"}))
    with pytest.raises(GateBlocked):
        off.check(_call("fetch"))
    on = UpstreamGate(policy)
    on.set_advertised(
        frozenset({"fetch", "send", "r"}),
        proxy_sinks=frozenset({"fetch", "send"}),
        dual_role=frozenset({"fetch", "ghost"}),
    )
    on.check(_call("fetch"))
    on.check(_call("r"))
    for name in ("send", "ghost"):
        with pytest.raises(GateBlocked):
            on.check(_call(name))
    look = UpstreamGate(policy)
    look.set_advertised(
        frozenset({"fetch", LOOK}), proxy_sinks=frozenset(), dual_role=frozenset({"fetch"})
    )
    with pytest.raises(GateBlocked):
        look.check(_call("fetch"))


def test_forwardable_dual_roles_is_empty_without_the_guard() -> None:
    tool = mcp_types.Tool(
        name="fetch_url",
        description="Fetches a URL from the internet and returns its contents.",
        input_schema={"type": "object", "properties": {"url": {"type": "string"}}},
    )
    assert set(proxy_roles(tool)) == set(DUAL)
    tools = [spec("fetch_url", SOURCE, SINK)]
    assert forwardable_dual_roles(tools, [tool], guard_passed=False) == frozenset()
    assert forwardable_dual_roles(tools, [tool], guard_passed=True) == {"fetch_url"}


# --- session honey (schema 3) ---------------------------------------------------------


def _with_honey(tmp_path: Path, honey: list[object]) -> dict[str, object]:
    data = json.loads(make_session(tmp_path).model_dump_json())
    data["honey"] = honey
    return data


def test_session_carries_honey_and_round_trips(tmp_path: Path) -> None:
    honey = sample_honey()
    session = make_session(tmp_path, honey=honey)  # type: ignore[arg-type]
    again = ProxySession.model_validate_json(session.model_dump_json())
    assert again.honey == honey
    assert make_session(tmp_path).honey == ()


def test_session_refuses_duplicate_honey(tmp_path: Path) -> None:
    h = sample_honey()[0].model_dump(mode="json")  # type: ignore[attr-defined]
    with pytest.raises(ValidationError, match="duplicate honey id"):
        ProxySession.model_validate(_with_honey(tmp_path, [h, h]))
    other = {**h, "value": sample_honey()[1].value}  # type: ignore[attr-defined]
    with pytest.raises(ValidationError, match="duplicate honey value"):
        ProxySession.model_validate(_with_honey(tmp_path, [h, {**h, "id": "h99"}]))
    ProxySession.model_validate(_with_honey(tmp_path, [h, {**other, "id": "h99"}]))


def test_session_refuses_more_than_max_honey(tmp_path: Path) -> None:
    many = [
        HoneyValue(id=f"h{i:02d}", kind=HoneyKind.TOKEN, value=f"pfhoney_token_{i:04x}abcdabcdabcd")
        for i in range(MAX_HONEY + 1)
    ]
    ok = [h.model_dump(mode="json") for h in many[:MAX_HONEY]]
    ProxySession.model_validate(_with_honey(tmp_path, ok))  # type: ignore[arg-type]
    too_many = [h.model_dump(mode="json") for h in many]
    with pytest.raises(ValidationError, match=f"at most {MAX_HONEY}"):
        ProxySession.model_validate(_with_honey(tmp_path, too_many))  # type: ignore[arg-type]


def test_session_refuses_a_t4_breaking_honey_value(tmp_path: Path) -> None:
    bad = {"id": "h01", "kind": "token", "value": "pfhoney_token_123456789012abcd"}
    with pytest.raises(ValidationError, match="T4"):
        ProxySession.model_validate(_with_honey(tmp_path, [bad]))


def test_session_honey_cap_equals_the_generator_cap() -> None:
    assert session_module.MAX_HONEY == generator.MAX_HONEY == 32
