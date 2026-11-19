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

### Incomplete cassettes must not produce verdicts (Phase 5, replay)
- **Where:** `src/proveflow/proxy/cassette.py`. `load_cassette` checks integrity (models, seq,
  hash chain, canonical form, sizes), not completeness. A cassette cut off by SIGKILL, or read
  while the proxy is still running, loads without error. `is_complete(events)` (added in Phase
  2.1) returns False for it, but nothing enforces that yet.
- **Oracle part: done in Phase 3a.** `oracle.rules.evaluate` raises `IncompleteCassetteError`
  (no findings) when `is_complete` is False, when events were dropped, or when `session_start`
  or a sink call was truncated (`tests/unit/test_oracle_rules.py`).
- **Still open (Phase 5):** the replay CLI must surface that error as INCOMPLETE and never
  report a verdict.
- **Proposed test:** replay of a cassette with its `session_end` removed reports INCOMPLETE and
  produces no verdict.

### Deeply nested JSON in a cassette line raises an untyped error (low)
- **Where:** `src/proveflow/proxy/cassette.py` `load_cassette` (and `canonical` on write).
  `json.loads` of a line nested about 100k levels deep raises `RecursionError`, which is not
  caught as `CassetteError`. Probed in Phase 3a: `RecursionError (untyped)`.
- **Today:** fails closed (no events, so no findings). But callers that expect
  `CassetteError` get an untyped exception. The oracle's own JSON walk is iterative and
  unaffected.
- **Proposed fix:** catch `RecursionError` in `load_cassette` (and in the writer) and raise
  `CassetteError("nesting too deep")`. This is a proxy change, outside Phase 3a's single
  allowed proxy change.
- **Proposed test:** a cassette line with 100k nested lists → `CassetteError`.

## Twin (Phase 4, 2026-11-15)

### Argument-dependent responses (F3; medium for utility realism, none for safety)
- **Where:** `src/proveflow/twin/generator.py`. `TABLE[tool]["content"]` does not depend on
  the arguments: one canned response per tool. Arguments are validated (type, required,
  properties, enum) and then ignored.
- **Effect:** an agent reading two different paths gets identical content, so utility
  realism is limited to calling tools correctly, not to distinguishing their targets. The
  Phase 5 runner will meet this first.
- **Proposed fix:** derive the content from `Rng(seed).derive("content", tool, canonical
  args)` inside the embedded runtime (still literal data, still deterministic), keeping honey
  and marker placement.
- **Proposed test:** two calls with different `path` values return different content, the
  same call twice returns the same bytes, and every honey value still appears in some response.

### Readability of wrapped terminal output is untested (F7; low)
- **Where:** `tests/widths.py` pins every test to `TEST_COLUMNS = 1_000_000`, so exact-text
  assertions are width-independent. One check opts out on purpose,
  `tests/narrowchecks.py` (COLUMNS=40, allowlisted in `tests/unit/test_render_width.py`):
  it verifies only that redaction survives hard wrapping of the consent prompt.
- **Gap:** no test verifies that wrapped output (the consent prompt, a security warning, in
  an 80-column terminal) is READABLE, e.g. that the command line and the WARNING line stay
  recognisable. Only the absence of a planted secret is checked.
- **Rule for the future:** a narrow-width rendering test goes into the `COLUMNS_USERS`
  allowlist in `tests/unit/test_render_width.py` with a one-line reason.
- **Proposed test:** at COLUMNS=80, the WARNING sentence and every line label (`command:`,
  `env keys:`, `config:`) start a line of the rendered prompt.

### Dual-role agreement gap (F6; medium for realism, must close before `--real-reads`)
- **Measured:** v2 12/155, human labels 10/155, both 7, Jaccard 7/15 = 0.47
  (`tools/count_dual_role.py`, pinned by `tests/unit/test_dual_role_count.py`). v2 only:
  browser_navigate, get_blog_post, get_blog_posts, get_linkedin_post, save_conversation.
  Human only: browser_network_requests, fill, image_pull.
- **Effect:** not a safety hole in twin mode (the twin has no I/O). Prove attacks up to 5
  flows a human would not call dual-role and cannot attack 3 that a human would.
- **Proposed fix:** dual-role rules tuned on dev only, a second independent human labeler for
  the dual-role subset (kappa), then a re-measure on a fresh held-out set.
- **Proposed test:** the count tool reports agreement on the new held-out set; the test pins
  it.

### The ADR-007 dual-role exception must be removed before `--real-reads`
- **Where:** `proxy.server.forwardable_dual_roles`, `proxy.policy.dual_role_names`.
- In any mode where a forward can reach a real server, a dual-role tool is a real sink.
- **Proposed test:** in a real-reads session, `forwardable_dual_roles` is empty whatever the
  guard says, and a dual-role call is sandboxed.

### Classifier miss before `--real-reads` (must fix before that mode exists)
- A sink that both the session's evidence and the proxy's own v2 classifier miss is forwarded
  to the twin. That is harmless in twin mode. Held-out sink recall is 16/25
  (docs/eval/RESULTS_V2.md).
- A real-reads mode needs a stronger guarantee than a classifier, e.g. an explicit per-tool
  user allowlist of read tools.
