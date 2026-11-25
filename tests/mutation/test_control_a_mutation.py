"""Mutations of Control A (Phase 7.3b), one per LAYER: each weakening must kill the matched-pair
control, and the control must NAME the layer that failed first. Plus the mutant that makes it a
matched PAIR: an oracle that fires on anything passes the compliant half and is killed only by
the negative half. Each runs on the 3-cell forced plan with the synthetic corpus."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import controlchecks
import planchecks
from proveflow.oracle import rules
from proveflow.proxy import server
from proveflow.runner import report, trial


def _ok_then(
    tmp_path: Path,
    mp: pytest.MonkeyPatch,
    patch: Callable[[pytest.MonkeyPatch], None],
    message: str,
    *,
    legs: tuple[int, ...] = (1,),
    negative: bool = False,
) -> None:
    plan_path = planchecks.small_plan(tmp_path)
    records = planchecks.synthetic_corpus(tmp_path)

    def check(where: str) -> Any:
        return controlchecks.assert_the_pipeline_counts_a_compromise_iff_the_flow_happens(
            tmp_path / where, mp, plan_path=plan_path, records=records, legs=legs,
            negative=negative,
        )  # fmt: skip

    check("ok")
    with mp.context() as m:
        patch(m)
        with pytest.raises(AssertionError, match=message):
            check("mut")


def test_an_unserved_injection_is_named_l3_delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutant (L3): the proxy serves no injection, so the reference code never reaches the
    model and the compliant client cannot find it."""
    _ok_then(tmp_path, monkeypatch,
             lambda m: m.setattr(server._CallHandler, "_inject", lambda self, *a, **k: None),
             "L3 delivery")  # fmt: skip


def test_an_unflagged_sink_is_named_l4_proxy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutant (L4): the proxy does not flag the fetch call as a sink."""
    _ok_then(tmp_path, monkeypatch,
             lambda m: m.setattr(server, "is_sink_call", lambda *a, **k: False),
             "L4 proxy")  # fmt: skip


def test_an_oracle_without_the_canary_needle_is_named_l5_oracle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutant (L5): the oracle drops the canary needle (leg 1: the canary is the only needle
    the compliant call carries)."""
    real = rules.needles_of

    def no_canary(start: Any) -> list[Any]:
        return [n for n in real(start) if n.id != rules.CANARY_NEEDLE]

    _ok_then(tmp_path, monkeypatch, lambda m: m.setattr(rules, "needles_of", no_canary),
             "L5 oracle")  # fmt: skip


def test_a_verdict_lost_before_the_ledger_is_named_l6_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutant (L6): the oracle's compromise is dropped between the oracle and the ledger."""
    real = trial.to_verdict

    def dropped(*a: Any, **k: Any) -> Any:
        return real(*a, **k).model_copy(update={"compromised": False})

    _ok_then(tmp_path, monkeypatch, lambda m: m.setattr(trial, "to_verdict", dropped),
             "L6 ledger")  # fmt: skip


def test_a_report_that_miscounts_the_numerator_is_named_l6_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutant (L6): the report's numerator does not count the ledger's compromises."""
    _ok_then(tmp_path, monkeypatch, lambda m: m.setattr(report, "_compromised", lambda a: False),
             "L6 report")  # fmt: skip


def test_an_oracle_that_fires_on_anything_is_killed_by_the_negative_half(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutant (the iff): every needle is "found" in every sink call. The compliant half still
    passes; only the negative half, which never sends anything, can kill it."""

    def everywhere(needle: Any, arguments: object) -> tuple[Any, ...]:
        return (rules.EncodingHit(path="$", encoding="raw"),)

    _ok_then(tmp_path, monkeypatch, lambda m: m.setattr(rules, "_hits", everywhere),
             r"Control A, negative: the non-compliant client counted [1-9]\d* compromised",
             negative=True)  # fmt: skip
