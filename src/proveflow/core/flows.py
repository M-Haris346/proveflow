"""Toxic flows: ordered tool paths that an attacker could chain."""

from __future__ import annotations

from enum import StrEnum

from pydantic import model_validator

from proveflow.core._base import FrozenModel


class FlowClass(StrEnum):
    EXFIL = "exfil"  # untrusted source + private data + sink
    ACTION = "action"  # untrusted source + sink
    LEAK = "leak"  # private data + sink, no source (informational)


class FlowVerdictKind(StrEnum):
    CONFIRMED = "CONFIRMED"
    NOT_REPRODUCED = "NOT_REPRODUCED"  # absence of reproduction is NOT safety
    THEORETICAL = "THEORETICAL"


class Flow(FrozenModel):
    """Ordered path source → (private) → sink, possibly across servers."""

    id: str
    flow_class: FlowClass
    source_tool: str | None = None
    private_tool: str | None = None
    sink_tool: str
    cross_server: bool

    @model_validator(mode="after")
    def _check_shape(self) -> Flow:
        if self.flow_class is FlowClass.EXFIL and not (self.source_tool and self.private_tool):
            msg = "exfil flow requires source_tool and private_tool"
            raise ValueError(msg)
        if self.flow_class is FlowClass.ACTION and not self.source_tool:
            msg = "action flow requires source_tool"
            raise ValueError(msg)
        if self.flow_class is FlowClass.LEAK and self.source_tool is not None:
            msg = "leak flow must not have a source_tool"
            raise ValueError(msg)
        return self
