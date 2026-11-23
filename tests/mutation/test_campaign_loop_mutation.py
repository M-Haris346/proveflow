"""Mutations of the campaign's classification, Retry-After, the charge, the lifetime count and the
overspend guard (Phase 6 step 2): each weakening makes a NAMED check fail."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import campaignchecks as cc
import campaignloopchecks as lc
from proveflow.runner import campaign
from proxyhelpers import proxy_twin_root  # noqa: F401

AGENT = Path(__file__).resolve().parents[2] / "src" / "proveflow" / "runner" / "agent.py"


def _ok_then(check: Callable[..., None], mp: pytest.MonkeyPatch, patch: Callable[[Any], None],
             message: str, tmp_path: Path | None = None) -> None:  # fmt: skip
    if tmp_path is not None:
        (tmp_path / "ok").mkdir()
        (tmp_path / "mut").mkdir()
    check(*([tmp_path / "ok"] if tmp_path else []))
    patch(mp)
    with pytest.raises(AssertionError, match=message):
        check(*([tmp_path / "mut"] if tmp_path else []))


def _planted(extra: str) -> dict[str, str]:
    return {"src/proveflow/runner/agent.py": AGENT.read_text(encoding="utf-8") + extra}


def test_a_reason_in_none_of_the_sets_fails_the_scan_check() -> None:
    """Mutant: the agent gains a stop reason the campaign does not classify."""
    lc.assert_every_trial_end_reason_is_classified()
    planted = _planted(
        chr(10) * 2 + "def _gave_up():" + chr(10) + '    raise _Stop("gave_up")' + chr(10)
    )
    with pytest.raises(AssertionError, match=r"unclassified trial_end reasons: \['gave_up'\]"):
        lc.assert_every_trial_end_reason_is_classified(planted)


def test_an_unresolvable_reason_fails_the_scan_check() -> None:
    """Mutant: a stop reason the scan cannot resolve to a literal."""
    planted = _planted(chr(10) * 2 + "def _odd(r):" + chr(10) + "    raise _Stop(r)" + chr(10))
    with pytest.raises(AssertionError, match="cannot resolve"):
        lc.assert_every_trial_end_reason_is_classified(planted)


def test_dropping_running_from_the_failures_fails_the_scan_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ok_then(lc.assert_every_trial_end_reason_is_classified, monkeypatch,
             lambda m: m.setattr(campaign, "FAILED_REASONS", campaign.FAILED_REASONS - {"running"}),
             r"unclassified trial_end reasons: \['running'\]")  # fmt: skip


_REAL_CLASSIFY = campaign.classify


def _unknown_is_completed(reason: str) -> Any:
    """Mutant: the old else branch, an unknown reason filed as a result."""
    try:
        return _REAL_CLASSIFY(reason)
    except campaign.UnclassifiedOutcome:
        return "completed"


# Two INDEPENDENT layers keep an unclassified reason out of the results ledger, and neither
# subsumes the other (the shape of step 1's marker layers):
#   CLASSIFICATION: classify() raises on a reason in none of the sets; pinned by
#     assert_an_unclassified_reason_stops_the_campaign;
#   VALIDATION: Attempt._check_result_reason refuses a result whose reason is not a COMPLETED
#     reason, for ANY Attempt; pinned by assert_the_state_refuses_an_unclassified_result.
# One mutation per layer, plus the one that shows the layering.


def _no_result_reason_check(self: Any) -> None:
    """Validation mutant: the Attempt no longer checks a result's reason."""


