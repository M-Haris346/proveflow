"""Phase 7.1 smoke campaign: six cells on REAL twins and proxies, the model side SCRIPTED
(nothing paid, no network). A 429, a kill mid-attempt, a resume: each completed trial counted
once, every attempt charged. Its report is SCRIPTED and is never written under docs/results/."""

from __future__ import annotations

from pathlib import Path

import enginechecks


def test_the_smoke_campaign_resumes_with_each_trial_once(tmp_path: Path) -> None:
    from proveflow.runner import report

    state = enginechecks.assert_the_smoke_campaign_resumes_with_each_trial_once(tmp_path)
    rep = report.aggregate(state)
    assert rep.model_side == "scripted"
    assert report.SCRIPTED_NOTE in report.format_report(rep)
    assert sum(r.trials for r in rep.per_source) == 6


def test_the_trial_runs_with_the_campaigns_limits(tmp_path: Path) -> None:
    """Phase 7.3a, F3: the campaign's tightened limits reach every trial's run_trial."""
    enginechecks.assert_the_trial_runs_with_the_campaigns_limits(tmp_path)
