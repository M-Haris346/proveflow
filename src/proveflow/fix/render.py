"""Renderers: a scan report + a flow id -> a ``FixBundle`` of patch files (Phase 8).

The ONLY input is the scan report. The user's config files are never opened: every path,
scope and server name comes from what discovery recorded (secrets were redacted at read time,
and no patch carries a value, only keys and JSON Pointers).

* M1 (``render_m1``): one RFC 6902 ``remove`` per entry of the sink's server, grouped per file.
  "The sink's server" is every entry of this profile with the same configured NAME (Cursor
  keeps every entry, so a name may appear twice), plus every Claude Code entry of that name
  that a higher-precedence scope SHADOWS: removing only the winning entry would let the shadowed
  one take over (docs/CLIENT_CONFIGS.md section 2, precedence).
* M3 (``render_m3``): Claude Code only. A settings fragment with one ``permissions.ask`` rule
  ``mcp__<server>__<tool>`` (``mcp__<server>__*`` for a server-level flow: the bare
  ``mcp__<server>`` form was not re-confirmed on the 2026-11-26 re-read). Server-name
  normalisation as cited: ``.`` and space become ``_``. A name that still has any character
  outside ``[A-Za-z0-9_-]``, or contains ``__``, is refused: its rule form is not cited.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from proveflow.core.client import ClientKind, ConfigScope
from proveflow.core.flows import Flow
from proveflow.core.mitigations import OUT_OF_PHASE, MitigationKind
from proveflow.fix.pointer import PointerUnknown, server_pointer
from proveflow.report.models import ProfileReport, ScanReport, SkipReason

RULE_TOKEN = re.compile(r"^[A-Za-z0-9_-]+$")
M3_CLIENTS = frozenset({ClientKind.CLAUDE_CODE})
M3_REFUSED = {
    ClientKind.CURSOR: "Cursor's per-tool permission syntax was not found in its docs "
    "(docs/CLIENT_CONFIGS.md section 3)",
}
M3_REFUSED_DEFAULT = (
    "no per-tool approval syntax for this client is cited in docs/CLIENT_CONFIGS.md"
)


# Haris's ruling (2026-11-26): if the rule syntax is wrong, an M3 patch applies cleanly and
# silently protects nothing. So every rendered M3 patch STARTS with this line, and the patch is
# a text file (the JSON to merge follows the header), so it cannot be applied blindly.
M3_SYNTAX_HEADER = (
    "FOR REVIEW, NOT FOR BLIND APPLICATION: the Claude Code MCP rule syntax used here was last "
    "verified 2026-11-10 and only PARTIALLY re-confirmed 2026-11-26 (the rule forms were not "
    "re-read verbatim; docs/CLIENT_CONFIGS.md section 2). If the syntax is wrong, this rule "
    "applies cleanly and protects nothing. Check it against "
    "https://code.claude.com/docs/en/permissions before you rely on it."
)


def m3_patch_text(rule: str) -> bytes:
    """The M3 patch file: the header line, a blank line, then the JSON fragment to merge."""
    fragment = json.dumps({"permissions": {"ask": [rule]}}, indent=2)
    return (M3_SYNTAX_HEADER + chr(10) + chr(10) + fragment + chr(10)).encode("utf-8")


def m3_fragment(data: bytes) -> object:
    """The JSON fragment inside an M3 patch file (after the header line)."""
    return json.loads(data.decode("utf-8").split(chr(10) + chr(10), 1)[1])


class FixRefused(ValueError):
    """Nothing can be written for this flow and mitigation (named reason)."""


MAX_SCAN_FILE = 64 * 1024 * 1024


def load_scan(path: Path) -> ScanReport:
    """A scan report, validated. A ``--no-launch`` scan is accepted: its flows are server-level,
    and M1 (remove the server) and M3 (``mcp__<server>``) are defined for them."""
    if path.stat().st_size > MAX_SCAN_FILE:
        raise FixRefused(f"scan report larger than {MAX_SCAN_FILE} bytes")
    return ScanReport.model_validate_json(path.read_bytes())


@dataclass(frozen=True)
class Edit:
    file: str
    client: str
    scope: str
    patch: str  # the patch file's name inside the bundle
    kind: str  # "rfc6902" | "settings-fragment"
    pointers: tuple[str, ...] = ()
    merge_into: tuple[str, ...] = ()


@dataclass(frozen=True)
class Refusal:
    client: str
    scope: str
    file: str
    reason: str


@dataclass(frozen=True)
class FixBundle:
    flow_id: str
    kind: MitigationKind
    profile: str
    server: str
    tool: str | None
    edits: tuple[Edit, ...]
    refused: tuple[Refusal, ...]
    files: dict[str, bytes] = field(default_factory=dict)  # patch name -> bytes


def _json(obj: object) -> bytes:
    return (json.dumps(obj, indent=2) + chr(10)).encode("utf-8")


def _flow(scan: ScanReport, flow_id: str) -> tuple[Flow, ProfileReport]:
    flows = [f for f in scan.flows if f.id == flow_id]
    if not flows:
        raise FixRefused(f"no flow {flow_id!r} in the scan")
    flow = flows[0]
    profile = next(p for p in scan.profiles if p.id == flow.profile)
    return flow, profile


def _sink_name(flow: Flow, profile: ProfileReport) -> str:
    member = next(s for s in profile.servers if s.key == flow.sink.server)
    return member.spec.name


def render(scan: ScanReport, flow_id: str, kind: MitigationKind) -> FixBundle:
    if kind in OUT_OF_PHASE:
        raise FixRefused(OUT_OF_PHASE[kind])
    if kind is MitigationKind.M1_REMOVE_SINK:
        return render_m1(scan, flow_id)
    return render_m3(scan, flow_id)


def shadowed_entries(
    scan: ScanReport, profile: ProfileReport, name: str
) -> list[tuple[ClientKind, ConfigScope, str | None, Path]]:
    """Every entry of server ``name`` that a higher-precedence entry of the same client SHADOWS:
    M1 must remove it too, or it takes over (docs/CLIENT_CONFIGS.md section 2)."""
    return [(k.client, k.scope, k.project, k.source_file) for k in scan.skipped
            if k.reason is SkipReason.SHADOWED and k.client is profile.client
            and k.server_ref == name]  # fmt: skip


def render_m1(scan: ScanReport, flow_id: str) -> FixBundle:
    flow, profile = _flow(scan, flow_id)
    name = _sink_name(flow, profile)
    entries = [(profile.client, s.spec.scope, s.spec.project, s.spec.source_file)
               for s in profile.servers if s.spec.name == name]  # fmt: skip
    entries += shadowed_entries(scan, profile, name)
    by_file: dict[tuple[Path, str], list[tuple[str, str]]] = {}
    refused: list[Refusal] = []
    for client, scope, project, path in entries:
        try:
            pointer = server_pointer(client, scope, project, name)
        except PointerUnknown as exc:
            refused.append(Refusal(client.value, scope.value, str(path), str(exc)))
            continue
        by_file.setdefault((path, client.value), []).append((scope.value, pointer))
    edits: list[Edit] = []
    files: dict[str, bytes] = {}
    for i, ((path, client_v), found) in enumerate(sorted(by_file.items()), start=1):
        scopes = "+".join(sorted({sc for sc, _ in found}))
        patch = f"{i:02d}-{client_v}-{scopes}.json-patch"
        pointers = tuple(sorted({p for _, p in found}))
        files[patch] = _json([{"op": "remove", "path": p} for p in pointers])
        edits.append(Edit(str(path), client_v, scopes, patch, "rfc6902", pointers=pointers))
    if not edits:
        raise FixRefused("M1: no config entry of this server can be patched: "
                         + "; ".join(r.reason for r in refused))  # fmt: skip
    return FixBundle(flow_id, MitigationKind.M1_REMOVE_SINK, profile.id, name, flow.sink.tool,
                     tuple(edits), tuple(refused), files)  # fmt: skip


def rule_token(name: str) -> str:
    """A server name as Claude Code writes it in a rule (cited normalisation only)."""
    token = name.replace(".", "_").replace(" ", "_")
    if not RULE_TOKEN.fullmatch(token) or "__" in token:
        raise FixRefused(f"M3: the rule form for server name {name!r} is not cited "
                         "(docs/CLIENT_CONFIGS.md section 2)")  # fmt: skip
    return token


def m3_rule(server: str, tool: str | None) -> str:
    if tool is None:  # server-level flow: the wildcard form (CLIENT_CONFIGS section 2)
        return f"mcp__{rule_token(server)}__*"
    if not RULE_TOKEN.fullmatch(tool):
        raise FixRefused(f"M3: the rule form for tool name {tool!r} is not cited")
    return f"mcp__{rule_token(server)}__{tool}"


def render_m3(scan: ScanReport, flow_id: str) -> FixBundle:
    flow, profile = _flow(scan, flow_id)
    if profile.client not in M3_CLIENTS:
        raise FixRefused(f"M3 for {profile.client.value}: "
                         + M3_REFUSED.get(profile.client, M3_REFUSED_DEFAULT))  # fmt: skip
    name = _sink_name(flow, profile)
    rule = m3_rule(name, flow.sink.tool)
    project = Path(scan.project)
    merge_into = (
        f"~/.claude/settings.json ({ConfigScope.USER.value})",
        f"{project / '.claude' / 'settings.json'} ({ConfigScope.PROJECT.value}, shared)",
        f"{project / '.claude' / 'settings.local.json'} ({ConfigScope.LOCAL.value}, private)",
    )
    patch = f"01-{profile.client.value}.settings-fragment.REVIEW.txt"
    files = {patch: m3_patch_text(rule)}
    edit = Edit("", profile.client.value, "settings", patch, "settings-fragment",
                merge_into=merge_into)  # fmt: skip
    return FixBundle(flow_id, MitigationKind.M3_HUMAN_APPROVAL, profile.id, name, flow.sink.tool,
                     (edit,), (), files)  # fmt: skip
