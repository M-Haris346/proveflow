"""Failure diagnostics of the real-session helpers (Phase 3b follow-up, diagnostics only): when a
real-session check fails, its message must say what the session DID, not only that a check
missed. No assertion of any check is changed by these helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from proveflow.proxy.cassette import CassetteWriter
from proxyhelpers import LAST_RUN, cassette_story, text_of


def _cassette(path: Path, end_reason: str) -> Path:
    w = CassetteWriter(path)
    w.emit("session_start", session_id="s", proveflow_version="test", upstream={"name": "twin"},
           policy={"tools": [], "computed": {}}, attack=None, limits={}, honey=[])  # fmt: skip
    w.emit("upstream_request", tool="crash", arguments={}, sink=False)
    w.emit("error", error_kind="upstream_timeout", detail="crash")
    w.emit("session_end", reason=end_reason, tool_calls=1, forwarded_calls=1, sandboxed_calls=0,
           upstream_stderr="", upstream_stderr_truncated=False, dropped_events=0)  # fmt: skip
    w.close()
    return path


def test_cassette_story_names_the_errors_the_tail_and_the_end_reason(tmp_path: Path) -> None:
    story = cassette_story(_cassette(tmp_path / "c.jsonl", "session_timeout"))
    assert "error[upstream_timeout: crash]" in story
    assert "upstream_request[crash]" in story
    assert "session_end reason: session_timeout" in story


def test_cassette_story_never_hides_an_unreadable_cassette(tmp_path: Path) -> None:
    bad = tmp_path / "bad.jsonl"
    bad.write_bytes(b"not a cassette\n")
    assert "unreadable" in cassette_story(bad)


def test_text_of_none_says_the_call_returned_no_result_and_why(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """proxyhelpers.text_of(None) used to raise "'NoneType' object has no attribute
    'content'", which said nothing. It now names the swallowed client error, the proxy's
    outcome reason, and what the session recorded."""
    cassette = _cassette(tmp_path / "c.jsonl", "upstream_message_limit")
    monkeypatch.setitem(LAST_RUN, "cassette", cassette)
    monkeypatch.setitem(LAST_RUN, "reason", "upstream_message_limit")
    monkeypatch.setitem(LAST_RUN, "client_error", RuntimeError("Connection closed"))
    with pytest.raises(AssertionError) as caught:
        text_of(None)  # type: ignore[arg-type]
    message = str(caught.value)
    assert "returned NO result" in message
    assert "upstream_message_limit" in message and "Connection closed" in message
    assert "error[upstream_timeout: crash]" in message
