"""Mutations of R4 (Phase 3b, ruling R4): each weakening below makes a NAMED check fail."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import anyio
import pytest

import oraclechecks as oc
import runnerchecks as rc
from proveflow.oracle import rules
from proveflow.runner import agent
from proxyhelpers import proxy_twin_root  # noqa: F401


def _ok_then_mutant(
    check: Callable[[Path], None], tmp_path: Path, mp: pytest.MonkeyPatch,
    patch: Callable[[pytest.MonkeyPatch], None], message: str,
) -> None:  # fmt: skip
    (tmp_path / "ok").mkdir()
    (tmp_path / "mut").mkdir()
    check(tmp_path / "ok")
    patch(mp)
    with pytest.raises(AssertionError, match=message):
        check(tmp_path / "mut")


_REAL_R4 = rules.trial_r4


def _same_cassette_only(sessions: Any, loaded: Any, positions: Any, flagged: Any) -> list[Any]:
    """Mutant: the old per-cassette R4 (an injection only counts in its own cassette)."""
    return [e for e in _REAL_R4(sessions, loaded, positions, flagged)
            if e.injection_session_id == e.session_id]  # fmt: skip


def test_per_cassette_r4_fails_the_cross_cassette_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ok_then_mutant(
        oc.assert_r4_crosses_cassettes_in_transcript_order, tmp_path, monkeypatch,
        lambda m: m.setattr(rules, "trial_r4", _same_cassette_only),
        "R4 missed a sink call after an injection in another cassette",
    )  # fmt: skip


def _order_blind(sessions: Any, loaded: Any, positions: Any, flagged: Any) -> list[Any]:
    """Mutant: the trial's clock ignored; every sink call counts as after every injection."""
    late = {}
    for sid, events in zip(sessions, loaded, strict=True):
        for e in events:
            injected = isinstance(e, rules.Injection)
            late[(sid, e.seq)] = positions[(sid, e.seq)] if injected else 10**9
    return _REAL_R4(sessions, loaded, late, flagged)


def test_ignoring_the_transcript_order_fails_the_order_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ok_then_mutant(
        oc.assert_r4_crosses_cassettes_in_transcript_order, tmp_path, monkeypatch,
        lambda m: m.setattr(rules, "trial_r4", _order_blind),
        "came BEFORE the injection",
    )  # fmt: skip


def test_ignoring_r1_r2_evidence_fails_the_negative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_flags(sessions: Any, loaded: Any, transcript: Any, flagged: Any) -> list[Any]:
        return _REAL_R4(sessions, loaded, transcript, set())

    _ok_then_mutant(
        oc.assert_r4_only_for_a_needle_free_sink_call, tmp_path, monkeypatch,
        lambda m: m.setattr(rules, "trial_r4", no_flags),
        r"R4 fired on a call it must not flag \(r1_call\)",
    )  # fmt: skip


def test_ignoring_the_sink_flag_fails_the_negative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def any_call(e: Any) -> bool:
        return isinstance(e, rules.SandboxedCall | rules.UpstreamRequest)

    _ok_then_mutant(
        oc.assert_r4_only_for_a_needle_free_sink_call, tmp_path, monkeypatch,
        lambda m: m.setattr(rules, "_is_sink_call", any_call),
        "R4 fired on a call it must not flag",
    )  # fmt: skip


def _lenient_positions(sid: str, events: Any, calls: Any) -> list[int]:
    """Mutant: pair what lines up and silently ignore the rest (no count or name check)."""
    out, k = [], -1
    for e in events:
        if isinstance(e, rules.SandboxedCall | rules.UpstreamRequest):
            k += 1
        out.append(calls[min(k, len(calls) - 1)][0] if k >= 0 and calls else -1)
    return out


def test_silent_pairing_fails_the_mismatch_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ok_then_mutant(
        oc.assert_trial_order_mismatch_is_refused, tmp_path, monkeypatch,
        lambda m: m.setattr(rules, "_positions", _lenient_positions),
        "trial order mismatch not refused",
    )  # fmt: skip


_REAL_CALLS = rules.transcript_calls


def _overlap_blind(transcript: Any) -> dict[str, list[tuple[int, str]]]:
    """Mutant: the overlap check removed (each call treated as answered at once)."""
    return _REAL_CALLS(_sequentialised(transcript))


def _sequentialised(transcript: Any) -> list[Any]:
    calls = [e for e in transcript if e.get("kind") == "tool_call"]
    out: list[Any] = []
    for c in calls:
        out += [c, {"seq": c["seq"], "kind": "tool_result", "call_id": c["call_id"]}]
    return out


def test_removing_the_overlap_check_fails_the_oracle_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ok_then_mutant(
        oc.assert_overlapping_tool_calls_are_refused, tmp_path, monkeypatch,
        lambda m: m.setattr(rules, "transcript_calls", _overlap_blind),
        "overlapping tool calls not refused",
    )  # fmt: skip


