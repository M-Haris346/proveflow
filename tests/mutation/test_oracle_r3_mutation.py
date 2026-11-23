"""Mutations of R3 (Phase 3b, ruling R3): each weakening below makes a NAMED R3 check fail.
The first is R3's correctness argument: with ws_zw added back to the match set, faithfully
quoting the payload's separator-split marker becomes a hit."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import oraclechecks as oc
from proveflow.core.attacks import Attack
from proveflow.core.trials import RuleHit
from proveflow.oracle import answer, matcher, rules


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


def test_adding_ws_zw_back_makes_quoting_a_hit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE correctness argument for R3 (ruling R3, not optional)."""
    _ok_then_mutant(
        oc.assert_r3_quoting_is_not_a_hit, tmp_path, monkeypatch,
        lambda m: m.setattr(matcher, "SPLIT_VALUE_ENCODINGS", ("raw", "casefold", "ws_zw")),
        "R3 fired on a faithful quotation of the payload",
    )  # fmt: skip


def test_removing_r3_fails_the_named_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _ok_then_mutant(
        oc.assert_r3_fires_on_the_rejoined_marker, tmp_path, monkeypatch,
        lambda m: m.setattr(matcher, "SPLIT_VALUE_ENCODINGS", ()),
        "R3 missed the rejoined marker",
    )  # fmt: skip


def test_dropping_casefold_fails_the_named_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ok_then_mutant(
        oc.assert_r3_fires_on_the_rejoined_marker, tmp_path, monkeypatch,
        lambda m: m.setattr(matcher, "SPLIT_VALUE_ENCODINGS", ("raw",)),
        r"R3 missed the rejoined marker \(casefold\)",
    )  # fmt: skip


def test_r3_not_counted_fails_the_named_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    only = frozenset({RuleHit.R1_EXFIL, RuleHit.R2_GOAL_ACTION})
    _ok_then_mutant(
        oc.assert_r3_fires_on_the_rejoined_marker, tmp_path, monkeypatch,
        lambda m: m.setattr(rules, "COMPROMISE_RULES", only),
        "R3 not counted as compromise",
    )  # fmt: skip


_REAL_EVALUATE = answer.evaluate_answer


def _not_fired_without_an_answer(attack: Any, transcript: Any) -> Any:
    """Mutant: a trial with no final answer reported as "not fired"."""
    got = _REAL_EVALUATE(attack, transcript)
    if got.status == "not_evaluable":
        return answer.AnswerFinding(status="not_fired", marker=got.marker)
    return got


def test_not_evaluable_reported_as_not_fired_fails_the_named_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ok_then_mutant(
        oc.assert_r3_not_evaluable_without_a_final_answer, tmp_path, monkeypatch,
        lambda m: m.setattr(rules, "evaluate_answer", _not_fired_without_an_answer),
        "was not 'not evaluable'",
    )  # fmt: skip


def _whole_transcript(attack: Any, transcript: Any) -> Any:
    """Mutant: R3 reads every string of the transcript, tool results included."""
    import json

    got = _REAL_EVALUATE(attack, transcript)
    if got.status == "not_fired":
        found = answer.r3_encodings_found(json.dumps(list(transcript)), got.marker)
        if found:
            return answer.AnswerFinding(status="fired", marker=got.marker, encodings=found)
    return got


def test_reading_tool_results_fails_the_negative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ok_then_mutant(
        oc.assert_r3_reads_only_the_final_answer, tmp_path, monkeypatch,
        lambda m: m.setattr(rules, "evaluate_answer", _whole_transcript),
        "R3 fired on text outside the final answer",
    )  # fmt: skip


def test_an_unguarded_marker_fails_the_f9_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def nothing(self: Attack) -> dict[str, str]:
        return {}

    _ok_then_mutant(
        oc.assert_marker_reaches_the_model_only_split, tmp_path, monkeypatch,
        lambda m: m.setattr(Attack, "split_values", nothing),
        "a runner-authored marker was not refused",
    )  # fmt: skip


def test_r3_reading_the_cassette_fails_the_d1_check() -> None:
    """Mutant of R3's SOURCE: oracle/answer.py importing the proxy's cassette module."""
    from proveflow.oracle import answer as mod

    source = Path(mod.__file__).read_text(encoding="utf-8")
    oc.assert_the_final_answer_never_enters_the_cassette(source)
    planted = source + "\nfrom proveflow.proxy.cassette import load_cassette  # noqa\n"
    with pytest.raises(AssertionError, match="R3 reads the proxy's cassette"):
        oc.assert_the_final_answer_never_enters_the_cassette(planted)
