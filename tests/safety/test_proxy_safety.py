"""Proxy safety (ADR-006). Evidence comes from the fake twin's OWN log, never the cassette.

* zero tools/call for sink, unknown, unclassified and not-advertised tools reach the twin;
  forwarded calls equal exactly the expected list
* the gate blocks on the write path even with no handler involved
* a non-python upstream is refused before anything is spawned
* killing the proxy kills the twin (Windows: TerminateProcess + Job; POSIX: SIGTERM handler
  kills the tree; SIGKILL: the twin exits on stdin EOF - residual in ADR-006)
* import guard: AST scan + a fresh ``python -I`` interpreter's sys.modules
"""

from __future__ import annotations

import ast
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import anyio
import psutil
import pytest
from typer.testing import CliRunner

import proveflow.proxy
from proveflow.cli import app
from proveflow.introspect import procs
from proveflow.proxy import upstream
from proveflow.proxy.gate import UpstreamGate
from proveflow.proxy.policy import TwinUpstream, TwinUpstreamError
from proxychecks import (
    assert_gate_blocks_on_write_path,
    assert_sink_call_sandboxed,
    assert_twin_never_sees_denied_calls,
)
from proxyhelpers import make_session, twin_messages, write_session

PROXY_DIR = Path(proveflow.proxy.__file__).parent
FORBIDDEN_PREFIXES = ("proveflow.discover",)
FORBIDDEN_EXACT = (
    "proveflow.introspect.launchspec",
    "proveflow.introspect.transport",
    "proveflow.introspect.runner",
    "proveflow.core.client",
)


def test_twin_never_sees_denied_calls(tmp_path: Path) -> None:
    assert_twin_never_sees_denied_calls(tmp_path)


def test_sink_call_is_sandboxed(tmp_path: Path) -> None:
    assert_sink_call_sandboxed(tmp_path)


def test_gate_blocks_on_write_path(tmp_path: Path) -> None:
    assert_gate_blocks_on_write_path(tmp_path)


def test_twin_log_records_before_parsing(tmp_path: Path) -> None:
    """A3: the twin log is written before parsing, so even a line the twin cannot parse
    would be visible. Every logged line here is a JSON-RPC message from the proxy."""
    assert_twin_never_sees_denied_calls(tmp_path)
    messages = twin_messages(tmp_path)
    assert messages[0]["method"] == "initialize"
    assert {m.get("method") for m in messages} <= {
        "initialize",
        "notifications/initialized",
        "tools/list",
        "tools/call",
        None,  # responses (none expected here, allowed by D4)
    }


# --- refused before spawn ----------------------------------------------------------------


def _forbid_spawn(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    calls: list[object] = []

    async def no_spawn(*args: object, **kwargs: object) -> None:
        calls.append(args)
        raise AssertionError("spawn must not be called")

    monkeypatch.setattr(procs, "spawn", no_spawn)
    monkeypatch.setattr(upstream, "spawn", no_spawn)
    return calls


@pytest.mark.parametrize(
    "argv",
    [["npx", "-y", "server-everything"], ["uvx", "mcp-server-fetch"], ["docker", "run", "x"],
     ["node", "s.js"], ["https://example.invalid/mcp"]],
    ids=["npx", "uvx", "docker", "node", "url"],
)  # fmt: skip
def test_cli_refuses_non_python_upstream_before_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, argv: list[str]
) -> None:
    calls = _forbid_spawn(monkeypatch)
    data = json.loads(make_session(tmp_path).model_dump_json())
    data["upstream"]["argv"] = argv
    path = tmp_path / "session.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    result = CliRunner().invoke(app, ["proxy", "--session", str(path)])
    assert result.exit_code == 1
    assert "invalid session file" in result.output
    assert calls == []
    assert not (tmp_path / "cassette.jsonl").exists()


