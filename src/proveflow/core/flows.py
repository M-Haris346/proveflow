"""Toxic flows: ordered tool paths that an attacker could chain."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from proveflow.core._base import FrozenModel
from proveflow.core.tools import Granularity, SinkSeverity


class FlowClass(StrEnum):
    EXFIL = "exfil"  # untrusted source + private data + sink
    ACTION = "action"  # untrusted source + sink
    LEAK = "leak"  # private data + sink, no source (informational)


class FlowVerdictKind(StrEnum):
    CONFIRMED = "CONFIRMED"
    NOT_REPRODUCED = "NOT_REPRODUCED"  # absence of reproduction is NOT safety
    THEORETICAL = "THEORETICAL"


class ToolRef(FrozenModel):
    """A tool on a server inside one agent profile. ``tool is None``: server-level."""

    server: str
    tool: str | None = None

    @property
    def label(self) -> str:
        return f"{self.server}/{self.tool if self.tool is not None else '*'}"


class Flow(FrozenModel):
    """Ordered path source → (private) → sink inside one agent profile."""

    id: str
    profile: str
    flow_class: FlowClass
    source: ToolRef | None = None
    private: ToolRef | None = None
    sink: ToolRef
    cross_server: bool
    sink_severity: SinkSeverity
    confidence: float = Field(ge=0.0, le=1.0)
    granularity: Granularity
    verdict: FlowVerdictKind = FlowVerdictKind.THEORETICAL

    @model_validator(mode="after")
    def _check_shape(self) -> Flow:
        if self.flow_class is FlowClass.EXFIL and not (self.source and self.private):
            msg = "exfil flow requires source and private"
            raise ValueError(msg)
        if self.flow_class is FlowClass.ACTION and (not self.source or self.private):
            msg = "action flow requires source and no private"
            raise ValueError(msg)
        if self.flow_class is FlowClass.LEAK and (self.source is not None or not self.private):
            msg = "leak flow requires private and no source"
            raise ValueError(msg)
        return self
