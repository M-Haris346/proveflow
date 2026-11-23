"""The campaign loop's classification, arithmetic and state file (Phase 6 step 2), with SCRIPTED
attempts (campaignloopchecks): no twin, no proxy, a real transcript per attempt. Offline."""

from __future__ import annotations

from pathlib import Path

import pytest

from campaignchecks import (
    assert_429_carries_the_exact_retry_after_text,
    assert_exactly_429_is_rate_limited,
    campaign_story,
    with_story,
)
from campaignloopchecks import (
    assert_an_interrupted_attempt_is_charged,
    assert_an_overspent_state_fails_closed,
    assert_an_unclassified_reason_stops_the_campaign,
    assert_backoff_between_rate_limited_attempts,
    assert_corrupt_state_fails_closed,
    assert_every_trial_end_reason_is_classified,
    assert_rate_limit_exhaustion_stops_and_resumes,
    assert_retry_after_extends_never_shortens,
    assert_the_lifetime_count_is_visible,
    assert_the_state_refuses_an_unclassified_result,
    assert_unknown_spend_is_the_full_reservation,
    scanned_trial_end_reasons,
)
from proveflow.runner import campaign as c
from proveflow.runner.limits import RunBudget


def test_backoff_between_rate_limited_attempts(tmp_path: Path) -> None:
    assert_backoff_between_rate_limited_attempts(tmp_path)


def test_rate_limit_exhaustion_stops_and_resumes(tmp_path: Path) -> None:
    assert_rate_limit_exhaustion_stops_and_resumes(tmp_path)


def test_corrupt_state_fails_closed(tmp_path: Path) -> None:
    assert_corrupt_state_fails_closed(tmp_path)


def test_an_interrupted_attempt_is_charged(tmp_path: Path) -> None:
    assert_an_interrupted_attempt_is_charged(tmp_path)


def test_429_carries_the_exact_retry_after_text() -> None:
    """Claim a: header extraction at the client, no trial."""
    assert_429_carries_the_exact_retry_after_text()


def test_retry_after_extends_never_shortens(tmp_path: Path) -> None:
    """Claim c: the wait arithmetic and its record, scripted."""
    assert_retry_after_extends_never_shortens(tmp_path)


def test_a_failed_campaign_check_says_what_happened(tmp_path: Path) -> None:
    """Diagnostics (item 4): the note names every leaf through nested groups and the cause
    chain, with its message and frames, and carries the failing attempt's cassette story."""
    from oraclechecks import write_cassette
    from proveflow.runner.campaign import AttemptFailed
    from proxyhelpers import cassette_story

    out = tmp_path / "out"
    out.mkdir()
    mine = write_cassette(out / "t2-a2.twin.cassette.jsonl", [])
    write_cassette(out / "t9-a1.other.cassette.jsonl", [])

    def boom() -> None:
        def inner() -> None:
            raise RuntimeError("connection to twin closed")

        try:
            raise ExceptionGroup("g", [ExceptionGroup("h", [_raised(inner)])])
        except ExceptionGroup as group:
            raise AttemptFailed("t2-a2: ExceptionGroup[RuntimeError]") from group

    with pytest.raises(AttemptFailed) as info:
        with_story(out, boom)
    note = chr(10).join(info.value.__notes__)
    assert "leaf builtins.RuntimeError: connection to twin closed" in note
    assert "in inner" in note  # the innermost frame: which call failed
    assert f"cassette t2-a2.twin.cassette.jsonl: {cassette_story(mine)}" in note
    assert "t9-a1" not in note  # only the failing attempt's cassettes
    story = campaign_story(out, RuntimeError("no id")).splitlines()
    assert sum(line.startswith("cassette ") for line in story) == 2  # no attempt id: all shown


