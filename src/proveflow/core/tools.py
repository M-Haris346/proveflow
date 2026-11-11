"""Tool specs and role classification evidence."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field

from proveflow.core._base import FrozenModel


class ToolRole(StrEnum):
    UNTRUSTED_SOURCE = "untrusted_source"
    PRIVATE_DATA = "private_data"
    SINK = "sink"


class RoleSource(StrEnum):
    HEURISTIC = "heuristic"
    OVERRIDE = "override"
    LLM_CONFIRMED = "llm_confirmed"


class Granularity(StrEnum):
    """``server``: inferred from server name/command only (tools unknown) — low confidence."""

    TOOL = "tool"
    SERVER = "server"


class SinkSeverity(StrEnum):
    """Ordered worst-first (ARCHITECTURE §5.3: external network > write > local)."""

    NETWORK_EGRESS = "network_egress"
    REMOTE_WRITE = "remote_write"
    LOCAL_WRITE = "local_write"

    @property
    def rank(self) -> int:
        return _SEVERITY_RANK[self]


_SEVERITY_RANK = {
    SinkSeverity.NETWORK_EGRESS: 0,
    SinkSeverity.REMOTE_WRITE: 1,
    SinkSeverity.LOCAL_WRITE: 2,
}


class RoleEvidence(FrozenModel):
    """Why a tool was assigned a role; provenance is always recorded."""

    role: ToolRole
    source: RoleSource
    reason: str
    weight: float = Field(ge=0.0, le=1.0)
    granularity: Granularity = Granularity.TOOL
    sink_severity: SinkSeverity | None = None


class ToolSpec(FrozenModel):
    """One tool exposed by a server, with its classified roles.

    ``name == "*"`` with server-granularity evidence stands for "all tools of this
    server" when tools are unknown (``scan --no-launch``).
    """

    name: str
    server: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    roles: tuple[RoleEvidence, ...] = ()
