"""Proxy cassette: JSONL, one validated event per line, hash-chained (D9, THREAT_MODEL T6).

* Every line is the canonical JSON of one event (``sort_keys=True``,
  ``separators=(",", ":")``, ``ensure_ascii=False``) followed by ``\\n``.
* ``seq`` is 0, 1, 2, ... ; there are NO wall-clock timestamps (byte-identical replays).
* ``sha256`` = sha256 of the canonical JSON of the event WITHOUT the ``sha256`` key;
  ``prev_sha256`` = the previous event's ``sha256`` (``"0" * 64`` for the first).
* Any string or JSON value over ``TEXT_CAP`` bytes (canonical UTF-8) is replaced by its
  first ``TEXT_CAP`` bytes as a string, and the event's ``truncated`` flag is set.
* ``upstream_response`` holds the RAW upstream result (before injection, including
  ``structuredContent``); ``agent_response`` holds exactly what the agent received.
* Arguments and results are verbatim (twin mode only: no real data). Upstream stderr is
  scrubbed (``introspect.scrub.scrub_stderr``: verbatim + free-text redaction rules).

``load_cassette`` re-validates every event model, the seq order, the hash chain and that
every line is byte-identical to the canonical form; it refuses lines over ``MAX_LINE`` and
files over ``MAX_CASSETTE``, and any ``schema_version`` other than the current one. Replay is
Phase 5.

Schema history: 1 (Phase 2); 2 (Phase 3a): ``sandboxed_call`` carries ``sink: bool``,
computed by the proxy at decision time (``policy.is_sink_call``). Schema-1 cassettes are
refused (a missing flag must never read as "not a sink").
3 (Phase 4): ``session_start`` carries ``honey`` (the session's honey values, a second kind
of needle for the oracle; never the twin's markers, F4), and ``upstream_request`` carries a
REQUIRED ``sink: bool`` from the same ``policy.is_sink_call``. ``sink=true`` on an
``upstream_request`` means exactly "a dual-role tool was forwarded to a guard-passing twin"
(ADR-007): every other forwarded name is, by the forward conditions, neither a session sink,
nor a proxy-classifier sink, nor in a look-alike group with one (a look-alike of a session
name is denied by ``build_policy``, of an advertised name by ``decide``). There is no
separate sandbox reason or event for it. Schema-2 cassettes are refused.
4 (Phase 7.0): ``handshake_stage`` events record the twin handshake per stage
(``HANDSHAKE_STAGES``: spawn, initialize, tools_list), each ``started`` then ``completed``, and a
stage that does not complete within ``limits.handshake_timeout_s`` ends the session with
``session_end.reason == "handshake_timeout"`` and ``session_end.handshake_outstanding`` naming
it. So "the twin never answered initialize" is read from the cassette ALONE. These events
carry NO elapsed time, ON PURPOSE: a wall-clock value in the hashed chain would break
byte-identical replays (ADR-008; tests/integration/test_proxy_integration.py
``test_cassette_is_byte_identical_across_runs``). The elapsed milliseconds per stage go to the
trial's NON-EVIDENCE timings sidecar instead (runner/trial.py). Do not "add elapsed_ms for
diagnosability" here: the stage facts already diagnose, and the time would silently break
determinism. Schema-3 cassettes are refused (fail closed, no shim).
"""

from __future__ import annotations

import hashlib
import json
import typing
from collections.abc import Callable
from pathlib import Path
from typing import IO, Annotated, Any, Literal

from pydantic import Field, TypeAdapter, ValidationError, model_validator

from proveflow.core._base import FrozenModel
from proveflow.introspect.limits import MAX_LINE

SCHEMA_VERSION = 4
GENESIS = "0" * 64
TEXT_CAP = 1024 * 1024
MAX_CASSETTE = 64 * 1024 * 1024
_HEX64 = r"^[0-9a-f]{64}$"


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(body: dict[str, Any]) -> str:
    """sha256 over the canonical JSON of ``body`` minus its ``sha256`` key."""
    rest = {k: v for k, v in body.items() if k != "sha256"}
    return hashlib.sha256(canonical(rest).encode("utf-8")).hexdigest()


class _Event(FrozenModel):
    schema_version: Literal[4] = 4
    seq: int = Field(ge=0)
    prev_sha256: str = Field(pattern=_HEX64)
    sha256: str = Field(pattern=_HEX64)
    truncated: bool = False


class SessionStart(_Event):
    kind: Literal["session_start"]
    session_id: str
    proveflow_version: str
    upstream: Any
    policy: Any
    attack: Any
    limits: Any
    honey: Any  # required (schema 3): list of HoneyValue dicts, [] when none


