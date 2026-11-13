# MCP Python SDK facts used by proveflow [research → verified 2026-11-11]

> Pinned dependency: `mcp==2.3.0` (PyPI, MIT, uploaded 2026-10-02). Every fact below was read in
> the **installed source** of that version (`.venv/Lib/site-packages/mcp/...`) or in the official
> docs <https://py.sdk.modelcontextprotocol.io/client/transports/> on 2026-11-11. Line numbers
> refer to 2.3.0. If the pin changes, re-verify this file first.

## Why proveflow does NOT use `StdioServerParameters` / `stdio_client`

| Fact | Source |
|---|---|
| `StdioServerParameters` is a pydantic `BaseModel` with `env: dict[str, str] \| None`. A raw env would sit inside a serializable model whose repr shows values, which breaks the LaunchSpec design (docs/REDACTION.md, THREAT_MODEL T2) | `mcp/client/stdio.py:94-101` |
| `stdio_client` sends the child's stderr to the caller's `errlog` (default `sys.stderr`). A server that prints its env would print it into our terminal | `mcp/client/stdio.py:115-116`; docs: "The child's stderr goes to yours." |
| Windows spawn assigns the process to a Job Object **after** spawn. The SDK's own comment: "Children spawned before the assignment completes land outside the job … the fix is a CREATE_SUSPENDED spawn -> assign -> resume." | `mcp/os/win32/utilities.py:168-170` |

proveflow therefore writes its own transport (it spawns the process with LaunchSpec env, captures
stderr into a bounded, scrubbed buffer, and uses its own Job Object handling, see
docs/PROCESS_KILL.md). It reuses the SDK only for the protocol.

## What proveflow relies on

| Fact | Source |
|---|---|
| A transport is "an async context manager that yields read and write streams". The type is `TransportStreams = tuple[ReadStream[SessionMessage \| Exception], WriteStream[SessionMessage]]` | `mcp/client/_transport.py:13-20` (exported as `mcp.client.Transport`, `mcp/client/__init__.py:4`) |
| `Client(server)` accepts "any `Transport` … used directly" | `mcp/client/client.py:267-294` |
| Message envelope: `SessionMessage(message: JSONRPCMessage, metadata=None)` | `mcp/shared/message.py:59-64` |
| stdio wire format: newline-delimited JSON. The SDK parses each line with `mcp_types.jsonrpc_message_adapter.validate_json(line, by_name=False)` and writes `message.model_dump_json(by_alias=True, exclude_unset=True) + "\n"` | `mcp/client/stdio.py` (`_parse_line`, `stdin_writer`) |
| Default env allow-list for a stdio child. Windows: `APPDATA, HOMEDRIVE, HOMEPATH, LOCALAPPDATA, PATH, PATHEXT, PROCESSOR_ARCHITECTURE, SYSTEMDRIVE, SYSTEMROOT, TEMP, USERNAME, USERPROFILE`. POSIX: `HOME, LOGNAME, PATH, SHELL, TERM, USER`. Values starting with `()` (shell functions) are skipped | `mcp/client/stdio.py:41-91` |
| `Client.list_tools(cursor=None)` returns **one page** (`ListToolsResult` with `next_cursor`). Only the internal `_relist_tool` loops pages (cap `_RELIST_PAGE_CAP = 100`). proveflow loops `next_cursor` itself with the same 100-page cap | `mcp/client/client.py:84, 951-982` |
| The dispatcher sends `notifications/cancelled` when a request times out / is abandoned | `mcp/shared/dispatcher.py:101`, `mcp/client/session.py:173` |
| Negotiated version: `Client.protocol_version` (after connect). The era is "modern" if it is in `mcp_types.version.MODERN_PROTOCOL_VERSIONS`, otherwise "handshake" (`HANDSHAKE_PROTOCOL_VERSIONS` = 2024-11-05 … 2025-11-25) | `mcp/client/client.py:502-504`; `mcp_types/version.py` |
| Outgoing envelope types: `JSONRPCRequest` / `JSONRPCNotification` carry `.method`; `JSONRPCResponse` / `JSONRPCError` do not | `mcp_types/jsonrpc.py:39-145` |
| Connect modes: `mode="auto"` (the default) sends a **`server/discover`** probe first and falls back to the `initialize` handshake. `mode="legacy"` sends only `initialize` | `mcp/client/client.py:78-81, 335`; `mcp/client/_probe.py:1-25` |
| `ping` is "removed as of 2026-07-28; the method only works under mode='legacy'" | `mcp/client/client.py:527` |

## Consequence for the method allowlist (checkpoint 1b, step 2)

Decision (Haris, 2026-11-11): `mode="auto"`. The transport's write path allows only these outgoing
methods: `server/discover`, `initialize`, `notifications/initialized`, `tools/list`, and
`notifications/cancelled` (sent by the SDK dispatcher on timeout/abandon, see above). It allows
responses/errors to server-initiated requests (no method). **Everything else, `tools/call` in
particular, raises `ForbiddenMethod` before a byte is written.**

`mcp.client.Transport` lives in a private module (`_transport.py`) that is re-exported publicly.
proveflow matches the protocol structurally, so a rename of the private module does not break it.

