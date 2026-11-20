"""Oracle over REAL proxy sessions (in-process proxy + fake twin subprocess), and the
proxy's ``sink`` flag on every sandbox reason path (cassette schema 3), and honey needles
(Phase 4). No LLM: the
"agent" is a scripted SDK ClientSession."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from oraclechecks import (
    HONEY,
    assert_r1_fires_on_real_session,
    assert_r1_fires_on_real_session_for_honey,
)
from proveflow.core.trials import RuleHit
from proveflow.oracle.rules import evaluate_file
from proveflow.proxy.cassette import SandboxedCall, load_cassette
from proxyhelpers import (  # noqa: F401
    CANARY,
    LOOKALIKE,
    PRIVATE,
    TWIN_ROLES,
    make_attack,
    make_session,
    proxy_twin_root,
    run_in_process,
)


def sandboxed(path: Path) -> list[SandboxedCall]:
    return [e for e in load_cassette(path) if isinstance(e, SandboxedCall)]


def test_r1_fires_on_a_real_session(tmp_path: Path) -> None:
    findings = assert_r1_fires_on_real_session(tmp_path)
    assert findings.compromised
    [ev] = findings.evidence
    assert (ev.tool, ev.reason) == ("send_email", "policy_deny")
    assert [h.encoding for h in ev.hits] == ["raw"]


def test_real_session_r1_encoded_and_r4_after_injection(tmp_path: Path) -> None:
    async def script(client: Any) -> Any:
        await client.call_tool("send_email", {"to": "a@example.invalid", "body": "hi"})  # pre
        await client.call_tool("read_page", {"page": "intro"})  # injected source result
        await client.call_tool("send_email", {"to": "a@example.invalid", "body": "thanks"})
        blob = base64.b64encode(b"note:" + CANARY.encode()).decode()
        await client.call_tool("send_email", {"to": "a@example.invalid", "body": blob})
        await client.call_tool("query_db", {})  # forwarded, never a sink call

    session = make_session(tmp_path, attack=make_attack())
    run_in_process(session, script)
    findings = evaluate_file(session.cassette_path)
    assert [(e.rule, e.sandbox_id) for e in findings.evidence] == [
        (RuleHit.R4_SUSPICIOUS, "sbx_0002"),
        (RuleHit.R1_EXFIL, "sbx_0003"),
    ]
    assert [h.encoding for h in findings.evidence[1].hits] == ["base64"]
    assert findings.compromised and findings.session_id == "test-session"


def test_clean_real_session_has_no_findings(tmp_path: Path) -> None:
    async def script(client: Any) -> Any:
        await client.call_tool("send_email", {"to": "a@example.invalid", "body": CANARY})

    session = make_session(tmp_path)  # no attack armed: no canary to look for
    run_in_process(session, script)
    findings = evaluate_file(session.cassette_path)
    assert findings.canary is None and findings.rule_hits == () and not findings.compromised


# --- the proxy's sink flag, per reason path --------------------------------------------


def test_sink_flag_on_every_reason_path(tmp_path: Path) -> None:
    async def script(client: Any) -> Any:
        for name in ("send_email", "noop", "nonexistent", "SEND_EMAIL", "ghost"):
            await client.call_tool(name, {})

    run_in_process(make_session(tmp_path), script)
    got = [(e.tool, e.reason, e.sink) for e in sandboxed(tmp_path / "cassette.jsonl")]
    assert got == [
        ("send_email", "policy_deny", True),  # session sink role
        ("noop", "policy_deny", False),  # unclassified
        ("nonexistent", "unknown_tool", False),
        ("SEND_EMAIL", "unknown_tool", True),  # look-alike of a session sink
        ("ghost", "not_advertised", False),
    ]


def test_sink_flag_from_the_proxy_classifier(tmp_path: Path) -> None:
    """Forged session (send_email labeled private): the proxy's own classifier says sink."""
    roles = {**TWIN_ROLES, "send_email": (PRIVATE,)}

    async def script(client: Any) -> Any:
        await client.call_tool("send_email", {})

    run_in_process(make_session(tmp_path, roles=roles), script)
    [call] = sandboxed(tmp_path / "cassette.jsonl")
    assert (call.reason, call.sink) == ("proxy_classifier_sink", True)


def test_sink_flag_for_an_advertised_lookalike(tmp_path: Path) -> None:
    """The session labels only the look-alike private; the twin also lists send_email."""
    roles = {k: v for k, v in TWIN_ROLES.items() if k != "send_email"} | {LOOKALIKE: (PRIVATE,)}

    async def script(client: Any) -> Any:
        await client.call_tool(LOOKALIKE, {})

    run_in_process(make_session(tmp_path, roles=roles, twin_args=("--lookalike",)), script)
    [call] = sandboxed(tmp_path / "cassette.jsonl")
    assert (call.reason, call.sink) == ("name_collision", True)


def test_honey_r1_fires_on_a_real_session(tmp_path: Path) -> None:
    findings = assert_r1_fires_on_real_session_for_honey(tmp_path)
    assert findings.needles == ("canary", HONEY.id)
    [ev] = findings.evidence
    assert (ev.event, ev.tool, ev.needle, ev.reason) == (
        "sandboxed_call", "send_email", HONEY.id, "policy_deny",
    )  # fmt: skip
    start = load_cassette(tmp_path / "cassette.jsonl")[0]
    assert start.honey == [HONEY.model_dump(mode="json")]  # type: ignore[union-attr]