def test_transport_rechecks_twin_argv_before_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even a TwinUpstream built WITHOUT validation (model_construct) is refused."""
    calls = _forbid_spawn(monkeypatch)
    forged = TwinUpstream.model_construct(name="real", argv=("npx", "-y", "server"))
    session = make_session(tmp_path)

    async def run() -> None:
        async with upstream.twin_stdio(
            forged, UpstreamGate(session.policy), upstream.UpstreamState(),
            lambda *a, **k: None, dict(os.environ),
        ):  # fmt: skip
            raise AssertionError("must not get here")

    with pytest.raises(TwinUpstreamError):
        anyio.run(run)
    assert calls == []


# --- killing the proxy kills the twin ------------------------------------------------------


def _twin_processes(tmp_path: Path) -> list[psutil.Process]:
    out = []
    for p in psutil.process_iter(["cmdline"]):
        cmd = p.info["cmdline"] or []
        if any("fake_twin.py" in a for a in cmd) and any(str(tmp_path) in a for a in cmd):
            out.append(p)
    return out


def _start_proxy(tmp_path: Path) -> tuple[subprocess.Popen[bytes], psutil.Process]:
    """Start the CLI proxy, wait until the twin answered tools/list, and return the real
    proxy process (parent of the top twin process; on Windows the venv python.exe is a
    launcher that runs the real interpreter as a child)."""
    path = write_session(tmp_path, make_session(tmp_path))
    proc = subprocess.Popen(
        [sys.executable, "-m", "proveflow", "proxy", "--session", str(path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if any(m.get("method") == "tools/list" for m in twin_messages(tmp_path)):
            break
        time.sleep(0.1)
    else:
        proc.kill()
        raise AssertionError("twin never received tools/list")
    twins = _twin_processes(tmp_path)
    assert twins, "no twin process found"
    twin_pids = {p.pid for p in twins}
    top = next(p for p in twins if p.ppid() not in twin_pids)
    return proc, psutil.Process(top.ppid())


def _assert_twins_gone(tmp_path: Path, timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        alive = [p for p in _twin_processes(tmp_path) if p.status() != psutil.STATUS_ZOMBIE]
        if not alive:
            return
        time.sleep(0.2)
    raise AssertionError(f"twin still alive: {[p.pid for p in alive]}")


def _cleanup(proc: subprocess.Popen[bytes], tmp_path: Path) -> None:
    for p in _twin_processes(tmp_path):
        try:
            p.kill()
        except psutil.Error:
            pass
    if proc.poll() is None:
        proc.kill()
    proc.wait(timeout=30)
    for stream in (proc.stdin, proc.stdout):
        if stream is not None:
            stream.close()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows: TerminateProcess + Job Object")
def test_terminating_proxy_kills_twin_windows(tmp_path: Path) -> None:
    proc, real = _start_proxy(tmp_path)
    try:
        real.kill()  # TerminateProcess: no handler runs; the Job closes with the process
        _assert_twins_gone(tmp_path)
    finally:
        _cleanup(proc, tmp_path)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
def test_sigterm_to_proxy_kills_twin_posix(tmp_path: Path) -> None:
    proc, real = _start_proxy(tmp_path)
    try:
        real.send_signal(signal.SIGTERM)
        _assert_twins_gone(tmp_path)
        events = (tmp_path / "cassette.jsonl").read_text(encoding="utf-8").splitlines()
        assert json.loads(events[-1])["reason"] == "sigterm"
    finally:
        _cleanup(proc, tmp_path)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
def test_sigkill_to_proxy_twin_exits_on_stdin_eof_posix(tmp_path: Path) -> None:
    """Residual (ADR-006): SIGKILL runs no handler; the twin exits because its stdin closes."""
    proc, real = _start_proxy(tmp_path)
    try:
        real.send_signal(signal.SIGKILL)
        _assert_twins_gone(tmp_path)
    finally:
        _cleanup(proc, tmp_path)


# --- import guard --------------------------------------------------------------------------


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{a.name}" for a in node.names)
    return names


def _forbidden(name: str) -> bool:
    return (
        name.startswith(FORBIDDEN_PREFIXES)
        or name in FORBIDDEN_EXACT
        or any(name.startswith(f + ".") for f in FORBIDDEN_EXACT)
        or name.endswith((".ServerSpec", ".LaunchSpec"))
    )


def test_proxy_sources_do_not_import_forbidden_modules() -> None:
    files = sorted(PROXY_DIR.glob("*.py"))
    assert {f.name for f in files} >= {"policy.py", "gate.py", "server.py", "upstream.py"}
    bad = {f.name: sorted(n for n in _imported_modules(f) if _forbidden(n)) for f in files}
    assert {k: v for k, v in bad.items() if v} == {}


def test_fresh_interpreter_import_guard() -> None:
    """Every proxy submodule imported in a fresh ``python -I``: no forbidden module loads."""
    code = (
        "import importlib, json, pkgutil, sys\n"
        "import proveflow.proxy as p\n"
        "mods = sorted(m.name for m in pkgutil.iter_modules(p.__path__, 'proveflow.proxy.'))\n"
        "for m in mods: importlib.import_module(m)\n"
        "print(json.dumps({'mods': mods, 'loaded': sorted(sys.modules)}))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-I", "-c", code], capture_output=True, timeout=120, check=True
    )
    data = json.loads(proc.stdout)
    assert "proveflow.proxy.server" in data["mods"] and "proveflow.proxy.upstream" in data["mods"]
    leaked = [m for m in data["loaded"] if _forbidden(m)]
    assert leaked == []


def test_guard_detects_a_forbidden_import() -> None:
    """The guard itself works: these names would be flagged."""
    for name in (*FORBIDDEN_EXACT, "proveflow.discover", "proveflow.discover.readers"):
        assert _forbidden(name)
    assert not _forbidden("proveflow.introspect.procs")
    assert not _forbidden("proveflow.core.attacks")


def test_cli_process_loads_discover_accepted() -> None:
    """Documented (ADR-006, C1): the CLI process itself imports discover (cli.py top level);
    the guard is about the proxy package."""
    code = "import sys, proveflow.cli; print('proveflow.discover' in sys.modules)"
    proc = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, timeout=120)
    assert proc.stdout.strip() == b"True"
