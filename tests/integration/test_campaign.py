"""429 and campaign resume on REAL trials (Phase 6 step 2; D3, D4): only the claims about a real
transcript or real proxy wiring, on real twins, real proxies and the fake provider
(HttpChatClient over MockTransport). Offline. The loop's arithmetic and state file run
scripted (tests/unit/test_campaign_loop.py)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from campaignchecks import (
    assert_a_429_ends_the_attempt,
    assert_resume_rebuilds_the_budget_from_attempt_usage,
    assert_retry_after_reaches_the_outcome,
)
from campaignloopchecks import assert_running_never_reaches_trial_end
from proxyhelpers import proxy_twin_root  # noqa: F401


def test_a_429_ends_the_attempt(tmp_path: Path, proxy_twin_root: Any) -> None:  # noqa: F811
    assert_a_429_ends_the_attempt(tmp_path)


def test_resume_rebuilds_the_budget_from_attempt_usage(
    tmp_path: Path,
    proxy_twin_root: Any,  # noqa: F811
) -> None:
    """Kept REAL: it reads run_trial's own trial_start.budget_remaining, and the usage a real
    429-ended and a real 500-ended attempt recorded before failing."""
    assert_resume_rebuilds_the_budget_from_attempt_usage(tmp_path)


def test_running_never_reaches_trial_end(tmp_path: Path, proxy_twin_root: Any) -> None:  # noqa: F811
    assert_running_never_reaches_trial_end(tmp_path)


def test_retry_after_reaches_the_outcome(tmp_path: Path, proxy_twin_root: Any) -> None:  # noqa: F811
    """Claim b: the wiring, client through agent to outcome, on ONE real trial."""
    assert_retry_after_reaches_the_outcome(tmp_path)
