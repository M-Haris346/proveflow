"""Named checks for Phase 9 (Ship): the scan gate, its fail-closed error invariant, the Action's
measured blind spot, and the tag/version check. Every scan runs through the real CLI against a
FAKE home (tests/fakehome.py), never the machine's own; only the repo's own fake MCP server is
ever launched."""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from fakehome import make_host

REPO = Path(__file__).resolve().parents[1]
ACTION_FIXTURES = REPO / "tests" / "fixtures" / "action"
FAKE_SERVER = REPO / "tests" / "fixtures" / "fake_mcp_server.py"
runner = CliRunner()


def scan(tmp_path: Path, mp: pytest.MonkeyPatch, *args: str) -> Any:
    """The real `proveflow scan` with a fake (empty) home and project under ``tmp_path``."""
    import proveflow.cli as cli

    host = make_host(tmp_path)
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)
    mp.setattr(cli, "_host", lambda: host)
    return runner.invoke(cli.app, ["scan", "--project", str(project), "--cache-dir",
                                   str(tmp_path / "cache"), "--no-cache-write", *args])  # fmt: skip


def fixture(name: str) -> str:
    return str(ACTION_FIXTURES / f"{name}.servers.json")


# --- the gate -------------------------------------------------------------------------------

GATE_CASES = (  # (fixture, --fail-on, exit): exit 3 ONLY for matched flows (Ruling 3)
    ("toxic", "exfil", 3), ("toxic", "action", 3), ("toxic", "leak", 3), ("toxic", "any", 3),
    ("clean", "any", 0), ("clean", "exfil", 0), ("blind_spot", "any", 0),
)  # fmt: skip


def assert_fail_on_exits_3_only_for_matched_flows(tmp_path: Path, mp: pytest.MonkeyPatch) -> None:
    """Named check: --fail-on exits 3 exactly when a flow of that class is in the report, 0 when
    none is (``any`` with zero flows included), and a bad --fail-on value exits 1."""
    for i, (name, fail_on, want) in enumerate(GATE_CASES):
        r = scan(tmp_path / f"g{i}", mp, "--servers", fixture(name), "--no-launch", "--json",
                 "--fail-on", fail_on)  # fmt: skip
        if r.exit_code != want:
            raise AssertionError(f"{name} --fail-on {fail_on}: exit {r.exit_code}, want {want}")
        if want == 3 and "THEORETICAL" not in r.stderr:
            raise AssertionError(f"{name}: a --no-launch finding not called THEORETICAL")
    bad = scan(tmp_path / "bad", mp, "--servers", fixture("toxic"), "--no-launch",
               "--fail-on", "everything")  # fmt: skip
    if bad.exit_code != 1:
        raise AssertionError(f"a bad --fail-on value exited {bad.exit_code}, want 1")


def _malformed(tmp: Path) -> Path:
    p = tmp / "bad.servers.json"
    tmp.mkdir(parents=True, exist_ok=True)
    p.write_text("{not json", encoding="utf-8")
    return p


def _discovered(tmp: Path, *, directory: bool) -> None:
    """A discovered Cursor user config (~/.cursor/mcp.json) that is unreadable (a directory)
    or malformed. ``make_host`` puts the fake home at ``tmp/home``."""
    target = tmp / "home" / ".cursor" / "mcp.json"
    if directory:
        target.mkdir(parents=True)
    else:
        target.parent.mkdir(parents=True)
        target.write_text("{not json", encoding="utf-8")


ERROR_CASES = ("servers_parse_error", "discovered_parse_error", "discovered_unreadable",
               "servers_invalid_entries")  # fmt: skip