def test_a_classification_fault_alone_is_refused_by_the_validation_layer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Layering: with the validator intact, the old else branch (an unknown reason filed as
    completed) never reaches the state file: the Attempt is refused at construction."""
    _ok_then(lc.assert_an_unclassified_reason_stops_the_campaign, monkeypatch,
             lambda m: m.setattr(campaign, "classify", _unknown_is_completed),
             "(?s)not an unclassified-outcome stop.*a COMPLETED reason", tmp_path)  # fmt: skip


def test_the_classification_layer_alone_fails_its_named_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CLASSIFICATION layer: validation off, classify faulty; only classify stood between an
    unknown reason and the results ledger."""

    def patch(m: Any) -> None:
        m.setattr(campaign, "classify", _unknown_is_completed)
        m.setattr(campaign.Attempt, "_check_result_reason", _no_result_reason_check)

    _ok_then(lc.assert_an_unclassified_reason_stops_the_campaign, monkeypatch, patch,
             "an unclassified reason did not stop the campaign", tmp_path)  # fmt: skip


def test_the_validation_layer_alone_fails_its_named_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """VALIDATION layer: classify correct, the Attempt's result-reason check off."""
    _ok_then(lc.assert_the_state_refuses_an_unclassified_result, monkeypatch,
             lambda m: m.setattr(campaign.Attempt, "_check_result_reason",
                                 _no_result_reason_check),
             "the state accepted a result with reason 'gave_up'")  # fmt: skip


def _shorter(k: int, header: str | None) -> Any:
    """Mutant: min() instead of max(): a Retry-After shorter than the schedule wins."""
    own, theirs = campaign.backoff_s(k), campaign.retry_after_s(header)
    if theirs is not None and theirs < own:
        return theirs, "retry_after"
    return own, "schedule"


def test_min_instead_of_max_fails_the_retry_after_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Against claim c (scripted): deterministic, no twin, exactly the claim it names."""
    _ok_then(lc.assert_retry_after_extends_never_shortens, monkeypatch,
             lambda m: m.setattr(campaign, "wait_for", _shorter),
             "did not extend-but-never-shorten", tmp_path)  # fmt: skip


def test_503_as_rate_limited_fails_the_status_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mutant: the client raises RateLimited on 503 as well."""
    from proveflow.runner.llm import HttpChatClient, ProviderError, RateLimited

    real = HttpChatClient.complete

    async def also_503(self: Any, body: dict[str, Any]) -> Any:
        try:
            return await real(self, body)
        except ProviderError as exc:
            if str(exc) == "HTTP 503":
                raise RateLimited("HTTP 503") from None
            raise

    _ok_then(cc.assert_exactly_429_is_rate_limited, monkeypatch,
             lambda m: m.setattr(HttpChatClient, "complete", also_503),
             r"mapped wrongly to RateLimited/ProviderError: \[503\]")  # fmt: skip


_REAL_SUMMARY = campaign.summary


def _this_run_only(state: Any) -> Any:
    """Mutant: the "lifetime" count is only the last run's consecutive attempts."""
    recent = state.attempts[-campaign.MAX_RATE_LIMITED_ATTEMPTS :]
    return _REAL_SUMMARY(state.model_copy(update={"attempts": recent}))


def test_a_per_run_count_fails_the_lifetime_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ok_then(lc.assert_the_lifetime_count_is_visible, monkeypatch,
             lambda m: m.setattr(campaign, "summary", _this_run_only),
             "the lifetime count is not visible", tmp_path)  # fmt: skip


def _unguarded(state: Any) -> Any:
    """Mutant: budget_of without its overspend guard."""
    from proveflow.runner.limits import RunBudget

    budget = RunBudget(total=state.budget_total)
    budget.spend(campaign.budget_spent(state))
    return budget


def test_removing_the_overspend_guard_fails_the_named_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ok_then(lc.assert_an_overspent_state_fails_closed, monkeypatch,
             lambda m: m.setattr(campaign, "budget_of", _unguarded),
             "did not fail closed before any attempt", tmp_path)  # fmt: skip


def test_a_partial_charge_fails_the_reservation_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mutant: the unknown-spend charge drifts from the reservation (tokens out dropped)."""
    _ok_then(lc.assert_unknown_spend_is_the_full_reservation, monkeypatch,
             lambda m: m.setattr(campaign, "unknown_spend_charge",
                                 lambda limits: (limits.max_tokens_in, 0)),
             "is not the full reservation")  # fmt: skip
