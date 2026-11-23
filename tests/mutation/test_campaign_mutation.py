"""Mutations of 429 handling and campaign state (Phase 6 step 2): each weakening makes a NAMED
check fail. The first is THE D4 pin's mutant: the budget rebuilt from completed trials."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import campaignchecks as cc
import campaignloopchecks as lc
from proveflow.runner import campaign
from proxyhelpers import proxy_twin_root  # noqa: F401


def _ok_then(check: Callable[[Path], None], tmp_path: Path, mp: pytest.MonkeyPatch,
             patch: Callable[[pytest.MonkeyPatch], None], message: str) -> None:  # fmt: skip
    (tmp_path / "ok").mkdir()
    (tmp_path / "mut").mkdir()
    check(tmp_path / "ok")
    patch(mp)
    with pytest.raises(AssertionError, match=message):
        check(tmp_path / "mut")


def _completed_only(state: Any) -> int:
    """Mutant (D4): the budget rebuilt from COMPLETED trials, not from every attempt."""
    return sum(a.tokens_in + a.tokens_out for a in state.attempts if a.status == "completed")


def test_rebuilding_the_budget_from_completed_trials_fails_the_resume_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    proxy_twin_root: Any,  # noqa: F811
) -> None:
    _ok_then(cc.assert_resume_rebuilds_the_budget_from_attempt_usage, tmp_path, monkeypatch,
             lambda m: m.setattr(campaign, "budget_spent", _completed_only),
             "the resumed budget was not rebuilt from every attempt's usage")  # fmt: skip


def test_retrying_a_429_inside_the_trial_fails_the_named_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    proxy_twin_root: Any,  # noqa: F811
) -> None:
    """Mutant (D3): the HTTP client retries a 429 itself, inside the trial."""
    from proveflow.runner.llm import HttpChatClient, RateLimited

    real = HttpChatClient.complete

    async def retrying(self: Any, body: dict[str, Any]) -> Any:
        try:
            return await real(self, body)
        except RateLimited:
            return await real(self, body)

    _ok_then(cc.assert_a_429_ends_the_attempt, tmp_path, monkeypatch,
             lambda m: m.setattr(HttpChatClient, "complete", retrying),
             "a 429 was retried inside the trial")  # fmt: skip


def test_a_rate_limited_attempt_as_a_result_fails_the_backoff_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutant (D4, results ledger), the CLASSIFICATION layer alone: a rate-limited attempt
    classified as completed, with the Attempt's result-reason check (the VALIDATION layer)
    off, since with it on the Attempt is refused at construction first (the layering; see
    test_campaign_loop_mutation.py). (Before the allowlist this mutant renamed RATE_LIMITED;
    with the allowlist a renamed reason STOPS the campaign, so the mutant states the claim.)
    Scripted since the cut."""
    real = campaign.classify

    def patch(m: Any) -> None:
        m.setattr(campaign, "classify", lambda r: "completed" if r == "rate_limited" else real(r))
        m.setattr(campaign.Attempt, "_check_result_reason", lambda self: None)

    _ok_then(lc.assert_backoff_between_rate_limited_attempts, tmp_path, monkeypatch, patch,
             "did not back off|each 429 did not end|counted as a result")  # fmt: skip


def test_no_backoff_fails_the_backoff_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ok_then(lc.assert_backoff_between_rate_limited_attempts, tmp_path, monkeypatch,
             lambda m: m.setattr(campaign, "backoff_s", lambda k: 0.0),
             "did not back off 2 s then 4 s")  # fmt: skip


def test_skipping_the_state_hash_fails_the_corrupt_state_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutant (D4): the loader trusts the content without its sha256 (the tampered, lower
    spend is then accepted). Scripted since the cut."""
    real = campaign._digest

    def lenient_load(path: Path) -> Any:
        import json

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            return _REAL_LOAD(path)
        if isinstance(raw, dict) and isinstance(raw.get("state"), dict):
            raw["sha256"] = real(raw["state"])
            path.write_text(json.dumps(raw), encoding="utf-8")
        return _REAL_LOAD(path)

    _ok_then(lc.assert_corrupt_state_fails_closed, tmp_path, monkeypatch,
             lambda m: m.setattr(campaign, "load_state", lenient_load),
             "a tampered state file was accepted")  # fmt: skip


_REAL_LOAD = campaign.load_state


def test_charging_unknown_spend_at_zero_fails_the_interrupted_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutant (D4): an attempt with no readable transcript charged nothing. Scripted since
    the cut."""
    real = campaign.transcript_usage
    _ok_then(lc.assert_an_interrupted_attempt_is_charged, tmp_path, monkeypatch,
             lambda m: m.setattr(campaign, "transcript_usage", lambda p: real(p) or (0, 0)),
             r"an interrupted attempt \(without transcript\) was charged 0")  # fmt: skip
