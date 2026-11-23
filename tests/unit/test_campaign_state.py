"""Campaign state, the two ledgers and the backoff schedule (Phase 6 step 2; D4). Pure, offline."""

from __future__ import annotations

from pathlib import Path

import httpx2
import pytest
from pydantic import ValidationError

from proveflow.runner import campaign as c
from proveflow.runner.campaign import Attempt, CampaignState

REASON = {"completed": "final_answer", "rate_limited": "rate_limited", "failed": "provider_error"}


def _a(key: str, n: int, status: str, tin: int = 100, tout: int = 10) -> Attempt:
    verdict = {"compromised": False} if status == "completed" else None
    return Attempt(trial_key=key, number=n, status=status, reason=REASON[status], tokens_in=tin,  # type: ignore[arg-type]
                   tokens_out=tout, usage_source="transcript", verdict=verdict)  # fmt: skip


def test_reason_and_exception_are_two_fields_tied_to_the_status() -> None:
    """A runner reason and an exception are never the same field (item 5): each status takes
    only the kind of value it can carry."""
    base = {"trial_key": "t1", "number": 1, "usage_source": "transcript"}
    Attempt(**base, status="failed", exception="ExceptionGroup[RuntimeError]")  # type: ignore[arg-type]
    Attempt(**base, status="failed", reason="gave_up")  # type: ignore[arg-type]  # unclassified stop
    bad = [
        {"status": "failed", "reason": "provider_error", "exception": "RuntimeError"},
        {"status": "failed"},
        {"status": "failed", "reason": "final_answer"},
        {"status": "rate_limited", "reason": "provider_error"},
        {"status": "completed", "reason": "gave_up", "verdict": {"x": 1}},
        {"status": "interrupted", "reason": "interrupted"},
        {"status": "completed", "exception": "RuntimeError", "verdict": {"x": 1}},
    ]
    for fields in bad:
        with pytest.raises(ValidationError):
            Attempt(**base, **fields)  # type: ignore[arg-type]


STATE = CampaignState(campaign_id="c1", budget_total=10_000, plan=("t1", "t2"),
                      attempts=(_a("t1", 1, "rate_limited"), _a("t1", 2, "completed"),
                                _a("t2", 1, "failed")))  # fmt: skip


def test_the_budget_ledger_is_every_attempt() -> None:
    assert c.budget_spent(STATE) == 3 * 110
    assert c.budget_of(STATE).remaining == 10_000 - 330


def test_the_results_ledger_is_each_completed_trial_once() -> None:
    assert {k: a.number for k, a in c.results(STATE).items()} == {"t1": 2}


def test_at_most_one_completed_attempt_per_trial() -> None:
    with pytest.raises(ValidationError, match="an attempt after 't1' completed"):
        CampaignState(campaign_id="c1", budget_total=10, plan=("t1",),
                      attempts=(_a("t1", 1, "completed"), _a("t1", 2, "completed")))  # fmt: skip


def test_the_state_validator_refuses_inconsistent_attempts() -> None:
    with pytest.raises(ValidationError, match="not 1, 2"):
        CampaignState(campaign_id="c1", budget_total=10, plan=("t1",),
                      attempts=(_a("t1", 2, "failed"),))  # fmt: skip
    with pytest.raises(ValidationError, match="not in the plan"):
        CampaignState(campaign_id="c1", budget_total=10, plan=("t1",),
                      attempts=(_a("t9", 1, "failed"),))  # fmt: skip
    with pytest.raises(ValidationError, match="only the last attempt"):
        CampaignState(campaign_id="c1", budget_total=10, plan=("t1", "t2"),
                      attempts=(Attempt(trial_key="t1", number=1, status="started"),
                                _a("t2", 1, "failed")))  # fmt: skip
    with pytest.raises(ValidationError, match="carries a verdict"):
        Attempt(trial_key="t1", number=1, status="failed", usage_source="transcript",
                verdict={"x": 1})  # fmt: skip
    with pytest.raises(ValidationError, match="no usage yet"):
        Attempt(trial_key="t1", number=1, status="started", tokens_in=5)


def test_state_round_trips_and_a_flipped_byte_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "s.json"
    c.save_state(path, STATE)
    assert c.load_state(path) == STATE
    assert not (tmp_path / "s.json.tmp").exists()
    lowered = path.read_text(encoding="utf-8").replace('"tokens_in": 100', '"tokens_in": 1', 1)
    path.write_text(lowered, encoding="utf-8")
    with pytest.raises(c.CorruptCampaignState, match="sha256 does not match"):
        c.load_state(path)
    path.write_text("{", encoding="utf-8")
    with pytest.raises(c.CorruptCampaignState, match="unreadable"):
        c.load_state(path)
    path.write_text('{"state": {}}', encoding="utf-8")
    with pytest.raises(c.CorruptCampaignState, match="not a campaign state file"):
        c.load_state(path)


def test_backoff_schedule_doubles_and_caps() -> None:
    assert [c.backoff_s(k) for k in range(1, 8)] == [2.0, 4.0, 8.0, 16.0, 32.0, 60.0, 60.0]
    with pytest.raises(ValueError, match="k starts at 1"):
        c.backoff_s(0)


def test_attempt_ids_are_valid_session_id_prefixes() -> None:
    import re

    from proveflow.proxy.session import SESSION_ID_PATTERN

    assert c.attempt_id("t1", 3) == "t1-a3"
    assert re.fullmatch(SESSION_ID_PATTERN, c.attempt_id("a" * 41, 99) + ".server")


def test_http_429_is_rate_limited_even_with_a_non_json_body() -> None:
    import anyio

    from proveflow.config import ProviderConfig
    from proveflow.runner.llm import HttpChatClient, ProviderError, RateLimited

    cfg = ProviderConfig(name="p", base_url="https://example.invalid/v1", model="m",
                         api_key_env="PF_UNUSED", send_seed=False)  # fmt: skip
    for status, body, kind in ((429, b"slow down", RateLimited), (500, b"{}", ProviderError)):
        client = HttpChatClient(cfg, environ={"PF_UNUSED": "x"}, transport=httpx2.MockTransport(
            lambda r, s=status, b=body: httpx2.Response(s, content=b)))  # fmt: skip
        with pytest.raises(kind) as info:
            anyio.run(client.complete, {"model": "m"})
        assert (type(info.value) is RateLimited) == (status == 429)
