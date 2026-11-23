"""stdio transport to the twin upstream, with the ``UpstreamGate`` on the write path.

Before spawn: ``check_twin_argv`` again (interpreter + script under ``TWIN_ROOT``), then
``prepare_twin_copy`` (R4, order pinned by a named test):
1. the script is COPIED into the private temp cwd;
2. the copy's bytes are read ONCE; their sha256 must equal the session's ``twin_sha256``;
3. ``twin.guard.check_no_io`` runs on THOSE SAME BYTES (never on the original path), and the
   result is ``UpstreamState.guard_passed`` (assigned, never OR-ed: a pre-set value cannot
   survive);
4. the COPY is what runs (no check-then-run gap on the original file).
A guard failure does NOT refuse the spawn (R-C1: the guard is not a spawn gate; the fake
twin fails it and still starts). Its only consequence is that the server's dual-role set is
empty (ADR-007). The guard is not a sandbox (THREAT_MODEL).
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
import time
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
from proveflow.proxy.cassette import HANDSHAKE_STAGES
from proveflow.proxy.gate import GateBlocked, UpstreamGate
from proveflow.proxy.lines import LineSplitter, LineTooLong
from proveflow.proxy.policy import TwinUpstream, TwinUpstreamError, check_twin_argv
from proveflow.twin.guard import check_no_io

STDERR_CAP = 64 * 1024
GRACE_SECONDS = 2.0

Record = Callable[..., Any]


class HandshakeProgress:
    """THE shared record of the twin handshake (Phase 7.0), one per session, written by BOTH
    the transport (``twin_stdio``: spawn; initialize, from the request it WRITES and the
    response it READS) and ``serve()`` (tools_list). Each stage records ``handshake_stage``
    started, then completed; ``outstanding`` is the stage that started and has not completed,
    which is what a handshake timeout names. ``on_stage`` lets ``serve()`` move its deadline:
    called with the stage at each start, and with None at each completion.

    ``elapsed_ms`` (monotonic clock) is NON-EVIDENCE: it goes to the trial's timings sidecar,
    never into the cassette (cassette.py docstring, ADR-008)."""

    def __init__(self, record: Record, on_stage: Callable[[str | None], None]) -> None:
        self._record = record
        self._on_stage = on_stage
        self.outstanding: str | None = None
        self.completed: list[str] = []
        self.elapsed_ms: dict[str, float] = {}
        self._t0 = 0.0

    def start(self, stage: str) -> None:
        if stage not in HANDSHAKE_STAGES:  # pragma: no cover - a programming error
            raise ValueError(f"unknown handshake stage {stage!r}")
        self.outstanding = stage
        self._t0 = time.monotonic()
        self._record("handshake_stage", stage=stage, status="started")
        self._on_stage(stage)

    def complete(self, stage: str) -> None:
        if self.outstanding != stage:  # pragma: no cover - a programming error
            raise RuntimeError(
                f"handshake stage {stage!r} completed while {self.outstanding!r} was outstanding"
            )
        self.elapsed_ms[stage] = (time.monotonic() - self._t0) * 1000.0
        self.outstanding = None
        self.completed.append(stage)
        self._record("handshake_stage", stage=stage, status="completed")
        self._on_stage(None)


@dataclass
class UpstreamState:
    # Set ONLY by twin_stdio, from guard_verdict on the hashed bytes (ADR-007).
    guard_passed: bool = False
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


def guard_verdict(data: bytes) -> bool:
    """True only if ``check_no_io`` completes on ``data`` decoded as UTF-8. Every failure
    (guard refusal, syntax error, null bytes, non-UTF-8, nesting too deep) is False."""
    try:
        check_no_io(data.decode("utf-8"))
    except (ValueError, RecursionError):  # TwinGuardError and UnicodeDecodeError are ValueError
        return False
    return True


def prepare_twin_copy(source: Path, workdir: Path, twin_sha256: str) -> tuple[Path, bool]:
    """Copy -> read the copy's bytes once -> sha256 of those bytes -> guard on those same
    bytes. Returns (copy, guard_passed). A hash mismatch raises before the guard runs."""
    copy = workdir / source.name
    shutil.copyfile(source, copy)
    data = copy.read_bytes()
    if hashlib.sha256(data).hexdigest() != twin_sha256:
        raise TwinUpstreamError("twin script sha256 does not match the session's twin_sha256")
    return copy, guard_verdict(data)


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
    progress: HandshakeProgress | None = None,
) -> AsyncIterator[tuple[MemoryObjectReceiveStream[SessionMessage | Exception], GatedWriteStream]]:
    check_twin_argv(upstream.argv)  # layer A again, right before spawn
    env = child_env(parent_env, {}, windows=sys.platform == "win32")
    workdir = tempfile.TemporaryDirectory(prefix="proveflow-twin-")
    try:
        # Run a private COPY whose hash is checked: the original file can change after the
        # check without affecting what runs. The guard verdict is on the same bytes.
        state.guard_passed = False
        copy, passed = prepare_twin_copy(Path(upstream.argv[1]), Path(workdir.name), twin_sha256)
        state.guard_passed = passed
        argv = [upstream.argv[0], str(copy), *upstream.argv[2:]]
        if progress is not None:
            progress.start("spawn")
        spawned = await spawn(argv, env, cwd=Path(workdir.name))
        if progress is not None:
            progress.complete("spawn")
    except BaseException:
        workdir.cleanup()
        raise
    state.spawned = spawned
    process = spawned.process
    read_w, read_r = anyio.create_memory_object_stream[SessionMessage | Exception](0)
    write_w, write_r = anyio.create_memory_object_stream[SessionMessage](0)
    reply_w = write_w.clone()  # the reader answers upstream requests through the same gate
    initialize_id: list[Any] = []  # the id of the initialize request WRITTEN (handshake stage)

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
                            if (progress is not None and initialize_id
                                    and progress.outstanding == "initialize"
                                    and getattr(msg, "id", None) == initialize_id[0]):  # fmt: skip
                                progress.complete("initialize")
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
                if (progress is not None and not initialize_id
                        and isinstance(message, mcp_types.JSONRPCRequest)
                        and message.method == "initialize"):  # fmt: skip
                    initialize_id.append(message.id)
                    progress.start("initialize")  # recorded BEFORE the bytes are written
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
