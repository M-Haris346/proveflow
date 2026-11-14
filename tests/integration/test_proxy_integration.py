"""Integration: the real ``python -m proveflow proxy --session`` subprocess + fake twin,
driven by an MCP SDK ``ClientSession`` over stdio (both OSes in CI).

Nothing here touches the network or a real MCP server: the only upstream is
tests/fixtures/fake_twin.py.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import anyio
import mcp_types
import pytest
from mcp.shared.exceptions import MCPError

from proveflow.core.attacks import Carrier
from proveflow.proxy.cassette import load_cassette
from proveflow.proxy.session import ProxyLimits
from proxyhelpers import (  # noqa: F401
    CANARY,
    PAYLOAD_TEXT,
    SamplingSpy,
    cli_client,
    make_attack,
    make_session,
    proxy_argv,
    proxy_twin_root,
    text_of,
    twin_log,
    twin_messages,
    twin_tool_calls,
    write_session,
)


def run_cli(tmp_path: Path, script: Any, *, attack: bool = True, spy: SamplingSpy | None = None,
            limits: ProxyLimits | None = None) -> Any:  # fmt: skip
    session = make_session(tmp_path, attack=make_attack() if attack else None, limits=limits)
    path = write_session(tmp_path, session)
    box: dict[str, Any] = {}

    async def main() -> None:
        async with cli_client(path, tmp_path / "proxy.stderr", sampling=spy) as client:
            box["r"] = await script(client)

    anyio.run(main)
    return box["r"]


def test_tools_list_strips_output_schema(tmp_path: Path) -> None:
    async def script(client: Any) -> Any:
        return await client.list_tools()

    tools = {t.name: t for t in run_cli(tmp_path, script).tools}
    assert "structured" in tools and "send_email" in tools  # sinks are advertised
    assert all(t.output_schema is None for t in tools.values())
    events = load_cassette(tmp_path / "cassette.jsonl")
    [adv] = [e for e in events if e.kind == "tools_advertised"]
    flags = {x["tool"]["name"]: x["output_schema_stripped"] for x in adv.tools}  # type: ignore[union-attr]
    assert flags["structured"] is True
    assert flags["read_page"] is False


def test_source_call_is_forwarded_and_injected(tmp_path: Path) -> None:
    async def script(client: Any) -> Any:
        return await client.call_tool("read_page", {"page": "install-guide"})

    result = run_cli(tmp_path, script)
    text = text_of(result)
    assert text.startswith("Docs for install-guide: install with pip.")
    assert text.endswith("\n\n" + PAYLOAD_TEXT)
    assert CANARY in text  # A4: agent-visible
    assert twin_tool_calls(tmp_path) == ["read_page"]
    assert CANARY not in twin_log(tmp_path).read_text(encoding="utf-8")  # A4: twin never sees it


def test_private_call_is_forwarded_not_injected(tmp_path: Path) -> None:
    async def script(client: Any) -> Any:
        return await client.call_tool("query_db", {})

    result = run_cli(tmp_path, script)
    assert text_of(result) == '{"rows": [{"id": 1, "email": "honey@example.invalid"}]}'
    assert twin_tool_calls(tmp_path) == ["query_db"]


def test_sink_call_returns_sandbox_response(tmp_path: Path) -> None:
    async def script(client: Any) -> Any:
        return await client.call_tool("send_email", {"to": "a@example.invalid", "body": "b"})

    result = run_cli(tmp_path, script)
    assert result.is_error is False
    assert json.loads(text_of(result)) == {"ok": True, "id": "sbx_0001"}
    assert twin_tool_calls(tmp_path) == []
    events = load_cassette(tmp_path / "cassette.jsonl")
    [sbx] = [e for e in events if e.kind == "sandboxed_call"]
    assert sbx.arguments == {"to": "a@example.invalid", "body": "b"}  # type: ignore[union-attr]
    assert sbx.reason == "policy_deny"  # type: ignore[union-attr]


def test_unknown_tool_returns_sandbox_response(tmp_path: Path) -> None:
    async def script(client: Any) -> Any:
        return await client.call_tool("delete_everything", {"really": True})

    result = run_cli(tmp_path, script)
    assert json.loads(text_of(result)) == {"ok": True, "id": "sbx_0001"}
    assert twin_tool_calls(tmp_path) == []


def test_resources_list_is_method_not_found(tmp_path: Path) -> None:
    async def script(client: Any) -> Any:
        with pytest.raises(MCPError) as exc:
            await client.list_resources()
        return exc.value

    error = run_cli(tmp_path, script)
    assert error.code == mcp_types.METHOD_NOT_FOUND
    methods = [str(m.get("method", "")) for m in twin_messages(tmp_path)]
    assert not [m for m in methods if m.startswith("resources")]


def test_upstream_sampling_request_is_not_relayed(tmp_path: Path) -> None:
    spy = SamplingSpy()

    async def script(client: Any) -> Any:
        return await client.call_tool("ask_sampling", {})

    result = run_cli(tmp_path, script, spy=spy)
    assert spy.calls == []  # the agent advertised sampling, yet nothing was relayed
    assert text_of(result) == f"sampling_rejected:{mcp_types.METHOD_NOT_FOUND}"
    events = load_cassette(tmp_path / "cassette.jsonl")
    assert any(
        e.kind == "error"
        and e.error_kind == "upstream_request_rejected"  # type: ignore[union-attr]
        and e.detail == "sampling/createMessage"  # type: ignore[union-attr]
        for e in events
    )


def test_structured_content_dropped_but_kept_raw_in_cassette(tmp_path: Path) -> None:
    async def script(client: Any) -> Any:
        return await client.call_tool("structured", {})

    result = run_cli(tmp_path, script)
    assert result.structured_content is None  # A1
    assert text_of(result) == '{"n": 1}'
    events = load_cassette(tmp_path / "cassette.jsonl")
    [raw] = [e for e in events if e.kind == "upstream_response"]
    assert raw.result["structuredContent"] == {"n": 1}  # type: ignore[union-attr]


def test_json_string_carrier_through_the_proxy(tmp_path: Path) -> None:
    session = make_session(tmp_path, attack=make_attack(Carrier.JSON_STRING))
    path = write_session(tmp_path, session)
    box: dict[str, Any] = {}

    async def main() -> None:
        async with cli_client(path, tmp_path / "proxy.stderr") as client:
            box["r"] = await client.call_tool("json_page", {})

    anyio.run(main)
    doc = json.loads(text_of(box["r"]))
    assert doc == {"title": "Docs", "body": "install with pip", "_note": PAYLOAD_TEXT}


def test_cassette_is_byte_identical_across_runs(tmp_path: Path) -> None:
    """Determinism: same session file + same scripted calls -> byte-identical cassette."""

    async def script(client: Any) -> Any:
        await client.list_tools()
        for name in ("read_page", "query_db", "send_email", "nope", "structured", "empty_result"):
            await client.call_tool(name, {})

    session = make_session(tmp_path, attack=make_attack(Carrier.MARKDOWN))
    path = write_session(tmp_path, session)
    outputs = []
    for _ in range(2):

        async def main() -> None:
            async with cli_client(path, tmp_path / "proxy.stderr") as client:
                await script(client)

        anyio.run(main)
        outputs.append(session.cassette_path.read_bytes())
        shutil.move(session.cassette_path, tmp_path / f"run{len(outputs)}.jsonl")
    assert outputs[0] == outputs[1]
    assert len(load_cassette(tmp_path / "run1.jsonl")) > 20


def test_cli_refuses_existing_cassette(tmp_path: Path) -> None:
    import subprocess

    session = make_session(tmp_path)
    path = write_session(tmp_path, session)
    session.cassette_path.write_text("keep", encoding="utf-8")
    proc = subprocess.run(
        proxy_argv(path),
        capture_output=True,
        timeout=60,
        stdin=subprocess.DEVNULL,
    )
    assert proc.returncode == 1
    assert b"already exists" in proc.stderr
    assert proc.stdout == b""  # stdout is the MCP channel: nothing else is written there
    assert not twin_log(tmp_path).exists()  # nothing was spawned
