"""Mutation (Phase 5): break one runner guard -> its NAMED check fails.

* payload put into the system prompt            -> assert_injection_only_through_tool_results
* the API key copied into the request body      -> assert_no_api_key_in_any_artifact
* the transcript digest check skipped           -> assert_altered_record_breaks_the_chain
* the cassette-reference check removed          -> assert_mismatched_cassette_ref_refused
* a cap removed (set out of reach)              -> assert_cap_fires
* the budget reservation removed                -> assert_budget_refuses_a_trial_it_cannot_cover
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from oraclechecks import write_cassette
from proveflow.runner import agent, transcript, validity
from proveflow.runner.limits import RunBudget, TrialLimits
from proxyhelpers import proxy_twin_root  # noqa: F401
from runnerchecks import (
    PLANTED_KEY,
    assert_altered_record_breaks_the_chain,
    assert_budget_refuses_a_trial_it_cannot_cover,
    assert_cap_fires,
    assert_injection_only_through_tool_results,
    assert_mismatched_cassette_ref_refused,
    assert_no_api_key_in_any_artifact,
    fixture_scenario,
)


def _dirs(tmp_path: Path) -> tuple[Path, Path]:
    ok, mut = tmp_path / "ok", tmp_path / "mut"
    ok.mkdir()
    mut.mkdir()
    return ok, mut


def test_payload_in_the_system_prompt_fails_the_named_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ok, mut = _dirs(tmp_path)
    assert_injection_only_through_tool_results(ok)
    payload = fixture_scenario("cross_server_exfil").attack.payload.text  # type: ignore[union-attr]
    real = agent.runner_messages
    monkeypatch.setattr(agent, "runner_messages",
                        lambda system, task: real(system + "\n" + payload, task))  # fmt: skip
    with pytest.raises(AssertionError, match="attack text in a runner-authored message"):
        assert_injection_only_through_tool_results(mut)


def test_key_in_the_request_fails_the_named_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ok, mut = _dirs(tmp_path)
    with monkeypatch.context() as m:
        assert_no_api_key_in_any_artifact(ok)
        m.undo()
    real = agent.build_request

    def leaky(**kwargs: Any) -> dict[str, Any]:
        return {**real(**kwargs), "metadata": {"k": PLANTED_KEY}}

    monkeypatch.setattr(agent, "build_request", leaky)
    monkeypatch.setattr(validity, "injection_channel_violations", lambda e, a: [])
    with pytest.raises(AssertionError, match="API key found in"):
        assert_no_api_key_in_any_artifact(mut)


def test_skipping_the_digest_check_fails_the_named_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ok, mut = _dirs(tmp_path)
    assert_altered_record_breaks_the_chain(ok)
    real = transcript.digest

    def skip_on_load(body: dict[str, Any]) -> str:
        # Mutant: when an event already carries a sha256 (the loader's check), trust it.
        return str(body["sha256"]) if "sha256" in body else real(body)

    monkeypatch.setattr(transcript, "digest", skip_on_load)
    with pytest.raises(AssertionError, match="was accepted"):
        assert_altered_record_breaks_the_chain(mut)


def test_removing_the_cassette_ref_check_fails_the_named_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ok, mut = _dirs(tmp_path)
    assert_mismatched_cassette_ref_refused(ok, write_cassette(ok / "pftwin-x.c.jsonl", []))
    monkeypatch.setattr(transcript, "verify_cassette_refs", lambda events, directory: [])
    with pytest.raises(AssertionError, match="mismatched cassette was accepted"):
        assert_mismatched_cassette_ref_refused(mut, write_cassette(mut / "pftwin-x.c.jsonl", []))


@pytest.mark.parametrize(("field", "value"), [("max_turns", 2), ("max_tool_calls", 1)])
def test_a_cap_out_of_reach_fails_the_named_check(tmp_path: Path, field: str, value: int) -> None:
    ok, mut = _dirs(tmp_path)
    assert_cap_fires(ok, TrialLimits.model_validate({field: value}), field)
    unreachable = TrialLimits.model_construct(**{**TrialLimits().model_dump(), field: 10**6})
    with pytest.raises(AssertionError, match=f"cap {field} did not fire"):
        assert_cap_fires(mut, unreachable, field)


def test_removing_the_budget_reservation_fails_the_named_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert_budget_refuses_a_trial_it_cannot_cover()
    monkeypatch.setattr(RunBudget, "reserve", lambda self, limits: None)
    with pytest.raises(AssertionError, match="budget allowed a trial"):
        assert_budget_refuses_a_trial_it_cannot_cover()
