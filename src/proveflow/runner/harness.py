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

from proveflow.proxy.cassette import HANDSHAKE_STAGES
from proveflow.proxy.server import ProxyOutcome, serve
from proveflow.proxy.session import ProxySession

PAGE_CAP = 100

# Phase 7.0, the HARNESS layer of the handshake bound (the proxy's per-stage bound is the
# other layer; neither subsumes the other: tests/unit/test_handshake.py, one mutation per layer
# plus the layering). A proxy cannot answer the agent's initialize until ITS upstream handshake
# is done, so the proxy's worst case is one per-stage bound per upstream stage,
# len(HANDSHAKE_STAGES) * handshake_timeout_s; the agent's own initialize + tools/list to the
# proxy needs one more bound. HARNESS_MARGIN on top makes the PROXY fire first whenever it can,
# because only the proxy can NAME the stage (the harness can only say "this proxy did not start").
# Derived, never a literal: raising HANDSHAKE_TIMEOUT_S must not invert the layers.
HARNESS_MARGIN = 1.5


def proxy_handshake_bound_s(handshake_timeout_s: float) -> float:
    """The proxy's worst case before it can serve the agent: one bound per upstream stage."""
    return len(HANDSHAKE_STAGES) * handshake_timeout_s


def startup_bound_s(handshake_timeout_s: float) -> float:
    """The harness's bound on one proxy's startup (initialize + tools/list), always above
    ``proxy_handshake_bound_s`` (pinned for a RANGE of timeouts). Module global: mutations."""
    return (len(HANDSHAKE_STAGES) + 1) * handshake_timeout_s * HARNESS_MARGIN


class ProxyStartupTimeout(RuntimeError):
    """A proxy did not complete the agent's initialize + tools/list within the harness bound:
    the backstop when the proxy itself did not end the session (it names no stage)."""


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
            bound = startup_bound_s(session.limits.handshake_timeout_s)
            try:
                with anyio.fail_after(bound):
                    await client.initialize()
                    tools = await _list_tools(client)
            except TimeoutError:
                raise ProxyStartupTimeout(
                    f"proxy {server!r} (session {session.session_id}) did not complete startup "
                    f"within {bound} s"
                ) from None
            handles.append(ProxyHandle(server, session, client, tools, box))
        yield handles
