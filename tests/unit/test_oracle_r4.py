"""R4 suspicious (Phase 3b, ruling R4): over the trial's cassettes, ORDERED BY THE RUNNER'S
TRANSCRIPT, computed by the trial evaluator only. Positives, negatives, the order refusals,
and the agent-side precondition the ordering depends on. Every fixture is authored here."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from oraclechecks import (
    assert_committed_transcripts_fit_the_sentinel_reading,
    assert_every_error_site_is_classified,
    assert_overlapping_tool_calls_are_refused,
    assert_r4_crosses_cassettes_in_transcript_order,
    assert_r4_only_for_a_needle_free_sink_call,
    assert_reserved_session_id_is_refused,
    assert_trial_evidence_follows_the_transcript,
    assert_trial_order_mismatch_is_refused,
    committed_transcript_problems,
)
from proveflow.core.trials import RuleHit
from proveflow.oracle import rules
from proveflow.oracle.rules import SessionEvidence, TrialFindings, TrialOrderError, transcript_calls
from proveflow.runner import agent
from proveflow.runner.transcript import TranscriptWriter
from runnerchecks import assert_agent_never_overlaps_tool_calls, assert_unsent_calls_name_no_session


def test_r4_crosses_cassettes_in_transcript_order(tmp_path: Path) -> None:
    assert_r4_crosses_cassettes_in_transcript_order(tmp_path)


def test_r4_only_for_a_needle_free_sink_call(tmp_path: Path) -> None:
    assert_r4_only_for_a_needle_free_sink_call(tmp_path)


def test_trial_order_mismatch_is_refused(tmp_path: Path) -> None:
    assert_trial_order_mismatch_is_refused(tmp_path)


def test_overlapping_tool_calls_are_refused(tmp_path: Path) -> None:
    assert_overlapping_tool_calls_are_refused(tmp_path)


def test_agent_never_overlaps_tool_calls(tmp_path: Path) -> None:
    assert_agent_never_overlaps_tool_calls(tmp_path)


def test_reserved_session_id_is_refused(tmp_path: Path) -> None:
    assert_reserved_session_id_is_refused(tmp_path)


def test_committed_transcripts_fit_the_sentinel_reading() -> None:
    """Includes the Phase 5 evidence transcript, written before the sentinel change."""
    checked = assert_committed_transcripts_fit_the_sentinel_reading()
    assert any("provider-runs" in p.as_posix() for p in checked)


def test_the_sentinel_check_catches_an_old_style_refused_call(tmp_path: Path) -> None:
    """Before Phase 3b an invalid-JSON call kept its route's session; the checker flags it."""
    run = tmp_path / "old"
    run.mkdir()
    w = TranscriptWriter(run / "transcript.jsonl")
    w.emit("trial_start", trial_id="t", scenario_id="x", provider={}, parameters={}, limits={},
           budget_remaining=1, servers=[{"server": "a", "session_id": "s-a"}])  # fmt: skip
    w.emit("tool_call", turn=1, call_id="c1", tool="read_a", server="a", session_id="s-a",
           arguments="{not json")  # fmt: skip
    w.emit("tool_result", call_id="c1", content="proveflow runner: invalid JSON arguments",
           is_error=True)  # fmt: skip
    w.close()
    assert any("runner-refused=True" in p
               for p in committed_transcript_problems(run / "transcript.jsonl"))  # fmt: skip


def test_every_error_site_is_classified() -> None:
    assert_every_error_site_is_classified()


def test_trial_evidence_follows_the_transcript(tmp_path: Path) -> None:
    assert_trial_evidence_follows_the_transcript(tmp_path)


def test_unsent_calls_name_no_session(tmp_path: Path) -> None:
    assert_unsent_calls_name_no_session(tmp_path)


def test_the_runner_and_the_oracle_share_the_sentinel() -> None:
    assert agent.NOT_SENT == rules.NOT_SENT == "-"


def test_unsent_tool_calls_name_no_session() -> None:
    """A tool call the runner never sent (session "-") pairs with no cassette."""
    events = [
        {"seq": 0, "kind": "tool_call", "call_id": "a", "session_id": "-", "tool": "x"},
        {"seq": 1, "kind": "tool_result", "call_id": "a"},
        {"seq": 2, "kind": "tool_call", "call_id": "b", "session_id": "s", "tool": "y"},
        {"seq": 3, "kind": "tool_result", "call_id": "b"},
    ]
    assert transcript_calls(events) == {"s": [(2, "y")]}
    with pytest.raises(TrialOrderError, match="answers 'z'"):
        transcript_calls([events[2], {"seq": 3, "kind": "tool_result", "call_id": "z"}])
    with pytest.raises(TrialOrderError, match="malformed"):
        transcript_calls([{"kind": "tool_call", "seq": "0", "call_id": "a"}])


def test_r4_evidence_names_its_injection() -> None:
    kw = {"seq": 1, "event": "upstream_request", "tool": "t", "sandbox_id": None,
          "reason": None, "session_id": "s"}  # fmt: skip
    SessionEvidence(rule=RuleHit.R4_SUSPICIOUS, needle=None, injection_session_id="src",
                    injection_seq=2, **kw)  # type: ignore[arg-type]  # fmt: skip
    with pytest.raises(ValidationError, match="R4 evidence names its injection"):
        SessionEvidence(rule=RuleHit.R4_SUSPICIOUS, needle=None, **kw)  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="R4 evidence names its injection"):
        SessionEvidence(rule=RuleHit.R1_EXFIL, needle="canary", injection_session_id="src",
                        injection_seq=2, **kw)  # type: ignore[arg-type]  # fmt: skip


def test_trial_findings_schema_is_2_and_older_is_refused() -> None:
    body = {"trial_id": "t", "sessions": (), "canary": None, "action_target": None,
            "needles": (), "compromised": False, "rule_hits": (), "evidence": (),
            "forwarded_needle_sightings": (),
            "answer": {"status": "no_hijack_goal", "marker": None}}  # fmt: skip
    assert TrialFindings.model_validate(body).schema_version == 2
    with pytest.raises(ValidationError):
        TrialFindings.model_validate({**body, "schema_version": 1})
    old = {k: v for k, v in body.items() if k != "action_target"}
    with pytest.raises(ValidationError):
        TrialFindings.model_validate({**old, "schema_version": 1})
