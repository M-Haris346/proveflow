"""proveflow's own stdio transport for the MCP SDK ``Client`` (docs/MCP_SDK.md).

Why not ``mcp.stdio_client``: it takes a pydantic ``StdioServerParameters`` holding the raw
env and sends server stderr to our stderr. This transport spawns via ``procs`` (job object /
process group) with env from a ``LaunchSpec``, captures stderr into a bounded buffer, and
enforces a METHOD ALLOWLIST on the write path: anything other than discovery, handshake and
``tools/list`` raises ``ForbiddenMethod`` before a single byte is written (ADR-003: never
``tools/call``).
"""

from __future__ import annotations

import codecs
import logging
import sys
import tempfile
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path

import anyio
import mcp_types
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from mcp.shared.message import SessionMessage

from proveflow.introspect.env import child_env
from proveflow.introspect.launchspec import LaunchSpec
from proveflow.introspect.limits import MAX_LINE
from proveflow.introspect.procs import Spawned, spawn

logger = logging.getLogger(__name__)

ALLOWED_METHODS: frozenset[str] = frozenset(
    {
        "server/discover",
        "initialize",
        "notifications/initialized",
        "tools/list",
        "notifications/cancelled",
    }
)
STDERR_CAP = 64 * 1024
GRACE_SECONDS = 2.0


class ForbiddenMethod(RuntimeError):
    def __init__(self, method: str) -> None:
        super().__init__(f"blocked outgoing method {method!r} (not in introspection allowlist)")
        self.method = method


def check_outgoing(message: object) -> None:
    """Raise unless ``message`` is allowed. Responses/errors (no ``method``) are allowed."""
    method = getattr(message, "method", None)
    if method is not None and method not in ALLOWED_METHODS:
        raise ForbiddenMethod(str(method))


@dataclass
class TransportState:
    """Facts the caller reads after the session (never raw values)."""

    spawned: Spawned | None = None
    stderr: bytearray = field(default_factory=bytearray)
    stderr_truncated: bool = False
    blocked: list[str] = field(default_factory=list)
    sent_methods: list[str] = field(default_factory=list)
    received: int = 0  # JSON-RPC messages read from the server's stdout


@asynccontextmanager
async def proveflow_stdio(
    spec: LaunchSpec,
    state: TransportState,
    parent_env: dict[str, str],
    untrusted_dirs: Sequence[Path] = (),
) -> AsyncIterator[
    tuple[
        MemoryObjectReceiveStream[SessionMessage | Exception],
        MemoryObjectSendStream[SessionMessage],
    ]
]:
    env = child_env(parent_env, spec.env, windows=sys.platform == "win32")
    # Empty private cwd: never the scanned project (binary planting, npx resolving a
    # project-local package). docs/PROCESS_KILL.md §4 states the gap vs. each client.
    workdir = tempfile.TemporaryDirectory(prefix="proveflow-srv-")
    try:
        spawned = await spawn(
            [spec.command, *spec.args],
            env,
            cwd=Path(workdir.name),
            untrusted_dirs=untrusted_dirs,
        )
    except BaseException:
        workdir.cleanup()
        raise
    del env
    state.spawned = spawned
    process = spawned.process
    read_w, read_r = anyio.create_memory_object_stream[SessionMessage | Exception](0)
    write_w, write_r = anyio.create_memory_object_stream[SessionMessage](0)

    async def stdout_reader() -> None:
        if process.stdout is None:
            raise RuntimeError("server process has no stdout pipe")
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        buffer = ""
        async with read_w:
            with suppress(anyio.EndOfStream, anyio.ClosedResourceError, anyio.BrokenResourceError):
                while True:
                    chunk = await process.stdout.receive()
                    buffer += decoder.decode(chunk)
                    if len(buffer) > MAX_LINE:
                        await read_w.send(ValueError("server stdout line too long"))
                        return
                    *lines, buffer = buffer.split("\n")
                    for line in lines:
                        if not line.strip():
                            continue
                        try:
                            msg = mcp_types.jsonrpc_message_adapter.validate_json(
                                line, by_name=False
                            )
                        except ValueError as exc:
                            await read_w.send(exc)
                            continue
                        state.received += 1
                        await read_w.send(SessionMessage(msg))

    async def stderr_reader() -> None:
        if process.stderr is None:
            raise RuntimeError("server process has no stderr pipe")
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
            raise RuntimeError("server process has no stdin pipe")
        async with write_r:
            async for session_message in write_r:
                message = session_message.message
                try:
                    check_outgoing(message)
                except ForbiddenMethod as exc:
                    state.blocked.append(exc.method)
                    raise
                method = getattr(message, "method", None)
                if method is not None:
                    state.sent_methods.append(str(method))
                data = message.model_dump_json(by_alias=True, exclude_unset=True) + "\n"
                with suppress(anyio.ClosedResourceError, anyio.BrokenResourceError, OSError):
                    await process.stdin.send(data.encode("utf-8"))

    try:
        async with anyio.create_task_group() as tg:
            tg.start_soon(stdout_reader)
            tg.start_soon(stderr_reader)
            tg.start_soon(stdin_writer)
            try:
                yield read_r, write_w
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
