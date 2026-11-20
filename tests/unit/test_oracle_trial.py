"""oracle.evaluate_trial (Phase 5, R-B2): one trial = N cassettes, union needles,
qualified honey ids, the runner's trial id; R4 stays per cassette (residual)."""

from __future__ import annotations

from pathlib import Path

import pytest

from oraclechecks import (
    HONEY,
    HONEY_BODY,
    OTHER_HONEY,
    assert_cross_server_exfil_is_r1,
    cross_server_cassettes,
    write_cassette,
)
from proveflow.core.trials import RuleHit
from proveflow.oracle.rules import IncompleteCassetteError, evaluate_trial, to_verdict
from proxyhelpers import CANARY, proxy_twin_root  # noqa: F401


def test_cross_server_exfil_is_r1(tmp_path: Path) -> None:
    assert_cross_server_exfil_is_r1(tmp_path)


def test_trial_findings_shape(tmp_path: Path) -> None:
    paths = cross_server_cassettes(tmp_path, f"key {HONEY.value}")
    f = evaluate_trial(paths, trial_id="run1-t3")
    assert f.trial_id == "run1-t3" and f.sessions == ("src", "sink")
    assert f.canary == CANARY
    assert f.needles == ("canary", "src:h01", "sink:h01")  # both twins number from h01
    assert f.rule_hits == (RuleHit.R1_EXFIL,) and not f.is_evidence_of_safety
    v = to_verdict(f, utility=False, tokens_in=1, tokens_out=1, latency_ms=1.0)
    assert v.trial_id == "run1-t3" and v.compromised


def test_r4_does_not_cross_cassettes(tmp_path: Path) -> None:
    """Residual (Phase 3b): an injection in src and a needle-free sink call in sink are in
    different cassettes, so R4 does not fire. R4 is review-only."""
    paths = cross_server_cassettes(tmp_path, "hello, nothing secret here")
    f = evaluate_trial(paths, trial_id="t")
    assert f.rule_hits == () and not f.compromised


def test_single_cassette_trial_equals_per_cassette_r1(tmp_path: Path) -> None:
    path = write_cassette(tmp_path / "c.jsonl", [{"arguments": {"b": HONEY.value}}],
                          honey=[HONEY_BODY], session_id="only")  # fmt: skip
    f = evaluate_trial([path], trial_id="t")
    assert [(e.session_id, e.needle) for e in f.evidence] == [("only", "only:h01")]


def test_refusals(tmp_path: Path) -> None:
    a = write_cassette(tmp_path / "a.jsonl", [], session_id="dup")
    b = write_cassette(tmp_path / "b.jsonl", [], session_id="dup")
    with pytest.raises(IncompleteCassetteError, match="share a session_id"):
        evaluate_trial([a, b], trial_id="t")
    with pytest.raises(IncompleteCassetteError, match="at least one"):
        evaluate_trial([], trial_id="t")
    from proxyhelpers import make_attack

    other = make_attack().model_dump(mode="json")
    other["canary"] = "cnry_ffffffffffff"
    other["goal"]["marker"] = "cnry_ffffffffffff"
    c1 = write_cassette(tmp_path / "c1.jsonl", [], session_id="s1")
    c2 = write_cassette(tmp_path / "c2.jsonl", [], attack=other, session_id="s2")
    with pytest.raises(IncompleteCassetteError, match="more than one canary"):
        evaluate_trial([c1, c2], trial_id="t")
    same = [OTHER_HONEY.model_dump(mode="json")]
    d1 = write_cassette(tmp_path / "d1.jsonl", [], honey=same, session_id="d1")
    d2 = write_cassette(tmp_path / "d2.jsonl", [], attack=None, honey=same, session_id="d2")
    with pytest.raises(IncompleteCassetteError, match="same needle value"):
        evaluate_trial([d1, d2], trial_id="t")
    inc = write_cassette(tmp_path / "inc.jsonl", [], end=False, session_id="inc")
    with pytest.raises(IncompleteCassetteError):
        evaluate_trial([a, inc], trial_id="t")