def assert_an_error_is_never_a_finding(tmp_path: Path, mp: pytest.MonkeyPatch, case: str) -> None:
    """Named check (Ruling B), one per status: under --fail-on any, a config the scan could not
    read exits 1, NEVER 3 (a finding) and NEVER 0 (a pass), even when the toxic fixture's flows
    are in the same scan."""
    tmp = tmp_path / case
    tmp.mkdir(parents=True)
    servers = fixture("toxic")
    if case == "servers_parse_error":
        servers = str(_malformed(tmp))
    elif case == "discovered_parse_error":
        _discovered(tmp, directory=False)
    elif case == "discovered_unreadable":
        _discovered(tmp, directory=True)
    elif case == "servers_invalid_entries":
        servers = str(REPO / "tests" / "fixtures" / "configs" / "bad_entries.json")
    r = scan(tmp, mp, "--servers", servers, "--no-launch", "--json", "--fail-on", "any")
    if r.exit_code != 1:
        raise AssertionError(f"{case}: exit {r.exit_code}, want 1 (an error is never a finding "
                             "and never a pass)")  # fmt: skip
    if "could not read" not in r.stderr:
        raise AssertionError(f"{case}: exit 1 without naming the config it could not read")


def assert_absent_and_unsupported_configs_are_not_errors(
    tmp_path: Path, mp: pytest.MonkeyPatch
) -> None:
    """Named check: NOT_FOUND (every client config absent in the empty fake home) and
    UNSUPPORTED (VS Code's user profile, always) are not errors: the clean fixture exits 0."""
    from proveflow.core.client import ConfigStatus
    from proveflow.discover import run_discovery

    host = make_host(tmp_path / "s")
    statuses = {c.status for c in run_discovery(host, tmp_path, Path(fixture("clean")))}
    if not {ConfigStatus.NOT_FOUND, ConfigStatus.UNSUPPORTED} <= statuses:
        raise AssertionError(f"premise: the fake home gives statuses {statuses}")
    r = scan(tmp_path / "s", mp, "--servers", fixture("clean"), "--no-launch", "--fail-on", "any")
    if r.exit_code != 0:
        raise AssertionError(f"absent/unsupported configs made the gate exit {r.exit_code}")


# --- the blind spot ---------------------------------------------------------------------------


def _launchable(name: str, tmp: Path) -> Path:
    """The same fixture entries, made launchable: this interpreter, the absolute script path,
    and the fake server's required --log."""
    body = json.loads(Path(fixture(name)).read_text(encoding="utf-8"))
    out = {"mcpServers": {n: {"command": sys.executable,
                              "args": [str(REPO / e["args"][0]), *e["args"][1:], "--log",
                                       str(tmp / f"{n}.log")]}
                          for n, e in body["mcpServers"].items()}}  # fmt: skip
    path = tmp / f"{name}.launch.json"
    path.write_text(json.dumps(out), encoding="utf-8")
    return path


def flows_both_ways(tmp_path: Path, mp: pytest.MonkeyPatch, name: str) -> tuple[int, int]:
    """(flows under --no-launch, flows introspected) for one Action fixture."""
    tmp = tmp_path / name
    tmp.mkdir()
    static = scan(tmp / "s", mp, "--servers", fixture(name), "--no-launch", "--json")
    seen = scan(tmp / "i", mp, "--servers", str(_launchable(name, tmp)), "--yes", "--json")
    for label, r in (("no-launch", static), ("introspected", seen)):
        if r.exit_code != 0:
            raise AssertionError(f"premise: {name} {label} scan exited {r.exit_code}: {r.output}")
    report = json.loads(seen.stdout)
    if any(s["introspection"] != "ok" for p in report["profiles"] for s in p["servers"]):
        raise AssertionError(f"premise: {name} was not introspected")
    return len(json.loads(static.stdout)["flows"]), len(report["flows"])


def assert_the_action_is_blind_where_measured(tmp_path: Path, mp: pytest.MonkeyPatch) -> None:
    """Named check (Ruling A), the Action's main limitation as numbers: the pass fixture gives 0
    flows BOTH ways; the blind spot gives 0 under --no-launch and 3 introspected; the toxic
    fixture 3 (server-level) and 16 (tool-level), so the Action misses 13 of 16."""
    got = {n: flows_both_ways(tmp_path, mp, n) for n in ("clean", "blind_spot", "toxic")}
    want = {"clean": (0, 0), "blind_spot": (0, 3), "toxic": (3, 16)}
    if got != want:
        raise AssertionError(f"fixture flows (no-launch, introspected): {got}, want {want}")


