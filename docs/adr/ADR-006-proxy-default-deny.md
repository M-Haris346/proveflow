# ADR-006: The proxy serves twins only and denies tool calls by default

- Status: accepted (2026-11-14), Phase 2; amended 2026-11-14, Phase 2.1 (review fixes H1, H2,
  M1, M2, L1, L2, L5; residuals L3, L4)
- Number: the Phase 2 spec called this "ADR-005", but ADR-005 already exists
  (never edit user configs), so it is ADR-006.
- Relates to: ADR-003 (twin mode is the default), THREAT_MODEL T3, T6, T1; docs/BACKLOG.md

## Decision

The proxy (`proveflow proxy --session FILE`, `src/proveflow/proxy/`) is an MCP stdio server
for an agent and an MCP stdio client for **one twin upstream**. Two independent layers keep a
sink call from leaving the proxy. A third, separate piece of evidence proves it.

### Layer A: a proveflow-owned twin directory plus a hash pin (D2, Phase 2.1 H2)
- The upstream is a `TwinUpstream(name, argv)`. It is valid only if:
  - `argv[0] == sys.executable`;
  - `argv[1]` is an absolute path to a `.py` file that exists;
  - that path **resolves (realpath, symlinks and junctions followed) under `TWIN_ROOT`**.
- `TWIN_ROOT` is the per-user proveflow data dir + `twins`:
  - Windows: `%LOCALAPPDATA%\proveflow\twins`;
  - POSIX: `$XDG_DATA_HOME/proveflow/twins`, else `~/.local/share/proveflow/twins`.
  - Conventions are cited in docs/PROCESS_KILL.md §3 and `proxy/policy.py`.
  - It is computed once at import. No proveflow flag or env var overrides it; tests
    monkeypatch the module constant.
- **Hash pin.** The session pins `twin_sha256`. Right before spawn, `upstream.twin_stdio`:
  1. re-runs the argv check;
  2. copies the script into the private, empty temp cwd;
  3. hashes the **copy** and refuses on any mismatch;
  4. runs the copy.

  A change to the original file after the check cannot change what runs.
