# Backlog: known residuals not fixed yet

Each item has a source, a severity from the review that found it, and a proposed test. An item
moves out of this file only with a fix and that test in the repo.

## Proxy (Phase 2 review, 2026-11-14; ADR-006)

### L3: the gate allows any error response and any cancel params (low)
- **Where:** `src/proveflow/proxy/gate.py` (`UpstreamGate.check`). JSON-RPC error responses
  always pass, and `notifications/cancelled` passes with any params.
- **Today:** only the proxy's transport and the MCP SDK create these, with fixed text (for
  example "caller cancelled"). Probe: a forged agent cancel reason never reached the twin.
- **Risk:** a future code path that copied agent text into an error `data` or a cancel `reason`
  would pass the gate.
- **Proposed fix:** allow error responses only for request ids the transport answered itself,
  and cancels only for in-flight upstream request ids; drop `data` and `reason`.
- **Proposed test:** the gate rejects an error response for an unknown id, and a cancel for an
  unknown `requestId`.

### L4: cancellation during spawn (low)
- **Where:** Phase 1 `src/proveflow/introspect/procs.py` `spawn`, reachable from the proxy.
- **Risk:** a SIGTERM or session deadline that lands during `await anyio.open_process` could
  leave the child running before `Spawned` exists. On Windows that is a suspended process never
  assigned to the Job; on POSIX a process group nobody kills.
- **Proposed test:** inject a cancellation right after `open_process` returns, then assert no
  child is alive (psutil).

### Classifier miss before `--real-reads` (must fix before that mode exists)
- A sink that both the session's evidence and the proxy's own v2 classifier miss is forwarded
  to the twin. That is harmless in twin mode. Held-out sink recall is 16/25
  (docs/eval/RESULTS_V2.md).
- A real-reads mode needs a stronger guarantee than a classifier, e.g. an explicit per-tool
  user allowlist of read tools.
