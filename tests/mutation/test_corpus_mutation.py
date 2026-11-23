"""Mutations of payload instantiation and the goal clause (Phase 6, step 1): each weakening
makes a NAMED check fail."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import corpuschecks as cc
from proveflow.core import attacks
from proveflow.core.attacks import Attack
from proveflow.corpus import instantiate as inst
from proxyhelpers import proxy_twin_root  # noqa: F401


def _ok_then(check: Callable[..., None], mp: pytest.MonkeyPatch, patch: Callable[[Any], None],
             message: str, tmp_path: Path | None = None) -> None:  # fmt: skip
    if tmp_path is not None:
        (tmp_path / "ok").mkdir()
        (tmp_path / "mut").mkdir()
    check(*([tmp_path / "ok"] if tmp_path else []))
    patch(mp)
    with pytest.raises(AssertionError, match=message):
        check(*([tmp_path / "mut"] if tmp_path else []))


def _payload_only(self: Attack) -> str:
    """Mutant: the proxy injects the payload alone (the clause is dropped)."""
    return self.payload.text


def test_dropping_the_clause_leaves_r2_dormant(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    proxy_twin_root: Any,  # noqa: F811
) -> None:
    _ok_then(cc.assert_payload_driven_r2_fires, monkeypatch,
             lambda m: m.setattr(Attack, "injected_text", _payload_only),
             "R2 did not fire on a payload-driven trial", tmp_path)  # fmt: skip


def test_dropping_the_clause_leaves_r3_dormant(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    proxy_twin_root: Any,  # noqa: F811
) -> None:
    _ok_then(cc.assert_payload_driven_r3_fires_and_quoting_does_not, monkeypatch,
             lambda m: m.setattr(Attack, "injected_text", _payload_only),
             "R3 on a payload-driven rejoin", tmp_path)  # fmt: skip


def test_a_changed_separator_fails_the_reconstruction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    proxy_twin_root: Any,  # noqa: F811
) -> None:
    _ok_then(cc.assert_injected_text_rebuilds_from_the_cassette, monkeypatch,
             lambda m: m.setattr(attacks, "GOAL_CLAUSE_SEPARATOR", " "),
             "cannot be rebuilt from the cassette", tmp_path)  # fmt: skip


# Two INDEPENDENT layers keep the marker from being readable, and neither subsumes the other
# (the same shape as Phase 3b's two layers keeping the action target out of R1):
#   COMPOSITION: goal_clause() shows the marker split (spaced_marker); pinned by
#     assert_goal_clause_carries_each_goals_value;
#   VALIDATION: the Attack validator refuses a readable marker in the clause or the payload,
#     for ANY Attack, including ones not built by instantiate(); pinned by
#     assert_attack_refuses_a_readable_split_value.
# One mutation per layer, plus the one that shows the layering. Since Phase 6 the action
# target has the same two layers (spaced_action_target; the same validator), and its own
# composition and layering mutations below.

_REAL_SPACED = inst.spaced_marker


def _readable_too(marker: str) -> str:
    """Composition mutant: the clause shows the split form AND the raw marker."""
    return f"{_REAL_SPACED(marker)} ({marker})"


def _no_clause_check(self: Attack, clause: str) -> None:
    """Validation mutant: the Attack validator no longer checks the clause."""


def test_a_composition_fault_alone_is_refused_by_the_validation_layer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Layering: with the validator intact, a composition fault never produces an Attack (it
    dies at construction), so the composition check sees a refusal, not a readable clause.
    This is why the composition layer needs its own mutation with validation off (below)."""
    _ok_then(cc.assert_goal_clause_carries_each_goals_value, monkeypatch,
             lambda m: m.setattr(inst, "spaced_marker", _readable_too),
             "(?s)instantiation refused a valid payload and goal.*marker split")  # fmt: skip


def test_the_composition_layer_alone_fails_its_named_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """COMPOSITION layer: validation off, composition faulty; only the composition check stands
    between a readable marker and the model."""

    def patch(m: Any) -> None:
        m.setattr(inst, "spaced_marker", _readable_too)
        m.setattr(Attack, "_check_goal_clause", _no_clause_check)

    _ok_then(cc.assert_goal_clause_carries_each_goals_value, monkeypatch, patch,
             "carries the marker readable")  # fmt: skip


