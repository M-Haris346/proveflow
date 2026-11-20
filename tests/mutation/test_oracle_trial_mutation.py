"""Mutation (Phase 5, R-B2): scan each cassette of a trial with only ITS OWN session's needles
(the pre-Phase-5 per-cassette view) -> the NAMED cross-server R1 check fails."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from oraclechecks import assert_cross_server_exfil_is_r1
from proveflow.oracle import rules
from proxyhelpers import proxy_twin_root  # noqa: F401


def _sink_session_needles_only(starts: Sequence[rules.SessionStart]) -> list[rules.Needle]:
    return rules.needles_of(starts[-1])  # the sink cassette's own needles, as if per cassette


def test_per_cassette_needles_miss_cross_server_exfil(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ok, mut = tmp_path / "ok", tmp_path / "mut"
    ok.mkdir()
    mut.mkdir()
    assert_cross_server_exfil_is_r1(ok)
    monkeypatch.setattr(rules, "trial_needles", _sink_session_needles_only)
    with pytest.raises(AssertionError, match="cross-server exfil not R1"):
        assert_cross_server_exfil_is_r1(mut)
