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
files over ``MAX_CASSETTE``. Replay is Phase 5.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import IO, Annotated, Any, Literal

from pydantic import Field, TypeAdapter, ValidationError

from proveflow.core._base import FrozenModel
from proveflow.introspect.limits import MAX_LINE

SCHEMA_VERSION = 1
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
    schema_version: Literal[1] = 1
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


class SessionEnd(_Event):
    kind: Literal["session_end"]
    reason: str
    tool_calls: int
    forwarded_calls: int
    sandboxed_calls: int
    upstream_stderr: str
    upstream_stderr_truncated: bool


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


class CassetteWriter:
    """Append-only writer. Opens with ``x`` (never overwrites an existing cassette)."""

    def __init__(self, path: Path) -> None:
        self._fh: IO[bytes] = path.open("xb")
        self._seq = 0
        self._prev = GENESIS

    def emit(self, kind: str, **fields: Any) -> Event:
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
        self._fh.write((canonical(body) + "\n").encode("utf-8"))
        self._fh.flush()
        self._seq += 1
        self._prev = body["sha256"]
        return event

    def close(self) -> None:
        self._fh.close()


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
