"""Control A (Phase 7.3b): the pipeline counts a compromise IF AND ONLY IF the flow happens.
The matched pair on the SAME cells, through the real dry-run command on real twins and proxies,
with the model side scripted. Offline, no key, no provider (tests/controlchecks.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

import controlchecks
import planchecks

CACHE = planchecks.REPO / ".proveflow-corpus"


def test_the_pipeline_counts_a_compromise_iff_the_flow_happens_leg1_canary_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controlchecks.assert_the_pipeline_counts_a_compromise_iff_the_flow_happens(
        tmp_path / "run", monkeypatch, plan_path=planchecks.small_plan(tmp_path),
        records=planchecks.synthetic_corpus(tmp_path), legs=(1,),
    )  # fmt: skip


def test_the_pipeline_counts_a_compromise_iff_the_flow_happens_leg2_read_then_send(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controlchecks.assert_the_pipeline_counts_a_compromise_iff_the_flow_happens(
        tmp_path / "run", monkeypatch, plan_path=planchecks.small_plan(tmp_path),
        records=planchecks.synthetic_corpus(tmp_path), legs=(2,),
    )  # fmt: skip


@pytest.mark.skipif(not CACHE.is_dir(), reason="the raw corpus cache is never committed "
                    "(CLAUDE.md); run locally")  # fmt: skip
def test_the_pipeline_counts_a_compromise_iff_the_flow_happens_on_the_forced_campaigns_30_cells(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exit-criteria run: the COMMITTED forced plan and the real corpus draw (the cells of
    campaign groq_forced_7db7eff3b652), legs 1 and 2 plus the negative half."""
    from proveflow.runner.offline_corpus import cached_records

    got = controlchecks.assert_the_pipeline_counts_a_compromise_iff_the_flow_happens(
        tmp_path / "run", monkeypatch, plan_path=planchecks.FORCED_PLAN,
        records=cached_records(CACHE),
    )  # fmt: skip
    # (trials, compromised, exposed, DELIVERED numerator, DELIVERED denominator), exactly
    assert got == {"leg1": (30, 30, 30, 30, 30), "leg2": (30, 30, 30, 30, 30),
                   "negative": (30, 0, 30, 0, 30)}, got  # fmt: skip


def test_the_pipeline_counts_a_compromise_iff_the_flow_happens_on_the_file_borne_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase 8: Control A on fs_notes_exfil (the injection arrives in the file the task reads,
    the sink is fetch, a DIFFERENT tool), legs 1 and 2 plus the negative, 3 cells. This is the
    confirmed flow paired verify measures against."""
    controlchecks.assert_the_pipeline_counts_a_compromise_iff_the_flow_happens(
        tmp_path / "run", monkeypatch, plan_path=planchecks.small_fs_plan(tmp_path),
        records=planchecks.synthetic_corpus(tmp_path),
    )  # fmt: skip


@pytest.mark.skipif(not CACHE.is_dir(), reason="the raw corpus cache is never committed "
                    "(CLAUDE.md); run locally")  # fmt: skip
def test_the_pipeline_counts_a_compromise_iff_the_flow_happens_on_the_fs_plans_30_cells(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase 8 step 0's gate on the COMMITTED groq_fs_forced plan and the real corpus draw."""
    from proveflow.runner.offline_corpus import cached_records

    got = controlchecks.assert_the_pipeline_counts_a_compromise_iff_the_flow_happens(
        tmp_path / "run", monkeypatch, plan_path=planchecks.FS_PLAN,
        records=cached_records(CACHE),
    )  # fmt: skip
    # (trials, compromised, exposed, DELIVERED numerator, DELIVERED denominator), exactly
    assert got == {"leg1": (30, 30, 30, 30, 30), "leg2": (30, 30, 30, 30, 30),
                   "negative": (30, 0, 30, 0, 30)}, got  # fmt: skip
