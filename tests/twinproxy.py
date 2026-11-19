"""Named checks for the proxy over GENERATED twins (Phase 4, step 7): dual-role forwarding,
the guard step (R4), markers (F4). Shared by safety, integration and mutation tests.

Evidence rules:
* Safety claims rest on a log written OUTSIDE the proxy: the fake twin's own raw-byte log,
  or, for a generated (guard-passing, so log-less) twin, ``fixtures/stdin_tee.py``, a byte
  tee that sits between the proxy and the twin process (``tee_spawn``). The tee is inserted
  at the process boundary AFTER the guard ran on the hashed copy; it changes no decision.
* Liveness evidence that the twin itself answered is the twin's per-tool marker, taken from
  the ``TwinBuild`` and never from the session (F4).

Uses ``proxyhelpers.proxy_twin_root`` (autouse, import it into the test module).
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from proveflow.core.tools import ToolSpec
from proveflow.proxy import policy as policy_module
from proveflow.proxy import upstream
from proveflow.proxy.cassette import load_cassette
from proveflow.proxy.policy import TwinUpstream
from proveflow.proxy.session import ProxySession
from proveflow.twin.generator import TwinBuild, generate_twin, write_twin
from proxyhelpers import (
    SINK,
    SOURCE,
    TWIN_ROLES,
    evidence,
    make_session,
    run_in_process,
    text_of,
    twin_tool_calls,
)
from twinchecks import stored_tools

TEE = Path(__file__).resolve().parent / "fixtures" / "stdin_tee.py"
DUAL_FAKE = "fetch_url"  # fake_twin.py --dual


def install_twin(build: TwinBuild) -> Path:
    """Write the generated twin into the (test) TWIN_ROOT; layer A then accepts it."""
    return write_twin(build, policy_module.TWIN_ROOT)


def twin_session(
    tmp_path: Path,
    build: TwinBuild,
    tools: list[ToolSpec],
    *,
    attack: Any = None,
    cassette: str = "cassette.jsonl",
) -> ProxySession:
    script = policy_module.TWIN_ROOT / build.filename
    if not script.exists():
        install_twin(build)
    return ProxySession(
        session_id="twin-session",
        upstream=TwinUpstream(name=build.server, argv=(sys.executable, str(script))),
        twin_sha256=build.sha256,
        tools=tuple(tools),
        attack=attack,
        honey=build.honey,
        cassette_path=tmp_path / cassette,
    )


def tee_log(tmp_path: Path) -> Path:
    return tmp_path / "tee.log"


def tee_spawn(monkeypatch: pytest.MonkeyPatch, log: Path) -> None:
    """Run the twin behind ``stdin_tee.py`` (process boundary only, after the guard step)."""
    real = upstream.spawn

    async def teed(argv: Any, env: Any, **kwargs: Any) -> Any:
        return await real([sys.executable, str(TEE), str(log), *argv], env, **kwargs)

    monkeypatch.setattr(upstream, "spawn", teed)


def tee_tool_calls(log: Path) -> list[str]:
    """Every tools/call name the generated twin's process RECEIVED (tee log)."""
    if not log.is_file():
        return []
    msgs = [json.loads(line) for line in log.read_bytes().split(b"\n") if line.strip()]
    return [m["params"]["name"] for m in msgs if m.get("method") == "tools/call"]


def cassette_events(session: ProxySession) -> list[Any]:
    return load_cassette(session.cassette_path)


# --- dual-role, pure sink, guard-passing twin ----------------------------------------


def mixed_tools() -> list[ToolSpec]:
    """Stored fetch/fetch (dual-role by session v2 AND proxy v2) plus two stored pure sinks
    from filesystem: write_file (honest session label: sink) and move_file whose session
    label is FORGED to untrusted_source + sink (the proxy's own classifier says sink only)."""
    fetch = stored_tools("fetch")
    fs = {t.name: t for t in stored_tools("filesystem")}  # type: ignore[attr-defined]
    forged = fs["move_file"].model_copy(  # type: ignore[attr-defined]
        update={"roles": (evidence(SOURCE), evidence(SINK))}
    )
    return [*fetch, fs["write_file"], forged]  # type: ignore[list-item]


