"""Mutation test: disable the transport's method allowlist -> the named safety check fails.

The named check drives a REAL fake server through ``proveflow_stdio`` and tries to send
``tools/call``. With the allowlist on, ForbiddenMethod is raised before a byte is written
and the server never sees the call. With it off, the server log shows ``tools/call``.
"""

from __future__ import annotations

import os
from pathlib import Path

import anyio
import mcp_types
import pytest
from mcp.shared.message import SessionMessage

from fakehome import fake_servers_file, logged_methods
from proveflow.discover.readers import read_explicit
from proveflow.introspect import transport
from proveflow.introspect.launchspec import build_launch_spec


def _send_tools_call(tmp_path: Path) -> BaseException | None:
    servers = fake_servers_file(tmp_path, {"srv": "legacy"})
    [cfg] = read_explicit(servers)
    caught: list[BaseException] = []

    async def run() -> None:
        with build_launch_spec(cfg.servers[0]) as spec:
            state = transport.TransportState()
            try:
                async with transport.proveflow_stdio(spec, state, dict(os.environ)) as (_r, w):
                    msg = mcp_types.JSONRPCRequest(
                        jsonrpc="2.0", id=1, method="tools/call", params={"name": "send_email"}
                    )
                    await w.send(SessionMessage(msg))
                    await anyio.sleep(1.5)  # give a (mutated) writer time to deliver
            except BaseException as exc:
                caught.append(exc)

    anyio.run(run)
    return caught[0] if caught else None


def assert_tools_call_blocked(tmp_path: Path) -> None:
    """Named safety check: tools/call never reaches the server."""
    exc = _send_tools_call(tmp_path)
    methods = logged_methods(tmp_path, "srv") or []
    assert "tools/call" not in methods, "tools/call reached the server"
    leaves = list(exc.exceptions) if isinstance(exc, BaseExceptionGroup) else [exc]
    assert any(isinstance(e, transport.ForbiddenMethod) for e in leaves), exc


def test_allowlist_blocks_tools_call(tmp_path: Path) -> None:
    assert_tools_call_blocked(tmp_path)


def test_disabling_allowlist_makes_named_check_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(transport, "check_outgoing", lambda message: None)
    with pytest.raises(AssertionError, match="tools/call reached the server"):
        assert_tools_call_blocked(tmp_path)


@pytest.mark.parametrize("method", ["tools/call", "resources/read", "prompts/get", "sampling/x"])
def test_check_outgoing_rejects_everything_else(method: str) -> None:
    msg = mcp_types.JSONRPCRequest(jsonrpc="2.0", id=1, method=method)
    with pytest.raises(transport.ForbiddenMethod):
        transport.check_outgoing(msg)


def test_check_outgoing_allows_responses() -> None:
    transport.check_outgoing(mcp_types.JSONRPCResponse(jsonrpc="2.0", id=1, result={}))
