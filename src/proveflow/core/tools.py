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


class RoleEvidence(FrozenModel):
    """Why a tool was assigned a role; provenance is always recorded."""

    role: ToolRole
    source: RoleSource
    reason: str
    weight: float = Field(ge=0.0, le=1.0)


class ToolSpec(FrozenModel):
    """One tool exposed by a server, with its classified roles."""

    name: str
    server: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    roles: tuple[RoleEvidence, ...] = ()
