"""In-process proxy (``serve`` over memory streams) + real fake-twin subprocess:
limits (A2), fail-closed paths (D5), dropped notifications, injection skips."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import anyio
import psutil
import pytest

from proveflow.proxy.cassette import load_cassette
from proveflow.proxy.session import ProxyLimits
from proxyhelpers import (
    make_attack,
    make_session,
    run_in_process,
    text_of,
    twin_tool_calls,
    write_session,
)


def events_of(tmp_path: Path, kind: str) -> list[Any]:
    return [e for e in load_cassette(tmp_path / "cassette.jsonl") if e.kind == kind]


def error_kinds(tmp_path: Path) -> list[str]:
    return [e.error_kind for e in events_of(tmp_path, "error")]


def test_max_calls_counts_sandboxed_and_forwarded(tmp_path: Path) -> None:
    async def script(client: Any) -> Any:
        out = []
        for name in ("query_db", "send_email", "query_db", "query_db", "send_email"):
            out.append(await client.call_tool(name, {}))
        return out

    session = make_session(tmp_path, limits=ProxyLimits(max_calls=3))
    results, outcome = run_in_process(session, script)
    assert [r.is_error for r in results] == [False, False, False, True, True]
    assert text_of(results[3]) == "proveflow proxy: tool call limit reached"
    assert twin_tool_calls(tmp_path) == ["query_db", "query_db"]  # 4th call never forwarded
    assert outcome.tool_calls == 5 and outcome.forwarded_calls == 2
    assert error_kinds(tmp_path).count("max_calls_exceeded") == 2


def test_per_call_timeout_returns_error_and_proxy_keeps_serving(tmp_path: Path) -> None:
    async def script(client: Any) -> Any:
        started = time.monotonic()
        slow = await client.call_tool("slow", {"seconds": 20})
        elapsed = time.monotonic() - started
        after = await client.call_tool("query_db", {})
        return slow, elapsed, after

    session = make_session(tmp_path, limits=ProxyLimits(call_timeout_s=1))
    (slow, elapsed, after), _ = run_in_process(session, script)
    assert slow.is_error is True
    assert text_of(slow) == "proveflow proxy: upstream call timed out"
    assert elapsed < 10
    assert after.is_error is False
    assert "upstream_timeout" in error_kinds(tmp_path)
    assert not events_of(tmp_path, "upstream_response") or all(
        e.tool != "slow" for e in events_of(tmp_path, "upstream_response")
    )


def test_session_timeout_ends_the_session(tmp_path: Path) -> None:
    async def script(client: Any) -> Any:
        await anyio.sleep(3)

    session = make_session(tmp_path, limits=ProxyLimits(session_timeout_s=1))
    started = time.monotonic()
    _, outcome = run_in_process(session, script)
    assert outcome.reason == "session_timeout"
    assert time.monotonic() - started < 15
    [end] = events_of(tmp_path, "session_end")
    assert end.reason == "session_timeout"


def test_cli_session_timeout_exits_and_kills_twin(tmp_path: Path) -> None:
    """The CLI process exits on the session limit even though the agent keeps stdin open."""
    session = make_session(tmp_path, limits=ProxyLimits(session_timeout_s=2))
    path = write_session(tmp_path, session)
    proc = subprocess.Popen(
        [sys.executable, "-m", "proveflow", "proxy", "--session", str(path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        code = proc.wait(timeout=60)
    finally:
        if proc.poll() is None:
            proc.kill()
        assert proc.stdin is not None
        proc.stdin.close()
    assert code == 1
    [end] = events_of(tmp_path, "session_end")
    assert end.reason == "session_timeout"
    alive = [
        p for p in psutil.process_iter(["cmdline"])
        if any(str(tmp_path) in a for a in (p.info["cmdline"] or []))
    ]  # fmt: skip
    assert alive == []


def test_upstream_crash_fails_closed(tmp_path: Path) -> None:
    async def script(client: Any) -> Any:
        crash = await client.call_tool("crash", {})
        later = await client.call_tool("query_db", {})
        sink = await client.call_tool("send_email", {})
        return crash, later, sink

    (crash, later, sink), outcome = run_in_process(make_session(tmp_path), script)
    assert crash.is_error is True and text_of(crash).startswith("proveflow proxy: ")
    assert later.is_error is True  # upstream gone: forwarded calls fail closed
    assert sink.is_error is False and '"sbx_0001"' in text_of(sink)  # sandbox still answers
    assert outcome.reason == "agent_closed"


def test_upstream_garbage_line_fails_closed(tmp_path: Path) -> None:
    async def script(client: Any) -> Any:
        return await client.call_tool("garbage", {})

    result, _ = run_in_process(make_session(tmp_path), script)
    assert result.is_error is True
    assert "upstream_invalid_message" in error_kinds(tmp_path)


def test_upstream_notifications_are_dropped_and_recorded(tmp_path: Path) -> None:
    async def script(client: Any) -> Any:
        return await client.call_tool("notify", {})

    result, _ = run_in_process(make_session(tmp_path), script)
    assert text_of(result) == "notified"
    dropped = [
        e.detail for e in events_of(tmp_path, "error")
        if e.error_kind == "upstream_notification_dropped"
    ]  # fmt: skip
    assert dropped == ["notifications/tools/list_changed"]
    sent_to_agent = [e.message.get("method") for e in events_of(tmp_path, "agent_response")]
    assert "notifications/tools/list_changed" not in sent_to_agent


@pytest.mark.parametrize(
    ("tool", "reason"), [("empty_result", "empty_content"), ("image_result", "no_text_content")]
)
def test_injection_skipped_for_non_text(tmp_path: Path, tool: str, reason: str) -> None:
    async def script(client: Any) -> Any:
        return await client.call_tool(tool, {})

    run_in_process(make_session(tmp_path, attack=make_attack()), script)
    [skip] = events_of(tmp_path, "injection_skipped")
    assert (skip.tool, skip.reason) == (tool, reason)
    assert events_of(tmp_path, "injection") == []


def test_no_attack_armed_means_no_injection(tmp_path: Path) -> None:
    async def script(client: Any) -> Any:
        return await client.call_tool("read_page", {"url": "u"})

    result, _ = run_in_process(make_session(tmp_path), script)
    assert text_of(result) == "Docs for u: install with pip."
    assert events_of(tmp_path, "injection") == []


def test_upstream_response_raw_agent_response_transformed(tmp_path: Path) -> None:
    async def script(client: Any) -> Any:
        return await client.call_tool("read_page", {"url": "u"})

    run_in_process(make_session(tmp_path, attack=make_attack()), script)
    [raw] = events_of(tmp_path, "upstream_response")
    assert raw.result["content"][0]["text"] == "Docs for u: install with pip."
    [inj] = events_of(tmp_path, "injection")
    assert (inj.tool, inj.carrier, inj.content_index) == ("read_page", "plain", 0)
    replies = [
        e.message for e in events_of(tmp_path, "agent_response")
        if "content" in e.message.get("result", {})
    ]  # fmt: skip
    assert replies[-1]["result"]["content"][0]["text"].startswith("Docs for u")
    assert "cnry_" in replies[-1]["result"]["content"][0]["text"]


def test_agent_cancel_of_forwarded_call_reaches_twin_only_for_that_call(tmp_path: Path) -> None:
    async def script(client: Any) -> Any:
        with anyio.move_on_after(1):
            await client.call_tool("slow", {"seconds": 20})
        return await client.call_tool("query_db", {})

    result, _ = run_in_process(make_session(tmp_path), script)
    assert result.is_error is False
    from proxyhelpers import twin_messages

    methods = [m.get("method") for m in twin_messages(tmp_path)]
    assert methods.count("notifications/cancelled") <= 1
    assert twin_tool_calls(tmp_path) == ["slow", "query_db"]
