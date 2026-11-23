"""A scenario: what one trial runs (Phase 5). Hand-written; there is no campaign engine yet.

* ``servers``: each twin's stored tool list and seed; one proxy per server.
* ``attack`` + ``attack_server``: the attack is armed in that ONE server's session only
  (the untrusted source), so no second proxy injects; the oracle still sees the canary in
  every cassette through the trial's union of needles (oracle.evaluate_trial).
* ``system_prompt`` + ``task``: the only text the runner authors (F9). The attack payload
  and the canary are refused in either: the injection must arrive only through a tool
  result, or every trial would be trivially "compromised".
* ``utility``: the name and parameters of a deterministic predicate (runner.utility, D5).
"""

from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from proveflow.core._base import FrozenModel
from proveflow.core.attacks import Attack
from proveflow.core.tools import ToolSpec

ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$"


class ScenarioServer(FrozenModel):
    name: str = Field(pattern=ID_PATTERN)
    tools: tuple[ToolSpec, ...] = Field(min_length=1)
    seed: str = Field(min_length=1, max_length=64)


class UtilitySpec(FrozenModel):
    predicate: str
    params: dict[str, Any] = Field(default_factory=dict)


class Scenario(FrozenModel):
    id: str = Field(pattern=ID_PATTERN)
    flow_id: str
    system_prompt: str = Field(min_length=1)
    task: str = Field(min_length=1)
    servers: tuple[ScenarioServer, ...] = Field(min_length=1)
    attack: Attack | None = None
    attack_server: str | None = None
    utility: UtilitySpec

    @model_validator(mode="after")
    def _consistent(self) -> Scenario:
        names = [s.name for s in self.servers]
        if len(set(names)) != len(names):
            raise ValueError("duplicate server name")
        if (self.attack is None) != (self.attack_server is None):
            raise ValueError("attack and attack_server go together")
        if self.attack_server is not None and self.attack_server not in names:
            raise ValueError("attack_server is not one of the scenario's servers")
        if self.attack is not None:
            authored = self.system_prompt + "\n" + self.task
            from proveflow.oracle.matcher import split_value_encodings_found

            for label, value in self.attack.split_values().items():
                for where, text in (("runner-authored message", authored),
                                    ("payload", self.attack.payload.text)):  # fmt: skip
                    if split_value_encodings_found(text, value):
                        raise ValueError(
                            f"the attack {label} is readable in the {where} (R2/R3, F9): it "
                            "must reach the model only separator-split"
                        )
            values = {**self.attack.tool_result_texts(), **self.attack.tool_result_values()}
            for label, needle in values.items():
                if needle in authored:
                    raise ValueError(
                        f"the attack {label} appears in a runner-authored message (F9): it "
                        "must arrive only through a tool result"
                    )
        return self
