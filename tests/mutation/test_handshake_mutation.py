"""Mutations of the handshake deadline (Phase 7.0). Two independent layers, one mutation per layer
with the OTHER layer switched off, plus one for the layering (handshakechecks docstring); and
the single-source-of-truth stage list."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import handshakechecks as hc
from proveflow.proxy import cassette, server
from proveflow.runner import harness
from proxyhelpers import proxy_twin_root  # noqa: F401


def _ok_then(check: Any, mp: pytest.MonkeyPatch, patch: Any, message: str,
             tmp_path: Path | None = None, *args: Any) -> None:  # fmt: skip
    if tmp_path is not None:
        (tmp_path / "ok").mkdir()
        (tmp_path / "mut").mkdir()
    check(*([tmp_path / "ok"] if tmp_path else []), *args)
    patch(mp)
    with pytest.raises(AssertionError, match=message):
        check(*([tmp_path / "mut"] if tmp_path else []), *args)


def test_the_proxy_layer_alone_fails_its_named_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    proxy_twin_root: Any,  # noqa: F811
) -> None:
    """PROXY layer, no harness (run_in_process): with the per-stage bound off, a hung
    initialize runs on to the (short, here) session timeout and names no stage."""
    _ok_then(hc.assert_a_hung_stage_is_named_in_the_cassette, monkeypatch,
             lambda m: m.setattr(server, "handshake_deadline", lambda stage, now, sd, t: sd),
             "did not end the session as handshake_timeout", tmp_path, "initialize", 5.0)  # fmt: skip  # noqa: E501


def test_the_harness_layer_alone_fails_its_named_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    proxy_twin_root: Any,  # noqa: F811
) -> None:
    """HARNESS layer, the proxy absent (a mute serve): with the harness bound off it never
    gives up (the check's own outer bound catches that)."""
    _ok_then(hc.assert_the_harness_bounds_a_proxy_that_never_answers, monkeypatch,
             lambda m: m.setattr(harness, "startup_bound_s", lambda t: 1e6),
             "the harness never gave up", tmp_path)  # fmt: skip


def test_an_inverted_layering_fails_the_layering_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    proxy_twin_root: Any,  # noqa: F811
) -> None:
    """LAYERING: a harness bound BELOW the proxy's (a literal that did not follow a raised
    HANDSHAKE_TIMEOUT_S) fires first and destroys the stage naming."""
    _ok_then(hc.assert_the_proxy_names_the_stage_before_the_harness_gives_up, monkeypatch,
             lambda m: m.setattr(harness, "startup_bound_s", lambda t: t * 0.5),
             "the harness fired before the proxy could name the stage", tmp_path)  # fmt: skip


def test_a_literal_harness_bound_fails_the_range_check(monkeypatch: pytest.MonkeyPatch) -> None:
    _ok_then(hc.assert_the_harness_bound_exceeds_the_proxy_bound_for_a_range, monkeypatch,
             lambda m: m.setattr(harness, "startup_bound_s", lambda t: 120.0),
             "harness bound 120.0 <= proxy bound")  # fmt: skip


def test_a_stage_added_without_recording_fails_the_stage_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    proxy_twin_root: Any,  # noqa: F811
) -> None:
    """Q2: the stage list is ONE source of truth; a stage added to it without being recorded
    (or without a hang test) fails."""
    _ok_then(hc.assert_every_stage_is_recorded, monkeypatch,
             lambda m: m.setattr(cassette, "HANDSHAKE_STAGES", (*cassette.HANDSHAKE_STAGES, "ready")),  # noqa: E501
             "not every handshake stage was recorded", tmp_path)  # fmt: skip


def test_a_stage_added_without_a_hang_test_fails_the_hang_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cassette, "HANDSHAKE_STAGES", (*cassette.HANDSHAKE_STAGES, "ready"))
    with pytest.raises(AssertionError, match="stages without a hang test"):
        hc.assert_every_hung_stage_is_named(tmp_path)