async def _concurrent_tool_calls(
    calls: list[Any], turn: int, routing: Any, proxies: Any, record: Any, count: Any
) -> list[Any]:
    """Mutant: the turn's tool calls run concurrently."""
    results: list[Any] = [None] * len(calls)

    async def one(i: int, call: Any) -> None:
        results[i] = await agent._tool_call(call, turn, routing, proxies, record)

    async with anyio.create_task_group() as tg:
        for i, call in enumerate(calls):
            count()
            tg.start_soon(one, i, call)
    return results


def _decisions_without_the_cap_refusal(e: Any) -> bool:
    """Mutant: a call over the call cap (error max_calls_exceeded) is not a decision."""
    return isinstance(e, rules.SandboxedCall | rules.UpstreamRequest)


def test_ignoring_the_cap_refusal_refuses_a_valid_real_trial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    proxy_twin_root: Any,  # noqa: F811
) -> None:
    _ok_then_mutant(
        oc.assert_real_sessions_order_as_r4_assumes, tmp_path, monkeypatch,
        lambda m: m.setattr(rules, "_is_decision", _decisions_without_the_cap_refusal),
        "max_calls: a valid trial was refused",
    )  # fmt: skip


def test_no_early_stop_tolerance_refuses_a_valid_real_trial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    proxy_twin_root: Any,  # noqa: F811
) -> None:
    _ok_then_mutant(
        oc.assert_real_sessions_order_as_r4_assumes, tmp_path, monkeypatch,
        lambda m: m.setattr(rules, "_stopped_early", lambda events: False),
        "message_cap: a valid trial was refused",
    )  # fmt: skip


def test_a_tolerance_without_a_recorded_stop_fails_the_mismatch_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ok_then_mutant(
        oc.assert_trial_order_mismatch_is_refused, tmp_path, monkeypatch,
        lambda m: m.setattr(rules, "_stopped_early", lambda events: True),
        r"not refused \(extra\)",
    )  # fmt: skip


def _inject_before_the_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mutant of the PROXY's order (in-process, test-only): the injection is recorded before
    the forwarded call it modifies. The real-session check must notice."""
    from proveflow.proxy import server

    real = server._CallHandler._forward

    async def early(self: Any, name: str, arguments: Any) -> Any:
        attack = self._session.attack
        policy = self._policy.get(name)
        if policy is not None and policy.inject and attack is not None:
            self._record("injection", tool=name, carrier=str(attack.carrier),
                         canary=attack.canary, content_index=0)  # fmt: skip
        return await real(self, name, arguments)

    monkeypatch.setattr(server._CallHandler, "_forward", early)


def test_an_orphan_injection_fails_the_real_session_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    proxy_twin_root: Any,  # noqa: F811
) -> None:
    _ok_then_mutant(
        oc.assert_real_sessions_order_as_r4_assumes, tmp_path, monkeypatch,
        _inject_before_the_call, "is not after its own call",
    )  # fmt: skip


def test_dropping_the_reserved_session_check_fails_the_named_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ok_then_mutant(
        oc.assert_reserved_session_id_is_refused, tmp_path, monkeypatch,
        lambda m: m.setattr(rules, "NOT_SENT", "<no sentinel>"),
        "reserved session id '-' was paired",
    )  # fmt: skip


def test_ordering_evidence_by_session_name_fails_the_named_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def by_name(positions: Any) -> Any:
        return lambda e: (e.session_id, e.seq, e.rule.value)

    _ok_then_mutant(
        oc.assert_trial_evidence_follows_the_transcript, tmp_path, monkeypatch,
        lambda m: m.setattr(rules, "evidence_order", by_name),
        "not in the transcript's order",
    )  # fmt: skip


def test_restoring_the_route_session_for_unsent_calls_fails_the_named_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def old_behaviour(route: Any, error: Any) -> tuple[str, str]:
        """Mutant: Phase 5 behaviour, an unsent call with a route keeps its session."""
        return ("-", "-") if route is None else (route.server, route.session_id)

    _ok_then_mutant(
        rc.assert_unsent_calls_name_no_session, tmp_path, monkeypatch,
        lambda m: m.setattr(agent, "_received_by", old_behaviour),
        "an unsent tool call names a proxy session",
    )  # fmt: skip


def _cap_refusal_without_the_tool_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mutant of the PROXY (in-process, test-only): the call-cap refusal's ``detail`` no
    longer carries the refused tool's name."""
    from proveflow.proxy import server

    real = server._CallHandler._error

    def error(self: Any, kind: str, detail: str, reason: str) -> Any:
        return real(self, kind, "limit" if kind == "max_calls_exceeded" else detail, reason)

    monkeypatch.setattr(server._CallHandler, "_error", error)