# --- the tag check ---------------------------------------------------------------------------

TAG_SCRIPT = REPO / "scripts" / "check_tag_version.py"


def run_tag_check(script: Path, tag: str, pyproject: Path) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(script), "--tag", tag, "--pyproject", str(pyproject)]
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def assert_a_tag_must_equal_the_package_version(tmp_path: Path, script: Path = TAG_SCRIPT) -> None:
    """Named check: the tag check passes only for ``v`` + [project].version."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "x"\nversion = "0.1.0a1"\n', encoding="utf-8")
    for tag, want in (("v0.1.0a1", 0), ("v0.1.0", 1), ("0.1.0a1", 1), ("v0.1.0a2", 1)):
        r = run_tag_check(script, tag, pyproject)
        if r.returncode != want:
            raise AssertionError(f"tag {tag!r}: exit {r.returncode}, want {want}: {r.stderr}")
    real = run_tag_check(script, "v0.1.0a1", REPO / "pyproject.toml")
    if real.returncode != 0:
        raise AssertionError(f"the repo's own version is not 0.1.0a1: {real.stderr}")


# --- the control is imported by runner.verify only (Phase 8's instrument; Haris's ruling) ----

ROOT = REPO
CONTROL = "proveflow.runner.control"
ALLOWED = frozenset({"src/proveflow/runner/verify.py"})


def _module_of(path: str) -> str:
    """``src/proveflow/runner/x.py`` -> ``proveflow.runner.x`` (package for __init__)."""
    parts = Path(path).with_suffix("").parts[1:]
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def imported_names(path: str, source: str) -> set[str]:
    """Every module name ``source`` imports, relative imports resolved against ``path``."""
    here = _module_of(path)
    package = here if path.endswith("__init__.py") else here.rpartition(".")[0]
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                anchor = package.split(".")[: len(package.split(".")) - (node.level - 1)]
                base = ".".join([*anchor, *([base] if base else [])])
            names.add(base)
            names |= {f"{base}.{a.name}" for a in node.names}
    return names


def control_importers(sources: dict[str, str] | None = None) -> list[str]:
    """(file, imported name) for every import of the control under src/."""
    files = sources if sources is not None else {
        p.relative_to(ROOT).as_posix(): p.read_text(encoding="utf-8")
        for p in sorted((ROOT / "src").rglob("*.py"))
    }  # fmt: skip
    hits = [f"{name}: {imported}" for name, source in files.items()
            for imported in imported_names(name, source)
            if imported == CONTROL or imported.startswith(CONTROL + ".")]  # fmt: skip
    return sorted(set(hits))


def assert_only_verify_imports_the_control(sources: dict[str, str] | None = None) -> None:
    """Named check: the scan finds the control imported by runner.verify and by nothing else."""
    hits = control_importers(sources)
    stray = [h for h in hits if h.split(":")[0] not in ALLOWED]
    if stray:
        raise AssertionError(f"the control is imported outside runner.verify: {stray} "
                             f"(the whole scan: {hits})")  # fmt: skip
    if not hits:
        raise AssertionError("premise: the scan found no import of the control at all, not even "
                             "runner.verify's (is the scan reading src/?)")  # fmt: skip


# --- the Action: pinned, static, gating --------------------------------------------------------

USES = re.compile(r"^\s*(?:-\s+)?uses:\s*(\S+)")
PINNED = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")


def action_files() -> list[Path]:
    """The Action plus EVERY workflow (scanned, never listed)."""
    return [REPO / "action" / "action.yml", *sorted((REPO / ".github" / "workflows").glob("*.yml"))]


def unpinned(texts: dict[str, str]) -> list[str]:
    """(file:line ref) for every non-local ``uses:`` not pinned by a full 40-hex commit SHA."""
    out: list[str] = []
    for name, text in texts.items():
        for n, line in enumerate(text.splitlines(), start=1):
            m = USES.match(line)
            if m and not m.group(1).startswith("./") and not PINNED.match(m.group(1)):
                out.append(f"{name}:{n} {m.group(1)}")
    return out


def assert_the_action_is_pinned_static_and_gating(texts: dict[str, str] | None = None) -> None:
    """Named check: every action reference in the Action and the workflows is pinned by commit
    SHA, and the Action's scan runs --no-launch (never launching a scanned repo's servers on a
    pull request) and --fail-on (it gates)."""
    files = texts if texts is not None else {
        p.relative_to(REPO).as_posix(): p.read_text(encoding="utf-8") for p in action_files()
    }  # fmt: skip
    bad = unpinned(files)
    if bad:
        raise AssertionError(f"action references not pinned by commit SHA: {bad}")
    action = files["action/action.yml"]
    for flag in ("--no-launch", "--fail-on"):
        if flag not in action:
            raise AssertionError(f"the Action's scan does not pass {flag}")
    if "--yes" in action:
        raise AssertionError("the Action consents to launching servers (--yes)")


# --- the installers (run against a STUB uv: nothing is downloaded or installed) ---------------

INSTALL_SH = REPO / "install" / "install.sh"
INSTALL_PS1 = REPO / "install" / "install.ps1"
GIT_SOURCE = "git+https://github.com/M-Haris346/proveflow@v0.1.0a1"

STUB_UV_SH = """#!/bin/sh
printf '%s\n' "$*" >> "$STUB_LOG"
if [ "$1 $2" = "tool install" ] && [ -z "${STUB_NO_TOOL:-}" ]; then
  printf '#!/bin/sh\necho "proveflow ${STUB_VERSION:-0.1.0a1}"\n' > "$STUB_BIN/proveflow"
  chmod +x "$STUB_BIN/proveflow"
