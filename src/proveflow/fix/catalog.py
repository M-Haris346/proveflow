"""The Phase 8 catalog entries: M1 and M3 (``core.mitigations.OUT_OF_PHASE`` has the rest, with
their reasons). Each entry's text goes into the patch's ``rationale.md``; its sources into the
manifest. Facts about clients come ONLY from docs/CLIENT_CONFIGS.md, which cites the official
pages.
"""

from __future__ import annotations

from dataclasses import dataclass

from proveflow.core.mitigations import MitigationKind

CLAUDE_CODE_PERMISSIONS = "https://code.claude.com/docs/en/permissions"
CLAUDE_CODE_MCP = "https://code.claude.com/docs/en/mcp"
RFC6901 = "https://www.rfc-editor.org/rfc/rfc6901"
RFC6902 = "https://www.rfc-editor.org/rfc/rfc6902"


@dataclass(frozen=True)
class CatalogEntry:
    kind: MitigationKind
    title: str
    does: str
    tradeoff: str
    does_not: str
    apply: str
    undo: str
    sources: tuple[str, ...]


M1 = CatalogEntry(
    kind=MitigationKind.M1_REMOVE_SINK,
    title="M1: remove the sink tool's server from this profile",
    does=(
        "Removes the server that provides the flow's sink tool from every config entry this "
        "profile connects to, including entries a higher-precedence entry shadows (otherwise "
        "the shadowed entry takes over: Claude Code precedence, docs/CLIENT_CONFIGS.md "
        "section 2). A config defines servers, not single tools, so the WHOLE server goes."
    ),
    tradeoff=(
        "Every tool of that server is gone from this profile, not only the sink. If a "
        "task needs any of them, that task can no longer be done."
    ),
    does_not=(
        "It does not stop a flow through another sink, and it does not touch any other "
        "profile or client."
    ),
    apply=(
        "Each *.json-patch file is an RFC 6902 JSON Patch for the file named in "
        "manifest.json. Back the file up, then apply the patch with any RFC 6902 tool, or "
        "delete the entry at the given JSON Pointer by hand. A 'remove' of an entry that is "
        "no longer there fails: re-run the scan."
    ),
    undo="Restore the backup, or re-add the server entry.",
    sources=(CLAUDE_CODE_MCP, RFC6901, RFC6902),
)

M3 = CatalogEntry(
    kind=MitigationKind.M3_HUMAN_APPROVAL,
    title="M3: require human approval before the sink tool runs (Claude Code)",
    does=(
        "Adds a Claude Code permission rule in the 'ask' list for the sink tool, so Claude "
        "Code asks before every call to it (rule syntax: docs/CLIENT_CONFIGS.md section 2, "
        "'Permission rule syntax')."
    ),
    tradeoff=(
        "Every call to the tool needs a human decision, including the legitimate ones. "
        "Its effect depends entirely on the human: approving an injected call lets the "
        "flow through."
    ),
    does_not=(
        "It does not block anything by itself, and it is not available for any other "
        "client in this phase (no cited per-tool approval syntax)."
    ),
    apply=(
        "Read the header line of the .REVIEW.txt file first. Then merge the JSON fragment that "
        "follows it (its permissions.ask entry) into ONE of the settings files listed in "
        "manifest.json (proveflow never reads settings.json, so it cannot merge for you). "
        "The local file is private to you; the project file is shared through git."
    ),
    undo="Remove the rule from the 'ask' list.",
    sources=(CLAUDE_CODE_PERMISSIONS,),
)

CATALOG: dict[MitigationKind, CatalogEntry] = {M1.kind: M1, M3.kind: M3}
