"""The proxy: an MCP stdio server for the agent, a gated MCP client for the twin (D1-D9).

Agent side: a lowlevel ``Server("proveflow-proxy")`` with ONLY ``tools/list`` and
``tools/call`` registered. The SDK answers every other method (resources/*, prompts/*,
completion/*, logging/setLevel, ...) with JSON-RPC -32601 "Method not found"
(``mcp/server/runner.py:203-210``); ``ping`` and ``server/discover`` are answered locally by
the SDK. Nothing an agent sends is forwarded except a ``tools/call`` the handler decided to
forward (and the SDK's own ``notifications/cancelled`` for that in-flight call).

Upstream side: ``Client(mode="legacy")`` over ``upstream.twin_stdio`` (initialize handshake,
then ``tools/list``). Every write passes ``UpstreamGate``.

``tools/call``: ``policy.decide`` -> sandbox (``sbx_NNNN``) or forward. A forwarded result
loses ``structuredContent`` (A1; ``outputSchema`` is stripped from every advertised tool,
D6) and, for an ``inject=True`` tool with an armed attack, gets the payload in its first
TextContent via the attack's carrier. Every failure (gate, timeout, upstream crash, error)
becomes ``isError=true`` "proveflow proxy: <reason>" and nothing is forwarded.

Limits (``ProxyLimits``): per call, per session, max tool calls (sandboxed calls count).
On exit or cancellation the twin's process tree is killed (``Spawned.kill_tree``); on
POSIX a SIGTERM handler kills the tree first (ADR-006; SIGKILL residual: the twin exits on
stdin EOF).
"""

from __future__ import annotations

import os
import signal
import sys
import threading
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any

import anyio
import anyio.from_thread
import anyio.lowlevel
import anyio.to_thread
import mcp_types
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from mcp import Client
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from mcp.shared.exceptions import MCPError
from mcp.shared.message import SessionMessage

from proveflow import __version__
from proveflow.introspect.limits import MAX_LINE
from proveflow.introspect.scrub import scrub_stderr
from proveflow.proxy.carriers import apply_carrier
from proveflow.proxy.cassette import CassetteWriter
from proveflow.proxy.gate import GateBlocked, UpstreamGate
from proveflow.proxy.policy import Decision, decide
from proveflow.proxy.sandbox import error_result_dict, sandbox_id, sandbox_result_dict
from proveflow.proxy.session import ProxySession
from proveflow.proxy.upstream import Record, UpstreamState, twin_stdio

SERVER_NAME = "proveflow-proxy"
PAGE_CAP = 100
STDERR_REPORT = 2000


class AgentLineTooLong(ValueError):
    """An agent line exceeded MAX_LINE: the session ends (fail closed)."""


@dataclass
class ProxyControl:
    """Lets an outside watcher (SIGTERM) stop a running ``serve`` with a reason."""

    reason: str | None = None
    scope: anyio.CancelScope | None = None
    upstream: UpstreamState | None = None

    async def stop(self, reason: str) -> None:
        self.reason = reason
        if self.upstream is not None and self.upstream.spawned is not None:
            await self.upstream.spawned.kill_tree()
        if self.scope is not None:
            self.scope.cancel()


@dataclass
class ProxyOutcome:
    reason: str
    tool_calls: int = 0
    forwarded_calls: int = 0
    sandboxed_calls: int = 0
    blocked_by_gate: list[str] = field(default_factory=list)


def _dump(model: Any) -> Any:
    return model.model_dump(by_alias=True, mode="json", exclude_unset=True)


class RecordingRead:
    """Agent read stream wrapper: records every inbound message (and stream errors)."""

    def __init__(self, inner: Any, record: Record) -> None:
        self._inner = inner
        self._record = record

    async def receive(self) -> SessionMessage | Exception:
        item: SessionMessage | Exception = await self._inner.receive()
        if isinstance(item, Exception):
            kind = (
                "agent_line_too_long"
                if isinstance(item, AgentLineTooLong)
                else "agent_invalid_message"
            )
            self._record("error", error_kind=kind, detail=type(item).__name__)
        else:
            self._record("agent_request", message=_dump(item.message))
        return item

    async def aclose(self) -> None:
        await self._inner.aclose()

    def __aiter__(self) -> RecordingRead:
        return self

    async def __anext__(self) -> SessionMessage | Exception:
        try:
            return await self.receive()
        except (anyio.EndOfStream, anyio.ClosedResourceError):
            raise StopAsyncIteration from None

    async def __aenter__(self) -> RecordingRead:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        await self.aclose()
        return None