class ToolsAdvertised(_Event):
    """``tools``: list of ``{"tool": <wire Tool as sent to the agent>,
    "output_schema_stripped": bool}`` (D6: outputSchema removed from every tool)."""

    kind: Literal["tools_advertised"]
    tools: Any


class AgentRequest(_Event):
    """Every JSON-RPC message received from the agent, verbatim (requests and
    notifications)."""

    kind: Literal["agent_request"]
    message: Any


class UpstreamRequest(_Event):
    kind: Literal["upstream_request"]
    tool: str
    arguments: Any
    # Required (schema 3). True exactly for a dual-role tool forwarded to a guard-passing
    # twin (ADR-007); the oracle scans these for R1 like sandboxed sink calls.
    sink: bool


class UpstreamResponse(_Event):
    kind: Literal["upstream_response"]
    tool: str
    result: Any


class SandboxedCall(_Event):
    kind: Literal["sandboxed_call"]
    tool: str
    arguments: Any
    sandbox_id: str
    reason: str
    # Required (no default): session sink role OR proxy-classifier sink OR the name's
    # look-alike group contains a sink. Recorded by the proxy; the oracle only reads it.
    sink: bool


class Injection(_Event):
    kind: Literal["injection"]
    tool: str
    carrier: str
    canary: str
    content_index: int


class InjectionSkipped(_Event):
    kind: Literal["injection_skipped"]
    tool: str
    reason: str


class AgentResponse(_Event):
    """Every JSON-RPC message sent to the agent, verbatim (after injection)."""

    kind: Literal["agent_response"]
    message: Any


class ErrorEvent(_Event):
    kind: Literal["error"]
    error_kind: str
    detail: str


# THE handshake stages, in order: the ONE source of truth (Phase 7.0). Everything that records,
# times out on or tests a stage derives from this literal; adding a stage here without
# recording it fails tests/unit/test_handshake.py.
HandshakeStageName = Literal["spawn", "initialize", "tools_list"]
HANDSHAKE_STAGES: tuple[str, ...] = typing.get_args(HandshakeStageName)
HANDSHAKE_TIMEOUT_REASON = "handshake_timeout"


class HandshakeStage(_Event):
    """One deterministic handshake fact: a stage started, or completed. No elapsed time
    (module docstring: ADR-008)."""

    kind: Literal["handshake_stage"]
    stage: HandshakeStageName
    status: Literal["started", "completed"]


class SessionEnd(_Event):
    kind: Literal["session_end"]
    reason: str
    tool_calls: int
    forwarded_calls: int
    sandboxed_calls: int
    upstream_stderr: str
    upstream_stderr_truncated: bool
    dropped_events: int = 0  # events not written because the cassette byte cap was hit
    # Phase 7.0: the stage that was outstanding when the handshake deadline fired; present iff
    # ``reason == "handshake_timeout"``.
    handshake_outstanding: HandshakeStageName | None = None

    @model_validator(mode="after")
    def _outstanding_iff_handshake_timeout(self) -> SessionEnd:
        if (self.reason == HANDSHAKE_TIMEOUT_REASON) != (self.handshake_outstanding is not None):
            raise ValueError("handshake_outstanding is present iff reason is handshake_timeout")
        return self


Event = Annotated[
    SessionStart
    | ToolsAdvertised
    | AgentRequest
    | UpstreamRequest
    | UpstreamResponse
    | SandboxedCall
    | Injection
    | InjectionSkipped
    | AgentResponse
    | ErrorEvent
    | HandshakeStage
    | SessionEnd,
    Field(discriminator="kind"),
]
EVENT_ADAPTER: TypeAdapter[Event] = TypeAdapter(Event)

_ENVELOPE = frozenset({"schema_version", "seq", "kind", "prev_sha256", "sha256", "truncated"})


class CassetteError(ValueError):
    pass


def _cap(value: Any) -> tuple[Any, bool]:
    """Return ``value`` unchanged, or its first TEXT_CAP canonical bytes as a string."""
    text = value if isinstance(value, str) else canonical(value)
    raw = text.encode("utf-8")
    if len(raw) <= TEXT_CAP:
        return value, False
    return raw[:TEXT_CAP].decode("utf-8", errors="ignore"), True


FINAL_RESERVE = 64 * 1024  # room kept for the cassette_full error + session_end


