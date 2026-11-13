"""Named proxy checks shared by safety, property and mutation tests.

Each ``assert_*`` is a named check: the safety/property tests call it on the real code,
the mutation tests break one layer and assert that the SAME check then fails.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import anyio
import mcp_types
from hypothesis import strategies as st
from mcp.shared.message import SessionMessage

from proveflow.core.attacks import Carrier
from proveflow.proxy import carriers, upstream
from proveflow.proxy.gate import GateBlocked, UpstreamGate
from proxyhelpers import (
    FORWARDED,
    TWIN_TOOLS,
    make_session,
    run_in_process,
    text_of,
    twin_policy,
    twin_tool_calls,
)

# --- layer B, handler ----------------------------------------------------------------

DENIED = ("send_email", "nonexistent_tool", "noop", "ghost")


def assert_sink_call_sandboxed(tmp_path: Path) -> None:
    """Named handler check: a sink call gets the sandbox response (not an error)."""

    async def script(client: Any) -> Any:
        return await client.call_tool("send_email", {"to": "x@example.invalid", "body": "b"})

    result, _ = run_in_process(make_session(tmp_path), script)
    assert result.is_error is False, f"sink call was not sandboxed: {text_of(result)!r}"
    assert json.loads(text_of(result)) == {"ok": True, "id": "sbx_0001"}


# --- layer B, gate on the write path ---------------------------------------------------


def assert_gate_blocks_on_write_path(tmp_path: Path) -> None:
    """Named gate check: a raw tools/call for a non-forward tool, written straight to the
    upstream transport (no handler involved), never reaches the twin."""
    session = make_session(tmp_path)
    caught: list[BaseException] = []

    async def run() -> None:
        state = upstream.UpstreamState()
        gate = UpstreamGate(session.policy)
        gate.set_advertised(TWIN_TOOLS)  # blocked because send_email is a sink, not unlisted
        try:
            async with upstream.twin_stdio(
                session.upstream, gate, state, lambda *a, **k: None, dict(os.environ)
            ) as (_read, write):
                msg = mcp_types.JSONRPCRequest(
                    jsonrpc="2.0", id=1, method="tools/call", params={"name": "send_email"}
                )
                try:
                    await write.send(SessionMessage(msg))
                except BaseException as exc:
                    caught.append(exc)
                await anyio.sleep(1.5)  # give a (mutated) writer time to deliver
        except BaseException as exc:
            caught.append(exc)

    anyio.run(run)
    assert "send_email" not in twin_tool_calls(tmp_path), "tools/call reached the twin"
    assert any(isinstance(e, GateBlocked) for e in caught), caught


# --- both layers: independent proof from the twin's own log ---------------------------


def assert_twin_never_sees_denied_calls(tmp_path: Path) -> None:
    """Named safety check (twin log, not cassette): zero tools/call for sink, unknown,
    unclassified and not-advertised tools; forwarded calls equal exactly the expected list."""

    async def script(client: Any) -> Any:
        for name in DENIED:
            await client.call_tool(name, {})
        for name in ("read_page", "query_db"):
            await client.call_tool(name, {})

    run_in_process(make_session(tmp_path), script)
    seen = twin_tool_calls(tmp_path)
    leaked = [n for n in seen if n in DENIED]
    assert not leaked, f"denied tools/call reached the twin: {leaked}"
    assert seen == ["read_page", "query_db"], seen
    assert set(seen) <= FORWARDED
    assert {n for n, p in twin_policy().items() if p.forward} == FORWARDED


# --- carriers (C3) ---------------------------------------------------------------------

CANARY_RE = st.from_regex(r"\Acnry_[0-9a-f]{12}\Z", fullmatch=True)
_SAFE = st.text(alphabet=st.characters(blacklist_categories=("Cs",)), max_size=40)
JSON_SCALAR = st.none() | st.booleans() | st.integers() | st.text(max_size=10)
JSON_DOC = st.recursive(
    JSON_SCALAR,
    lambda inner: (
        st.lists(inner, max_size=4) | st.dictionaries(st.text(max_size=6), inner, max_size=4)
    ),
    max_leaves=10,
)
JSON_OBJECT_TEXT = st.dictionaries(st.text(max_size=8), JSON_DOC, max_size=5).map(
    lambda d: json.dumps(d, ensure_ascii=False)
)
JSON_ARRAY_TEXT = st.lists(JSON_DOC, max_size=5).map(lambda v: json.dumps(v, ensure_ascii=False))
ANY_TEXT = _SAFE | JSON_OBJECT_TEXT | JSON_ARRAY_TEXT | JSON_SCALAR.map(json.dumps)


@st.composite
def payloads(draw: st.DrawFn) -> tuple[str, str]:
    """(payload, canary): a payload containing the canary exactly once."""
    canary = draw(CANARY_RE)
    prefix = draw(_SAFE.filter(lambda s: "cnry_" not in s))
    suffix = draw(_SAFE.filter(lambda s: "cnry_" not in s))
    return prefix + " " + canary + " " + suffix, canary


def assert_canary_once_more(carrier: Carrier, text: str, payload: str, canary: str) -> None:
    """C3 (1): the canary is in the output verbatim, once more than in the input text."""
    out = carriers.apply_carrier(carrier, text, payload)
    assert canary in out, "canary missing from carrier output"
    assert out.count(canary) == text.count(canary) + 1, "canary count changed unexpectedly"
