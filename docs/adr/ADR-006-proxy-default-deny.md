# ADR-006: The proxy serves twins only and denies tool calls by default

- Status: accepted (2026-11-14), Phase 2
- Number: the Phase 2 spec called this "ADR-005", but ADR-005 already exists
  (never edit user configs), so it is ADR-006.
- Relates to: ADR-003 (twin mode is the default), THREAT_MODEL T3, T6, T1

## Decision

The proxy (`proveflow proxy --session FILE`, `src/proveflow/proxy/`) is an MCP stdio server
for an agent and an MCP stdio client for **one twin upstream**. Two independent layers keep a
sink call from leaving the proxy. A third, separate piece of evidence proves it.

### Layer A: only a twin can be launched (D2)
- The upstream is a `TwinUpstream(name, argv)`.
- It is valid only if `argv[0] == sys.executable` and `argv[1]` is an absolute path to an
  existing `.py` file.
- Everything else is refused at validation: `npx`, `uvx`, `node`, `docker`, URLs, bare
  `python`, `-c`, `-m`, relative paths. `upstream.twin_stdio` checks again right before spawn,
  so a model built without validation (`model_construct`) is also refused.
- `proveflow.proxy` does not import `proveflow.discover*`, `introspect.launchspec`,
  `introspect.transport`, `introspect.runner` or `core.client`. So a discovered `ServerSpec` or
  `LaunchSpec` cannot be handed to the proxy at all.
  - Two checks enforce this: an AST scan of the package, and a fresh `python -I` interpreter
    that imports every proxy submodule and inspects `sys.modules`.
  - Two pure moves made that possible: `core/redact_rules.py` (`discover/redact_rules.py` is now
    an alias of the same module object) and `introspect/limits.py` (`MAX_LINE`).
  - `core/__init__.py` now loads the `core.client` models lazily (PEP 562).
  - **Accepted:** the `proveflow` CLI process itself imports `discover` (top of `cli.py`). The
    guard is about the proxy package, not the process. A test documents this.
- The upstream is launched through the existing `introspect.procs.spawn`:
  - Windows: Job Object with `KILL_ON_JOB_CLOSE`, child created suspended, then assigned.
  - POSIX: its own process group.
  - `introspect.env.child_env` provides a minimal environment, and the cwd is an empty temp
    directory.

### Layer B: default-deny policy plus a write-path gate (D3, D5)
- `ToolPolicy(forward, inject)` comes from `build_policy(tools)`:
  - `forward` = has at least one role, AND no `sink` role, AND every role evidence is
    tool-granularity, AND the name is not `"*"`;
  - `inject` = the tool has the `untrusted_source` role.
- Every other `tools/call` gets the sandbox response and is never forwarded. That covers sink,
  source+sink, unclassified, server-level, `*`, unknown names, and names absent from the
  upstream's own `tools/list`.
- **There is no flag, environment variable or config that disables the sandbox.** There is one
  mode (twin mode). `ProxySession` forbids extra fields, so an attempted `"sandbox": false` is a
  validation error, not something silently ignored.
- `UpstreamGate` checks every message on the upstream write path, independently of the handler:
  - Only `initialize`, `notifications/initialized`, `tools/list`, `tools/call`, `ping` and
    `notifications/cancelled` may be sent.
  - `tools/call` passes only for a name that is `forward=True` in the policy **and** in the
    upstream's own `tools/list`. Until that list is known, no `tools/call` passes at all.
  - A successful response carrying a non-empty result is blocked: the proxy never answers an
    upstream request with data.
- The gate runs twice, both times before a byte is written. First in `GatedWriteStream.send`,
  which raises `GateBlocked` to the caller. Then again in the stdin writer task.
- The gate's advertised-list condition was added during implementation. The layer-independence
  mutation test (`tests/mutation/test_proxy_mutation.py::test_handler_broken_alone_is_still_caught_by_gate`)
  showed that with the handler broken, a policy-forward tool missing from the upstream list got
  past a gate that checked only the policy. The gate now enforces the full D3 forward condition.
- Fail closed:
  - An exception, a gate block, an upstream crash, an invalid upstream line, a line over
    `MAX_LINE` (16 MiB), or a per-call timeout each give the agent
    `CallToolResult(isError=true, "proveflow proxy: <reason>")`, and nothing is forwarded.
  - An agent line over `MAX_LINE` ends the session.
- Limits (`ProxyLimits`) can only be tightened: per call 30 s, session 600 s, at most 200 tool
  calls (sandboxed calls count). A session file cannot loosen them.
- Upstream-initiated requests are answered by the transport and never reach the agent:
  - `sampling/*`, `roots/*`, `elicitation/*` and anything else get JSON-RPC `-32601`;
  - `ping` gets `{}`.
- Upstream notifications are dropped and recorded (`upstream_notification_dropped`).

### Independent evidence (D10)
- The test twin (`tests/fixtures/fake_twin.py`, an SDK lowlevel server) appends **every line it
  receives** to its own log, flushed **before** parsing.
- Safety tests assert on that log, never on the proxy's own cassette.

## Consequences

- **Residual (must be closed before any `--real-reads` mode):** a real sink that the classifier
  mislabels as source/private only (no `sink` role) is forwarded **to the twin**.
  - In twin mode this is harmless, because the twin is our own script with synthetic data.
  - With real reads it would be a real sink call. Phase 1c measured held-out sink recall at
    16/25 (docs/eval/RESULTS_V2.md), so mislabels are expected.
- **POSIX kill residual:**
  - Windows: `TerminateProcess` on the proxy closes the Job handle, and the OS kills the twin
    tree.
  - POSIX: a SIGTERM handler kills the twin's process group first.
  - **SIGKILL runs no handler.** The twin then exits only because its stdin reaches EOF. A twin
    (or a twin's child) that ignores stdin EOF, or a descendant that called `setsid()`, would
    survive. No `PR_SET_PDEATHSIG` (Linux-only, not used).
  - Tested: Windows locally; POSIX SIGTERM and SIGKILL tests run only on the ubuntu CI job.
- `outputSchema` is stripped from every advertised tool, recorded per tool as
  `output_schema_stripped`. Forwarded results lose `structuredContent`, while the raw upstream
  result keeps it in the cassette. Revisit in Phase 4, when twins generate structured output.
- Determinism: the cassette has no wall-clock timestamps, so the same session and the same
  scripted agent calls give a byte-identical cassette (tested through the real CLI).

## Tests

- `tests/safety/test_proxy_safety.py`:
  - the twin log shows zero denied `tools/call`, and the forwarded list is exact;
  - gate on the write path;
  - non-python upstream refused before spawn (CLI and transport);
  - killing the proxy kills the twin (Windows; POSIX SIGTERM/SIGKILL in CI);
  - AST and fresh-interpreter import guards.
- `tests/mutation/test_proxy_mutation.py`:
  - (a) handler forwards everything → `assert_sink_call_sandboxed` fails;
  - (b) gate off → `assert_gate_blocks_on_write_path` fails;
  - (c) both off → `assert_twin_never_sees_denied_calls` fails;
  - with either layer alone broken, the same safety check still passes;
  - (d) JSON_STRING fallback broken → the canary property fails;
  - each carrier dropping its payload → the canary property fails.
- `tests/unit/test_proxy_*.py`, `tests/property/test_proxy_properties.py`,
  `tests/integration/test_proxy_integration.py` (real CLI subprocess),
  `tests/integration/test_proxy_inprocess.py` (limits, fail-closed paths).