class CassetteWriter:
    """Append-only writer. Opens with ``x`` (never overwrites an existing cassette).

    ``max_bytes`` (M1): total file size cap. Ordinary events may use ``max_bytes -
    FINAL_RESERVE``; the first event that does not fit is DROPPED, the writer turns ``full``
    and calls ``on_full`` once (the proxy then records one ``error`` and ends the session).
    While full only that one ``error`` and ``session_end`` are written (within ``max_bytes``);
    every other event is dropped and counted in ``dropped``. The chain stays valid because
    dropped events never get a ``seq``.
    """

    def __init__(
        self,
        path: Path,
        *,
        max_bytes: int | None = None,
        on_full: Callable[[], None] | None = None,
    ) -> None:
        self._fh: IO[bytes] = path.open("xb")
        self._seq = 0
        self._prev = GENESIS
        self._max = max_bytes
        self._on_full = on_full
        self._written = 0
        self.full = False
        self.dropped = 0
        self._final_error_left = 1

    def _fits(self, kind: str, size: int) -> bool:
        if self._max is None:
            return True
        if kind == "session_end":
            return self._written + size <= self._max
        if not self.full:
            return self._written + size <= max(self._max - FINAL_RESERVE, 0)
        if kind == "session_end" or (kind == "error" and self._final_error_left > 0):
            return self._written + size <= self._max
        return False

    def emit(self, kind: str, **fields: Any) -> Event | None:
        if self._fh.closed:
            raise CassetteError("cassette already closed")
        truncated = False
        body: dict[str, Any] = {}
        for key, value in fields.items():
            if key in _ENVELOPE:
                raise CassetteError(f"reserved field {key!r}")
            body[key], cut = _cap(value)
            truncated = truncated or cut
        body.update(
            schema_version=SCHEMA_VERSION,
            seq=self._seq,
            kind=kind,
            prev_sha256=self._prev,
            truncated=truncated,
        )
        body["sha256"] = digest(body)
        event = EVENT_ADAPTER.validate_python(body)  # never write an invalid event
        line = (canonical(body) + "\n").encode("utf-8")
        if not self._fits(kind, len(line)):
            self.dropped += 1
            if not self.full:
                self.full = True
                if self._on_full is not None:
                    self._on_full()
            return None
        if self.full and kind == "error":
            self._final_error_left -= 1
        self._fh.write(line)
        self._fh.flush()
        self._written += len(line)
        self._seq += 1
        self._prev = body["sha256"]
        return event

    def close(self) -> None:
        self._fh.close()


def is_complete(events: list[Event]) -> bool:
    """True only for a whole session: first event ``session_start``, last event
    ``session_end``, and exactly one of each. ``load_cassette`` validates integrity (chain,
    models, sizes), NOT completeness: a cassette cut off by SIGKILL or read while the proxy is
    still running loads fine, and only this check says it is incomplete."""
    kinds = [e.kind for e in events]
    return (
        bool(kinds)
        and kinds[0] == "session_start"
        and kinds[-1] == "session_end"
        and kinds.count("session_start") == 1
        and kinds.count("session_end") == 1
    )


def load_cassette(
    path: Path, *, max_line: int = MAX_LINE, max_bytes: int = MAX_CASSETTE
) -> list[Event]:
    """Validate and return every event. Raises ``CassetteError`` on any defect."""
    size = path.stat().st_size
    if size > max_bytes:
        raise CassetteError(f"cassette larger than {max_bytes} bytes")
    events: list[Event] = []
    prev = GENESIS
    with path.open("rb") as fh:
        while True:
            raw = fh.readline(max_line + 2)
            if not raw:
                break
            n = len(events)
            if not raw.endswith(b"\n"):
                if len(raw) > max_line:
                    raise CassetteError(f"line {n}: longer than {max_line} bytes")
                raise CassetteError(f"line {n}: missing trailing newline")
            line = raw[:-1]
            if len(line) > max_line:
                raise CassetteError(f"line {n}: longer than {max_line} bytes")
            try:
                text = line.decode("utf-8")
                body = json.loads(text)
            except (UnicodeDecodeError, ValueError) as exc:
                raise CassetteError(f"line {n}: not JSON") from exc
            if not isinstance(body, dict):
                raise CassetteError(f"line {n}: not a JSON object")
            if body.get("schema_version") != SCHEMA_VERSION:
                raise CassetteError(
                    f"line {n}: unsupported cassette schema_version "
                    f"{body.get('schema_version')!r} (this proveflow reads {SCHEMA_VERSION})"
                )
            if canonical(body) != text:
                raise CassetteError(f"line {n}: not in canonical form")
            try:
                event = EVENT_ADAPTER.validate_python(body)
            except ValidationError as exc:
                raise CassetteError(f"line {n}: invalid event: {exc.error_count()} errors") from exc
            if event.seq != n:
                raise CassetteError(f"line {n}: seq {event.seq} out of order")
            if event.prev_sha256 != prev:
                raise CassetteError(f"line {n}: hash chain broken (prev_sha256)")
            if digest(body) != event.sha256:
                raise CassetteError(f"line {n}: sha256 mismatch")
            prev = event.sha256
            events.append(event)
    return events