def test_the_validation_layer_alone_fails_its_named_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """VALIDATION layer: composition correct, validation of the clause off; an Attack written
    by hand with a readable marker in its clause is then accepted."""
    _ok_then(cc.assert_attack_refuses_a_readable_split_value, monkeypatch,
             lambda m: m.setattr(Attack, "_check_goal_clause", _no_clause_check),
             "accepted a marker readable in its clause")  # fmt: skip


def test_adding_ws_zw_back_to_r2_makes_the_body_quote_a_hit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    proxy_twin_root: Any,  # noqa: F811
) -> None:
    """THE correctness argument for the split (Phase 6 ruling, not optional): with ws_zw added
    back to R2's match set, the faithful quote into goal arg "body" (the check's default case)
    is a hit, because ws_zw undoes the split the clause applies."""
    from proveflow.oracle import matcher

    _ok_then(cc.assert_r2_quoting_is_not_a_hit, monkeypatch,
             lambda m: m.setattr(matcher, "SPLIT_VALUE_ENCODINGS", ("raw", "casefold", "ws_zw")),
             r"R2 fired on a faithful quotation of the page \(goal arg 'body'\)",
             tmp_path)  # fmt: skip


_REAL_SPACED_ACTION = inst.spaced_action_target


def _readable_action_too(action_target: str) -> str:
    """Composition mutant: the clause shows the split target AND the raw one."""
    return f"{_REAL_SPACED_ACTION(action_target)} ({action_target})"


def test_the_action_target_composition_layer_alone_fails_its_named_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """COMPOSITION layer for the action target (Phase 6): validation off, composition faulty;
    only the composition check stands between a readable target and the model."""

    def patch(m: Any) -> None:
        m.setattr(inst, "spaced_action_target", _readable_action_too)
        m.setattr(Attack, "_check_goal_clause", _no_clause_check)

    _ok_then(cc.assert_goal_clause_carries_each_goals_value, monkeypatch, patch,
             "carries the action target readable")  # fmt: skip


def test_an_action_target_composition_fault_alone_is_refused_by_the_validation_layer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Layering, for the action target: with the validator intact, the composition fault dies
    at construction."""
    _ok_then(cc.assert_goal_clause_carries_each_goals_value, monkeypatch,
             lambda m: m.setattr(inst, "spaced_action_target", _readable_action_too),
             "(?s)instantiation refused a valid payload and goal.*action target split")  # fmt: skip


def test_an_echoing_sandbox_fails_the_echo_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    proxy_twin_root: Any,  # noqa: F811
) -> None:
    """Mutant: a sandbox whose reply carries the call's value (here the action target the
    calls send, upper-cased: casefold is in F9's set)."""
    from oraclechecks import ACTION_TARGET
    from proveflow.proxy import server

    real = server.sandbox_result_dict

    def echoing(seq: int) -> dict[str, Any]:
        out = real(seq)
        out["content"][0]["text"] += f" (sent to {ACTION_TARGET.upper()})"
        return out

    _ok_then(cc.assert_the_sandbox_never_echoes_sink_arguments, monkeypatch,
             lambda m: m.setattr(server, "sandbox_result_dict", echoing),
             "the sandbox reply to 'send_email' echoed", tmp_path)  # fmt: skip


def test_a_carrier_that_duplicates_the_injection_fails_the_canary_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from proveflow.proxy import carriers

    real = carriers.plain
    _ok_then(cc.assert_exfil_canary_is_injected_exactly_once, monkeypatch,
             lambda m: m.setitem(carriers._CARRIERS, attacks.Carrier.PLAIN,
                                 lambda text, payload: real(text, payload) + payload),
             "did not add exactly one canary")  # fmt: skip


def test_an_unguarded_clause_fails_the_f9_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def payload_only(self: Attack) -> dict[str, str]:
        return {"payload": self.payload.text}

    _ok_then(cc.assert_goal_clause_only_through_tool_results, monkeypatch,
             lambda m: m.setattr(Attack, "tool_result_texts", payload_only),
             "a runner-authored goal clause was not refused", tmp_path)  # fmt: skip


def test_skipping_the_sha256_check_fails_the_tamper_check(monkeypatch: pytest.MonkeyPatch) -> None:
    _ok_then(cc.assert_tampered_payload_is_refused, monkeypatch,
             lambda m: m.setattr(inst, "verify_payload", lambda payload: None),
             "does not match its text was instantiated")  # fmt: skip
