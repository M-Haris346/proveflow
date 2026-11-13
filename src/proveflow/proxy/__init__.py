"""Twin-mode stdio MCP proxy (Phase 2; docs/ARCHITECTURE.md §5.5, ADR-006).

Serves ONE twin upstream (a Python script run by this interpreter) to an agent. Two
independent layers keep sink calls from leaving the proxy:

A. ``TwinUpstream`` accepts only ``[sys.executable, <existing .py file>]``: a real server
   (npx, uvx, node, docker, a URL, ...) cannot even be described.
B. Default-deny tool policy: only tools classified with tool-granularity evidence, at least
   one role and no ``sink`` role are forwarded; every other ``tools/call`` gets a sandbox
   response. ``UpstreamGate`` re-checks every outgoing message on the upstream write path.

There is no flag, environment variable or config that disables the sandbox.

This package must not import ``proveflow.discover``, ``proveflow.introspect.launchspec``,
``proveflow.introspect.transport``, ``proveflow.introspect.runner`` or
``proveflow.core.client`` (tests/safety/test_proxy_safety.py checks both the AST and a fresh
interpreter's ``sys.modules``). The MCP SDK is imported lazily by ``server``/``upstream``.
"""
