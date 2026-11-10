"""Round-trip and validation tests for every core domain model."""

from __future__ import annotations

import pytest
from examples import EXAMPLE_PAYLOAD, EXAMPLES
from pydantic import BaseModel, ValidationError

from proveflow.core import (
    Attack,
    Carrier,
    ExfilGoal,
    Flow,
    FlowClass,
    RoleEvidence,
    Verdict,
)


def example_id(instance: BaseModel) -> str:
    return type(instance).__name__


@pytest.mark.parametrize("instance", EXAMPLES, ids=example_id)
def test_json_round_trip(instance: BaseModel) -> None:
    dumped = instance.model_dump_json()
    restored = type(instance).model_validate_json(dumped)
    assert restored == instance


@pytest.mark.parametrize("instance", EXAMPLES, ids=example_id)
def test_extra_fields_rejected(instance: BaseModel) -> None:
    data = instance.model_dump()
    data["bogus_field"] = 1
    with pytest.raises(ValidationError):
        type(instance).model_validate(data)


@pytest.mark.parametrize("instance", EXAMPLES, ids=example_id)
def test_frozen(instance: BaseModel) -> None:
    field = next(iter(type(instance).model_fields))
    with pytest.raises(ValidationError):
        setattr(instance, field, "overwritten")


def test_invalid_enum_rejected() -> None:
    with pytest.raises(ValidationError):
        RoleEvidence.model_validate(
            {"role": "not_a_role", "source": "heuristic", "reason": "x", "weight": 0.5}
        )


def test_invalid_canary_rejected() -> None:
    payload = EXAMPLE_PAYLOAD.model_dump()
    with pytest.raises(ValidationError):
        Attack.model_validate(
            {
                "payload": payload,
                "carrier": Carrier.PLAIN,
                "goal": ExfilGoal(sink_tool="s").model_dump(),
                "canary": "cnry_NOTHEX",
            }
        )


def test_exfil_flow_requires_source_and_private() -> None:
    with pytest.raises(ValidationError):
        Flow(id="F", flow_class=FlowClass.EXFIL, sink_tool="send", cross_server=True)


def test_leak_flow_rejects_source() -> None:
    with pytest.raises(ValidationError):
        Flow(
            id="F",
            flow_class=FlowClass.LEAK,
            source_tool="fetch",
            private_tool="db",
            sink_tool="send",
            cross_server=False,
        )


def test_negative_tokens_rejected() -> None:
    with pytest.raises(ValidationError):
        Verdict(
            trial_id="T",
            utility=True,
            compromised=False,
            tokens_in=-1,
            tokens_out=0,
            latency_ms=0.0,
        )
