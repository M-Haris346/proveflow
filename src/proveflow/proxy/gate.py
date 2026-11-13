"""``UpstreamGate``: the check on the upstream WRITE path (ADR-006, D5).

Independent of the handler's decision: even if the handler wrongly decided to forward,
the gate raises ``GateBlocked`` before a single byte reaches the twin when
  * the method is not in ``UPSTREAM_ALLOWED`` (resources/*, prompts/*, sampling/*, ...), or
  * the method is ``tools/call`` for a name that is not ``forward=True`` in the policy or
    not in the upstream's own ``tools/list`` (before that list is known: every name), or
  * the message is a successful response carrying a non-empty result (the proxy never
    answers an upstream request with data: sampling/roots/elicitation are refused with
    errors, and ``ping`` is answered with ``{}``).
JSON-RPC error responses are always allowed (they are how upstream requests are refused).
"""

from __future__ import annotations

from collections.abc import Mapping

from proveflow.proxy.policy import ToolPolicy

UPSTREAM_ALLOWED: frozenset[str] = frozenset(
    {
        "initialize",
        "notifications/initialized",
        "tools/list",
        "tools/call",
        "ping",
        "notifications/cancelled",
    }
)


class GateBlocked(RuntimeError):
    def __init__(self, method: str, reason: str) -> None:
        super().__init__(f"upstream gate blocked {method!r}: {reason}")
        self.method = method
        self.reason = reason


class UpstreamGate:
    """``tools/call`` passes only for names that are ``forward=True`` in the policy AND in
    the upstream's own ``tools/list`` (the full D3 forward condition, enforced here
    independently of the handler). Until ``set_advertised`` is called, no ``tools/call``
    passes at all."""

    def __init__(self, policy: Mapping[str, ToolPolicy]) -> None:
        self._policy_forward = frozenset(name for name, p in policy.items() if p.forward)
        self._forward: frozenset[str] = frozenset()
        self._advertised_set = False

    def set_advertised(self, names: frozenset[str]) -> None:
        """Called once, after the upstream's tools/list; can only narrow the forward set."""
        if self._advertised_set:
            raise RuntimeError("advertised tools already set")
        self._advertised_set = True
        self._forward = self._policy_forward & names

    def check(self, message: object) -> None:
        method = getattr(message, "method", None)
        if method is None:
            if getattr(message, "error", None) is not None:
                return  # JSON-RPC error response: how upstream requests are refused
            result = getattr(message, "result", None)
            if result:
                raise GateBlocked("<response>", "non-empty result to an upstream request")
            return
        if not isinstance(method, str) or method not in UPSTREAM_ALLOWED:
            raise GateBlocked(str(method), "method not in upstream allowlist")
        if method == "tools/call":
            params = getattr(message, "params", None)
            name = params.get("name") if isinstance(params, dict) else None
            if not isinstance(name, str) or name not in self._forward:
                raise GateBlocked(
                    method, "tool is not forward=True in the policy and advertised upstream"
                )
