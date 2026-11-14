"""stdio transport to the twin upstream, with the ``UpstreamGate`` on the write path.

Before spawn: ``check_twin_argv`` again (interpreter + script under ``TWIN_ROOT``), then the
script is COPIED into the private temp cwd, the COPY is hashed and must equal the session's
``twin_sha256``, and the COPY is what runs (no check-then-run gap on the original file).
Spawned through ``introspect.procs.spawn`` (Windows Job Object with KILL_ON_JOB_CLOSE;
POSIX own process group), with ``introspect.env.child_env`` (minimal environment, no config
env). The tree is killed on exit.

Write path (two checks, both before a byte is written):
1. ``GatedWriteStream.send`` calls ``gate.check`` and raises ``GateBlocked`` straight back
   to the caller (the SDK's ``send_request`` -> the proxy handler -> error result).
2. ``stdin_writer`` re-checks every message before encoding it.

Read path (nothing from the upstream is ever relayed to the agent):
* upstream REQUESTS (sampling/*, roots/*, elicitation/*, anything) are answered here with
  a JSON-RPC error (``ping`` with ``{}``) and never reach the SDK client; each is recorded.
* upstream NOTIFICATIONS are dropped and recorded (``upstream_notification_dropped``).
* a line over ``MAX_LINE`` BYTES (``lines.LineSplitter``), one that is not a JSON-RPC
  message, or more than ``max_messages`` messages ends the upstream connection (fail
  closed): pending and later forwarded calls get an error result. The message cap also ends
  the session (``on_limit``).
"""

from __future__ import annotations

import hashlib
import shutil
import sys
import tempfile
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import Any

import anyio
import mcp_types
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from mcp.shared.message import SessionMessage

from proveflow.introspect.env import child_env
from proveflow.introspect.limits import MAX_LINE
from proveflow.introspect.procs import Spawned, spawn
from proveflow.proxy.gate import GateBlocked, UpstreamGate
from proveflow.proxy.lines import LineSplitter, LineTooLong
from proveflow.proxy.policy import TwinUpstream, TwinUpstreamError, check_twin_argv

STDERR_CAP = 64 * 1024
GRACE_SECONDS = 2.0

Record = Callable[..., Any]


@dataclass
class UpstreamState:
    spawned: Spawned | None = None
    stderr: bytearray = field(default_factory=bytearray)
    stderr_truncated: bool = False
    blocked: list[str] = field(default_factory=list)
    closed_reason: str | None = None


class GatedWriteStream:
    """``WriteStream[SessionMessage]`` that runs the gate before handing a message on."""

    def __init__(
        self,
        inner: MemoryObjectSendStream[SessionMessage],
        gate: UpstreamGate,
        state: UpstreamState,
    ) -> None:
        self._inner = inner
        self._gate = gate
        self._state = state

    async def send(self, item: SessionMessage, /) -> None:
        try:
            self._gate.check(item.message)
        except GateBlocked as exc:
            self._state.blocked.append(exc.method)
            raise
        await self._inner.send(item)

    async def aclose(self) -> None:
        await self._inner.aclose()

    async def __aenter__(self) -> GatedWriteStream:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        await self.aclose()
        return None


def _dump(message: Any) -> Any:
    return message.model_dump(by_alias=True, mode="json", exclude_unset=True)


