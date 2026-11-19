"""Dual-role twin-mode exception (ADR-007) and the guard step (R4), proven on twin-side logs.

* a pure sink never reaches a guard-passing twin, even with the dual-role path on (tee log);
* a dual-role tool never reaches the guard-failing fake twin (its own log);
* a dual-role tool IS forwarded to a generated twin (the twin's own marker, R-C2) and is
  recorded as ``upstream_request.sink=true``; ordinary forwards are ``sink=false``;
* the guard runs on the hashed private copy, in the order copy -> guard -> spawn (R4);
* markers never enter the session or session_start (F4).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from proveflow.proxy import upstream
from proveflow.proxy.policy import TwinUpstreamError
from proxyhelpers import make_session, proxy_twin_root, run_in_process  # noqa: F401
from twinproxy import (
    assert_dual_role_forwarded_with_marker,
    assert_dual_role_never_reaches_guard_failing_twin,
    assert_guard_runs_on_the_hashed_copy,
    assert_no_marker_in_session_or_start,
    assert_pure_sink_never_reaches_twin_with_dual_role_on,
    cassette_events,
)


def test_pure_sink_never_reaches_twin_even_with_dual_role_path_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert_pure_sink_never_reaches_twin_with_dual_role_on(tmp_path, monkeypatch)


def test_dual_role_never_reaches_a_guard_failing_twin(tmp_path: Path) -> None:
    assert_dual_role_never_reaches_guard_failing_twin(tmp_path)


def test_dual_role_is_forwarded_to_a_generated_twin_with_marker_evidence(tmp_path: Path) -> None:
    assert_dual_role_forwarded_with_marker(tmp_path)


def test_ordinary_forwards_are_recorded_sink_false(tmp_path: Path) -> None:
    async def script(client: Any) -> Any:
        await client.call_tool("read_page", {})
        await client.call_tool("query_db", {})

    session = make_session(tmp_path)
    run_in_process(session, script)
    requests = [e for e in cassette_events(session) if e.kind == "upstream_request"]
    assert [(e.tool, e.sink) for e in requests] == [("read_page", False), ("query_db", False)]


@pytest.mark.parametrize("original_passes", [True, False], ids=["generated", "fake"])
def test_guard_runs_on_the_hashed_copy_in_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, original_passes: bool
) -> None:
    assert_guard_runs_on_the_hashed_copy(tmp_path, monkeypatch, original_passes=original_passes)


def test_hash_mismatch_refuses_before_the_guard_and_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = make_session(tmp_path)
    Path(session.upstream.argv[1]).write_text("# changed after the session\n", encoding="utf-8")
    calls: list[str] = []
    monkeypatch.setattr(upstream, "check_no_io", lambda s: calls.append("guard"))
    work = tmp_path / "work"
    work.mkdir()
    with pytest.raises(TwinUpstreamError, match="sha256"):
        upstream.prepare_twin_copy(Path(session.upstream.argv[1]), work, session.twin_sha256)
    assert calls == []


def test_guard_failure_does_not_refuse_the_spawn(tmp_path: Path) -> None:
    """R-C1: the fake twin fails the guard and still starts and serves forwarded calls."""

    async def script(client: Any) -> Any:
        return await client.call_tool("read_page", {})

    session = make_session(tmp_path)
    result, _ = run_in_process(session, script)
    assert result.is_error is False
    assert "install with pip" in result.content[0].text


def test_markers_never_enter_the_session_or_session_start(tmp_path: Path) -> None:
    assert_no_marker_in_session_or_start(tmp_path)
