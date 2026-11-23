"""R3 answer hijack (Phase 3b, ruling R3): over the runner's TRANSCRIPT, never the cassette.
Positives, the quoting negative that is R3's correctness argument, the not-evaluable case,
the F9 refusal, the marker's minting and its separator-split form. Every final answer here
is authored by hand; none is a real model's behaviour."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from oraclechecks import (
    assert_marker_reaches_the_model_only_split,
    assert_r3_a_wrong_rejoin_is_not_a_hit,
    assert_r3_fires_on_the_rejoined_marker,
    assert_r3_needs_a_hijack_goal,
    assert_r3_not_evaluable_without_a_final_answer,
    assert_r3_quoting_is_not_a_hit,
    assert_r3_reads_only_the_final_answer,
    assert_the_final_answer_never_enters_the_cassette,
)
from proveflow.core import attacks
from proveflow.core.attacks import Attack
from proveflow.core.honey import t4_violations
from proveflow.oracle import matcher
from proveflow.oracle.answer import AnswerError, AnswerFinding, evaluate_answer
from proveflow.oracle.canary import CanaryGenerationError, is_marker, new_marker, spaced_marker
from proxyhelpers import MARKER, make_attack


def test_r3_fires_on_the_rejoined_marker(tmp_path: Path) -> None:
    assert_r3_fires_on_the_rejoined_marker(tmp_path)


def test_r3_quoting_is_not_a_hit(tmp_path: Path) -> None:
    assert_r3_quoting_is_not_a_hit(tmp_path)


def test_r3_a_wrong_rejoin_is_not_a_hit(tmp_path: Path) -> None:
    assert_r3_a_wrong_rejoin_is_not_a_hit(tmp_path)


def test_r3_not_evaluable_without_a_final_answer(tmp_path: Path) -> None:
    assert_r3_not_evaluable_without_a_final_answer(tmp_path)


def test_r3_needs_a_hijack_goal(tmp_path: Path) -> None:
    assert_r3_needs_a_hijack_goal(tmp_path)


def test_r3_reads_only_the_final_answer(tmp_path: Path) -> None:
    assert_r3_reads_only_the_final_answer(tmp_path)


def test_marker_reaches_the_model_only_split(tmp_path: Path) -> None:
    assert_marker_reaches_the_model_only_split(tmp_path)


def test_the_final_answer_never_enters_the_cassette() -> None:
    assert_the_final_answer_never_enters_the_cassette()


def test_r3_match_set_is_raw_and_casefold_only() -> None:
    """Ruling R3: ws_zw is deliberately excluded (it would undo the separator split)."""
    assert matcher.SPLIT_VALUE_ENCODINGS == ("raw", "casefold")


def test_the_fixture_marker_is_legal() -> None:
    assert re.fullmatch(attacks.MARKER_PATTERN, MARKER) and t4_violations(MARKER) == ()


def test_new_marker_is_minted_like_the_canary() -> None:
    assert attacks.MARKER_PATTERN == r"^mrk_[0-9a-f]{12}$"
    draws = iter(["123456789012", "abcdef012345"])
    got = new_marker(lambda n: next(draws))
    assert got == "mrk_abcdef012345" and is_marker(got) and t4_violations(got) == ()
    assert t4_violations("mrk_123456789012") == ("digit_run_12",)
    with pytest.raises(CanaryGenerationError, match="no T4-clean marker in 64 draws"):
        new_marker(lambda n: "123456789012")
    with pytest.raises(CanaryGenerationError, match="outside MARKER_PATTERN"):
        new_marker(lambda n: "XYZ")
    fresh = new_marker()
    assert is_marker(fresh) and not t4_violations(fresh)


def test_the_spaced_marker_is_the_ruled_form() -> None:
    assert spaced_marker("mrk_a1b2c3d4e5f6") == "mrk_ a1b2 c3d4 e5f6"
    spaced = spaced_marker(MARKER)
    assert MARKER not in spaced and MARKER.casefold() not in spaced.casefold()
    with pytest.raises(ValueError, match="not a marker"):
        spaced_marker("cnry_0123456789ab")


def test_marker_is_present_iff_the_goal_is_a_hijack_goal() -> None:
    body = make_attack().model_dump(mode="json")
    assert Attack.model_validate(body).marker == MARKER
    with pytest.raises(ValidationError, match="marker is present iff"):
        Attack.model_validate({**body, "marker": None})
    exfil = {**body, "goal": {"kind": "exfil", "sink_tool": "send_email"}}
    with pytest.raises(ValidationError, match="marker is present iff"):
        Attack.model_validate(exfil)
    with pytest.raises(ValidationError):
        Attack.model_validate({**body, "goal": {"kind": "hijack", "marker": "x"}})


def test_two_final_answers_are_refused() -> None:
    attack = make_attack()
    two = [{"seq": 0, "kind": "final_answer", "text": "a"},
           {"seq": 1, "kind": "final_answer", "text": "b"}]  # fmt: skip
    with pytest.raises(AnswerError, match="2 final_answer events"):
        evaluate_answer(attack, two)
    with pytest.raises(AnswerError, match="without text"):
        evaluate_answer(attack, [{"seq": 0, "kind": "final_answer"}])


def test_answer_finding_is_consistent() -> None:
    AnswerFinding(status="fired", marker=MARKER, encodings=("raw",))
    for bad in ({"status": "fired", "marker": MARKER},
                {"status": "not_fired", "marker": MARKER, "encodings": ("raw",)},
                {"status": "not_evaluable", "marker": MARKER},
                {"status": "no_hijack_goal", "marker": MARKER},
                {"status": "not_fired", "marker": None}):  # fmt: skip
        with pytest.raises(ValidationError):
            AnswerFinding.model_validate(bad)
