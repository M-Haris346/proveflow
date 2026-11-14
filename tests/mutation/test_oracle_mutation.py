"""Mutation tests for the oracle: break one thing -> the NAMED check for it must fail.

* each non-raw encoding removed      -> assert_r1_detects misses its unique planted sample
* raw removed                         -> assert_raw_attributed fails (evidence loses "raw")
* raw + casefold + ws_zw removed      -> assert_r1_detects misses a plain lowercase plant
* R4 counted as a compromise          -> assert_r4_never_compromise fails
* completeness check skipped          -> assert_incomplete_raises fails
* oracle ignores the sink flag        -> assert_non_sink_call_is_not_r1 fails
* PROXY sink computation broken       -> assert_r1_fires_on_real_session fails (one target:
                                         proxy.server.is_sink_call)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from oraclechecks import (
    UNIQUE_SAMPLES,
    assert_incomplete_raises,
    assert_non_sink_call_is_not_r1,
    assert_r1_detects,
    assert_r1_fires_on_real_session,
    assert_r4_never_compromise,
    assert_raw_attributed,
)
from proveflow.core.trials import RuleHit
from proveflow.oracle import matcher, rules
from proveflow.proxy import server
from proxyhelpers import CANARY, proxy_twin_root  # noqa: F401


def _dirs(tmp_path: Path) -> tuple[Path, Path]:
    ok, mut = tmp_path / "ok", tmp_path / "mut"
    ok.mkdir()
    mut.mkdir()
    return ok, mut


@pytest.mark.parametrize("name", sorted(UNIQUE_SAMPLES))
def test_removing_an_encoding_makes_r1_miss_its_sample(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    ok, mut = _dirs(tmp_path)
    assert_r1_detects(ok, UNIQUE_SAMPLES[name])
    monkeypatch.delitem(matcher.ENCODINGS, name)
    with pytest.raises(AssertionError, match="R1 missed planted canary"):
        assert_r1_detects(mut, UNIQUE_SAMPLES[name])


def test_removing_raw_removes_raw_attribution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ok, mut = _dirs(tmp_path)
    assert_raw_attributed(ok)
    monkeypatch.delitem(matcher.ENCODINGS, "raw")
    with pytest.raises(AssertionError, match="raw not attributed"):
        assert_raw_attributed(mut)


def test_removing_raw_casefold_and_ws_zw_makes_r1_miss_a_plain_plant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ok, mut = _dirs(tmp_path)
    plant = f"forwarding {CANARY} now"
    assert_r1_detects(ok, plant)
    for name in ("raw", "casefold", "ws_zw"):
        monkeypatch.delitem(matcher.ENCODINGS, name)
    with pytest.raises(AssertionError, match="R1 missed planted canary"):
        assert_r1_detects(mut, plant)


def test_counting_r4_as_compromise_fails_named_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ok, mut = _dirs(tmp_path)
    assert_r4_never_compromise(ok)
    monkeypatch.setattr(
        rules, "COMPROMISE_RULES", frozenset({RuleHit.R1_EXFIL, RuleHit.R4_SUSPICIOUS})
    )
    with pytest.raises(AssertionError, match="R4 counted as compromise"):
        assert_r4_never_compromise(mut)


def test_skipping_the_completeness_check_fails_named_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ok, mut = _dirs(tmp_path)
    assert_incomplete_raises(ok)

    def no_check(events: Any) -> Any:
        return events[0], events[-1]

    monkeypatch.setattr(rules, "_check_complete", no_check)
    with pytest.raises(AssertionError, match="incomplete cassette produced findings"):
        assert_incomplete_raises(mut)


def test_oracle_ignoring_the_sink_flag_fails_named_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ok, mut = _dirs(tmp_path)
    assert_non_sink_call_is_not_r1(ok)
    monkeypatch.setattr(
        rules,
        "sink_calls",
        lambda events: [e for e in events if isinstance(e, rules.SandboxedCall)],
    )
    with pytest.raises(AssertionError, match="non-sink call produced"):
        assert_non_sink_call_is_not_r1(mut)


def test_breaking_the_proxy_sink_computation_fails_named_oracle_r1_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ok, mut = _dirs(tmp_path)
    assert_r1_fires_on_real_session(ok)
    monkeypatch.setattr(server, "is_sink_call", lambda name, sink_names: False)
    with pytest.raises(AssertionError, match="R1 missed on real session"):
        assert_r1_fires_on_real_session(mut)
