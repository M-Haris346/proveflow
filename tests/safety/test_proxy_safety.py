"""Proxy safety (ADR-006). Evidence comes from the fake twin's OWN log, never the cassette.

* zero tools/call for sink, unknown, unclassified and not-advertised tools reach the twin;
  forwarded calls equal exactly the expected list
* H1: a session whose evidence forges a sink as private cannot get it forwarded (the
  proxy's own classifier); a ``policy`` key is refused
* the gate blocks on the write path even with no handler involved
* H2: a non-python upstream, an installed package module, a .py outside TWIN_ROOT, a
  symlink escaping TWIN_ROOT, and a hash-pin mismatch are all refused before spawn
* M2: the twin log is raw bytes written before decoding (tested with unparseable input)
* L5: a full in-process session in ``python -I`` loads no forbidden module
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
from proveflow.proxy import policy as policy_module
from proveflow.proxy import upstream
from proveflow.proxy.gate import UpstreamGate
from proveflow.proxy.policy import TwinUpstream, TwinUpstreamError
from proxychecks import (
    assert_forged_session_cannot_forward_sink,
    assert_gate_blocks_on_write_path,
    assert_sink_call_sandboxed,
    assert_twin_never_sees_denied_calls,
)
from proxyhelpers import (  # noqa: F401
    TWIN_SRC,
    make_escape_link,
    make_session,
    proxy_argv,
    proxy_twin_root,
    twin_messages,
    twin_script,
    write_session,
)

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


def test_forged_session_cannot_forward_sink(tmp_path: Path) -> None:
    assert_forged_session_cannot_forward_sink(tmp_path)


def test_cli_refuses_session_with_policy_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _forbid_spawn(monkeypatch)
    data = json.loads(make_session(tmp_path).model_dump_json())
    data["policy"] = {"send_email": {"forward": True, "inject": False}}
    path = tmp_path / "session.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    result = CliRunner().invoke(app, ["proxy", "--session", str(path)])
    assert result.exit_code == 1
    assert "policy" in result.output
    assert calls == []


def test_twin_log_records_raw_bytes_before_parsing(tmp_path: Path) -> None:
    """M2/A3: lines the twin cannot decode or parse are in its log, byte-exact, in order,
    before the valid message that follows them."""
    log = tmp_path / "raw.log"
    lines = [
        b"this is not json",
        b'[{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"send_email"}}]',
        b"\xff\xfe",
        b'{"jsonrpc":"2.0","id":2,"method":"initialize","params":{"protocolVersion":'
        b'"2025-06-18","capabilities":{},"clientInfo":{"name":"t","version":"0"}}}',
    ]
    proc = subprocess.run(
        [sys.executable, str(TWIN_SRC), "--log", str(log)],
        input=b"".join(line + b"\n" for line in lines),
        capture_output=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert log.read_bytes().split(b"\n")[:-1] == lines
    assert b'"id":2' in proc.stdout  # the twin kept serving and answered initialize


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
    with pytest.raises(TwinUpstreamError):
        _open_transport(tmp_path, forged)
    assert calls == []


def _open_transport(tmp_path: Path, up: TwinUpstream, sha: str | None = None) -> None:
    session = make_session(tmp_path)

    async def run() -> None:
        async with upstream.twin_stdio(
            up,
            sha or session.twin_sha256,
            UpstreamGate(session.policy),
            upstream.UpstreamState(),
            lambda *a, **k: None,
            dict(os.environ),
            max_messages=100,
            on_limit=lambda reason: None,
        ):
            raise AssertionError("must not get here")

    anyio.run(run)


def _forge(argv1: Path) -> TwinUpstream:
    return TwinUpstream.model_construct(name="twin", argv=(sys.executable, str(argv1)))


def test_installed_package_module_refused_before_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import mcp

    calls = _forbid_spawn(monkeypatch)
    with pytest.raises(TwinUpstreamError, match="TWIN_ROOT"):
        _open_transport(tmp_path, _forge(Path(mcp.__file__).parent / "server" / "__main__.py"))
    assert calls == []


def test_py_outside_twin_root_refused_before_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _forbid_spawn(monkeypatch)
    outside = tmp_path / "fake_twin.py"
    outside.write_bytes(twin_script().read_bytes())  # identical content, wrong place
    with pytest.raises(TwinUpstreamError, match="TWIN_ROOT"):
        _open_transport(tmp_path, _forge(outside))
    assert calls == []


def test_symlink_escaping_twin_root_refused_before_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _forbid_spawn(monkeypatch)
    outside = tmp_path / "outside"
    outside.mkdir()
    link = make_escape_link(policy_module.TWIN_ROOT, outside)
    with pytest.raises(TwinUpstreamError, match="TWIN_ROOT"):
        _open_transport(tmp_path, _forge(link))
    assert calls == []


def test_hash_mismatch_refused_before_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The session pins twin_sha256; the twin file changed afterwards -> refused (the copy
    in the private cwd is what gets hashed)."""
    calls = _forbid_spawn(monkeypatch)
    session = make_session(tmp_path)  # pins the current hash
    twin_script().write_bytes(twin_script().read_bytes() + b"\n# swapped after the session\n")
    with pytest.raises(TwinUpstreamError, match="sha256"):
        _open_transport(tmp_path, session.upstream, session.twin_sha256)
    assert calls == []