- Refused before anything is spawned:
  - `npx`, `uvx`, `node`, `docker`, URLs, bare `python`, `-c`, `-m`, relative paths;
  - an installed package module (e.g. the MCP SDK's own `server/__main__.py`);
  - any `.py` outside `TWIN_ROOT`;
  - a symlink or junction escaping `TWIN_ROOT`;
  - a hash mismatch;
  - a `model_construct`-forged `TwinUpstream`.
- **What layer A does not prove:** that a script someone placed inside `TWIN_ROOT` is a harmless
  twin. It is "only scripts in proveflow's own twin directory, pinned by hash". It is not "real
  servers are impossible by construction".
- `proveflow.proxy` does not import `proveflow.discover*`, `introspect.launchspec`,
  `introspect.transport`, `introspect.runner` or `core.client`.
  - Enforced by an AST scan, by a fresh `python -I` interpreter that imports every proxy
    submodule (including `flows.roles`, the second opinion), and by a fresh `python -I`
    interpreter that runs a **full in-process session** (L5).
  - Pure moves that made this possible: `core/redact_rules.py` (`discover/redact_rules.py` is an
    alias of the same module object) and `introspect/limits.py`. `core/__init__.py` loads the
    `core.client` models lazily (PEP 562).
  - **Accepted:** the `proveflow` CLI process itself imports `discover` (top of `cli.py`). A
    test documents this.
- Launched through `introspect.procs.spawn`:
  - Windows: Job Object with `KILL_ON_JOB_CLOSE`, created suspended, then assigned.
  - POSIX: own process group.
  - Minimal environment via `child_env`.

### Layer B: default-deny policy, second opinion, write-path gate (D3, D5, Phase 2.1 H1/L1)
- **The session carries classified tools, never decisions.**
  - `ProxySession` (schema 2) has `tools: tuple[ToolSpec, ...]` (roles plus evidence).
  - The proxy computes `build_policy(tools)` itself.
  - A `policy` key is rejected (`extra=forbid`). Schema 1's `policy` field let a session file
    set `forward: true` on a sink; the review demonstrated this, and schema 1 is gone.
- `build_policy`:
  - `forward` = has at least one role, AND no `sink` role, AND all evidence is
    tool-granularity, AND the name is not `"*"`, AND the name does not collide with another
    policy name (L1);
  - `inject` = the tool has the `untrusted_source` role.
- **Second opinion the session cannot forge.**
  - After the twin's `tools/list`, the proxy runs the v2 classifier
    (`flows.roles.classify_tool`) on each **advertised** name + description + inputSchema.
  - A tool it marks `sink` is never forwarded, whatever the session's evidence says.
  - The result is recorded per tool as `proxy_roles` in `tools_advertised`.
- **L1 look-alike names.**
  - Key = NFKC, then casefold, then removal of every Default_Ignorable_Code_Point (table copied
    from Unicode `DerivedCoreProperties-15.0.0.txt`, 4174 code points, cited in
    `proxy/names.py`).
  - Every member of a colliding group is denied, both within the session's tools
    (`build_policy`) and within the twin's advertised names (`decide` and the gate).
  - Example: `send_email` and `send_<U+200B>email` collide. Separators are not folded:
    `send<U+200B>email` keys to `sendemail` and does not collide with `send_email`.
- Forward therefore requires all of the following; everything else gets the sandbox response:
  - session-policy forward;
  - listed by the twin;
  - no advertised collision;
  - not a sink by the proxy's classifier.
- **No flag, environment variable or session field disables the sandbox.**
- `UpstreamGate` is on the upstream write path, independent of the handler. It receives the same
  inputs (policy, advertised names, proxy sinks) and computes collisions itself.
  - Only `initialize`, `notifications/initialized`, `tools/list`, `tools/call`, `ping`,
    `notifications/cancelled` may be sent.
  - `tools/call` passes only for the forward set above. Until the twin's list is known, none
    pass.
  - A successful response with a non-empty result is blocked.
  - The gate runs twice before a byte is written: in `GatedWriteStream.send` and again in the
    stdin writer.
- Fail closed:
  - An exception, a gate block, an upstream crash, an invalid line, a line over `MAX_LINE`
    (16 MiB, counted in **bytes**, L2), or a per-call timeout gives the agent `isError=true`
    "proveflow proxy: <reason>", and nothing is forwarded.
  - An agent line over `MAX_LINE` ends the session.
- Limits (`ProxyLimits`, tighten-only):
  - per call 30 s, session 600 s, 200 tool calls;
  - and since Phase 2.1 (M1): 1000 agent messages (all methods), 2000 upstream messages, and a
    32 MiB cassette (below the loader's 64 MiB cap).
  - Hitting one of the last three ends the session fail-closed, with one `error` event and a
    `session_end` carrying that reason and `dropped_events`. The cassette stays loadable.
- Upstream-initiated requests are answered by the transport (`-32601`; `ping` → `{}`) and never
  reach the agent. Upstream notifications are dropped and recorded.

### Independent evidence (D10, Phase 2.1 M2)
- The test twin (`tests/fixtures/fake_twin.py`) appends every line it receives to its own log
  as **raw bytes**, read from `sys.stdin.buffer` and flushed **before** decoding or parsing.
- A safety test pipes four lines straight into the twin and asserts they appear byte-exact and
  in order: non-JSON, a JSON-RPC batch, `\xff\xfe`, and a valid `initialize`.
- Safety tests assert on that log, never on the proxy's own cassette.

## Consequences and residuals

- **Classifier miss (must be closed before any `--real-reads` mode):** a sink that **both** the
  session's evidence and the proxy's own classifier miss is forwarded **to the twin**.
  - That happens when the twin describes the tool innocently.
  - Phase 1c measured held-out sink recall at 16/25 (docs/eval/RESULTS_V2.md). The second
    opinion catches a forged or wrong session label, not a sink the classifier itself misses.
  - Harmless in twin mode (synthetic twin); a real sink call with real reads.
- **Second-opinion cost:** the classifier marks fetch-a-URL tools as sinks (a GET can carry
  data). Such sources (source+sink) are never forwarded, so injection into them cannot be tested
  in twin mode. This is consistent with D3's source+sink deny.
- **L3 (not fixed, docs/BACKLOG.md):** the gate allows any JSON-RPC error response and any
  `notifications/cancelled` params.
  - Today only the proxy or the SDK generates them, with fixed text.
  - A future path that copied agent text into an error's `data` or a cancel `reason` would pass
    the gate.
- **L4 (not fixed, docs/BACKLOG.md):** a SIGTERM or session deadline that lands during
  `await anyio.open_process` (Phase 1 `introspect.procs.spawn`) could leave a child running
  before `Spawned` exists. On Windows that is a suspended, unassigned process. Low probability.
- **POSIX kill residual:**
  - Windows: `TerminateProcess` closes the Job handle, and the OS kills the twin tree.
  - POSIX: a SIGTERM handler kills the process group first.
  - **SIGKILL runs no handler.** The twin exits only on stdin EOF; a twin child that ignores EOF
    or calls `setsid()` would survive. No `PR_SET_PDEATHSIG`.
  - Tested: Windows locally and in CI; the POSIX SIGTERM and SIGKILL tests run only on the
    ubuntu CI job: run `43509278369` (commit `38feec6`): not skipped, 0 failed.
- `outputSchema` is stripped from every advertised tool, and forwarded results lose
  `structuredContent` (the raw result keeps it in the cassette). Revisit in Phase 4.
- Determinism: no wall-clock timestamps. The same session and the same calls give a
  byte-identical cassette (tested through the real CLI).

## Tests

- `tests/safety/test_proxy_safety.py`:
  - zero denied `tools/call` in the twin log, and an exact forwarded list;
  - a forged session (send_email labeled private) gets zero `tools/call send_email`;
  - a `policy` key is refused;
  - gate on the write path;
  - refused before spawn: non-python, installed module, outside `TWIN_ROOT`, escaping
    symlink/junction, hash mismatch (transport and CLI);
  - the raw-byte twin log;
  - kill tests;
  - AST, import-time and runtime (full session) import guards.
- `tests/mutation/test_proxy_mutation.py`:
  - (a) handler forwards everything → `assert_sink_call_sandboxed` fails;
  - (b) gate off → `assert_gate_blocks_on_write_path` fails;
  - (c) both → `assert_twin_never_sees_denied_calls` fails; with either layer alone broken, the
    same check still passes;
  - (d) JSON_STRING fallback broken, and (e) each carrier dropping its payload → the canary
    property fails;
  - (f) second opinion disabled → `assert_forged_session_cannot_forward_sink` fails;
  - (g) collision detection disabled → the look-alike check fails.
- Unit:
  - `tests/unit/test_proxy_names.py`: the Unicode table total (4174) and each line's general
    category checked against Python's own `unicodedata` 15.0.0;
  - `tests/unit/test_proxy_lines.py`: byte limit with a multibyte line, plus a chunking
    property;
  - `tests/unit/test_proxy_cassette.py`: the byte cap;
  - `tests/unit/test_proxy_policy.py`, `test_proxy_gate.py`, `test_proxy_session.py`.
- Integration:
  - `tests/integration/test_proxy_inprocess.py`: the M1 caps, L1 end to end, limits, fail-closed
    paths;
  - `tests/integration/test_proxy_integration.py`: the real CLI.
