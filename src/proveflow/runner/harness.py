"""N twin proxies in this process, one MCP client session each (Phase 5, D4).

Each proxy is the real ``proxy.server.serve`` with its own ``ProxySession``, twin and
cassette, driven over in-memory streams (``serve`` takes any read/write streams;
proxy/server.py ``serve`` signature). Nothing in the proxy changes: the runner is just an
agent that holds N client sessions at once. Closing the agent side ends each proxy with
``agent_closed``, so every cassette gets its ``session_end``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import anyio
import mcp_types
from mcp import ClientSession
from mcp.shared.message import SessionMessage

from proveflow.proxy.server import ProxyOutcome, serve
from proveflow.proxy.session import ProxySession

PAGE_CAP = 100


@dataclass
class ProxyHandle:
    server: str
    session: ProxySession
    client: ClientSession
    tools: list[mcp_types.Tool]
    outcome: list[ProxyOutcome] = field(default_factory=list)


async def _list_tools(client: ClientSession) -> list[mcp_types.Tool]:
    tools: list[mcp_types.Tool] = []
    cursor: str | None = None
    for _ in range(PAGE_CAP):
        params = mcp_types.PaginatedRequestParams(cursor=cursor) if cursor else None
        page = await client.list_tools(params=params)
        tools.extend(page.tools)
        cursor = page.next_cursor
        if cursor is None:
            break
    return tools


@asynccontextmanager
async def running_proxies(
    sessions: Sequence[tuple[str, ProxySession]], *, parent_env: Mapping[str, str]
) -> AsyncIterator[list[ProxyHandle]]:
    """Start one in-process proxy per (server, session); yield their handles."""
    if len({s.session_id for _, s in sessions}) != len(sessions):
        raise ValueError("each proxy needs its own session_id")
    async with anyio.create_task_group() as tg, AsyncExitStack() as stack:
        handles: list[ProxyHandle] = []
        for server, session in sessions:
            a2p_w, a2p_r = anyio.create_memory_object_stream[SessionMessage | Exception](0)
            p2a_w, p2a_r = anyio.create_memory_object_stream[SessionMessage | Exception](0)
            box: list[ProxyOutcome] = []

            async def run(s: ProxySession = session, r: Any = a2p_r, w: Any = p2a_w,
                          b: list[ProxyOutcome] = box) -> None:  # fmt: skip
                b.append(await serve(s, r, w, parent_env=parent_env))

            tg.start_soon(run)
            stack.push_async_callback(a2p_w.aclose)  # runs AFTER the client session exits
            client = await stack.enter_async_context(ClientSession(p2a_r, a2p_w))
            await client.initialize()
            handles.append(ProxyHandle(server, session, client, await _list_tools(client), box))
        yield handles