PURE_SINKS = ("write_file", "move_file")


def assert_pure_sink_never_reaches_twin_with_dual_role_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Named safety check (tee log): with a guard-passing twin the dual-role path is ON
    (fetch reaches the twin), and still neither pure sink does, not even the one whose
    session label was forged to source + sink."""
    tools = mixed_tools()
    build = generate_twin("mixed", tools, seed="pure-sink")
    session = twin_session(tmp_path, build, tools)
    log = tee_log(tmp_path)
    tee_spawn(monkeypatch, log)

    async def script(client: Any) -> Any:
        await client.call_tool("write_file", {"path": "/x.txt", "content": "c"})
        await client.call_tool("move_file", {"source": "/a", "destination": "/b"})
        return await client.call_tool("fetch", {"url": "https://example.invalid/"})

    run_in_process(session, script)
    seen = tee_tool_calls(log)
    leaked = [n for n in seen if n in PURE_SINKS]
    if leaked:
        raise AssertionError(f"pure sink reached the twin on the dual-role path: {leaked}")
    if seen != ["fetch"]:
        raise AssertionError(f"dual-role path not exercised as expected: {seen}")


# --- dual-role tool, guard-FAILING twin (fake twin) ----------------------------------


def assert_dual_role_never_reaches_guard_failing_twin(tmp_path: Path) -> None:
    """Named safety check (fake twin's own log): the session AND the proxy's classifier both
    say fetch_url is source + sink, but the fake twin fails the guard, so fetch_url is
    sandboxed and its tools/call never reaches the twin."""
    roles = {**TWIN_ROLES, DUAL_FAKE: (SOURCE, SINK)}
    session = make_session(tmp_path, roles=roles, twin_args=("--dual",))

    async def script(client: Any) -> Any:
        return await client.call_tool(DUAL_FAKE, {"url": "https://example.invalid/"})

    result, _ = run_in_process(session, script)
    if DUAL_FAKE in twin_tool_calls(tmp_path):
        raise AssertionError("dual-role tool reached a guard-failing twin")
    if json.loads(text_of(result)) != {"ok": True, "id": "sbx_0001"}:
        raise AssertionError(f"dual-role call on a guard-failing twin not sandboxed: {result}")


# --- dual-role forwarded to a generated twin: marker evidence -------------------------


def assert_dual_role_forwarded_with_marker(tmp_path: Path, attack: Any = None) -> TwinBuild:
    """Named check: fetch (dual-role) IS forwarded to the generated fetch twin. Evidence:
    the twin's own marker (from the TwinBuild, never the session) is the last block of the
    upstream_response, and the upstream_request is recorded with sink=true."""
    tools = stored_tools("fetch")
    build = generate_twin("fetch", tools, seed="dual")  # type: ignore[arg-type]
    session = twin_session(tmp_path, build, tools, attack=attack)  # type: ignore[arg-type]

    async def script(client: Any) -> Any:
        return await client.call_tool("fetch", {"url": "https://example.invalid/"})

    run_in_process(session, script)
    events = cassette_events(session)
    requests = [e for e in events if e.kind == "upstream_request"]
    responses = [e for e in events if e.kind == "upstream_response"]
    if [(e.tool, e.sink) for e in requests] != [("fetch", True)]:
        raise AssertionError(f"dual-role forward not recorded as sink=true: {requests}")
    if len(responses) != 1:
        raise AssertionError(f"expected one upstream_response, got {len(responses)}")
    last = responses[0].result["content"][-1]["text"]
    if last != f"twin-marker: {build.markers['fetch']}":
        raise AssertionError("upstream_response does not carry the twin's own marker")
    return build


# --- R4: copy -> hash the copy -> guard the same bytes -> spawn -----------------------


def assert_guard_runs_on_the_hashed_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, original_passes: bool
) -> None:
    """Named check (R4). The ORIGINAL file is swapped right after the copy is made:
    to a guard-failing script when the original passes, to a guard-passing one when it
    fails. ``guard_passed`` must follow the COPY, the guard must see exactly bytes whose
    sha256 is the session pin, the copy (not the original) is spawned, and the order is
    copy -> guard -> spawn."""
    import anyio

    from proveflow.proxy.gate import UpstreamGate
    from twinchecks import VALID_TWIN

    if original_passes:
        tools = stored_tools("fetch")
        build = generate_twin("fetch", tools, seed="r4")  # type: ignore[arg-type]
        session = twin_session(tmp_path, build, tools)  # type: ignore[arg-type]
        swap_to = VALID_TWIN + "\nopen('x', 'w')\n"
    else:
        session = make_session(tmp_path)
        swap_to = VALID_TWIN
    original = Path(session.upstream.argv[1])
    trace: list[str] = []
    guarded: list[str] = []
    spawned_argv: list[list[str]] = []
    real_copy, real_guard, real_spawn = (
        upstream.shutil.copyfile,
        upstream.check_no_io,
        upstream.spawn,
    )

    def copyfile(src: Any, dst: Any) -> Any:
        trace.append("copy")
        out = real_copy(src, dst)
        Path(src).write_text(swap_to, encoding="utf-8")  # the original changes after the copy
        return out

    def guard(source: str) -> None:
        trace.append("guard")
        guarded.append(source)
        real_guard(source)

    async def spawn(argv: Any, env: Any, **kwargs: Any) -> Any:
        trace.append("spawn")
        spawned_argv.append(list(argv))
        return await real_spawn(argv, env, **kwargs)

    monkeypatch.setattr(upstream.shutil, "copyfile", copyfile)
    monkeypatch.setattr(upstream, "check_no_io", guard)
    monkeypatch.setattr(upstream, "spawn", spawn)
    state = upstream.UpstreamState()

    async def run() -> None:
        async with upstream.twin_stdio(
            session.upstream,
            session.twin_sha256,
            UpstreamGate(session.policy),
            state,
            lambda *a, **k: None,
            {**__import__("os").environ},
            max_messages=100,
            on_limit=lambda reason: None,
        ):
            pass

    saved = original.read_bytes()
    try:
        anyio.run(run)
    finally:
        original.write_bytes(saved)  # the swap is part of this check only
    if trace != ["copy", "guard", "spawn"]:
        raise AssertionError(f"guard step order is {trace}")
    if state.guard_passed is not original_passes:
        raise AssertionError("guard verdict did not follow the hashed copy")
    [source] = guarded
    if hashlib.sha256(source.encode("utf-8")).hexdigest() != session.twin_sha256:
        raise AssertionError("the guard did not see the bytes that were hashed")
    if Path(spawned_argv[0][1]) == original:
        raise AssertionError("the original file was spawned, not the private copy")


# --- F4: markers never enter the session or session_start -----------------------------


def assert_no_marker_in_session_or_start(tmp_path: Path) -> None:
    """Named check (F4): no marker value appears in the session file or session_start."""
    tools = stored_tools("filesystem")
    build = generate_twin("filesystem", tools, seed="f4")  # type: ignore[arg-type]
    session = twin_session(tmp_path, build, tools)  # type: ignore[arg-type]
    session_file = tmp_path / "session.json"
    session_file.write_text(session.model_dump_json(indent=2), encoding="utf-8")
    text = session_file.read_text(encoding="utf-8")

    async def script(client: Any) -> Any:
        return await client.list_tools()

    run_in_process(session, script)
    start = cassette_events(session)[0]
    start_text = json.dumps(start.model_dump(mode="json"))
    if not build.markers:
        raise AssertionError("build has no markers; check is vacuous")
    for name, marker in build.markers.items():
        if marker in text:
            raise AssertionError(f"marker of {name} in the session file")
        if marker in start_text:
            raise AssertionError(f"marker of {name} in session_start")
    if len(start.honey) != len(build.honey) or not build.honey:
        raise AssertionError("session_start does not carry the session's honey")
