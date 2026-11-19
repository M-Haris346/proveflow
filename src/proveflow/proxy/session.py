"""``ProxySession``: everything one proxy run needs, validated (schema_version 3).

The session carries the tools' role CLASSIFICATION (``ToolSpec`` with evidence), never a
forward/deny decision: the proxy computes the policy itself (``build_policy``), and at run
time adds its own classifier's second opinion that a session cannot forge. A ``policy`` key
is rejected (``extra=forbid``). Schema 2 (Phase 2.1) replaced schema 1's ``policy``.
Schema 3 (Phase 4) adds ``honey``: the twin's honey values (the oracle's second kind of
needle). Older schemas are refused.

The session carries NOTHING about the twin's per-tool markers (Phase 4 F4): a marker is
R-C2's independent evidence that the twin itself answered, which only holds while the proxy
does not know it. Nor does it carry any guard result: ``guard_passed`` is computed by the
proxy from the hashed copy of the script (``upstream.twin_stdio``); ``extra=forbid`` refuses
any such key.

``twin_sha256`` pins the twin script; it is checked on a private copy right before spawn.

Limits are configurable DOWNWARD only: the defaults are also the ceilings (D5 + Phase 2.1
M1), so a session file can tighten them (tests use tiny values) but never loosen them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from proveflow.core._base import FrozenModel
from proveflow.core.attacks import Attack
from proveflow.core.honey import HoneyValue, t4_violations
from proveflow.core.tools import ToolSpec
from proveflow.proxy.policy import ToolPolicy, TwinUpstream, build_policy

SESSION_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$"
MAX_SESSION_FILE = 1024 * 1024

CALL_TIMEOUT_S = 30.0
SESSION_TIMEOUT_S = 600.0
MAX_CALLS = 200
MAX_AGENT_MESSAGES = 1000
MAX_UPSTREAM_MESSAGES = 2000
MAX_CASSETTE_BYTES = 32 * 1024 * 1024  # below the loader's 64 MiB cap
MAX_HONEY = 32  # equal to twin.generator.MAX_HONEY (pinned by a test)


class ProxyLimits(FrozenModel):
    call_timeout_s: float = Field(default=CALL_TIMEOUT_S, gt=0, le=CALL_TIMEOUT_S)
    session_timeout_s: float = Field(default=SESSION_TIMEOUT_S, gt=0, le=SESSION_TIMEOUT_S)
    max_calls: int = Field(default=MAX_CALLS, ge=1, le=MAX_CALLS)
    max_agent_messages: int = Field(default=MAX_AGENT_MESSAGES, ge=1, le=MAX_AGENT_MESSAGES)
    max_upstream_messages: int = Field(
        default=MAX_UPSTREAM_MESSAGES, ge=1, le=MAX_UPSTREAM_MESSAGES
    )
    max_cassette_bytes: int = Field(default=MAX_CASSETTE_BYTES, ge=1, le=MAX_CASSETTE_BYTES)


class ProxySession(FrozenModel):
    schema_version: Literal[3] = 3
    session_id: str = Field(pattern=SESSION_ID_PATTERN)
    upstream: TwinUpstream
    twin_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    tools: tuple[ToolSpec, ...]
    attack: Attack | None = None
    honey: tuple[HoneyValue, ...] = ()
    cassette_path: Path
    limits: ProxyLimits = Field(default_factory=ProxyLimits)

    @field_validator("cassette_path")
    @classmethod
    def _absolute(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("cassette_path must be absolute")
        return value

    @field_validator("honey")
    @classmethod
    def _honey_ok(cls, value: tuple[HoneyValue, ...]) -> tuple[HoneyValue, ...]:
        """At most MAX_HONEY (the R1 bound is stated for H <= 32, ADR-004), unique ids and
        values, and every value T4-clean (no 12-digit run, no NINO shape)."""
        if len(value) > MAX_HONEY:
            raise ValueError(f"at most {MAX_HONEY} honey values per session")
        if len({h.id for h in value}) != len(value):
            raise ValueError("duplicate honey id")
        if len({h.value for h in value}) != len(value):
            raise ValueError("duplicate honey value")
        for h in value:
            if t4_violations(h.value):
                raise ValueError(f"honey {h.id} breaks a T4 rule")
        return value

    @model_validator(mode="after")
    def _policy_builds(self) -> ProxySession:
        build_policy(self.tools)  # duplicate names -> validation error at load
        return self

    @property
    def policy(self) -> dict[str, ToolPolicy]:
        """Computed by the proxy from ``tools`` (never read from the session file)."""
        return build_policy(self.tools)


class SessionFileError(ValueError):
    pass


def load_session(path: Path) -> ProxySession:
    """Read and validate a session file. The cassette must not exist yet (no overwrite)."""
    size = path.stat().st_size
    if size > MAX_SESSION_FILE:
        raise SessionFileError(f"session file larger than {MAX_SESSION_FILE} bytes")
    session = ProxySession.model_validate_json(path.read_bytes())
    if session.cassette_path.exists():
        raise SessionFileError("cassette_path already exists; refusing to overwrite")
    return session
