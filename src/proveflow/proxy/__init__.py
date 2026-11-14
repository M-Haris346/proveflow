"""Twin-mode stdio MCP proxy (Phase 2; docs/ARCHITECTURE.md §5.5, ADR-006).

Serves ONE twin upstream (a Python script run by this interpreter) to an agent. Two
independent layers keep sink calls from leaving the proxy:

A. ``TwinUpstream`` accepts only ``[sys.executable, <script>]`` where the script resolves
   under proveflow's own twin directory (``policy.TWIN_ROOT``) and matches the session's
   ``twin_sha256`` (the hashed private copy is what runs). npx, uvx, node, docker, URLs and
   any other .py file are refused. This does not prove a script placed in TWIN_ROOT is
   harmless.
B. Default-deny tool policy computed by the proxy from the session's classified tools, plus
   the proxy's own classifier on what the twin advertises (second opinion) and look-alike
   name denial; every other ``tools/call`` gets a sandbox response. ``UpstreamGate``
   re-checks every outgoing message on the upstream write path.

There is no flag, environment variable or session field that disables the sandbox.
Residual: a sink that both the session's labels and the proxy's classifier miss is
forwarded to the twin (ADR-006, docs/BACKLOG.md).

This package must not import ``proveflow.discover``, ``proveflow.introspect.launchspec``,
``proveflow.introspect.transport``, ``proveflow.introspect.runner`` or
``proveflow.core.client`` (tests/safety/test_proxy_safety.py checks the AST, a fresh
interpreter's ``sys.modules`` after import, and after a full session).
"""
