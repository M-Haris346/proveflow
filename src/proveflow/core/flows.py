"""Toxic flows: ordered tool paths that an attacker could chain, and flow groups."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from enum import StrEnum
from typing import Any

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


# --- flow groups (ARCHITECTURE §5.3 "Flow grouping") ----------------------------------------

GroupKey = tuple[FlowClass, str | None, str | None, str]


def group_key(flow: Flow) -> GroupKey:
    """(class, source server, private server, sink server). The profile is NOT in the key."""
    return (
        flow.flow_class,
        flow.source.server if flow.source else None,
        flow.private.server if flow.private else None,
        flow.sink.server,
    )


def group_id(key: GroupKey) -> str:
    """'G-' + sha256 of the JSON array [class, src, prv, snk] (None -> null). JSON, not a
    '|'-join, so server names containing '|' cannot make two keys hash the same input."""
    cls, src, prv, snk = key
    data = json.dumps([cls.value, src, prv, snk], ensure_ascii=False)
    return "G-" + hashlib.sha256(data.encode("utf-8")).hexdigest()[:8]


def group_attributes(members: Sequence[Flow]) -> dict[str, Any]:
    """Group fields that are derived from its member flows (used to build AND to validate)."""
    return {
        "cross_server": any(f.cross_server for f in members),
        "worst_sink_severity": min((f.sink_severity for f in members), key=lambda s: s.rank),
        "max_confidence": max(f.confidence for f in members),
        "profiles": tuple(sorted({f.profile for f in members})),
        "granularities": tuple(sorted({f.granularity for f in members})),
    }


class FlowGroup(FrozenModel):
    """Flows with the same (class, source server, private server, sink server), across
    profiles. Grouping reduces table rows, not the number of tool paths: every member flow
    stays in the report and per-path triage is Prove (Phase 7)."""

    id: str
    flow_class: FlowClass
    source_server: str | None = None
    private_server: str | None = None
    sink_server: str
    cross_server: bool
    worst_sink_severity: SinkSeverity
    max_confidence: float = Field(ge=0.0, le=1.0)
    profiles: tuple[str, ...]
    member_ids: tuple[str, ...]
    granularities: tuple[Granularity, ...]

    @property
    def key(self) -> GroupKey:
        return (self.flow_class, self.source_server, self.private_server, self.sink_server)

    @model_validator(mode="after")
    def _check_shape(self) -> FlowGroup:
        cls, src, prv = self.flow_class, self.source_server, self.private_server
        if cls is FlowClass.EXFIL and (src is None or prv is None):
            raise ValueError("exfil group requires source and private servers")
        if cls is FlowClass.ACTION and (src is None or prv is not None):
            raise ValueError("action group requires a source server and no private server")
        if cls is FlowClass.LEAK and (src is not None or prv is None):
            raise ValueError("leak group requires a private server and no source server")
        if not self.member_ids or len(set(self.member_ids)) != len(self.member_ids):
            raise ValueError("group member ids must be non-empty and unique")
        for name in ("profiles", "granularities"):
            values = getattr(self, name)
            if list(values) != sorted(set(values)):
                raise ValueError(f"group {name} must be sorted and unique")
        return self
