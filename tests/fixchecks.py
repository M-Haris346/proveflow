"""Named checks for the patch writers (Phase 8). Fixture configs only (tests/fakehome.py, every
planted secret marked ``PLANTED``); nothing is launched, no config is ever edited."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fakehome import MARKER, full_setup
from proveflow.config import ProveflowConfig
from proveflow.core.client import ClientKind, ConfigScope
from proveflow.core.mitigations import MitigationKind
from proveflow.discover import run_discovery
from proveflow.report.models import ScanReport
from proveflow.scan import build_scan

M1, M3 = MitigationKind.M1_REMOVE_SINK, MitigationKind.M3_HUMAN_APPROVAL


def fake_scan(tmp_path: Path) -> tuple[ScanReport, Any]:
    s = full_setup(tmp_path)
    return build_scan(run_discovery(s.host, s.project), s.host, s.project, ProveflowConfig()), s


def flow_to(scan: ScanReport, profile_prefix: str, sink: str) -> str:
    for f in scan.flows:
        if f.profile.startswith(profile_prefix) and f.sink.server == sink:
            return f.id
    raise AssertionError(f"premise: no {profile_prefix} flow with sink {sink!r} in the fixture")


POINTERS: tuple[tuple[ClientKind, ConfigScope, str | None, str, str], ...] = (
    (ClientKind.CLAUDE_DESKTOP, ConfigScope.USER, None, "fetch", "/mcpServers/fetch"),
    (ClientKind.CLAUDE_CODE, ConfigScope.USER, None, "fetch", "/mcpServers/fetch"),
    (ClientKind.CLAUDE_CODE, ConfigScope.PROJECT, "D:/p", "fetch", "/mcpServers/fetch"),
    (ClientKind.CLAUDE_CODE, ConfigScope.LOCAL, "D:/work/demo", "fetch",
     "/projects/D:~1work~1demo/mcpServers/fetch"),
    (ClientKind.CURSOR, ConfigScope.USER, None, "fetch", "/mcpServers/fetch"),
    (ClientKind.CURSOR, ConfigScope.PROJECT, "D:/p", "fetch", "/mcpServers/fetch"),
    (ClientKind.VSCODE, ConfigScope.PROJECT, "D:/p", "fetch", "/servers/fetch"),
    (ClientKind.WINDSURF, ConfigScope.USER, None, "fetch", "/mcpServers/fetch"),
    (ClientKind.CLAUDE_DESKTOP, ConfigScope.USER, None, "a/b~c", "/mcpServers/a~1b~0c"),
)  # fmt: skip


def assert_m1_pointers_are_the_readers_keys() -> None:
    """Named check: the M1 pointer for each client and scope is the key its reader reads, RFC
    6901-escaped; the ``--servers`` file (content-dependent key) is refused with a reason."""
    from proveflow.fix.pointer import PointerUnknown, server_pointer

    for client, scope, project, name, want in POINTERS:
        got = server_pointer(client, scope, project, name)
        if got != want:
            raise AssertionError(f"{client.value} {scope.value}: pointer {got!r}, want {want!r}")
    try:
        server_pointer(ClientKind.EXPLICIT_FILE, ConfigScope.EXPLICIT, None, "fetch")
    except PointerUnknown:
        return
    raise AssertionError("a pointer into a --servers file was guessed")


def assert_m1_removes_every_entry_that_would_connect(tmp_path: Path) -> None:
    """Named check: M1 for the Claude Code sink ``slack`` removes the winning entry AND the
    user-scope entry it shadows (else that one takes over), each by its own pointer."""
    from proveflow.fix.render import render

    scan, s = fake_scan(tmp_path)
    bundle = render(scan, flow_to(scan, "claude_code", "slack"), M1)
    got = sorted((e.scope, p) for e in bundle.edits for p in e.pointers)
    user = s.host.home / ".claude.json"
    files = {e.file for e in bundle.edits}
    scopes = {sc for e in bundle.edits for sc in e.scope.split("+")}
    if "user" not in scopes or str(user) not in files or len(got) < 2:
        raise AssertionError(f"M1 for slack did not cover the shadowed user entry: {got}")
    for e in bundle.edits:
        ops = json.loads(bundle.files[e.patch])
        if ops != [{"op": "remove", "path": p} for p in e.pointers]:
            raise AssertionError(f"{e.patch}: not one RFC 6902 remove per pointer: {ops}")


M3_RULES = (  # (server, tool, rule) per docs/CLIENT_CONFIGS.md section 2
    ("github", None, "mcp__github__*"), ("github", "create_issue", "mcp__github__create_issue"),
    ("my.server", "send", "mcp__my_server__send"), ("my server", "send", "mcp__my_server__send"),
)  # fmt: skip
M3_REFUSED_NAMES = ("a/b", "x__y", "caf\u00e9")


def assert_m3_rule_form_is_the_cited_one(tmp_path: Path) -> None:
    """Named check: the M3 rule is ``mcp__<server>__<tool>`` (``mcp__<server>__*`` for a
    server-level flow), with ``.`` and space normalised to ``_``; an uncited name is refused;
    the Claude Code fragment holds exactly that rule under ``permissions.ask``; and every other
    client is refused with its reason."""
    from proveflow.fix.render import FixRefused, m3_rule, render

    for server, tool, want in M3_RULES:
        if m3_rule(server, tool) != want:
            raise AssertionError(f"m3_rule({server!r}, {tool!r}) = {m3_rule(server, tool)!r}")
    for name in M3_REFUSED_NAMES:
        try:
            m3_rule(name, "t")
        except FixRefused:
            continue
        raise AssertionError(f"M3 accepted the uncited server name {name!r}")
    scan, _ = fake_scan(tmp_path)
    bundle = render(scan, flow_to(scan, "claude_code", "github"), M3)
    (data,) = bundle.files.values()
    from proveflow.fix.render import M3_SYNTAX_HEADER, m3_fragment

    if data.decode("utf-8").split(chr(10), 1)[0] != M3_SYNTAX_HEADER:
        raise AssertionError("the M3 patch does not start with the syntax-verification header")
    for words in ("FOR REVIEW", "2026-11-10", "2026-11-26", "protects nothing"):
        if words not in M3_SYNTAX_HEADER:
            raise AssertionError(f"the M3 header does not say {words!r}")
    if m3_fragment(data) != {"permissions": {"ask": ["mcp__github__*"]}}:
        raise AssertionError(f"the M3 fragment is {data!r}")
    for prefix, sink in (("claude_desktop", "brave-search"), ("windsurf", "github")):
        try:
            render(scan, flow_to(scan, prefix, sink), M3)
        except FixRefused as exc:
            if "cited" not in str(exc):
                raise AssertionError(f"M3 for {prefix} refused without its reason: {exc}") from None
            continue
        raise AssertionError(f"M3 was rendered for {prefix}, which has no cited syntax")


def assert_m3_is_refused_for_cursor() -> None:
    """Named check: Cursor's per-tool permission syntax was not found in its docs, so M3 for a
    Cursor profile is refused with that reason (docs/CLIENT_CONFIGS.md section 3)."""
    from proveflow.fix import render as r

    if ClientKind.CURSOR in r.M3_CLIENTS or "not found" not in r.M3_REFUSED[ClientKind.CURSOR]:
        raise AssertionError("M3 is not refused for Cursor with its reason")


def assert_out_of_phase_kinds_are_refused(tmp_path: Path) -> None:
    """Named check: M2, M4, M5 and M6 are refused by ``fix`` with their reason, never stubbed."""
    from proveflow.core.mitigations import OUT_OF_PHASE
    from proveflow.fix.render import FixRefused, render

    scan, _ = fake_scan(tmp_path)
    fid = flow_to(scan, "claude_code", "github")
    for kind, reason in OUT_OF_PHASE.items():
        try:
            render(scan, fid, kind)
        except FixRefused as exc:
            if str(exc) != reason:
                raise AssertionError(f"{kind}: refused with {exc!r}, want {reason!r}") from None
            continue
        raise AssertionError(f"{kind} was rendered")


def assert_the_writer_never_overwrites_and_leaves_no_partial_output(tmp_path: Path) -> None:
    """Named check: the layout and manifest (``applied: false``); a second write is refused
    with ``FixTargetExists`` and leaves the first untouched; a failing write leaves nothing."""
    from proveflow.fix import writer
    from proveflow.fix.render import render

    scan, _ = fake_scan(tmp_path)
    bundle = render(scan, flow_to(scan, "claude_code", "slack"), M1)
    out = tmp_path / "fixes"
    target = writer.write_bundle(bundle, out)
    names = sorted(p.name for p in target.iterdir())
    if names != sorted(["manifest.json", "rationale.md", *bundle.files]):
        raise AssertionError(f"layout: {names}")
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    if manifest["applied"] is not False or manifest["mitigation"] != M1.value:
        raise AssertionError(f"manifest: {manifest}")
    if "NOT been applied" not in (target / "rationale.md").read_text(encoding="utf-8"):
        raise AssertionError("the rationale does not say the patch was not applied")
    before = {p.name: p.read_bytes() for p in target.iterdir()}
    try:
        writer.write_bundle(bundle, out)
    except writer.FixTargetExists:
        pass
    except OSError as exc:
        raise AssertionError(
            f"a second write was not refused as FixTargetExists: {exc!r}"
        ) from None
    else:
        raise AssertionError("a second write over an existing fix was accepted")
    if {p.name: p.read_bytes() for p in target.iterdir()} != before:
        raise AssertionError("a refused write changed the existing fix")
    broken = type(bundle)(**{**bundle.__dict__, "flow_id": "F-broken",
                             "files": {"../escape/x": b"x"}})  # fmt: skip
    try:
        writer.write_bundle(broken, out)
    except OSError:
        pass
    leftovers = [
        p.name for p in out.rglob("*") if "F-broken" in str(p) or ".proveflow-fix-" in p.name
    ]
    if leftovers:
        raise AssertionError(f"a failed write left partial output: {leftovers}")


def assert_fix_never_touches_a_config(tmp_path: Path) -> None:
    """Named check (safety): ``proveflow fix`` leaves every config's bytes and mtime unchanged,
    writes nothing outside its out-dir, and no planted secret reaches any output."""
    from typer.testing import CliRunner

    import proveflow.cli as cli
    from proveflow.cli import app

    scan, s = fake_scan(tmp_path)
    scan_path = tmp_path / "scan.json"
    scan_path.write_text(scan.model_dump_json(), encoding="utf-8")
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in s.files}
    snapshot = {p for p in tmp_path.rglob("*")}
    out = tmp_path / "fixes"
    runner = CliRunner()
    for sink, kind in (("slack", "m1"), ("github", "m3")):
        result = runner.invoke(app, ["fix", "--from", str(scan_path), "--flow",
                                     flow_to(scan, "claude_code", sink), "--mitigation", kind,
                                     "--out-dir", str(out)])  # fmt: skip
        if result.exit_code != 0:
            raise AssertionError(f"fix {kind} exited {result.exit_code}: {result.output}")
        if MARKER in result.output:
            raise AssertionError("a planted secret reached the fix command's output")
    del cli
    after = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in s.files}
    if after != before:
        changed = [str(p) for p in s.files if after[p] != before[p]]
        raise AssertionError(f"fix changed a client config: {changed}")
    new = {p for p in tmp_path.rglob("*")} - snapshot
    outside = [p for p in new if out not in p.parents and p != out]
    if outside:
        raise AssertionError(f"fix wrote outside its out-dir: {outside}")
    for p in out.rglob("*"):
        if p.is_file() and MARKER.encode() in p.read_bytes():
            raise AssertionError(f"a planted secret reached {p.name}")
