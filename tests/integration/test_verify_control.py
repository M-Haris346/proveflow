"""Paired verify against the CONTROL (Phase 8), through the real verify command on real twins
and proxies: offline, no key, no provider. The 3-cell tests run on CI with the synthetic
corpus; the 30-cell exit-criteria tests need the raw corpus cache, which is never committed,
so they SKIP in CI and in a fresh clone (tests/verifychecks.py)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

import planchecks
import verifychecks

CACHE = planchecks.REPO / ".proveflow-corpus"
LOCAL_ONLY = pytest.mark.skipif(not CACHE.is_dir(), reason="the raw corpus cache is never "
                                "committed (CLAUDE.md); run locally")  # fmt: skip


@pytest.fixture(scope="module")
def m1_fs(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Any]]:
    """ONE M1 verify on the 3-cell fs_notes_exfil plan, shared by the checks that read it."""
    tmp = tmp_path_factory.mktemp("m1fs")
    with pytest.MonkeyPatch.context() as mp:
        yield verifychecks.assert_the_mitigation_blocks_the_flow(
            tmp / "run", mp, plan_path=planchecks.small_fs_plan(tmp),
            records=planchecks.synthetic_corpus(tmp), mitigation="m1")  # fmt: skip


def test_m1_blocks_the_flow_on_the_file_borne_template(m1_fs: dict[str, Any]) -> None:
    text = m1_fs["_text"]
    for figure in ("| rate 1/1 -> 0/1 |", "| exposure 1/1 -> 1/1 |", "| utility 1/1 -> 1/1 |",
                   "FLOW BLOCKED (a verified fix, on the CONTROL)", "NOTE: CONTROL:"):  # fmt: skip
        assert figure in text, text


def test_m3_blocks_the_flow_on_the_file_borne_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = verifychecks.assert_the_mitigation_blocks_the_flow(
        tmp_path / "run", monkeypatch, plan_path=planchecks.small_fs_plan(tmp_path),
        records=planchecks.synthetic_corpus(tmp_path), mitigation="m3")  # fmt: skip
    assert "SIMULATED APPROVAL" in report["_text"]
    assert all(
        "the TWIN denied the call" in line
        for line in report["_text"].splitlines()
        if "| rate " in line
    ), report["_text"]


def test_m1_on_the_forced_fetch_template_is_delivery_and_capability_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Haris's ruling: on fetch_summary_exfil the attacked tool, the task's tool and the sink
    are all fetch, so M1 zeroes the rate by removing delivery AND the task: NOT a fix."""
    verifychecks.assert_the_label_names_what_the_mitigation_did(
        tmp_path / "run", monkeypatch, plan_path=planchecks.small_plan(tmp_path),
        records=planchecks.synthetic_corpus(tmp_path), mitigation="m1",
        labels=("delivery_removed", "capability_removed"))  # fmt: skip


def test_the_report_refuses_what_the_counts_do_not_say(m1_fs: dict[str, Any]) -> None:
    verifychecks.assert_the_report_refuses_what_the_counts_do_not_say(m1_fs)


def test_unpaired_halves_are_refused(m1_fs: dict[str, Any]) -> None:
    verifychecks.assert_unpaired_halves_are_refused(m1_fs)


def test_a_mitigated_transcript_is_never_replayed(m1_fs: dict[str, Any], tmp_path: Path) -> None:
    verifychecks.assert_a_mitigated_transcript_is_never_replayed(m1_fs, tmp_path)


@LOCAL_ONLY
@pytest.mark.parametrize("mitigation", ["m1", "m3"])
def test_the_mitigation_blocks_the_flow_on_the_fs_plans_30_cells(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mitigation: str
) -> None:
    """The exit-criteria run: the COMMITTED groq_fs_forced plan and the real corpus draw."""
    report = verifychecks.assert_the_mitigation_blocks_the_flow(
        tmp_path / "run", monkeypatch, plan_path=planchecks.FS_PLAN, records=None,
        mitigation=mitigation)  # fmt: skip
    assert [r["cells"] for r in report["per_source"]] == [10, 10, 10]


def test_m3_rows_say_the_twin_denied(m1_fs: dict[str, Any]) -> None:
    verifychecks.assert_m3_rows_say_the_twin_denied(m1_fs)