class RecordingWrite:
    """Agent write stream wrapper: records every outbound message exactly as sent."""

    def __init__(self, inner: Any, record: Record) -> None:
        self._inner = inner
        self._record = record

    async def send(self, item: SessionMessage, /) -> None:
        self._record("agent_response", message=_dump(item.message))
        await self._inner.send(item)

    async def aclose(self) -> None:
        await self._inner.aclose()

    async def __aenter__(self) -> RecordingWrite:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        await self.aclose()
        return None


def _strip_output_schema(tool: mcp_types.Tool) -> tuple[mcp_types.Tool, dict[str, Any], bool]:
    wire = _dump(tool)
    stripped = "outputSchema" in wire
    wire.pop("outputSchema", None)
    return mcp_types.Tool.model_validate(wire), wire, stripped


class _CallHandler:
    def __init__(
        self,
        session: ProxySession,
        client: Client,
        advertised: frozenset[str],
        record: Record,
        outcome: ProxyOutcome,
    ) -> None:
        self._session = session
        self._client = client
        self._advertised = advertised
        self._record = record
        self._outcome = outcome
        self._sbx_seq = 0

    def _error(self, kind: str, detail: str, reason: str) -> mcp_types.CallToolResult:
        self._record("error", error_kind=kind, detail=detail)
        return mcp_types.CallToolResult.model_validate(error_result_dict(reason))

    async def __call__(
        self, ctx: ServerRequestContext[Any], params: mcp_types.CallToolRequestParams
    ) -> mcp_types.CallToolResult:
        name = params.name
        arguments = params.arguments
        self._outcome.tool_calls += 1
        if self._outcome.tool_calls > self._session.limits.max_calls:
            return self._error("max_calls_exceeded", name, "tool call limit reached")
        decision, why = decide(self._session.policy, self._advertised, name)
        if decision is not Decision.FORWARD:
            self._outcome.sandboxed_calls += 1
            self._sbx_seq += 1
            self._record(
                "sandboxed_call",
                tool=name,
                arguments=arguments,
                sandbox_id=sandbox_id(self._sbx_seq),
                reason=why.value if why is not None else "policy_deny",
            )
            return mcp_types.CallToolResult.model_validate(sandbox_result_dict(self._sbx_seq))
        return await self._forward(name, arguments)

    async def _forward(
        self, name: str, arguments: dict[str, Any] | None
    ) -> mcp_types.CallToolResult:
        self._outcome.forwarded_calls += 1
        self._record("upstream_request", tool=name, arguments=arguments)
        try:
            with anyio.fail_after(self._session.limits.call_timeout_s):
                raw = await self._client.call_tool(name, arguments)
        except GateBlocked as exc:
            self._outcome.blocked_by_gate.append(name)
            return self._error("gate_blocked", exc.method, "blocked by upstream gate")
        except TimeoutError:
            return self._error("upstream_timeout", name, "upstream call timed out")
        except MCPError as exc:
            return self._error("upstream_error", str(exc.code), "upstream error")
        except Exception as exc:
            return self._error("upstream_failure", type(exc).__name__, "upstream failure")
        result = _dump(raw)
        self._record("upstream_response", tool=name, result=result)
        result.pop("structuredContent", None)  # A1: the raw value stays in the cassette
        policy = self._session.policy.get(name)
        attack = self._session.attack
        if policy is not None and policy.inject and attack is not None:
            self._inject(name, result, attack.carrier, attack.payload.text, attack.canary)
        return mcp_types.CallToolResult.model_validate(result)

    def _inject(
        self, name: str, result: dict[str, Any], carrier: Any, payload: str, canary: str
    ) -> None:
        content = result.get("content")
        if not isinstance(content, list) or not content:
            self._record("injection_skipped", tool=name, reason="empty_content")
            return
        for index, item in enumerate(content):
            if isinstance(item, dict) and item.get("type") == "text":
                item["text"] = apply_carrier(carrier, str(item.get("text", "")), payload)
                self._record(
                    "injection",
                    tool=name,
                    carrier=str(carrier),
                    canary=canary,
                    content_index=index,
                )
                return
        self._record("injection_skipped", tool=name, reason="no_text_content")


