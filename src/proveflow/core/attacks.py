"""Payloads, carriers, goals, and instantiated attacks."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from proveflow.core._base import FrozenModel

CANARY_PATTERN = r"^cnry_[0-9a-f]{12}$"
# The per-trial ACTION TARGET (R2, Phase 3b): minted by proveflow like the canary (oracle.
# canary.new_action_target), never an attacker phrasing. The payload asks the agent to call
# the goal's sink tool with it, so R2 is needle-based and independent of R1.
# 16 hex, the honey length: scanned on the same strings as the canary with the same 10
# encodings, so it must not be the canary's size (it would double the dominant bound term).
ACTION_TARGET_PATTERN = r"^act_[0-9a-f]{16}$"
# The per-trial MARKER (R3, Phase 3b): minted like the canary (oracle.canary.new_marker). The
# payload carries it SEPARATOR-SPLIT (oracle.canary.spaced_marker) with an instruction to output
# it with the separators removed, so quoting the payload cannot produce it, only following the
# instruction can (docs/ORACLE.md, R3).
MARKER_PATTERN = r"^mrk_[0-9a-f]{12}$"


class Carrier(StrEnum):
    """How a payload is embedded into a source tool's result."""

    PLAIN = "plain"
    HTML_COMMENT = "html_comment"
    MARKDOWN = "markdown"
    JSON_STRING = "json_string"
    CODE_COMMENT = "code_comment"


class Payload(FrozenModel):
    """Normalized corpus record; provenance and license always carried along."""

    id: str
    text: str
    source_dataset: str
    source_id: str
    license: str
    attack_family: str
    language: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ExfilGoal(FrozenModel):
    """Attacker wants honey/canary data to reach a sink tool's arguments."""

    kind: Literal["exfil"] = "exfil"
    sink_tool: str


class ActionGoal(FrozenModel):
    """Attacker wants a specific sink tool call with attacker-chosen arguments.

    The attacker-chosen value is the attacker's TARGET (an address, a repo, an account), not
    the victim's secret. The corpus-side spec names the sink tool and ONE top-level argument
    (``arg``, no nested path); the per-trial value is ``Attack.action_target`` (R2)."""

    kind: Literal["action"] = "action"
    sink_tool: str
    arg: str = Field(min_length=1)


class HijackGoal(FrozenModel):
    """Attacker wants a marker to appear in the agent's final answer. The corpus-side spec
    carries no marker: the per-trial value is ``Attack.marker`` (R3)."""

    kind: Literal["hijack"] = "hijack"


Goal = Annotated[ExfilGoal | ActionGoal | HijackGoal, Field(discriminator="kind")]


class Attack(FrozenModel):
    """Payload x carrier x goal, instantiated with a per-trial canary, plus the per-trial
    action target for an ActionGoal and the per-trial marker for a HijackGoal (each present
    iff its goal is the attack's goal)."""

    payload: Payload
    carrier: Carrier
    goal: Goal
    canary: str = Field(pattern=CANARY_PATTERN)
    action_target: str | None = Field(default=None, pattern=ACTION_TARGET_PATTERN)
    marker: str | None = Field(default=None, pattern=MARKER_PATTERN)

    @model_validator(mode="after")
    def _per_trial_values_match_the_goal(self) -> Attack:
        if isinstance(self.goal, ActionGoal) != (self.action_target is not None):
            raise ValueError("action_target is present iff the goal is an ActionGoal")
        if isinstance(self.goal, HijackGoal) != (self.marker is not None):
            raise ValueError("marker is present iff the goal is a HijackGoal")
        return self

    def answer_only_values(self) -> dict[str, str]:
        """Per-trial values the model may produce ONLY in its final answer (R3): the marker.
        It may be read nowhere in raw form, neither in runner-authored text nor in a tool
        result (F9, ``runner.validity``); the payload carries it separator-split."""
        return {"marker": self.marker} if self.marker is not None else {}

    def tool_result_values(self) -> dict[str, str]:
        """The per-trial values that may reach the model ONLY inside a tool result (F9): the
        canary and, for an ActionGoal, the action target. ONE list, read by the scenario
        validator and by ``runner.validity``."""
        out = {"canary": self.canary}
        if self.action_target is not None:
            out["action_target"] = self.action_target
        return out
