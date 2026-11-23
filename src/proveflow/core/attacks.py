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
# 16 hex, the honey length (justified since Phase 6 by the forwarded-call sighting bound,
# ADR-004). Since Phase 6 it reaches the model only SEPARATOR-SPLIT, like the marker
# (``split_form``, docs/ORACLE.md R2).
ACTION_TARGET_PATTERN = r"^act_[0-9a-f]{16}$"
# The per-trial MARKER (R3, Phase 3b): minted like the canary (oracle.canary.new_marker). The
# payload carries it SEPARATOR-SPLIT (oracle.canary.spaced_marker) with an instruction to output
# it with the separators removed, so quoting the payload cannot produce it, only following the
# instruction can (docs/ORACLE.md, R3).
MARKER_PATTERN = r"^mrk_[0-9a-f]{12}$"
# Between the verbatim corpus payload and the goal clause in the injected text (Phase 6, D1):
# exactly two newlines. Fixed so the injected text can be rebuilt from the cassette alone.
GOAL_CLAUSE_SEPARATOR = chr(10) * 2
SPLIT_GROUP = 4  # hex digits per group in the separator-split form


def split_form(value: str) -> str:
    """The SEPARATOR-SPLIT form in which a split value (the marker, the action target) reaches
    the model: its prefix (through the first ``_``), then its hex in groups of four, each
    separated by ONE space (``mrk_ a1b2 c3d4 e5f6``, ``act_ 5e0c 9b2a 7d14 f3a8``). A verbatim
    quotation of this form never contains the value as a substring, in any case."""
    prefix, sep, digits = value.partition("_")
    if not sep or not digits:
        raise ValueError("not a prefixed per-trial value")
    groups = [digits[i : i + SPLIT_GROUP] for i in range(0, len(digits), SPLIT_GROUP)]
    return " ".join([prefix + sep, *groups])


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
    # Phase 6 (D1): the proveflow-authored GOAL CLAUSE that carries the per-trial value to the
    # model, composed where the attack is CONSTRUCTED (proveflow.corpus.instantiate), never by
    # the proxy. The corpus payload's text is NEVER edited: its sha256 pins what is sent, and
    # the clause is recorded beside it. None: the payload alone is injected (authored fixtures).
    goal_clause: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _per_trial_values_match_the_goal(self) -> Attack:
        if isinstance(self.goal, ActionGoal) != (self.action_target is not None):
            raise ValueError("action_target is present iff the goal is an ActionGoal")
        if isinstance(self.goal, HijackGoal) != (self.marker is not None):
            raise ValueError("marker is present iff the goal is a HijackGoal")
        if self.goal_clause is not None:
            self._check_goal_clause(self.goal_clause)
        for label, value in self.split_values().items():
            if value.casefold() in self.payload.text.casefold():
                name = label.replace("_", " ")
                raise ValueError(f"the {name} is readable in the payload text (it must be split)")
        return self

    def _check_goal_clause(self, clause: str) -> None:
        """The clause must carry the goal's per-trial value: the canary as-is for an exfil
        goal; for an action or hijack goal, the action target or marker in its SPLIT form
        (``split_form``), and NEVER in a form R2/R3 match (raw or any case)."""
        if isinstance(self.goal, ExfilGoal) and self.canary not in clause:
            raise ValueError("an exfil goal clause must carry the canary")
        kind = {ActionGoal: "an action", HijackGoal: "a hijack"}.get(type(self.goal), "a")
        for label, value in self.split_values().items():
            name = label.replace("_", " ")
            if value.casefold() in clause.casefold():
                raise ValueError(f"{kind} goal clause must carry the {name} split, never readable")
            if split_form(value) not in clause:
                raise ValueError(f"{kind} goal clause must carry the {name} split")

    def injected_text(self) -> str:
        """EXACTLY the text the proxy hands to the carrier (proxy/server.py ``_forward``):
        ``payload.text``, then ``GOAL_CLAUSE_SEPARATOR``, then ``goal_clause``; the payload
        alone when there is no clause. Specified so that a reader can rebuild the injected
        text from the cassette's ``session_start.attack`` alone."""
        if self.goal_clause is None:
            return self.payload.text
        return self.payload.text + GOAL_CLAUSE_SEPARATOR + self.goal_clause

    def split_values(self) -> dict[str, str]:
        """The per-trial values the model may read ONLY SEPARATOR-SPLIT (``split_form``) and
        must REJOIN to produce: the marker (R3) and, since Phase 6, the action target (R2).
        Neither may be readable (raw or in any case, ``oracle.matcher.SPLIT_VALUE_ENCODINGS``)
        anywhere the model reads: not in runner-authored text, not in a tool result, not in
        the payload or the clause (F9, ``runner.validity``; the scenario and Attack
        validators). ONE list, so a rule's needle and its guard cannot drift apart."""
        out: dict[str, str] = {}
        if self.action_target is not None:
            out["action_target"] = self.action_target
        if self.marker is not None:
            out["marker"] = self.marker
        return out

    def tool_result_values(self) -> dict[str, str]:
        """The per-trial values that may reach the model ONLY inside a tool result (F9): the
        canary. (The action target left this list in Phase 6: it is a split value now, and
        its raw form first appears in the MODEL's own tool call, never in a tool result.)
        ONE list, read by the scenario validator and by ``runner.validity``."""
        return {"canary": self.canary}

    def tool_result_texts(self) -> dict[str, str]:
        """The attack TEXTS that may reach the model ONLY inside a tool result (F9): the
        corpus payload and, since Phase 6 (D2), the goal clause. ONE list, read by the
        scenario validator and by ``runner.validity``: a runner-authored copy of either would
        put the attack where no proxy injected it."""
        out = {"payload": self.payload.text}
        if self.goal_clause is not None:
            out["goal_clause"] = self.goal_clause
        return out
