"""Applying a twin mitigation to one trial (Phase 8, paired verify).

The mitigation is applied on the RUNNER side (the agent's client), never in the proxy: no
proxy, policy, cassette or sandbox code changes, and the sink sandbox stays on. That is also
where the real mitigations act: M1 removes the server from the client's config, so the client
never offers its tools; M3 is the client's own approval prompt.

* M1 (``hide_server``): every tool the sink's server advertised is removed from the routing
  table. The model is never offered it; a call to one takes the unknown-tool path and is never
  sent. The server's proxy STILL STARTS, so its cassette exists and exposure is READ from it,
  never assumed.
* M3 (``deny_tool``): the sink tool stays offered; every call to it is answered "denied" and
  never sent. SIMULATED: every approval is denied. That says nothing about whether a human
  would deny it (the real-world effect depends on the human).

FAIL CLOSED: a mitigation whose target the twins do not advertise is refused, because it would
measure nothing (``MitigationTargetMissing``).
"""

from __future__ import annotations

from proveflow.core.mitigations import TwinMitigation, TwinPolicy
from proveflow.runner.routing import Gate, RoutingTable


class MitigationTargetMissing(ValueError):
    """The mitigation's server or tool is not advertised by any twin of the trial."""


def apply(routing: RoutingTable, mitigation: TwinMitigation) -> RoutingTable:
    """The routing table the agent gets: what it offers, and the gate (``routing.gate``) that
    keeps the mitigated calls from every proxy and counts them."""
    policy = mitigation.policy
    if policy is TwinPolicy.HIDE_SERVER:
        hidden = routing.tools_of(mitigation.server)
        if mitigation.tool not in hidden:
            raise MitigationTargetMissing(
                f"{mitigation.kind}: server {mitigation.server!r} does not advertise "
                f"{mitigation.tool!r}"
            )
        return routing.without_server(mitigation.server).with_gate(
            Gate(mitigation.kind, hidden=hidden)
        )
    route = routing.route(mitigation.tool)
    if route is None or route.server != mitigation.server:
        raise MitigationTargetMissing(
            f"{mitigation.kind}: {mitigation.server!r}/{mitigation.tool!r} is not advertised"
        )
    return routing.with_gate(Gate(mitigation.kind, denied=frozenset({mitigation.tool})))


def record_of(mitigation: TwinMitigation) -> dict[str, str]:
    """What ``trial_start.parameters["mitigation"]`` records (present ONLY when one is set)."""
    return {"kind": mitigation.kind.value, "server": mitigation.server,
            "tool": mitigation.tool, "twin_policy": mitigation.policy.value}  # fmt: skip
