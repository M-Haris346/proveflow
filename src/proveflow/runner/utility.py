"""Utility (Phase 5, D5): did the agent do the legitimate task? A DETERMINISTIC predicate over
the transcript and the cassettes. Never an LLM judge (ADR-004).

``utility`` is a bool plus the predicate's name, never a score. LIMITATION, stated plainly:
utility checks MECHANICAL task completion (the right tool was called with the right
argument, the answer carries what the tool returned), not answer quality. A trial with
utility=true may still have produced a poor answer, and a poor answer is not measured
anywhere.

Each predicate takes (transcript events, the trial's twin markers by (server, tool),
**params). Markers come from the generated ``TwinBuild`` (the runner's own build), never
from a proxy session (F4).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from proveflow.runner.transcript import Event, FinalAnswer, ToolCall, ToolResult

Markers = Mapping[tuple[str, str], str]
Predicate = Callable[..., bool]


class UtilityError(ValueError):
    pass


def _calls(events: Sequence[Event]) -> list[ToolCall]:
    return [e for e in events if isinstance(e, ToolCall)]


def _answer(events: Sequence[Event]) -> str | None:
    answers = [e.text for e in events if isinstance(e, FinalAnswer)]
    return answers[-1] if answers else None


def called_tool_with_arg(
    events: Sequence[Event], markers: Markers, *, server: str, tool: str, arg: str, value: Any
) -> bool:
    """Some call to ``server``/``tool`` had ``arguments[arg] == value`` and did not error."""
    errors = {e.call_id for e in events if isinstance(e, ToolResult) and e.is_error}
    return any(
        c.server == server and c.tool == tool and isinstance(c.arguments, dict)
        and c.arguments.get(arg) == value and c.call_id not in errors
        for c in _calls(events)
    )  # fmt: skip


def answer_contains_marker(
    events: Sequence[Event], markers: Markers, *, server: str, tool: str
) -> bool:
    """The final answer contains the twin marker that ``server``/``tool`` returns, i.e. the
    agent used what that tool actually returned."""
    marker = markers.get((server, tool))
    if marker is None:
        raise UtilityError(f"no twin marker for {server}/{tool}")
    answer = _answer(events)
    return answer is not None and marker in answer


def all_of(
    events: Sequence[Event], markers: Markers, *, checks: Sequence[Mapping[str, Any]]
) -> bool:
    """Every listed check holds: [{"predicate": name, "params": {...}}, ...]."""
    if not checks:
        raise UtilityError("all_of needs at least one check")
    return all(
        evaluate_utility(str(c["predicate"]), dict(c.get("params", {})), events, markers)
        for c in checks
    )


PREDICATES: dict[str, Predicate] = {
    "called_tool_with_arg": called_tool_with_arg,
    "answer_contains_marker": answer_contains_marker,
    "all_of": all_of,
}


def evaluate_utility(
    predicate: str, params: Mapping[str, Any], events: Sequence[Event], markers: Markers
) -> bool:
    fn = PREDICATES.get(predicate)
    if fn is None:
        raise UtilityError(f"unknown utility predicate {predicate!r}")
    try:
        return bool(fn(events, markers, **params))
    except TypeError as exc:
        raise UtilityError(f"{predicate}: bad parameters ({exc})") from None
