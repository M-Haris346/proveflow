"""``ProxySession``: everything one proxy run needs, validated (schema_version 1).

Limits are configurable DOWNWARD only: the D5 values (per call 30 s, session 600 s, 200
tool calls) are both the defaults and the ceilings, so a session file can tighten them
(tests use tiny values) but never loosen them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator

from proveflow.core._base import FrozenModel
from proveflow.core.attacks import Attack
from proveflow.proxy.policy import ToolPolicy, TwinUpstream

SESSION_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$"
MAX_SESSION_FILE = 1024 * 1024

CALL_TIMEOUT_S = 30.0
SESSION_TIMEOUT_S = 600.0
MAX_CALLS = 200


class ProxyLimits(FrozenModel):
    call_timeout_s: float = Field(default=CALL_TIMEOUT_S, gt=0, le=CALL_TIMEOUT_S)
    session_timeout_s: float = Field(default=SESSION_TIMEOUT_S, gt=0, le=SESSION_TIMEOUT_S)
    max_calls: int = Field(default=MAX_CALLS, ge=1, le=MAX_CALLS)


class ProxySession(FrozenModel):
    schema_version: Literal[1] = 1
    session_id: str = Field(pattern=SESSION_ID_PATTERN)
    upstream: TwinUpstream
    policy: dict[str, ToolPolicy]
    attack: Attack | None = None
    cassette_path: Path
    limits: ProxyLimits = Field(default_factory=ProxyLimits)

    @field_validator("cassette_path")
    @classmethod
    def _absolute(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("cassette_path must be absolute")
        return value


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
