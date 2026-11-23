"""The twin handshake deadline on REAL in-process proxies and the fake twin (Phase 7.0). A hang is
made visible, bounded and named; its root cause is still unknown (docs/BACKLOG.md)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from handshakechecks import (
    assert_a_handshake_timeout_reads_as_an_early_stop,
    assert_a_handshake_timeout_writes_no_trial_end,
    assert_every_hung_stage_is_named,
    assert_every_stage_is_recorded,
    assert_the_campaign_files_a_handshake_timeout_as_a_failure,
    assert_the_harness_bounds_a_proxy_that_never_answers,
    assert_the_proxy_names_the_stage_before_the_harness_gives_up,
)
from proxyhelpers import proxy_twin_root  # noqa: F401


def test_every_stage_is_recorded(tmp_path: Path, proxy_twin_root: Any) -> None:  # noqa: F811
    assert_every_stage_is_recorded(tmp_path)


def test_every_hung_stage_is_named(tmp_path: Path, proxy_twin_root: Any) -> None:  # noqa: F811
    assert_every_hung_stage_is_named(tmp_path)


def test_the_harness_bounds_a_proxy_that_never_answers(
    tmp_path: Path,
    proxy_twin_root: Any,  # noqa: F811
) -> None:
    assert_the_harness_bounds_a_proxy_that_never_answers(tmp_path)


def test_the_proxy_names_the_stage_before_the_harness_gives_up(
    tmp_path: Path,
    proxy_twin_root: Any,  # noqa: F811
) -> None:
    assert_the_proxy_names_the_stage_before_the_harness_gives_up(tmp_path)


def test_a_handshake_timeout_reads_as_an_early_stop(tmp_path: Path, proxy_twin_root: Any) -> None:  # noqa: F811
    assert_a_handshake_timeout_reads_as_an_early_stop(tmp_path)


def test_a_handshake_timeout_writes_no_trial_end(tmp_path: Path, proxy_twin_root: Any) -> None:  # noqa: F811
    assert_a_handshake_timeout_writes_no_trial_end(tmp_path)


def test_the_campaign_files_a_handshake_timeout_as_a_failure(
    tmp_path: Path,
    proxy_twin_root: Any,  # noqa: F811
) -> None:
    assert_the_campaign_files_a_handshake_timeout_as_a_failure(tmp_path)