@asynccontextmanager
async def twin_stdio(
    upstream: TwinUpstream,
    twin_sha256: str,
    gate: UpstreamGate,
    state: UpstreamState,
    record: Record,
    parent_env: Mapping[str, str],
    *,
    max_messages: int,
    on_limit: Callable[[str], None],
) -> AsyncIterator[tuple[MemoryObjectReceiveStream[SessionMessage | Exception], GatedWriteStream]]:
    check_twin_argv(upstream.argv)  # layer A again, right before spawn
    env = child_env(parent_env, {}, windows=sys.platform == "win32")
    workdir = tempfile.TemporaryDirectory(prefix="proveflow-twin-")
    try:
        # Run a private COPY whose hash is checked: the original file can change after the
        # check without affecting what runs.
        source = Path(upstream.argv[1])
        copy = Path(workdir.name) / source.name
        shutil.copyfile(source, copy)
        if hashlib.sha256(copy.read_bytes()).hexdigest() != twin_sha256:
            raise TwinUpstreamError("twin script sha256 does not match the session's twin_sha256")
        argv = [upstream.argv[0], str(copy), *upstream.argv[2:]]
        spawned = await spawn(argv, env, cwd=Path(workdir.name))
    except BaseException:
        workdir.cleanup()
        raise
    state.spawned = spawned
    process = spawned.process
    read_w, read_r = anyio.create_memory_object_stream[SessionMessage | Exception](0)
    write_w, write_r = anyio.create_memory_object_stream[SessionMessage](0)
    reply_w = write_w.clone()  # the reader answers upstream requests through the same gate

    def fail(kind: str, detail: str) -> None:
        if state.closed_reason is None:
            state.closed_reason = kind
            record("error", error_kind=kind, detail=detail)

    async def answer(request: mcp_types.JSONRPCRequest) -> None:
        reply: mcp_types.JSONRPCMessage
        if request.method == "ping":
            reply = mcp_types.JSONRPCResponse(jsonrpc="2.0", id=request.id, result={})
        else:
            reply = mcp_types.JSONRPCError(
                jsonrpc="2.0",
                id=request.id,
                error=mcp_types.ErrorData(
                    code=mcp_types.METHOD_NOT_FOUND,
                    message="proveflow proxy: upstream requests are not relayed",
                ),
            )
            record("error", error_kind="upstream_request_rejected", detail=request.method)
        with suppress(anyio.ClosedResourceError, anyio.BrokenResourceError):
            await reply_w.send(SessionMessage(reply))

    async def stdout_reader() -> None:
        if process.stdout is None:
            raise RuntimeError("twin has no stdout pipe")
        splitter = LineSplitter(MAX_LINE)
        count = 0
        async with read_w, reply_w:
            with suppress(anyio.EndOfStream, anyio.ClosedResourceError, anyio.BrokenResourceError):
                while True:
                    chunk = await process.stdout.receive()
                    try:
                        lines = splitter.feed(chunk)
                    except LineTooLong:
                        fail("upstream_line_too_long", f"line longer than {MAX_LINE} bytes")
                        return
                    for line in lines:
                        if not line.strip():
                            continue
                        count += 1
                        if count > max_messages:
                            fail("upstream_message_limit", f"more than {max_messages} messages")
                            on_limit("upstream_message_limit")
                            return
                        try:
                            msg = mcp_types.jsonrpc_message_adapter.validate_json(
                                line, by_name=False
                            )
                        except ValueError:
                            fail("upstream_invalid_message", "line is not a JSON-RPC message")
                            return
                        if isinstance(msg, mcp_types.JSONRPCRequest):
                            await answer(msg)
                        elif isinstance(msg, mcp_types.JSONRPCNotification):
                            record(
                                "error",
                                error_kind="upstream_notification_dropped",
                                detail=msg.method,
                            )
                        else:
                            await read_w.send(SessionMessage(msg))
            if state.closed_reason is None:
                state.closed_reason = "upstream_eof"

    async def stderr_reader() -> None:
        if process.stderr is None:
            raise RuntimeError("twin has no stderr pipe")
        with suppress(anyio.EndOfStream, anyio.ClosedResourceError, anyio.BrokenResourceError):
            while True:
                chunk = await process.stderr.receive()
                room = STDERR_CAP - len(state.stderr)
                if room > 0:
                    state.stderr += chunk[:room]
                if len(chunk) > room:
                    state.stderr_truncated = True

    async def stdin_writer() -> None:
        if process.stdin is None:
            raise RuntimeError("twin has no stdin pipe")
        async with write_r:
            async for session_message in write_r:
                message = session_message.message
                try:
                    gate.check(message)  # second, independent check right before the bytes
                except GateBlocked as exc:
                    # Only reachable if the stream-level check was bypassed; the request is
                    # never written, so its caller fails on the per-call timeout.
                    state.blocked.append(exc.method)
                    record("error", error_kind="gate_blocked_at_writer", detail=exc.method)
                    continue
                data = message.model_dump_json(by_alias=True, exclude_unset=True) + "\n"
                with suppress(anyio.ClosedResourceError, anyio.BrokenResourceError, OSError):
                    await process.stdin.send(data.encode("utf-8"))

    try:
        async with anyio.create_task_group() as tg:
            tg.start_soon(stdout_reader)
            tg.start_soon(stderr_reader)
            tg.start_soon(stdin_writer)
            try:
                yield read_r, GatedWriteStream(write_w, gate, state)
            finally:
                with anyio.CancelScope(shield=True):
                    with suppress(Exception):
                        await process.stdin.aclose()  # type: ignore[union-attr]
                    with anyio.move_on_after(GRACE_SECONDS):
                        await process.wait()
                    await spawned.kill_tree()
                tg.cancel_scope.cancel()
    finally:
        with anyio.CancelScope(shield=True):
            await spawned.kill_tree()
        with suppress(OSError):
            workdir.cleanup()