async def _list_upstream_tools(client: Client) -> list[mcp_types.Tool]:
    tools: list[mcp_types.Tool] = []
    cursor: str | None = None
    for _ in range(PAGE_CAP):
        page = await client.list_tools(cursor=cursor)
        tools.extend(page.tools)
        cursor = page.next_cursor
        if cursor is None:
            break
    return tools


def _leaf_names(exc: BaseException) -> str:
    if isinstance(exc, BaseExceptionGroup):
        return ",".join(sorted({_leaf_names(e) for e in exc.exceptions}))
    return type(exc).__name__


async def serve(
    session: ProxySession,
    agent_read: Any,
    agent_write: Any,
    *,
    parent_env: Mapping[str, str],
    control: ProxyControl | None = None,
) -> ProxyOutcome:
    """Run one proxy session over the given agent streams until the agent disconnects,
    a limit is hit, or ``control.stop`` is called. Always writes ``session_end``."""
    control = control or ProxyControl()
    writer = CassetteWriter(session.cassette_path)
    record: Record = writer.emit
    outcome = ProxyOutcome(reason="agent_closed")
    upstream_state = UpstreamState()
    control.upstream = upstream_state
    gate = UpstreamGate(session.policy)
    record(
        "session_start",
        session_id=session.session_id,
        proveflow_version=__version__,
        upstream=session.upstream.model_dump(mode="json"),
        policy={k: v.model_dump(mode="json") for k, v in sorted(session.policy.items())},
        attack=session.attack.model_dump(mode="json") if session.attack else None,
        limits=session.limits.model_dump(mode="json"),
    )
    try:
        with anyio.CancelScope() as scope:
            control.scope = scope
            scope.deadline = anyio.current_time() + session.limits.session_timeout_s
            transport = twin_stdio(session.upstream, gate, upstream_state, record, parent_env)
            async with Client(transport, mode="legacy") as client:
                tools = await _list_upstream_tools(client)
                stripped = [_strip_output_schema(t) for t in tools]
                record(
                    "tools_advertised",
                    tools=[{"tool": w, "output_schema_stripped": s} for _, w, s in stripped],
                )
                advertised_tools = [t for t, _, _ in stripped]
                advertised_names = frozenset(t.name for t in tools)
                gate.set_advertised(advertised_names)
                handler = _CallHandler(session, client, advertised_names, record, outcome)

                async def on_list_tools(
                    ctx: ServerRequestContext[Any], params: mcp_types.PaginatedRequestParams | None
                ) -> mcp_types.ListToolsResult:
                    return mcp_types.ListToolsResult(tools=advertised_tools)

                server: Server[Any] = Server(
                    SERVER_NAME,
                    version=__version__,
                    on_list_tools=on_list_tools,
                    on_call_tool=handler,
                )
                await server.run(
                    RecordingRead(agent_read, record),
                    RecordingWrite(agent_write, record),
                    server.create_initialization_options(),
                )
        if scope.cancelled_caught:
            outcome.reason = control.reason or "session_timeout"
    except Exception as exc:
        record("error", error_kind="proxy_failure", detail=_leaf_names(exc))
        outcome.reason = control.reason or "error"
    finally:
        with anyio.CancelScope(shield=True):
            if upstream_state.spawned is not None:
                await upstream_state.spawned.kill_tree()
            # The agent sees the session end (EOF), e.g. after a session timeout.
            for stream in (agent_write, agent_read):
                with suppress(Exception):
                    await stream.aclose()
        raw = bytes(upstream_state.stderr)
        text = scrub_stderr(raw, (), limit=STDERR_REPORT)
        outcome.blocked_by_gate.extend(upstream_state.blocked)
        record(
            "session_end",
            reason=outcome.reason,
            tool_calls=outcome.tool_calls,
            forwarded_calls=outcome.forwarded_calls,
            sandboxed_calls=outcome.sandboxed_calls,
            upstream_stderr=text,
            upstream_stderr_truncated=upstream_state.stderr_truncated
            or len(raw.decode("utf-8", errors="replace")) > STDERR_REPORT,
        )
        writer.close()
    return outcome


# --- agent stdio (CLI) -------------------------------------------------------------


CHUNK = 64 * 1024