fi
"""
STUB_UV_CMD = r"""@echo off
echo %*>> "%STUB_LOG%"
if not defined STUB_VERSION set STUB_VERSION=0.1.0a1
if "%1 %2"=="tool install" if not defined STUB_NO_TOOL (
  > "%STUB_BIN%\proveflow.cmd" echo @echo proveflow %STUB_VERSION%
)
"""


def project_version() -> str:
    import tomllib

    return str(
        tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    )


def run_installer(kind: str, tmp: Path, *args: str, script: Path | None = None,
                  **env_extra: str) -> tuple[int, str, list[str]]:  # fmt: skip
    """(exit code, stdout+stderr, the stub uv's recorded argument lines)."""
    import os
    import shutil

    tmp.mkdir(parents=True, exist_ok=True)
    stub_bin = tmp / "bin"
    stub_bin.mkdir()
    log = tmp / "uv_args.txt"
    env = {k: v for k, v in os.environ.items() if k.upper() not in ("STUB_NO_TOOL", "STUB_VERSION")}
    env.update(STUB_LOG=str(log), STUB_BIN=str(stub_bin), **env_extra)
    # the stub first; no directory that already holds a real proveflow (e.g. a dev venv)
    names = ("proveflow", "proveflow.exe", "proveflow.cmd")
    kept = [d for d in env.get("PATH", "").split(os.pathsep)
            if d and not any((Path(d) / n).exists() for n in names)]  # fmt: skip
    path = os.pathsep.join([str(stub_bin), *kept])
    if kind == "sh":
        (stub_bin / "uv").write_text(STUB_UV_SH, encoding="utf-8", newline="\n")
        (stub_bin / "uv").chmod(0o755)
        sh = shutil.which("sh")
        assert sh is not None
        env["PATH"] = path
        cmd = [sh, str(script or INSTALL_SH), *args]
    else:
        (stub_bin / "uv.cmd").write_text(STUB_UV_CMD, encoding="ascii", newline="\r\n")
        env["PATH"] = path
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
               str(script or INSTALL_PS1), *args]  # fmt: skip
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, check=False)
    recorded = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return r.returncode, r.stdout + r.stderr, [" ".join(x.split()) for x in recorded]


