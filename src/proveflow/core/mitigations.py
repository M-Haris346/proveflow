"""Mitigation catalog entries (M1-M6). Rendered as patches, never auto-applied."""

from __future__ import annotations

from enum import StrEnum

from proveflow.core._base import FrozenModel


class MitigationKind(StrEnum):
    M1_REMOVE_SINK = "m1_remove_sink"
    M2_SPLIT_PROFILES = "m2_split_profiles"
    M3_HUMAN_APPROVAL = "m3_human_approval"
    M4_TAINT_GATE = "m4_taint_gate"
    M5_SPOTLIGHTING = "m5_spotlighting"
    M6_TOOL_FILTER = "m6_tool_filter"


class Mitigation(FrozenModel):
    """One candidate fix for a flow, written as a reviewable patch."""

    id: str
    kind: MitigationKind
    flow_id: str
    title: str
    rationale: str
    expected_tradeoff: str
