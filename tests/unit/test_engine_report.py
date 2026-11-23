"""Phase 7.1 and 7.2 offline: the stratified sampler, the results-ledger-only aggregation, no
pooled figure, the lower-bound note, scripted data refused under docs/results/, fail closed.
SCRIPTED attempts only (no twin, no provider): see tests/enginechecks.py."""

from __future__ import annotations

from pathlib import Path

import enginechecks


def test_the_sampler_is_stratified_seeded_and_recorded(tmp_path: Path) -> None:
    enginechecks.assert_the_sampler_is_stratified_seeded_and_recorded(tmp_path)


def test_aggregation_reads_only_the_results_ledger(tmp_path: Path) -> None:
    enginechecks.assert_aggregation_reads_only_the_results_ledger(tmp_path)


def test_no_pooled_figure_is_emitted(tmp_path: Path) -> None:
    enginechecks.assert_no_pooled_figure_is_emitted(tmp_path)


def test_the_lower_bound_note_is_beside_the_numbers(tmp_path: Path) -> None:
    enginechecks.assert_the_lower_bound_note_is_beside_the_numbers(tmp_path)


def test_scripted_data_never_reaches_docs_results(tmp_path: Path) -> None:
    enginechecks.assert_scripted_data_never_reaches_docs_results(tmp_path)


def test_the_engine_fails_closed(tmp_path: Path) -> None:
    enginechecks.assert_the_engine_fails_closed(tmp_path)


def test_a_resume_with_another_draw_is_refused(tmp_path: Path) -> None:
    """The state pins the draw: resuming with another seed is another campaign (fail closed)."""
    import anyio
    import pytest

    from proveflow.core.attacks import Carrier
    from proveflow.runner.campaign import CorruptCampaignState
    from proveflow.runner.engine import run_engine

    enginechecks.scripted_engine(tmp_path, {k: list(v) for k, v in enginechecks.MIXED.items()})
    fn = enginechecks.ScriptedCells(tmp_path / "out", {})

    async def go() -> object:
        return await run_engine(enginechecks.corpus(tmp_path), campaign_id="smoke",
                                state_path=tmp_path / "smoke.campaign.json",
                                out_dir=tmp_path / "out", budget_total=500_000,
                                per_source_n=enginechecks.PER_SOURCE, seed=8,
                                carriers=[Carrier.PLAIN], goals=enginechecks.GOALS,
                                models=["scripted-model"], model_side="scripted",
                                attempt_for=fn)  # fmt: skip

    with pytest.raises(CorruptCampaignState):
        anyio.run(go)
    assert fn.calls == 0


def test_per_source_n_below_one_is_refused(tmp_path: Path) -> None:
    import pytest

    from proveflow.runner.engine import sample_records

    with pytest.raises(ValueError, match="at least 1"):
        sample_records(enginechecks.corpus(tmp_path), per_source_n=0, seed=7)