def test_a_caught_expected_exception_still_tells_its_story(tmp_path: Path) -> None:
    """The expected-exception gap (sighting 3): a check that EXPECTS an exception, catches it,
    and then finds its premise wrong must fail WITH the caught exception's story (its leaves,
    their frames, the failing attempt's cassette story), not with the bare premise message."""
    from campaignchecks import premise_failed
    from oraclechecks import write_cassette
    from proveflow.runner.campaign import AttemptFailed
    from proxyhelpers import cassette_story

    out = tmp_path / "out"
    out.mkdir()
    mine = write_cassette(out / "t1-a2.filesystem.cassette.jsonl", [])

    def boom() -> None:
        def handshake() -> None:
            raise RuntimeError("twin never answered initialize")

        try:
            raise ExceptionGroup("g", [_raised(handshake)])
        except ExceptionGroup as group:
            raise AttemptFailed("t1-a2: ExceptionGroup[RuntimeError]") from group

    caught = _raised(boom)
    err = premise_failed("premise broken: the failed attempts did not spend: [...]", out, caught)
    text = str(err)
    assert text.startswith("premise broken: the failed attempts did not spend")
    assert "leaf builtins.RuntimeError: twin never answered initialize" in text
    assert "in handshake" in text
    assert f"cassette t1-a2.filesystem.cassette.jsonl: {cassette_story(mine)}" in text
    assert str(premise_failed("plain", out, None)) == "plain"  # nothing caught: nothing added


def _raised(fn: object) -> BaseException:
    try:
        fn()  # type: ignore[operator]
    except BaseException as exc:
        return exc
    raise AssertionError("did not raise")


def test_every_trial_end_reason_is_classified() -> None:
    assert_every_trial_end_reason_is_classified()


def test_the_scan_finds_exactly_these_twelve_reasons() -> None:
    """The scan's own result, spelled out, so a change in what the runner writes is visible."""
    reasons, unresolved = scanned_trial_end_reasons()
    assert unresolved == []
    assert reasons == {
        "final_answer", "limit:max_turns", "limit:max_tokens_in", "limit:max_tokens_out",
        "limit:max_tool_calls", "limit:wall_clock", "rate_limited", "provider_error",
        "replay_mismatch", "usage_missing", "malformed_response", "running",
    }  # fmt: skip


def test_classify_is_an_allowlist() -> None:
    assert c.classify("final_answer") == "completed"
    assert c.classify("limit:wall_clock") == "completed"
    assert c.classify("rate_limited") == "rate_limited"
    assert c.classify("running") == "failed"
    with pytest.raises(c.UnclassifiedOutcome, match="'gave_up'"):
        c.classify("gave_up")


def test_an_unclassified_reason_stops_the_campaign(tmp_path: Path) -> None:
    assert_an_unclassified_reason_stops_the_campaign(tmp_path)


def test_the_state_refuses_an_unclassified_result() -> None:
    assert_the_state_refuses_an_unclassified_result()


def test_the_lifetime_count_is_visible(tmp_path: Path) -> None:
    assert_the_lifetime_count_is_visible(tmp_path)


def test_an_overspent_state_fails_closed(tmp_path: Path) -> None:
    assert_an_overspent_state_fails_closed(tmp_path)


def test_run_budget_spend_alone_goes_negative() -> None:
    """MEASURED, the reason budget_of guards: RunBudget.spend never refuses an overshoot."""
    budget = RunBudget(total=100)
    budget.spend(150)
    assert budget.remaining == -50


def test_unknown_spend_is_the_full_reservation() -> None:
    assert_unknown_spend_is_the_full_reservation()


def test_exactly_429_is_rate_limited() -> None:
    assert_exactly_429_is_rate_limited()


def test_retry_after_numeric_only_and_sane() -> None:
    assert c.retry_after_s("30") == 30.0
    assert c.retry_after_s(" 7 ") == 7.0
    assert c.retry_after_s("0") == 0.0
    assert c.retry_after_s(str(c.RETRY_AFTER_MAX_S)) == float(c.RETRY_AFTER_MAX_S)
    for ignored in (None, "", "-5", "1.5", "Fri, 31 Dec 1999 23:59:59 GMT", "soon",
                    str(c.RETRY_AFTER_MAX_S + 1), "99999999999999999999"):  # fmt: skip
        assert c.retry_after_s(ignored) is None, ignored


def test_wait_is_max_of_schedule_and_retry_after() -> None:
    assert c.wait_for(1, "30") == (30.0, "retry_after")
    assert c.wait_for(1, "1") == (2.0, "schedule")
    assert c.wait_for(1, "2") == (2.0, "schedule")  # a tie: the schedule decided
    assert c.wait_for(3, "garbage") == (8.0, "schedule")
    assert c.wait_for(6, None) == (60.0, "schedule")