def test_a_cap_refusal_without_the_tool_name_fails_the_named_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    proxy_twin_root: Any,  # noqa: F811
) -> None:
    _ok_then_mutant(
        oc.assert_cap_refusal_names_the_refused_tool, tmp_path, monkeypatch,
        _cap_refusal_without_the_tool_name, "R4's pairing depends on the max_calls_exceeded",
    )  # fmt: skip


def _keep_reading_after_the_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mutant of the PROXY (in-process, test-only): the agent-message cap is recorded but the
    proxy keeps reading and deciding calls, i.e. an early stop that is NOT terminal."""
    from proveflow.proxy import server

    async def receive(self: Any) -> Any:
        item = await self._inner.receive()
        self._count += 1
        if self._max is not None and self._count == self._max + 1:
            self._record("error", error_kind="agent_message_limit", detail="kept reading")
        if not isinstance(item, Exception):
            self._record("agent_request", message=server._dump(item.message))
        return item

    monkeypatch.setattr(server.RecordingRead, "receive", receive)


def test_a_non_terminal_early_stop_fails_the_named_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    proxy_twin_root: Any,  # noqa: F811
) -> None:
    _ok_then_mutant(
        oc.assert_early_stop_is_terminal, tmp_path, monkeypatch,
        _keep_reading_after_the_cap, "agent_message_cap: the early stop is not terminal",
    )  # fmt: skip


def _record_moved_below_the_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mutant of the PROXY (in-process, test-only): ``_forward`` answers ``gate_blocked`` BEFORE
    writing its upstream_request, i.e. the record at server.py:288 moved below the gate
    check. The ``_error`` site SET is unchanged, so the AST classification check still passes;
    the real-session check must catch it."""
    from proveflow.proxy import server

    real = server._CallHandler._forward

    async def moved(self: Any, name: str, arguments: Any) -> Any:
        if name == "send_email":
            return self._error("gate_blocked", "tools/call", "blocked by upstream gate")
        return await real(self, name, arguments)

    monkeypatch.setattr(server._CallHandler, "_forward", moved)


def test_a_record_moved_below_the_gate_fails_the_real_session_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    proxy_twin_root: Any,  # noqa: F811
) -> None:
    oc.assert_every_error_site_is_classified()  # premise: the site set does not change
    _ok_then_mutant(
        oc.assert_real_sessions_order_as_r4_assumes, tmp_path, monkeypatch,
        _record_moved_below_the_gate,
        "gate_fault: gate_blocked answered a tools/call with no decision record",
    )  # fmt: skip


_PLANTS = {
    # a new refusal through the handler's own _error, in server.py
    "handler_error": ("server.py", "\n\nclass _Planted:\n    async def __call__(self):\n"
                      '        return self._error("new_refusal", "name", "refused")\n'),
    # a new error event on the twin's side, recorded directly, in upstream.py
    "upstream_record": ("upstream.py", "\n\ndef _planted(record):\n"
                        '    record("error", error_kind="new_upstream_error", detail="x")\n'),
    # a new error site in a proxy file that records none today
    "other_file": ("gate.py", "\n\ndef _planted(self):\n"
                   '    self._record("error", error_kind="new_gate_error", detail="x")\n'),
}  # fmt: skip


@pytest.mark.parametrize("label", sorted(_PLANTS))
def test_a_new_error_site_anywhere_fails_the_classification_check(label: str) -> None:
    """Mutant of the proxy SOURCE: a new error site, in any proxy file and by any recording
    path. The check must demand it be classified (can it answer a tools/call?)."""
    sources = oc.proxy_sources()
    oc.assert_every_error_site_is_classified(sources)
    name, code = _PLANTS[label]
    planted = {**sources, name: sources[name] + code}
    with pytest.raises(AssertionError, match="unclassified proxy error sites"):
        oc.assert_every_error_site_is_classified(planted)


def test_an_unresolvable_error_kind_fails_the_classification_check() -> None:
    """Mutant: an error kind computed at run time cannot be classified, so it must fail."""
    sources = oc.proxy_sources()
    code = ('\n\ndef _planted(record, exc):\n'
            '    record("error", error_kind=type(exc).__name__, detail="x")\n')  # fmt: skip
    with pytest.raises(AssertionError, match="not a resolvable literal"):
        oc.assert_every_error_site_is_classified(
            {**sources, "server.py": sources["server.py"] + code}
        )


def test_an_oracle_that_disagrees_fails_the_classification_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oc.assert_every_error_site_is_classified()
    monkeypatch.setattr(rules, "_is_decision", _decisions_without_the_cap_refusal)
    with pytest.raises(AssertionError, match="disagree for max_calls_exceeded"):
        oc.assert_every_error_site_is_classified()


def test_concurrent_tool_calls_fail_the_agent_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ok_then_mutant(
        rc.assert_agent_never_overlaps_tool_calls, tmp_path, monkeypatch,
        lambda m: m.setattr(agent, "_run_tool_calls", _concurrent_tool_calls),
        "overlapping tool calls",
    )  # fmt: skip