## `mode="auto"` fallback: observed behaviour (fake server, 2026-11-11)

`negotiate_auto` (`mcp/client/_probe.py:52-114`): every `MCPError` from `server/discover`
("every other rpc-error -> legacy (the denylist)", line 80) falls back to `initialize`, apart
from the `-32022` cases. A non-`MCPError` (transport/connection error) propagates (lines
96-97). `read_timeout_seconds` defaults to `None` (`client.py:303`), so an unanswered probe
waits for the caller. Test: `tests/safety/test_review_4a_fixes.py::test_sdk_auto_mode_fallback_behaviour`.

| Fake mode (tests/fixtures/fake_mcp_server.py) | Result under proveflow | Methods the server received |
|---|---|---|
| `legacy` (-32601 on discover) | ok, handshake era | discover, initialize, initialized, tools/list |
| `discover_error` (-32603 on discover) | ok, handshake era | discover, initialize, initialized, tools/list |
| `discover_silent` (no reply to discover) | **timeout** (whole budget used) | discover |
| `exit_unknown` (exits on discover) | **failed** ("Connection closed") | discover |

**Implemented (Haris, 2026-11-12):**
- If the connection **closed** after only `server/discover` was written and nothing came back,
  proveflow relaunches the server **once** with `mode="legacy"`, under the same consent and the
  same overall deadline. `detail` says "relaunched once with --protocol legacy … (its code ran
  twice)". `exit_unknown` therefore ends `ok`.
- **Silent** servers (`discover_silent`) are **not** relaunched. They time out, and the timeout
  `detail` suggests `--protocol legacy`.
- `scan --protocol legacy` sends only the `initialize` handshake.

Tests: `tests/safety/test_review_round3.py`.


## Server side and proxy facts (Phase 2, verified 2026-11-14 in the installed 2.3.0 source)

Read before implementing the proxy (Phase 2 step 0). None of these facts contradicted D4/D6.

| Fact | Source |
|---|---|
| Lowlevel `Server(name, *, version, ..., on_list_tools, on_call_tool, ...)`. A spec request handler is registered only when its `on_*` argument is not `None`; `ping` (default `_ping_handler`) and `server/discover` are always registered | `mcp/server/lowlevel/server.py:459-474` |
| A request whose method has no registered handler is answered with `MCPError(code=METHOD_NOT_FOUND, message="Method not found", data=method)` (-32601). The proxy registers only `tools/list` and `tools/call`, so agent `resources/*`, `prompts/*`, `completion/*`, `logging/setLevel` get -32601 locally | `mcp/server/runner.py:197, 210` |
| `Server.run(read_stream, write_stream, initialization_options, raise_exceptions=False)` serves a stream pair | `mcp/server/lowlevel/server.py:703` |
| `stdio_server(stdin=None, stdout=None)`: with explicit streams it skips claiming fd 0/1. It reads with `async for line in stdin` and parses each line with `jsonrpc_message_adapter.validate_json`. The fake twin passes a logging stdin wrapper (log before parse, A3). The proxy uses its own fd-based agent transport (daemon reader thread on a dup of fd 0, `MAX_LINE` enforced, fd 1 pointed at stderr while serving) | `mcp/server/stdio.py:162-210` |
| ClientSession default callbacks REJECT server-initiated requests: sampling ("Sampling not supported"), elicitation, roots/list, each with `INVALID_REQUEST`. A non-default sampling callback makes the client advertise the `sampling` capability. The proxy never relays: its upstream transport answers every upstream request itself (-32601; `ping` → `{}`), so the SDK client never sees one | `mcp/client/session.py:249-274, 425-436, 631` |
| `ClientSession.call_tool` revalidates a non-error result against the tool's `outputSchema` from `tools/list`. It raises if `structuredContent` is missing or invalid. That is why the proxy strips `outputSchema` from every advertised tool AND drops `structuredContent` from forwarded results (D6/A1) | `mcp/client/session.py:1102, 1118-1150` |
| A request is written via `await self._write(msg, ...)` → `write_stream.send(SessionMessage(...))`. Only `BrokenResourceError`/`ClosedResourceError` are converted; any other exception from `send` propagates to the caller of `send_request`. So `GatedWriteStream.send` raising `GateBlocked` reaches the proxy handler before anything is written | `mcp/shared/jsonrpc_dispatcher.py:408-412, 797-798` |
| `Client(transport, mode="legacy")` runs `session.initialize()` (initialize + notifications/initialized) and nothing else on connect | `mcp/client/client.py:452-470` |
| `Client.call_tool(name, arguments=None, read_timeout_seconds=None, ...)`; a caller cancellation (e.g. `anyio.fail_after`) sends a courtesy `notifications/cancelled` to the server | `mcp/client/client.py` (`call_tool`); `mcp/shared/jsonrpc_dispatcher.py:443-451` |
| Field names: `CallToolResult(content, structured_content, is_error)` (wire: `structuredContent`, `isError`); `TextContent(type, text)`; `Tool(name, description, input_schema, output_schema, ...)` (wire: `inputSchema`, `outputSchema`) | `mcp_types` (checked with `model_fields`) |