def test_cli_hash_mismatch_refused(tmp_path: Path) -> None:
    """Same through the real CLI subprocess: exit 1, no twin ever started."""
    data = json.loads(make_session(tmp_path).model_dump_json())
    data["twin_sha256"] = "0" * 64
    path = tmp_path / "session.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    proc = subprocess.run(proxy_argv(path), capture_output=True, timeout=60, stdin=subprocess.PIPE)
    assert proc.returncode == 1
    assert not (tmp_path / "twin.log").exists()
    events = (tmp_path / "cassette.jsonl").read_text(encoding="utf-8").splitlines()
    assert any(json.loads(e).get("detail") == "TwinUpstreamError" for e in events)


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
        proxy_argv(path),
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


def _is_alive(p: psutil.Process) -> bool:
    """A process that vanished between listing and inspection is gone (the success case);
    a zombie is gone too. Fixes a NoSuchProcess race seen once in a local full-suite run."""
    try:
        return p.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def _assert_twins_gone(tmp_path: Path, timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        alive = [p for p in _twin_processes(tmp_path) if _is_alive(p)]
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


# Exit code of a HANDLED SIGTERM: the watcher calls control.stop("sigterm")
# (src/proveflow/proxy/server.py:570-574), which sets the reason before killing the tree and
# cancelling the session (server.py:87-92); serve() reports outcome.reason == "sigterm"
# (server.py:430-433); the CLI raises typer.Exit(1) only for reasons NOT in
# ("agent_closed", "sigterm") (src/proveflow/cli.py:383-386), so the process exits 0.
# Without a handler, the default action kills the process: Popen.returncode == -SIGTERM.
HANDLED_SIGTERM_EXIT = 0


def _wait_proxy(
    proc: subprocess.Popen[bytes], real: psutil.Process, timeout: float = 30
) -> tuple[int | None, str]:
    """Wait for the REAL proxy process to exit. On POSIX the bootstrap argv runs the proxy in
    ``proc`` itself (no launcher), so ``real.pid == proc.pid`` is expected; if not, wait on
    ``real`` (psutil returns no exit code for a non-child: ``None``) and say so."""
    if real.pid == proc.pid:
        return proc.wait(timeout=timeout), "proc"
    return real.wait(timeout=timeout), f"real (pid {real.pid} != Popen pid {proc.pid})"


def _check_sigterm_kills_twin(tmp_path: Path) -> None:
    proc, real = _start_proxy(tmp_path)
    try:
        real.send_signal(signal.SIGTERM)
        _assert_twins_gone(tmp_path)
        # The twin dies first (stop() kills the tree), session_end is written afterwards:
        # wait for the proxy to EXIT before reading the cassette (the race seen in CI run
        # 43575764649: the last line was not yet session_end).
        code, waited_on = _wait_proxy(proc, real)
        events = (tmp_path / "cassette.jsonl").read_text(encoding="utf-8").splitlines()
        last = json.loads(events[-1])
        if code == HANDLED_SIGTERM_EXIT:
            verdict = "handler ran"
        elif code == -signal.SIGTERM:
            verdict = "-15: SIGTERM NOT handled (default action, no handler ran)"
        elif code is None:
            verdict = f"exit code unknown, waited on {waited_on}"
        else:
            verdict = f"unexpected exit code {code}"
        if waited_on == "proc":
            assert code == HANDLED_SIGTERM_EXIT, (
                f"proxy exit {code} ({verdict}); last event kind={last.get('kind')}"
            )
        assert last.get("kind") == "session_end", (
            f"cassette incomplete ({verdict}): last event {last}"
        )
        assert last["reason"] == "sigterm", last
    finally:
        _cleanup(proc, tmp_path)


def _check_sigkill_twin_exits(tmp_path: Path) -> None:
    proc, real = _start_proxy(tmp_path)
    try:
        real.send_signal(signal.SIGKILL)
        _assert_twins_gone(tmp_path)
    finally:
        _cleanup(proc, tmp_path)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
def test_sigterm_to_proxy_kills_twin_posix(tmp_path: Path) -> None:
    _check_sigterm_kills_twin(tmp_path)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
def test_sigkill_to_proxy_twin_exits_on_stdin_eof_posix(tmp_path: Path) -> None:
    """Residual (ADR-006): SIGKILL runs no handler; the twin exits because its stdin closes."""
    _check_sigkill_twin_exits(tmp_path)


# TEMPORARY race check (Phase 2.1, CI run 43575764649): each POSIX kill test 10 more times.
# Remove in a separate change once CI shows all 20 repetitions green.
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
@pytest.mark.parametrize("rep", range(10))
def test_repeat_sigterm_posix(tmp_path: Path, rep: int) -> None:
    _check_sigterm_kills_twin(tmp_path)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
@pytest.mark.parametrize("rep", range(10))
def test_repeat_sigkill_posix(tmp_path: Path, rep: int) -> None:
    _check_sigkill_twin_exits(tmp_path)


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
    assert "proveflow.flows.roles" in data["loaded"]  # the second opinion is in the guard
    leaked = [m for m in data["loaded"] if _forbidden(m)]
    assert leaked == []


RUNTIME_GUARD = """
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import proveflow.proxy.policy as p
p.TWIN_ROOT = Path(sys.argv[2])
from proxyhelpers import make_attack, make_session, run_in_process
tmp = Path(sys.argv[3])
async def script(c):
    await c.list_tools()
    for n in ("read_page", "send_email", "structured", "bump_tools", "crash"):
        await c.call_tool(n, {})
_, outcome = run_in_process(make_session(tmp, attack=make_attack()), script)
print(json.dumps({"reason": outcome.reason, "loaded": sorted(sys.modules)}))
"""


def test_runtime_import_guard_after_full_session(tmp_path: Path) -> None:
    """L5: a FULL in-process session (injection, sink, structured, notification, crash) in a
    fresh ``python -I`` interpreter: still no forbidden module in sys.modules afterwards."""
    tests_dir = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [sys.executable, "-I", "-c", RUNTIME_GUARD, str(tests_dir),
         str(policy_module.TWIN_ROOT), str(tmp_path)],
        capture_output=True,
        timeout=180,
    )  # fmt: skip
    assert proc.returncode == 0, proc.stderr[-3000:]
    data = json.loads(proc.stdout.splitlines()[-1])
    assert data["reason"] == "agent_closed"
    assert "proveflow.proxy.server" in data["loaded"]
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
