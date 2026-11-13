"""Mutation tests for the proxy: break one thing -> the NAMED check for it must fail.

(a) handler forwards everything      -> assert_sink_call_sandboxed fails
(b) gate disabled                    -> assert_gate_blocks_on_write_path fails
(c) handler AND gate broken          -> assert_twin_never_sees_denied_calls fails
    (and with only ONE layer broken the safety check still passes: layers are independent)
(d) JSON_STRING fallback broken      -> the C3 canary property fails
(e) each carrier dropping its payload -> the C3 canary property fails for that carrier
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings

from proveflow.core.attacks import Carrier
from proveflow.proxy import carriers, server
from proveflow.proxy.gate import UpstreamGate
from proveflow.proxy.policy import Decision
from proxychecks import (
    ANY_TEXT,
    assert_canary_once_more,
    assert_gate_blocks_on_write_path,
    assert_sink_call_sandboxed,
    assert_twin_never_sees_denied_calls,
    payloads,
)


def _forward_everything(*_args: Any, **_kwargs: Any) -> tuple[Decision, None]:
    return Decision.FORWARD, None


def _gate_off(self: UpstreamGate, message: object) -> None:
    return None


def _break_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "decide", _forward_everything)


def _dirs(tmp_path: Path) -> tuple[Path, Path]:
    ok, mut = tmp_path / "ok", tmp_path / "mut"
    ok.mkdir()
    mut.mkdir()
    return ok, mut


def _break_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(UpstreamGate, "check", _gate_off)


# (a) ----------------------------------------------------------------------------------


def test_a_handler_forwarding_everything_fails_named_handler_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ok, mut = _dirs(tmp_path)
    assert_sink_call_sandboxed(ok)
    _break_handler(monkeypatch)
    with pytest.raises(AssertionError, match="sink call was not sandboxed"):
        assert_sink_call_sandboxed(mut)


# (b) ----------------------------------------------------------------------------------


def test_b_gate_disabled_fails_named_gate_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ok, mut = _dirs(tmp_path)
    assert_gate_blocks_on_write_path(ok)
    _break_gate(monkeypatch)
    with pytest.raises(AssertionError, match="tools/call reached the twin"):
        assert_gate_blocks_on_write_path(mut)


# (c) ----------------------------------------------------------------------------------


def test_c_both_layers_broken_fails_safety_log_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ok, mut = _dirs(tmp_path)
    assert_twin_never_sees_denied_calls(ok)
    _break_handler(monkeypatch)
    _break_gate(monkeypatch)
    with pytest.raises(AssertionError, match="denied tools/call reached the twin"):
        assert_twin_never_sees_denied_calls(mut)


def test_handler_broken_alone_is_still_caught_by_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _break_handler(monkeypatch)
    assert_twin_never_sees_denied_calls(tmp_path)


def test_gate_broken_alone_is_still_caught_by_handler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _break_gate(monkeypatch)
    assert_twin_never_sees_denied_calls(tmp_path)


# (d) + (e) --------------------------------------------------------------------------------


def _run_canary_property(carrier: Carrier) -> None:
    @settings(max_examples=100, deadline=None, database=None)
    @given(text=ANY_TEXT, pc=payloads())
    def prop(text: str, pc: tuple[str, str]) -> None:
        assert_canary_once_more(carrier, text, pc[0], pc[1])

    prop()


def test_d_json_string_fallback_broken_fails_property(monkeypatch: pytest.MonkeyPatch) -> None:
    _run_canary_property(Carrier.JSON_STRING)  # sanity: passes unmutated
    monkeypatch.setattr(carriers, "json_fallback", lambda text, payload: text)
    with pytest.raises(AssertionError, match="canary missing"):
        _run_canary_property(Carrier.JSON_STRING)


@pytest.mark.parametrize("carrier", list(Carrier))
def test_e_carrier_dropping_payload_fails_property(
    carrier: Carrier, monkeypatch: pytest.MonkeyPatch
) -> None:
    _run_canary_property(carrier)
    monkeypatch.setitem(carriers._CARRIERS, carrier, lambda text, payload: text + "\n\n")
    with pytest.raises(AssertionError, match="canary missing"):
        _run_canary_property(carrier)
