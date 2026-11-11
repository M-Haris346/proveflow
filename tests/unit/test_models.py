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
    Granularity,
    RoleEvidence,
    SinkSeverity,
    ToolRef,
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


FLOW_COMMON = {
    "id": "F",
    "profile": "p",
    "cross_server": True,
    "sink_severity": SinkSeverity.NETWORK_EGRESS,
    "confidence": 0.5,
    "granularity": Granularity.TOOL,
    "sink": ToolRef(server="b", tool="send"),
}


def test_exfil_flow_requires_source_and_private() -> None:
    with pytest.raises(ValidationError):
        Flow(flow_class=FlowClass.EXFIL, **FLOW_COMMON)  # type: ignore[arg-type]


def test_action_flow_rejects_private() -> None:
    with pytest.raises(ValidationError):
        Flow(
            flow_class=FlowClass.ACTION,
            source=ToolRef(server="a", tool="fetch"),
            private=ToolRef(server="a", tool="db"),
            **FLOW_COMMON,  # type: ignore[arg-type]
        )


def test_leak_flow_rejects_source() -> None:
    with pytest.raises(ValidationError):
        Flow(
            flow_class=FlowClass.LEAK,
            source=ToolRef(server="a", tool="fetch"),
            private=ToolRef(server="a", tool="db"),
            **FLOW_COMMON,  # type: ignore[arg-type]
        )


def test_confidence_bounds() -> None:
    with pytest.raises(ValidationError):
        Flow(
            flow_class=FlowClass.LEAK,
            private=ToolRef(server="a", tool="db"),
            **{**FLOW_COMMON, "confidence": 1.5},  # type: ignore[arg-type]
        )


def test_tool_ref_label() -> None:
    assert ToolRef(server="gh").label == "gh/*"
    assert ToolRef(server="gh", tool="x").label == "gh/x"


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
