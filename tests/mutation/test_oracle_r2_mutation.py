"""Mutations of R2 (Phase 3b): each weakening below makes a NAMED R2 check fail."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import oraclechecks as oc
from proveflow.core.attacks import Attack
from proveflow.core.trials import RuleHit
from proveflow.oracle import matcher, rules


def _ok_then_mutant(
    check: Any, tmp_path: Path, mp: pytest.MonkeyPatch, patch: Any, message: str
) -> None:
    (tmp_path / "ok").mkdir()
    (tmp_path / "mut").mkdir()
    check(tmp_path / "ok")
    patch(mp)
    with pytest.raises(AssertionError, match=message):
        check(tmp_path / "mut")


def test_removing_r2_fails_the_named_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _ok_then_mutant(
        oc.assert_r2_fires_without_any_needle, tmp_path, monkeypatch,
        lambda m: m.setattr(rules, "r2_hits", lambda call, action: ()),
        "R2 missed the action target",
    )  # fmt: skip


def test_r2_not_counted_fails_the_named_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ok_then_mutant(
        oc.assert_r2_fires_without_any_needle, tmp_path, monkeypatch,
        lambda m: m.setattr(rules, "COMPROMISE_RULES", frozenset({RuleHit.R1_EXFIL})),
        "R2 not counted as compromise",
    )  # fmt: skip


def test_exact_tool_names_fail_the_look_alike_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ok_then_mutant(
        oc.assert_r2_matches_the_tool_by_look_alike_group, tmp_path, monkeypatch,
        lambda m: m.setattr(rules, "name_key", lambda name: name),
        "R2 missed the look-alike tool",
    )  # fmt: skip


def test_a_dropped_encoding_fails_the_encoding_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    smaller = {k: v for k, v in matcher.ENCODINGS.items() if k != "base64"}
    _ok_then_mutant(
        oc.assert_r2_uses_every_matcher_encoding, tmp_path, monkeypatch,
        lambda m: m.setattr(matcher, "ENCODINGS", smaller),
        "under encoding base64",
    )  # fmt: skip


def _whole_arguments(call: Any, action: Any) -> tuple[Any, ...]:
    """Mutant: the action target ANYWHERE in the arguments (``arg`` ignored)."""
    if action is None or rules.name_key(call.tool) != action.sink_key:
        return ()
    return tuple(rules.EncodingHit(path=h.path, encoding=h.encoding)
                 for h in matcher.match(action.target, call.arguments).hits)  # fmt: skip


def test_ignoring_the_goal_argument_fails_the_negative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ok_then_mutant(
        oc.assert_r2_needs_the_goal_argument, tmp_path, monkeypatch,
        lambda m: m.setattr(rules, "r2_hits", _whole_arguments),
        "R2 fired outside the goal argument",
    )  # fmt: skip


def _any_tool(call: Any, action: Any) -> tuple[Any, ...]:
    """Mutant: the goal's sink tool ignored."""
    if action is None or not isinstance(call.arguments, dict) or action.arg not in call.arguments:
        return ()
    hits = matcher.match(action.target, call.arguments[action.arg]).hits
    return tuple(rules.EncodingHit(path=h.path, encoding=h.encoding) for h in hits)


def test_ignoring_the_goal_tool_fails_the_negative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ok_then_mutant(
        oc.assert_r2_needs_the_goal_tool, tmp_path, monkeypatch,
        lambda m: m.setattr(rules, "r2_hits", _any_tool),
        "R2 fired on a sink tool that is not the goal",
    )  # fmt: skip


def _every_call(events: Any) -> list[Any]:
    """Mutant: the proxy's sink flag ignored."""
    return [e for e in events if isinstance(e, rules.SandboxedCall | rules.UpstreamRequest)]


def test_ignoring_the_sink_flag_fails_the_negative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ok_then_mutant(
        oc.assert_r2_needs_a_sink_call, tmp_path, monkeypatch,
        lambda m: m.setattr(rules, "sink_calls", _every_call),
        "R2 fired on a sink=false",
    )  # fmt: skip


def _no_action_sightings(events: Any, needles: Any) -> list[Any]:
    """Mutant: the action target dropped from the forwarded-call sighting scan."""
    real = rules.NeedleSighting
    kept = [n for n in needles if n.id != rules.ACTION_TARGET_NEEDLE]
    return [s for s in _REAL_SIGHTINGS(events, kept) if isinstance(s, real)]


_REAL_SIGHTINGS = rules.forwarded_sightings


def test_dropping_the_action_target_sighting_fails_the_negative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ok_then_mutant(
        oc.assert_r2_needs_a_sink_call, tmp_path, monkeypatch,
        lambda m: m.setattr(rules, "forwarded_sightings", _no_action_sightings),
        "was not sighted",
    )  # fmt: skip


_REAL_NEEDLES_OF = rules.needles_of


def _action_target_as_r1_needle(start: Any) -> list[Any]:
    """Mutant: the action target added to R1's needle set. Its id is NOT "action_target", so
    the Evidence validator (a second, independent guard) does not stop it first: the NAMED
    check is what must catch it."""
    out = _REAL_NEEDLES_OF(start)
    attack = rules._attack(start)
    if attack is not None and attack.action_target is not None:
        out.append(rules.Needle(id="act", value=attack.action_target))
    return out


def test_action_target_as_an_r1_needle_fails_the_named_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ok_then_mutant(
        oc.assert_action_target_is_not_an_r1_needle, tmp_path, monkeypatch,
        lambda m: m.setattr(rules, "needles_of", _action_target_as_r1_needle),
        "R1 counted the action target as exfiltration",
    )  # fmt: skip


def _flat_value_only(call: Any, action: Any) -> tuple[Any, ...]:
    """Mutant: only a plain string directly under the goal argument is scanned."""
    if action is None or rules.name_key(call.tool) != action.sink_key:
        return ()
    if not isinstance(call.arguments, dict) or not isinstance(call.arguments.get(action.arg), str):
        return ()
    hits = matcher.match(action.target, call.arguments[action.arg]).hits
    return tuple(rules.EncodingHit(path=f"$.{action.arg}", encoding=h.encoding) for h in hits)


def test_a_flat_value_scan_fails_the_recursive_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ok_then_mutant(
        oc.assert_r2_scans_the_goal_argument_value_recursively, tmp_path, monkeypatch,
        lambda m: m.setattr(rules, "r2_hits", _flat_value_only),
        "nested under the goal argument",
    )  # fmt: skip


def test_r2_not_counted_fails_the_verdict_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ok_then_mutant(
        oc.assert_r2_reaches_the_verdict, tmp_path, monkeypatch,
        lambda m: m.setattr(rules, "COMPROMISE_RULES", frozenset({RuleHit.R1_EXFIL})),
        "R2 did not reach the verdict",
    )  # fmt: skip


def test_runner_authored_action_target_unguarded_fails_the_negative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def only_canary(self: Attack) -> dict[str, str]:
        return {"canary": self.canary}

    _ok_then_mutant(
        oc.assert_action_target_only_through_tool_results, tmp_path, monkeypatch,
        lambda m: m.setattr(Attack, "tool_result_values", only_canary),
        "runner-authored action target not refused",
    )  # fmt: skip
