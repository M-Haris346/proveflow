"""The runner's TRANSCRIPT (Phase 5, D2/D3, ADR-008): every LLM request and response, every
tool call and result, and the agent's final answer, in order, hash-chained.

Same discipline as the proxy cassette (proxy/cassette.py), and the same ``canonical`` and
``digest`` functions, so there is one definition of the hash:
* one canonical JSON event per line, ``seq`` 0, 1, 2, ...;
* ``sha256`` over the event without its ``sha256`` key, ``prev_sha256`` = the previous
  event's ``sha256`` (``GENESIS`` for the first);
* NO wall-clock value anywhere in the hashed content. Latency lives in an unhashed
  timings sidecar (``runner.timings``), which is not evidence;
* a value over ``TEXT_CAP`` bytes is cut and the event marked ``truncated``.

The transcript is a SEPARATE file from the cassettes. The proxy never sees the final answer
(it passes between the agent and the LLM), and the runner never writes into a proxy's
cassette: the cassette stays the proxy's own independent record. The transcript instead
REFERENCES each cassette by that cassette's final chain hash (``trial_end.cassettes``), and
``verify_cassette_refs`` refuses a transcript whose referenced cassette does not match.

``llm_request.body`` is the request body exactly as sent. Headers are never recorded, so the
API key cannot reach this file.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import IO, Annotated, Any, Literal

from pydantic import Field, TypeAdapter, ValidationError

from proveflow.core._base import FrozenModel
from proveflow.introspect.limits import MAX_LINE
from proveflow.proxy.cassette import (
    GENESIS,
    TEXT_CAP,
    CassetteError,
    canonical,
    digest,
    is_complete,
    load_cassette,
)

SCHEMA_VERSION = 1
MAX_TRANSCRIPT = 64 * 1024 * 1024
_HEX64 = r"^[0-9a-f]{64}$"
_BASENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class TranscriptError(ValueError):
    pass


class _Event(FrozenModel):
    # Still 1 after Phase 3b, on purpose: no field, type or shape changed. The ``-`` sentinel
    # for ``ToolCall.session_id`` existed since Phase 5 (unknown tool); Phase 3b only makes a
    # call with non-object arguments use it too, i.e. it narrows WHICH calls name a real
    # session. Every committed transcript (fixtures and the Phase 5 evidence run) is checked to
    # fit that reading (oraclechecks.assert_committed_transcripts_fit_the_sentinel_reading).
    schema_version: Literal[1] = 1
    seq: int = Field(ge=0)
    prev_sha256: str = Field(pattern=_HEX64)
    sha256: str = Field(pattern=_HEX64)
    truncated: bool = False


class TrialStart(_Event):
    kind: Literal["trial_start"]
    trial_id: str
    scenario_id: str
    provider: Any  # {"name", "base_url", "model"}; never a key
    parameters: Any  # {"temperature", "max_tokens", "seed", "seed_sent"}
    limits: Any
    budget_remaining: int = Field(ge=0)
    servers: Any  # [{"server", "session_id"}]


class LlmRequest(_Event):
    kind: Literal["llm_request"]
    turn: int = Field(ge=1)
    body: Any  # exactly as sent (no headers)


class LlmResponse(_Event):
    kind: Literal["llm_response"]
    turn: int = Field(ge=1)
    status: int
    body: Any
    tokens_in: int | None  # provider-reported usage.prompt_tokens (F10)
    tokens_out: int | None  # provider-reported usage.completion_tokens


class ToolCall(_Event):
    """One tool call the model asked for. ``server`` / ``session_id`` name the proxy that
    RECEIVED it. The sentinel ``-`` (``NOT_SENT``) means no proxy received it: an unknown
    tool (since Phase 5) or arguments that are not a JSON object (since Phase 3b; before, such
    a call carried its route's session although it was never sent). ``-`` can never be a real
    session id (``proxy.session.SESSION_ID_PATTERN`` starts with a letter or digit). The
    oracle's R4 pairs a session's tool calls with that session's cassette by this field."""

    kind: Literal["tool_call"]
    turn: int = Field(ge=1)
    call_id: str
    tool: str
    server: str
    session_id: str
    arguments: Any


class ToolResult(_Event):
    kind: Literal["tool_result"]
    call_id: str
    content: str  # exactly what the agent was given for this call
    is_error: bool


class FinalAnswer(_Event):
    kind: Literal["final_answer"]
    text: str


class LimitHit(_Event):
    kind: Literal["limit_hit"]
    limit: str
    detail: str


class ErrorEvent(_Event):
    kind: Literal["error"]
    error_kind: str
    detail: str


class CassetteRef(FrozenModel):
    session_id: str
    server: str
    file: str = Field(pattern=_BASENAME.pattern)  # a basename next to the transcript
    final_sha256: str = Field(pattern=_HEX64)


class TrialEnd(_Event):
    kind: Literal["trial_end"]
    reason: str
    tokens_in: int = Field(ge=0)
    tokens_out: int = Field(ge=0)
    cassettes: tuple[CassetteRef, ...]


Event = Annotated[
    TrialStart
    | LlmRequest
    | LlmResponse
    | ToolCall
    | ToolResult
    | FinalAnswer
    | LimitHit
    | ErrorEvent
    | TrialEnd,
    Field(discriminator="kind"),
]
EVENT_ADAPTER: TypeAdapter[Event] = TypeAdapter(Event)
_ENVELOPE = frozenset({"schema_version", "seq", "kind", "prev_sha256", "sha256", "truncated"})


def _cap(value: Any) -> tuple[Any, bool]:
    text = value if isinstance(value, str) else canonical(value)
    raw = text.encode("utf-8")
    if len(raw) <= TEXT_CAP:
        return value, False
    return raw[:TEXT_CAP].decode("utf-8", errors="ignore"), True


class TranscriptWriter:
    """Append-only; opens with ``x`` (never overwrites)."""

    def __init__(self, path: Path) -> None:
        self._fh: IO[bytes] = path.open("xb")
        self._seq = 0
        self._prev = GENESIS

    def emit(self, kind: str, **fields: Any) -> Event:
        if self._fh.closed:
            raise TranscriptError("transcript already closed")
        body: dict[str, Any] = {}
        truncated = False
        for key, value in fields.items():
            if key in _ENVELOPE:
                raise TranscriptError(f"reserved field {key!r}")
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


def load_transcript(path: Path, *, max_bytes: int = MAX_TRANSCRIPT) -> list[Event]:
    """Validate models, seq order, the hash chain, canonical form and sizes. Any defect, or
    any altered request or response, raises ``TranscriptError``."""
    if path.stat().st_size > max_bytes:
        raise TranscriptError(f"transcript larger than {max_bytes} bytes")
    events: list[Event] = []
    prev = GENESIS
    with path.open("rb") as fh:
        while True:
            raw = fh.readline(MAX_LINE + 2)
            if not raw:
                break
            n = len(events)
            if not raw.endswith(b"\n") or len(raw) - 1 > MAX_LINE:
                raise TranscriptError(f"line {n}: missing newline or longer than {MAX_LINE}")
            try:
                text = raw[:-1].decode("utf-8")
                body = json.loads(text)
            except (UnicodeDecodeError, ValueError, RecursionError) as exc:
                raise TranscriptError(f"line {n}: not JSON") from exc
            if not isinstance(body, dict) or body.get("schema_version") != SCHEMA_VERSION:
                raise TranscriptError(f"line {n}: not a schema {SCHEMA_VERSION} event")
            if canonical(body) != text:
                raise TranscriptError(f"line {n}: not in canonical form")
            try:
                event = EVENT_ADAPTER.validate_python(body)
            except ValidationError as exc:
                raise TranscriptError(f"line {n}: invalid event ({exc.error_count()})") from exc
            if event.seq != n:
                raise TranscriptError(f"line {n}: seq {event.seq} out of order")
            if event.prev_sha256 != prev:
                raise TranscriptError(f"line {n}: hash chain broken (prev_sha256)")
            if digest(body) != event.sha256:
                raise TranscriptError(f"line {n}: sha256 mismatch")
            prev = event.sha256
            events.append(event)
    return events


def is_complete_transcript(events: list[Event]) -> bool:
    kinds = [e.kind for e in events]
    return (
        bool(kinds)
        and kinds[0] == "trial_start"
        and kinds[-1] == "trial_end"
        and kinds.count("trial_start") == 1
        and kinds.count("trial_end") == 1
    )


def verify_cassette_refs(events: list[Event], directory: Path) -> list[Path]:
    """Every cassette ``trial_end`` references must exist next to the transcript, load as a
    valid and COMPLETE cassette, and end with exactly the referenced chain hash. Returns the
    cassette paths in reference order."""
    if not is_complete_transcript(events):
        raise TranscriptError("transcript is not complete (trial_start ... trial_end)")
    end = events[-1]
    if not isinstance(end, TrialEnd):  # pragma: no cover - is_complete guarantees it
        raise TranscriptError("last event is not trial_end")
    paths: list[Path] = []
    for ref in end.cassettes:
        path = directory / ref.file
        try:
            cassette = load_cassette(path)
        except (OSError, CassetteError) as exc:
            raise TranscriptError(f"cassette {ref.file}: {exc}") from None
        if not is_complete(cassette):
            raise TranscriptError(f"cassette {ref.file} is not complete")
        if cassette[-1].sha256 != ref.final_sha256:
            raise TranscriptError(f"cassette {ref.file}: final hash does not match the reference")
        paths.append(path)
    return paths
