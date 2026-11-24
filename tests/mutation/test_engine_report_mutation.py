"""Mutations of the campaign engine's sampler and of the report (Phase 7.1, 7.2): each mutant is
the defect its named check exists to catch, and each named check must fail on it."""

from __future__ import annotations

import random
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import enginechecks as ec
from proveflow.runner import engine, report
from proveflow.runner.campaign import SamplingRecord, SourceDraw


def _ok_then(check: Callable[[Path], Any], tmp_path: Path, mp: pytest.MonkeyPatch,
             patch: Callable[[pytest.MonkeyPatch], None], message: str) -> None:  # fmt: skip
    (tmp_path / "ok").mkdir()
    (tmp_path / "mut").mkdir()
    check(tmp_path / "ok")
    patch(mp)
    with pytest.raises(AssertionError, match=message):
        check(tmp_path / "mut")


def _by_source(records: Any) -> dict[str, list[Any]]:
    out: dict[str, list[Any]] = {}
    for r in records:
        out.setdefault(r.source_dataset, []).append(r)
    return dict(sorted(out.items(), key=lambda kv: (engine._source_rank(kv[0]), kv[0])))


def proportional(records: Any, *, per_source_n: int, seed: int) -> Any:
    """MUTANT: a PROPORTIONAL allocation of the same total (BIPIA's share would dominate)."""
    groups = _by_source(records)
    total, population = per_source_n * len(groups), len(list(records))
    drawn: list[Any] = []
    per: dict[str, SourceDraw] = {}
    for source, pool in groups.items():
        k = min(len(pool), round(total * len(pool) / population))
        pool = sorted(pool, key=lambda r: r.id)
        rng = random.Random(f"{seed}:{source}")  # noqa: S311 (a mutant of a sampling draw)
        drawn += sorted(rng.sample(pool, k), key=lambda r: r.id)
        per[source] = SourceDraw(population=len(pool), drawn=k)
    return drawn, SamplingRecord(seed=seed, per_source_n=per_source_n, per_source=per)


def family_seeded(records: Any, *, per_source_n: int, seed: int) -> Any:
    """MUTANT: the draw depends on attack_family (a per-source taxonomy, never an axis)."""
    groups = _by_source(records)
    drawn: list[Any] = []
    per: dict[str, SourceDraw] = {}
    for source, pool in groups.items():
        pool = sorted(pool, key=lambda r: r.id)
        k = min(per_source_n, len(pool))
        families = ",".join(sorted({r.attack_family or "" for r in pool}))
        rng = random.Random(f"{seed}:{source}:{families}")  # noqa: S311 (a mutant)
        drawn += sorted(rng.sample(pool, k), key=lambda r: r.id)
        per[source] = SourceDraw(population=len(pool), drawn=k)
    return drawn, SamplingRecord(seed=seed, per_source_n=per_source_n, per_source=per)


def test_a_proportional_allocation_fails_the_sampler_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ok_then(ec.assert_the_sampler_is_stratified_seeded_and_recorded, tmp_path, monkeypatch,
             lambda m: m.setattr(engine, "sample_records", proportional),
             "not equal per source")  # fmt: skip


def test_a_family_dependent_draw_fails_the_sampler_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ok_then(ec.assert_the_sampler_is_stratified_seeded_and_recorded, tmp_path, monkeypatch,
             lambda m: m.setattr(engine, "sample_records", family_seeded),
             "attack_family changed the draw")  # fmt: skip


def test_counting_every_attempt_fails_the_results_ledger_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D7: one per attempt is one per transcript on disk; the rate-limited attempt would count."""
    _ok_then(ec.assert_aggregation_reads_only_the_results_ledger, tmp_path, monkeypatch,
             lambda m: m.setattr(report, "counted_trials",
                                 lambda s: [(a.trial_key, a) for a in s.attempts]),
             "did not read the results ledger only")  # fmt: skip


def test_folding_limit_ended_trials_into_final_answer_fails_the_ledger_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BACKLOG "Limit-ended trials are counted results": their number per reason is reported."""
    _ok_then(ec.assert_aggregation_reads_only_the_results_ledger, tmp_path, monkeypatch,
             lambda m: m.setattr(report, "ended_by", lambda t: {"final_answer": len(t)}),
             "not reported by reason")  # fmt: skip


def test_a_pooled_line_in_the_text_fails_the_no_pooled_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = report.format_report

    def pooled(r: Any) -> str:
        n = sum(x.trials for x in r.per_source)
        k = sum(x.compromised for x in r.per_source)
        return original(r) + chr(10) + f"  total: {k}/{n} compromised, Wilson 95% [0, 1]"

    _ok_then(ec.assert_no_pooled_figure_is_emitted, tmp_path, monkeypatch,
             lambda m: m.setattr(report, "format_report", pooled), "rate lines")  # fmt: skip


def test_a_pooled_field_in_the_json_fails_the_no_pooled_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    original = report.report_bytes

    def pooled(r: Any) -> bytes:
        body = json.loads(original(r))
        body["pooled_rate"] = 0.5
        return json.dumps(body).encode("utf-8")

    _ok_then(ec.assert_no_pooled_figure_is_emitted, tmp_path, monkeypatch,
             lambda m: m.setattr(report, "report_bytes", pooled),
             "fields beyond the per-source rows")  # fmt: skip


def test_dropping_the_note_from_the_text_fails_the_note_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = report.format_report

    def silent(r: Any) -> str:
        return chr(10).join(ln for ln in original(r).splitlines() if "NOTE:" not in ln)

    _ok_then(ec.assert_the_lower_bound_note_is_beside_the_numbers, tmp_path, monkeypatch,
             lambda m: m.setattr(report, "format_report", silent),
             "required note is missing")  # fmt: skip


def test_dropping_the_note_from_the_json_fails_the_note_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = report.aggregate
    _ok_then(ec.assert_the_lower_bound_note_is_beside_the_numbers, tmp_path, monkeypatch,
             lambda m: m.setattr(report, "aggregate",
                                 lambda s: original(s).model_copy(update={"notes": ()})),
             "required note is missing")  # fmt: skip


def test_removing_the_docs_results_guard_fails_the_scripted_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ok_then(ec.assert_scripted_data_never_reaches_docs_results, tmp_path, monkeypatch,
             lambda m: m.setattr(report, "_under_docs_results", lambda p: False),
             "written under docs/results")  # fmt: skip


def test_removing_the_model_side_guard_fails_the_scripted_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guard's second layer is the report's type (model_side is not Optional): with the
    guard gone pydantic still refuses, and the check names that the guard did not."""
    original = report.aggregate

    def unguarded(s: Any) -> Any:
        if s.model_side is None:
            s = s.model_copy(update={"model_side": "provider"})  # the mutant guesses a side
        return original(s)

    _ok_then(ec.assert_scripted_data_never_reaches_docs_results, tmp_path, monkeypatch,
             lambda m: m.setattr(report, "aggregate", unguarded),
             "no recorded model side was aggregated")  # fmt: skip


def test_dropping_the_limits_in_the_engine_fails_the_limits_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MUTANT: F3's defect: run_trial is called WITHOUT the campaign's limits (defaults)."""
    from proveflow.runner import trial

    original = trial.run_trial

    async def dropped(*args: Any, **kwargs: Any) -> Any:
        kwargs.pop("limits", None)
        return await original(*args, **kwargs)

    _ok_then(ec.assert_the_trial_runs_with_the_campaigns_limits, tmp_path, monkeypatch,
             lambda m: m.setattr(trial, "run_trial", dropped), "ran with other limits")  # fmt: skip
