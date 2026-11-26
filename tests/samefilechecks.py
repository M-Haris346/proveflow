"""Named checks for the same-file collapse (a Find defect, Phase 9; docs/BACKLOG.md). MEASURED
before the fix: with the project directory == the home directory, Cursor's user and project
scope name ONE file, and the toxic fixture's two servers appeared as 4 entries, 16 flows and 16
groups where scanning that file once gives 2, 3 and 3. Fake homes only (tests/fakehome.py)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from fakehome import make_host
from proveflow.config import ProveflowConfig
from proveflow.discover import run_discovery
from proveflow.discover.profiles import canonical_path
from proveflow.report.models import ScanReport
from proveflow.scan import build_scan

REPO = Path(__file__).resolve().parents[1]
TOXIC = REPO / "tests" / "fixtures" / "action" / "toxic.servers.json"
SERVERS = ("fetch", "filesystem")


def cursor_home(tmp_path: Path) -> tuple[Any, Path]:
    """A fake home with the toxic fixture at <home>/.cursor/mcp.json."""
    host = make_host(tmp_path)
    target = host.home / ".cursor" / "mcp.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(TOXIC.read_bytes())
    return host, target


def figures(report: ScanReport) -> tuple[int, int, int, int]:
    """(entries of the fixture's servers across profiles, flows, groups, discovered servers)."""
    entries = sum(1 for p in report.profiles for s in p.servers if s.spec.name in SERVERS)
    return entries, len(report.flows), len(report.groups), report.discovered_servers


def scanned_once(tmp_path: Path, path: Path) -> tuple[int, int, int, int]:
    """The same file scanned ONCE, as an explicit --servers file, in an empty home."""
    host = make_host(tmp_path / "once")
    project = tmp_path / "once-project"
    project.mkdir()
    return figures(build_scan(run_discovery(host, project, path), host, project,
                              ProveflowConfig()))  # fmt: skip


def scan_as_project(host: Any, project: Path) -> ScanReport:
    return build_scan(run_discovery(host, project, None), host, project, ProveflowConfig())


def assert_one_file_is_read_once(tmp_path: Path, project: Path | None = None) -> ScanReport:
    """Named check (the measured numbers): with the project directory == the home directory
    (or ``project``, another path to it), the report has 2 server entries, 3 flows and 3 groups,
    and counts 2 servers discovered: equal to scanning that file once. Before the fix: 4, 16,
    16."""
    host, target = cursor_home(tmp_path / "h")
    report = scan_as_project(host, project or host.home)
    got = figures(report)
    want = scanned_once(tmp_path, target)
    if got != want or got[:3] != (2, 3, 3):
        raise AssertionError(f"(entries, flows, groups, discovered) = {got}, scanning the file "
                             f"once gives {want}; want (2, 3, 3, 2)")  # fmt: skip
    return report


def assert_the_collapse_is_said(tmp_path: Path) -> None:
    """Named check: the report SAYS the collapse happened. The Cursor profile's notes name the
    kept config (user), the config collapsed into it (project), and the canonical path they
    share. A number that moved for a reason the report does not state is the same defect."""
    host, target = cursor_home(tmp_path / "h")
    report = scan_as_project(host, host.home)
    notes = [n for p in report.profiles if p.client.value == "cursor" for n in p.notes]
    said = [n for n in notes if "is the same file as" in n]  # the collapse note itself
    if not said:
        raise AssertionError(f"the collapse is silent: cursor notes are {notes}")
    note = said[0]
    for needed in ("cursor project config", "cursor user config", canonical_path(target),
                   "collapsed into"):  # fmt: skip
        if needed not in note:
            raise AssertionError(f"the collapse note does not name {needed!r}: {note!r}")


def assert_case_and_links_resolve_to_one_file(tmp_path: Path) -> list[str]:
    """Named check (the resolution, measured, not assumed): another spelling of the home path
    is the same file. On Windows a differently CASED project path collapses; on POSIX a
    differently cased path is a different path and must NOT be folded. A JUNCTION (Windows,
    `mklink /J`, no admin) or a SYMLINK (POSIX) to the home also collapses. Returns what it
    measured, one line each."""
    out: list[str] = []
    host, _ = cursor_home(tmp_path / "h")
    if sys.platform == "win32":
        upper = Path(str(host.home).upper())
        if str(upper) == str(host.home):
            raise AssertionError("premise: the upper-cased path is the same string")
        assert_one_file_is_read_once(tmp_path / "case", Path(str(tmp_path / "case" / "h" /
                                                                 "home").upper()))  # fmt: skip
        out.append("windows: a differently cased project path collapsed (2, 3, 3)")
        jhost, _ = cursor_home(tmp_path / "jt")
        link = tmp_path / "junction-to-home"
        cmd = os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe")
        made = subprocess.run([cmd, "/c", "mklink", "/J", str(link), str(jhost.home)],
                              capture_output=True, text=True, check=False)  # fmt: skip
        if made.returncode != 0:  # mklink /J needs no admin rights; if it fails, say so
            raise AssertionError(f"premise: mklink /J failed: {made.stdout} {made.stderr}")
        got = figures(scan_as_project(jhost, link))
        if got[:3] != (2, 3, 3):
            raise AssertionError(f"a junction to the home was not resolved: {got}")
        out.append("windows: a junction to the home collapsed (2, 3, 3)")
    else:
        a, b = tmp_path / "Case", tmp_path / "case"
        if canonical_path(a) == canonical_path(b):
            raise AssertionError("POSIX: differently cased paths were folded into one")
        out.append("posix: differently cased paths stay different (case-sensitive)")
        sym = tmp_path / "symlink-home"
        sym.symlink_to(host.home, target_is_directory=True)
        got = figures(scan_as_project(host, sym))
        if got[:3] != (2, 3, 3):
            raise AssertionError(f"a symlink to the home was not resolved: {got}")
        out.append("posix: a symlink to the home collapsed (2, 3, 3)")
    return out


def assert_two_clients_are_never_collapsed(tmp_path: Path) -> None:
    """Named check: different client kinds naming one file are two agents and are never
    collapsed. claude_code project and vscode project both name <home>/.mcp.json; vscode's
    experimental .mcp.json is UNSUPPORTED, so the servers count once (claude_code), and no
    collapse note is written."""
    host = make_host(tmp_path / "h")
    (host.home / ".mcp.json").write_bytes(TOXIC.read_bytes())
    report = scan_as_project(host, host.home)
    if figures(report)[:3] != (2, 3, 3):
        raise AssertionError(f".mcp.json: {figures(report)}")
    if any("is the same file as" in n for p in report.profiles for n in p.notes):
        raise AssertionError("two different clients were reported as one collapsed file")
    json.dumps(report.model_dump(mode="json"))  # the report still serialises
