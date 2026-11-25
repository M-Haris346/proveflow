"""Mitigation catalog entries (M1-M6). Rendered as patches, never auto-applied.

Phase 8 builds TWO kinds, M1 and M3, each with a patch renderer (``proveflow.fix``) and a TWIN
policy with the same semantics as its patch (``runner.mitigation``), so paired verify measures
the catalog entry the patch describes. Every other kind is OUT of Phase 8, with its reason in
``OUT_OF_PHASE``: ``fix`` and ``verify`` refuse it with that reason, never a stub.
"""

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


class TwinPolicy(StrEnum):
    """How a mitigation is applied in the twin (runner side; the proxy is unchanged)."""

    HIDE_SERVER = "hide_server"  # M1: every tool of the server is hidden; a call is never sent
    DENY_TOOL = "deny_tool"  # M3: the tool stays visible; every call is denied, never sent


TWIN_POLICY: dict[MitigationKind, TwinPolicy] = {
    MitigationKind.M1_REMOVE_SINK: TwinPolicy.HIDE_SERVER,
    MitigationKind.M3_HUMAN_APPROVAL: TwinPolicy.DENY_TOOL,
}

OUT_OF_PHASE: dict[MitigationKind, str] = {
    MitigationKind.M2_SPLIT_PROFILES: (
        "M2 is not built in Phase 8: the single-agent twin harness runs the task in ONE "
        "profile, so its twin effect equals M1's; a distinct verify needs a two-profile harness"
    ),
    MitigationKind.M4_TAINT_GATE: "M4 is v1 (docs/ARCHITECTURE.md section 6), not Phase 8",
    MitigationKind.M5_SPOTLIGHTING: (
        "M5 is not built in Phase 8: the control is a scripted client that never reads the "
        "prompt, so its verify would measure the script"
    ),
    MitigationKind.M6_TOOL_FILTER: (
        "M6 is not built in Phase 8: no client documentation cited in docs/CLIENT_CONFIGS.md "
        "gives a per-task tool-filter syntax, so its patch cannot be written from cited docs"
    ),
}


class Mitigation(FrozenModel):
    """One candidate fix for a flow, written as a reviewable patch."""

    id: str
    kind: MitigationKind
    flow_id: str
    title: str
    rationale: str
    expected_tradeoff: str


class TwinMitigation(FrozenModel):
    """A mitigation as the twin applies it: the kind and its target (the sink's server and
    tool). Its policy is fixed by the kind (``TWIN_POLICY``), never chosen separately."""

    kind: MitigationKind
    server: str
    tool: str

    @property
    def policy(self) -> TwinPolicy:
        try:
            return TWIN_POLICY[self.kind]
        except KeyError:
            raise ValueError(OUT_OF_PHASE[self.kind]) from None
