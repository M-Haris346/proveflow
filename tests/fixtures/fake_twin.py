"""Fake TWIN upstream for proxy tests: an MCP SDK lowlevel server over stdio.

Usage: python fake_twin.py --log LOG

Independent evidence (D10/A3): every line received on stdin is appended to LOG and
flushed BEFORE it is parsed or handled. Safety tests assert on this log, never on the
proxy's own cassette. All data here is synthetic (no real endpoints, no real secrets).

Tools (roles are assigned by the tests' policy, not here):
  read_page      text page (source)            json_page    JSON object text (source)
  json_list      JSON array text (source)      empty_result content [] (source)
  image_result   image-only content (source)   query_db     honey rows (private)
  structured     outputSchema + structuredContent (private)
  ask_sampling   sends sampling/createMessage to the proxy, reports the outcome (private)
  notify         sends a tools/list_changed notification first (private)
  slow           sleeps ``seconds`` (default 5) (private)
  crash          exits the process immediately (private)
  garbage        writes a non-JSON-RPC line to stdout (private)
  send_email     sink                          noop         no roles
"""

from __future__ import annotations

import argparse
import io
import os
import sys
import warnings
from pathlib import Path
from typing import Any

import anyio
import mcp_types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.shared.exceptions import MCPError

OBJ = {"type": "object", "properties": {}}
TOOLS = [
    types.Tool(name="read_page", description="Read a web page.", input_schema={
        "type": "object", "properties": {"url": {"type": "string"}}}),
    types.Tool(name="json_page", description="Read a JSON document.", input_schema=OBJ),
    types.Tool(name="json_list", description="Read a JSON list.", input_schema=OBJ),
    types.Tool(name="empty_result", description="Returns nothing.", input_schema=OBJ),
    types.Tool(name="image_result", description="Returns an image.", input_schema=OBJ),
    types.Tool(name="query_db", description="Query the customer table.", input_schema=OBJ),
    types.Tool(
        name="structured",
        description="Returns structured content.",
        input_schema=OBJ,
        output_schema={
            "type": "object",
            "properties": {"n": {"type": "integer"}},
            "required": ["n"],
        },
    ),
    types.Tool(name="ask_sampling", description="Asks the client to sample.", input_schema=OBJ),
    types.Tool(name="notify", description="Sends a notification.", input_schema=OBJ),
    types.Tool(name="slow", description="Sleeps.", input_schema={
        "type": "object", "properties": {"seconds": {"type": "number"}}}),
    types.Tool(name="crash", description="Exits.", input_schema=OBJ),
    types.Tool(name="garbage", description="Writes garbage.", input_schema=OBJ),
    types.Tool(name="send_email", description="Send an email.", input_schema={
        "type": "object", "properties": {"to": {"type": "string"}, "body": {"type": "string"}}}),
    types.Tool(name="noop", description="Does nothing.", input_schema=OBJ),
]  # fmt: skip


def _text(text: str) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)])


class LoggingStdin:
    """Async line iterator over stdin that logs each raw line before returning it."""

    def __init__(self, log: Path) -> None:
        self._log = log
        self._stdin = anyio.wrap_file(
            io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace", newline="\n")
        )

    def __aiter__(self) -> LoggingStdin:
        return self

    async def __anext__(self) -> str:
        line = await self._stdin.readline()
        if not line:
            raise StopAsyncIteration
        with self._log.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(line if line.endswith("\n") else line + "\n")
            fh.flush()
        return line


async def list_tools(ctx: Any, params: Any) -> types.ListToolsResult:
    return types.ListToolsResult(tools=TOOLS)


async def call_tool(ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
    args = params.arguments or {}
    name = params.name
    if name == "read_page":
        return _text(f"Docs for {args.get('url', 'the page')}: install with pip.")
    if name == "json_page":
        return _text('{"title": "Docs", "body": "install with pip"}')
    if name == "json_list":
        return _text('["a", "b"]')
    if name == "empty_result":
        return types.CallToolResult(content=[])
    if name == "image_result":
        return types.CallToolResult(
            content=[types.ImageContent(type="image", data="AAAA", mime_type="image/png")]
        )
    if name == "query_db":
        return _text('{"rows": [{"id": 1, "email": "honey@example.invalid"}]}')
    if name == "structured":
        return types.CallToolResult(
            content=[types.TextContent(type="text", text='{"n": 1}')],
            structured_content={"n": 1},
        )
    if name == "ask_sampling":
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                await ctx.session.create_message(
                    [
                        types.SamplingMessage(
                            role="user", content=types.TextContent(type="text", text="hi")
                        )
                    ],
                    max_tokens=5,
                    related_request_id=ctx.request_id,
                )
            except MCPError as exc:
                return _text(f"sampling_rejected:{exc.code}")
            except Exception as exc:
                return _text(f"sampling_failed:{type(exc).__name__}")
        return _text("sampling_accepted")
    if name == "notify":
        await ctx.session.send_tool_list_changed()
        return _text("notified")
    if name == "slow":
        await anyio.sleep(float(args.get("seconds", 5)))
        return _text("slow done")
    if name == "crash":
        os._exit(3)
    if name == "garbage":
        sys.stdout.buffer.write(b"this is not json-rpc\n")
        sys.stdout.buffer.flush()
        await anyio.sleep(5)
        return _text("garbage sent")
    if name == "send_email":
        return _text("sent")
    if name == "noop":
        return _text("noop")
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=f"unknown tool {name}")], is_error=True
    )


async def main(log: Path) -> None:
    server: Server[Any] = Server(
        "fake-twin", version="0.0.1", on_list_tools=list_tools, on_call_tool=call_tool
    )
    stdout = anyio.wrap_file(io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", newline="\n"))
    async with stdio_server(stdin=LoggingStdin(log), stdout=stdout) as (read, write):  # type: ignore[arg-type]
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", type=Path, required=True)
    anyio.run(main, parser.parse_args().log)