def _stdin_pump(
    fd: int,
    send: MemoryObjectSendStream[bytes | None],
    token: anyio.lowlevel.EventLoopToken,
) -> None:
    """Daemon thread reading a private dup of stdin with ``os.read``.

    A raw fd (no buffered file object, so no IO lock) in a daemon thread: a read still
    blocked when the session ends never keeps the process alive and never touches an
    object the interpreter finalizes (a blocked ``sys.stdin.buffer.readline`` crashed the
    Windows interpreter at exit with 0xC0000005 in testing).
    """
    try:
        while True:
            chunk = os.read(fd, CHUNK)
            anyio.from_thread.run(send.send, chunk or None, token=token)
            if not chunk:
                return
    except Exception:
        return


@asynccontextmanager
async def agent_stdio(
    stdin_fd: int, stdout_fd: int
) -> AsyncIterator[
    tuple[
        MemoryObjectReceiveStream[SessionMessage | Exception],
        MemoryObjectSendStream[SessionMessage],
    ]
]:
    """Line-delimited JSON-RPC on the given fds (dup'd), MAX_LINE enforced."""
    in_fd = os.dup(stdin_fd)
    out_fd = os.dup(stdout_fd)
    # While serving, fd 1 points at stderr: a stray print cannot corrupt the MCP channel.
    with suppress(Exception):
        sys.stdout.flush()
    saved_stdout = os.dup(stdout_fd)
    os.dup2(2, stdout_fd)
    read_w, read_r = anyio.create_memory_object_stream[SessionMessage | Exception](0)
    write_w, write_r = anyio.create_memory_object_stream[SessionMessage](0)
    chunks_w, chunks_r = anyio.create_memory_object_stream[bytes | None](16)
    token = anyio.lowlevel.current_token()
    threading.Thread(target=_stdin_pump, args=(in_fd, chunks_w, token), daemon=True).start()

    async def deliver(line: bytes) -> None:
        if not line.strip():
            return
        try:
            msg = mcp_types.jsonrpc_message_adapter.validate_json(line, by_name=False)
        except ValueError as exc:
            await read_w.send(exc)
            return
        await read_w.send(SessionMessage(msg))

    async def reader() -> None:
        buffer = b""
        async with read_w, chunks_r:
            with suppress(anyio.ClosedResourceError, anyio.BrokenResourceError):
                async for chunk in chunks_r:
                    if chunk is None:
                        if buffer:
                            await deliver(buffer)
                        return
                    buffer += chunk
                    *lines, buffer = buffer.split(b"\n")
                    if len(buffer) > MAX_LINE or any(len(x) > MAX_LINE for x in lines):
                        await read_w.send(AgentLineTooLong(f"line over {MAX_LINE} bytes"))
                        return
                    for line in lines:
                        await deliver(line)

    def write_line(data: bytes) -> None:
        view = memoryview(data)
        while view:
            written = os.write(out_fd, view)
            view = view[written:]

    async def writer() -> None:
        async with write_r:
            async for item in write_r:
                data = item.message.model_dump_json(by_alias=True, exclude_unset=True) + "\n"
                with suppress(OSError, ValueError):
                    await anyio.to_thread.run_sync(write_line, data.encode("utf-8"))

    try:
        async with anyio.create_task_group() as tg:
            tg.start_soon(reader)
            tg.start_soon(writer)
            try:
                yield read_r, write_w
            finally:
                tg.cancel_scope.cancel()
    finally:
        with suppress(OSError):
            os.dup2(saved_stdout, stdout_fd)
            os.close(saved_stdout)
        with suppress(OSError):
            os.close(out_fd)  # in_fd stays open: the daemon thread may still be reading it


async def _watch_sigterm(control: ProxyControl) -> None:
    with anyio.open_signal_receiver(signal.SIGTERM) as signals:
        async for _ in signals:
            await control.stop("sigterm")
            return


async def run_proxy(session: ProxySession) -> ProxyOutcome:
    """CLI entry: serve the agent on this process's stdin/stdout."""
    control = ProxyControl()
    async with agent_stdio(sys.stdin.fileno(), sys.stdout.fileno()) as (read, write):
        async with anyio.create_task_group() as tg:
            if sys.platform != "win32":
                tg.start_soon(_watch_sigterm, control)
            outcome = await serve(session, read, write, parent_env=os.environ, control=control)
            tg.cancel_scope.cancel()
    return outcome
