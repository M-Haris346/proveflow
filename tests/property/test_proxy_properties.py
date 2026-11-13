"""Property tests for carriers (C3/C4) and the upstream gate.

C3 (1) every carrier: a canary inside the payload is in the output verbatim, and
       count(output) == count(input text) + 1.
C3 (2) non-JSON carriers: output.startswith(original text).
C3 (3) JSON_STRING on a JSON object/array: the output is valid JSON and the injected value
       equals the payload exactly (ensure_ascii=False). C4: scalars and non-JSON text use
       the PLAIN fallback (covered by (1) and unit tests), not (3).
Gate: tools/call never passes for any name that is not forward=True.
"""

from __future__ import annotations

import json

import mcp_types
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from proveflow.core.attacks import Carrier
from proveflow.proxy.carriers import NOTE_KEY, apply_carrier
from proveflow.proxy.gate import GateBlocked, UpstreamGate
from proveflow.proxy.policy import ToolPolicy
from proxychecks import (
    ANY_TEXT,
    JSON_ARRAY_TEXT,
    JSON_OBJECT_TEXT,
    assert_canary_once_more,
    payloads,
)

NON_JSON = [c for c in Carrier if c is not Carrier.JSON_STRING]


@pytest.mark.parametrize("carrier", list(Carrier))
@settings(max_examples=150, deadline=None)
@given(text=ANY_TEXT, pc=payloads())
def test_canary_appears_exactly_once_more(carrier: Carrier, text: str, pc: tuple[str, str]) -> None:
    payload, canary = pc
    assert_canary_once_more(carrier, text, payload, canary)


@pytest.mark.parametrize("carrier", NON_JSON)
@settings(max_examples=150, deadline=None)
@given(text=ANY_TEXT, pc=payloads())
def test_non_json_carriers_keep_original_prefix(
    carrier: Carrier, text: str, pc: tuple[str, str]
) -> None:
    assert apply_carrier(carrier, text, pc[0]).startswith(text)


@settings(max_examples=200, deadline=None)
@given(text=JSON_OBJECT_TEXT, pc=payloads())
def test_json_string_object_injected_value_is_exact(text: str, pc: tuple[str, str]) -> None:
    payload, _ = pc
    original = json.loads(text)
    out = json.loads(apply_carrier(Carrier.JSON_STRING, text, payload))
    added = [k for k in out if k not in original]
    assert len(added) == 1 and added[0].startswith(NOTE_KEY)
    assert out[added[0]] == payload
    assert {k: v for k, v in out.items() if k != added[0]} == original


@settings(max_examples=200, deadline=None)
@given(text=JSON_ARRAY_TEXT, pc=payloads())
def test_json_string_array_injected_value_is_exact(text: str, pc: tuple[str, str]) -> None:
    payload, _ = pc
    out = json.loads(apply_carrier(Carrier.JSON_STRING, text, payload))
    assert out[:-1] == json.loads(text)
    assert out[-1] == payload


NAMES = st.text(max_size=12)


@settings(max_examples=300, deadline=None)
@given(
    policy=st.dictionaries(
        NAMES, st.builds(ToolPolicy, forward=st.booleans(), inject=st.booleans()), max_size=8
    ),
    name=NAMES,
    advertised=st.none() | st.frozensets(NAMES, max_size=8),
)
def test_gate_never_passes_tools_call_unless_forward(
    policy: dict[str, ToolPolicy], name: str, advertised: frozenset[str] | None
) -> None:
    gate = UpstreamGate(policy)
    if advertised is not None:
        gate.set_advertised(advertised)
    msg = mcp_types.JSONRPCRequest(
        jsonrpc="2.0", id=1, method="tools/call", params={"name": name, "arguments": {}}
    )
    entry = policy.get(name)
    if entry is not None and entry.forward and advertised is not None and name in advertised:
        gate.check(msg)
    else:
        with pytest.raises(GateBlocked):
            gate.check(msg)
