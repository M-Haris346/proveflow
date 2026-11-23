"""The runner end to end (Phase 5), driven ONLY by strict replay of committed transcripts:
one agent, two generated twins, two real in-process proxies. No provider, no network."""

from __future__ import annotations

import os
from pathlib import Path

import anyio
import pytest

from proveflow.config import ProviderConfig
from proveflow.core.trials import RuleHit
from proveflow.proxy import policy as policy_module
from proveflow.runner.limits import BudgetExhausted, RunBudget, TrialLimits
from proveflow.runner.llm import ReplayChatClient, ReplayMismatch
from proveflow.runner.transcript import load_transcript, verify_cassette_refs
from proveflow.runner.trial import MissingTimings, run_trial
from proxyhelpers import proxy_twin_root  # noqa: F401
from runnerchecks import (
    AUTHORED,
    assert_calls_landed_in_their_own_cassettes,
    assert_cap_fires,
    fixture_scenario,
    replay,
)


def test_two_proxies_each_call_lands_in_its_own_cassette(tmp_path: Path) -> None:
    assert_calls_landed_in_their_own_cassettes(replay(tmp_path, "cross_server_exfil"))


def test_cross_server_honey_exfil_is_r1_and_utility_holds(tmp_path: Path) -> None:
    r = replay(tmp_path, "cross_server_exfil")
    assert r.outcome.reason == "final_answer" and r.utility is True
    assert r.verdict.compromised and r.verdict.rule_hits == (RuleHit.R1_EXFIL,)
    [ev] = [e for e in r.findings.evidence if e.rule is RuleHit.R1_EXFIL]
    assert ev.session_id == "cross_server_exfil.fetch" and ev.event == "upstream_request"
    assert ev.needle.startswith("cross_server_exfil.filesystem:h")  # honey from the OTHER twin
    assert r.verdict.trial_id == "cross_server_exfil"
    assert r.latency_recorded and r.verdict.latency_ms == 42.0  # the recorded sidecar's value
    assert r.verdict.tokens_in == r.outcome.tokens_in
    assert r.verdict.tokens_out == r.outcome.tokens_out


def test_clean_trial_has_utility_and_no_hits(tmp_path: Path) -> None:
    r = replay(tmp_path, "clean_utility")
    assert r.utility is True and not r.verdict.compromised and r.verdict.rule_hits == ()
    assert r.findings.is_evidence_of_safety


def test_new_transcript_references_its_cassettes(tmp_path: Path) -> None:
    r = replay(tmp_path, "cross_server_exfil")
    events = load_transcript(r.transcript)
    assert verify_cassette_refs(events, r.transcript.parent) == list(r.cassettes)


def test_replay_without_a_timings_sidecar_fails_loudly(tmp_path: Path) -> None:
    with pytest.raises(MissingTimings, match="latency_ms cannot be reported"):
        replay(tmp_path, "cross_server_exfil", timings=False)


def test_a_changed_request_is_a_replay_mismatch(tmp_path: Path) -> None:
    changed = fixture_scenario("clean_utility").model_copy(update={"task": "Something else."})
    with pytest.raises(ReplayMismatch):
        replay(tmp_path, "clean_utility", scenario=changed)


@pytest.mark.parametrize(
    ("field", "value", "limit"),
    [("max_turns", 2, "max_turns"), ("max_tool_calls", 1, "max_tool_calls"),
     ("max_tokens_in", 1000, "max_tokens_in")],
)  # fmt: skip
def test_each_cap_fails_closed(tmp_path: Path, field: str, value: int, limit: str) -> None:
    assert_cap_fires(tmp_path, TrialLimits.model_validate({field: value}), limit)


def test_the_out_token_cap_fails_closed(tmp_path: Path) -> None:
    assert_cap_fires(tmp_path, TrialLimits(max_tokens_out=4000), "max_tokens_out", 5000)


def test_the_budget_refuses_before_anything_is_created(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()

    async def go() -> None:
        await run_trial(
            fixture_scenario("clean_utility"), trial_id="nobudget",
            llm=ReplayChatClient([]), provider=ProviderConfig(**AUTHORED), temperature=0.0,
            seed=0, out_dir=out, twin_dir=policy_module.TWIN_ROOT,
            budget=RunBudget(total=1000), parent_env=dict(os.environ),
        )  # fmt: skip

    with pytest.raises(BudgetExhausted, match="refusing to start"):
        anyio.run(go)
    assert list(out.iterdir()) == []


@pytest.mark.parametrize("status", [400, 401, 429, 500])
def test_a_provider_error_ends_the_trial_fail_closed(tmp_path: Path, status: int) -> None:
    """No retry INSIDE a trial: any non-200 ends the trial, the error is recorded, nothing more
    is sent, and the trial still gets a verdict. Every status ends it as provider_error except
    429, which since Phase 6 (D3) ends it as rate_limited: the CAMPAIGN backs off and starts a
    new attempt (runner.campaign); the trial itself still sends exactly one request."""
    import httpx2

    from proveflow.runner.llm import HttpChatClient

    sent: list[object] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        return httpx2.Response(status, json={"error": {"message": "x"}})

    provider = ProviderConfig(**AUTHORED)
    client = HttpChatClient(provider, environ={"PF_AUTHORED_UNUSED": "x"},
                            transport=httpx2.MockTransport(handler))  # fmt: skip
    out = tmp_path / "out"
    out.mkdir()

    async def go() -> object:
        return await run_trial(
            fixture_scenario("clean_utility"), trial_id="err", llm=client, provider=provider,
            temperature=0.0, seed=0, out_dir=out, twin_dir=policy_module.TWIN_ROOT,
            budget=RunBudget(), parent_env=dict(os.environ),
        )  # fmt: skip

    r = anyio.run(go)
    errors = [e for e in load_transcript(r.transcript) if e.kind == "error"]  # type: ignore[attr-defined]
    kind = "rate_limited" if status == 429 else "provider_error"
    assert r.outcome.reason == kind and len(sent) == 1  # type: ignore[attr-defined]
    assert [(e.error_kind, e.detail) for e in errors] == [(kind, f"HTTP {status}")]
    assert r.utility is False and not r.verdict.compromised  # type: ignore[attr-defined]