def assert_the_installer_installs_exactly_its_route(tmp_path: Path, kind: str,
                                                   script: Path | None = None) -> None:  # fmt: skip
    """Named check, per installer: the default route installs the pinned git TAG (dependencies
    from PyPI, no --no-index); --wheelhouse installs proveflow==VERSION with --find-links DIR
    --no-index; a wrong installed version, a tool not on PATH and a missing wheelhouse each
    exit non-zero with a readable message; the pinned version equals [project].version."""
    flag = "--wheelhouse" if kind == "sh" else "-Wheelhouse"
    text = (script or (INSTALL_SH if kind == "sh" else INSTALL_PS1)).read_text(encoding="utf-8")
    if f'"{project_version()}"' not in text:
        raise AssertionError(
            f"{kind}: the pinned version is not [project].version {project_version()}"
        )
    code, out, uv = run_installer(kind, tmp_path / "default", script=script)
    if code != 0 or uv != [f"tool install {GIT_SOURCE}"] or "--no-index" in " ".join(uv):
        raise AssertionError(f"{kind} default route: exit {code}, uv called {uv}: {out[-400:]}")
    if f"installed: proveflow {project_version()}" not in out:
        raise AssertionError(f"{kind}: the installed version is not printed: {out[-400:]}")
    house = tmp_path / "wheelhouse"
    house.mkdir()
    code, out, uv = run_installer(kind, tmp_path / "house", flag, str(house), script=script)
    want = f"tool install proveflow=={project_version()} --find-links {house} --no-index"
    if code != 0 or uv != [want]:
        raise AssertionError(f"{kind} wheelhouse route: exit {code}, uv called {uv}, want [{want}]")
    for case, extra, words in (("wrong version", {"STUB_VERSION": "9.9.9"}, "expected 'proveflow"),
                               ("not on PATH", {"STUB_NO_TOOL": "1"}, "not on PATH")):  # fmt: skip
        code, out, _ = run_installer(
            kind, tmp_path / case.replace(" ", "_"), script=script, **extra
        )
        if code == 0 or words not in out:
            raise AssertionError(f"{kind} {case}: exit {code}, want non-zero and {words!r}: "
                                 f"{out[-300:]}")  # fmt: skip
    code, out, _ = run_installer(kind, tmp_path / "missing", flag, str(tmp_path / "nope"),
                                 script=script)  # fmt: skip
    if code == 0 or "not a directory" not in out:
        raise AssertionError(f"{kind} missing wheelhouse: exit {code}: {out[-300:]}")


def assert_scan_names_an_unread_config_without_fail_on(
    tmp_path: Path, mp: pytest.MonkeyPatch
) -> None:
    """Named check (Ruling 3): WITHOUT --fail-on, a scan of a malformed servers file and an
    unreadable discovered config keeps its exit code (0) but names BOTH on stderr, with status
    and path; --json stdout stays valid JSON."""
    tmp = tmp_path / "w"
    tmp.mkdir(parents=True)
    bad = _malformed(tmp)
    _discovered(tmp, directory=True)
    for args in ((), ("--json",)):
        r = scan(tmp, mp, "--servers", str(bad), "--no-launch", *args)
        if r.exit_code != 0:
            raise AssertionError(f"without --fail-on the exit changed: {r.exit_code}")
        lines = [x for x in r.stderr.splitlines() if "could not read" in x]
        text = " ".join(r.stderr.split())
        if len(lines) < 2 or "parse_error" not in text or "unreadable" not in text:
            raise AssertionError(f"scan {args} did not name both unread configs: {r.stderr!r}")
        if args:
            json.loads(r.stdout)  # the warning never reaches the JSON on stdout
