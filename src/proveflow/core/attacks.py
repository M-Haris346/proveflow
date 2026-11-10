"""Payloads, carriers, goals, and instantiated attacks."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field

from proveflow.core._base import FrozenModel

CANARY_PATTERN = r"^cnry_[0-9a-f]{12}$"


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
    """Attacker wants a specific sink tool call with attacker-chosen arguments."""

    kind: Literal["action"] = "action"
    sink_tool: str
    arg_predicate: str


class HijackGoal(FrozenModel):
    """Attacker wants a marker to appear in the agent's final answer."""

    kind: Literal["hijack"] = "hijack"
    marker: str


Goal = Annotated[ExfilGoal | ActionGoal | HijackGoal, Field(discriminator="kind")]


class Attack(FrozenModel):
    """Payload x carrier x goal, instantiated with a per-trial canary."""

    payload: Payload
    carrier: Carrier
    goal: Goal
    canary: str = Field(pattern=CANARY_PATTERN)
