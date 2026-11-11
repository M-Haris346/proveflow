"""Deterministic tool-role heuristics (ARCHITECTURE §5.3).

Signals from the tool name (strong), description (weak), and input-schema property
names (medium) are combined per role with noisy-OR; a role is assigned when its
score reaches ``ROLE_THRESHOLD``. Every matched signal is kept as ``RoleEvidence``
(reason + weight). Weights are initial values; tuning happens only on the dev split
of the labeled tool set (Phase 1b), never on the test split.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from proveflow.core.tools import (
    Granularity,
    RoleEvidence,
    RoleSource,
    SinkSeverity,
    ToolRole,
    ToolSpec,
)

ROLE_THRESHOLD = 0.5
_DESC_MAX_HITS_PER_ROLE = 2

READ_VERBS = frozenset(
    "get read list fetch search find view show retrieve query lookup browse load open "
    "describe inspect export download pull".split()
)
UNTRUSTED_NOUNS = frozenset(
    "email mail inbox message chat conversation thread channel issue comment pull pr "
    "review ticket discussion notification web page url html website webpage feed rss "
    "tweet post forum news article snapshot content".split()
)
PRIVATE_NOUNS = frozenset(
    "file directory dir folder document doc database db table row record sql customer "
    "user secret credential key token env config repository repo code memory note "
    "entity graph contact calendar event account payment invoice log history commit "
    "diff branch drive sheet spreadsheet email mail inbox message".split()
)
SOURCE_VERBS = frozenset("fetch browse navigate scrape crawl download".split())
EGRESS_VERBS = frozenset(
    "send post publish upload notify tweet reply forward share submit invite push "
    "webhook broadcast dispatch".split()
)
EXEC_VERBS = frozenset("exec execute eval evaluate shell spawn".split())
EXEC_NOUNS = frozenset("command code script shell terminal process".split())
WRITE_VERBS = frozenset(
    "create update delete remove edit modify set add insert merge close assign archive "
    "move rename patch put write append upsert drop overwrite save store".split()
)
BROWSER_ACTION_VERBS = frozenset("click fill hover press type select drag".split())
LOCAL_NOUNS = frozenset("file directory dir folder path disk local".split())
WEB_NOUNS = frozenset("web internet online google bing url page website".split())

DESC_EGRESS = frozenset("send post publish upload webhook notify email".split())
DESC_WRITE = frozenset("create delete update write modify remove overwrite".split())
DESC_SOURCE = frozenset(
    "web internet url website webpage html browser fetch email inbox issue comment message".split()
)
DESC_PRIVATE = frozenset(
    "file database secret credential private personal repository document table record".split()
)

SCHEMA_EGRESS = frozenset(
    "to recipient recipients cc bcc channel channel_id webhook webhook_url endpoint".split()
)
SCHEMA_URL = frozenset("url uri href link".split())
SCHEMA_SQL = frozenset("sql".split())
SCHEMA_PATH = frozenset("path file filepath file_path filename directory".split())

_CAMEL = re.compile(r"([a-z0-9])([A-Z])")
_SPLIT = re.compile(r"[^A-Za-z0-9]+")


def _norm(token: str) -> str:
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokenize(text: str) -> list[str]:
    """Split snake/kebab/camel/space text into lowercase, lightly singularized tokens."""
    spaced = _CAMEL.sub(r"\1 \2", text)
    return [_norm(t.lower()) for t in _SPLIT.split(spaced) if t]


def _schema_props(schema: dict[str, Any]) -> list[str]:
    props = schema.get("properties")
    if not isinstance(props, dict):
        return []
    return sorted(str(k).lower() for k in props)


def _ev(
    role: ToolRole, reason: str, weight: float, severity: SinkSeverity | None = None
) -> RoleEvidence:
    return RoleEvidence(
        role=role,
        source=RoleSource.HEURISTIC,
        reason=reason,
        weight=weight,
        granularity=Granularity.TOOL,
        sink_severity=severity if role is ToolRole.SINK else None,
    )


def _first(tokens: Iterable[str], vocab: frozenset[str]) -> str | None:
    return next((t for t in tokens if t in vocab), None)


def _name_evidence(name: str) -> list[RoleEvidence]:
    toks = tokenize(name)
    out: list[RoleEvidence] = []
    local = _first(toks, LOCAL_NOUNS) is not None
    write_sev = SinkSeverity.LOCAL_WRITE if local else SinkSeverity.REMOTE_WRITE

    verb = _first(toks, READ_VERBS)
    if verb:
        noun = _first(toks, UNTRUSTED_NOUNS)
        if noun:
            out.append(_ev(ToolRole.UNTRUSTED_SOURCE, f"name: read verb '{verb}' + '{noun}'", 0.7))
        pnoun = _first(toks, PRIVATE_NOUNS)
        if pnoun:
            out.append(_ev(ToolRole.PRIVATE_DATA, f"name: read verb '{verb}' + '{pnoun}'", 0.7))
    if (v := _first(toks, SOURCE_VERBS)) is not None:
        out.append(_ev(ToolRole.UNTRUSTED_SOURCE, f"name: verb '{v}'", 0.7))
    if "search" in toks:
        web = _first(toks, WEB_NOUNS)
        if web:
            out.append(_ev(ToolRole.UNTRUSTED_SOURCE, f"name: 'search' + '{web}'", 0.7))
        else:
            out.append(_ev(ToolRole.UNTRUSTED_SOURCE, "name: 'search' (target unknown)", 0.3))
    if "navigate" in toks:
        out.append(
            _ev(
                ToolRole.SINK,
                "name: 'navigate' (URL can carry data)",
                0.4,
                SinkSeverity.NETWORK_EGRESS,
            )
        )
    if (v := _first(toks, EGRESS_VERBS)) is not None:
        out.append(
            _ev(ToolRole.SINK, f"name: egress verb '{v}'", 0.75, SinkSeverity.NETWORK_EGRESS)
        )
    exec_v = _first(toks, EXEC_VERBS)
    run_cmd = "run" in toks and _first(toks, EXEC_NOUNS) is not None
    if exec_v or run_cmd:
        out.append(
            _ev(
                ToolRole.SINK,
                f"name: code/command execution '{exec_v or 'run'}'",
                0.7,
                SinkSeverity.NETWORK_EGRESS,
            )
        )
    if (v := _first(toks, WRITE_VERBS)) is not None:
        out.append(_ev(ToolRole.SINK, f"name: write verb '{v}'", 0.65, write_sev))
    if (v := _first(toks, BROWSER_ACTION_VERBS)) is not None and "browser" in toks:
        out.append(
            _ev(ToolRole.SINK, f"name: browser action '{v}'", 0.5, SinkSeverity.NETWORK_EGRESS)
        )
    return out


def _desc_evidence(description: str) -> list[RoleEvidence]:
    toks = set(tokenize(description))
    local = bool(toks & LOCAL_NOUNS)
    found: dict[ToolRole, list[RoleEvidence]] = {}

    def hit(
        role: ToolRole, vocab: frozenset[str], label: str, w: float, sev: SinkSeverity | None
    ) -> None:
        for word in sorted(toks & vocab):
            found.setdefault(role, []).append(_ev(role, f"description: {label} '{word}'", w, sev))

    hit(ToolRole.SINK, DESC_EGRESS, "egress word", 0.35, SinkSeverity.NETWORK_EGRESS)
    hit(
        ToolRole.SINK,
        DESC_WRITE,
        "write word",
        0.3,
        SinkSeverity.LOCAL_WRITE if local else SinkSeverity.REMOTE_WRITE,
    )
    hit(ToolRole.UNTRUSTED_SOURCE, DESC_SOURCE, "external-content word", 0.3, None)
    hit(ToolRole.PRIVATE_DATA, DESC_PRIVATE, "private-data word", 0.3, None)
    out: list[RoleEvidence] = []
    for role in sorted(found):
        ranked = sorted(found[role], key=lambda e: (-e.weight, e.reason))
        out.extend(ranked[:_DESC_MAX_HITS_PER_ROLE])
    return out


def _schema_evidence(schema: dict[str, Any]) -> list[RoleEvidence]:
    out: list[RoleEvidence] = []
    for prop in _schema_props(schema):
        if prop in SCHEMA_EGRESS:
            out.append(
                _ev(
                    ToolRole.SINK,
                    f"schema: recipient-like param '{prop}'",
                    0.4,
                    SinkSeverity.NETWORK_EGRESS,
                )
            )
        if prop in SCHEMA_URL:
            out.append(_ev(ToolRole.UNTRUSTED_SOURCE, f"schema: URL param '{prop}'", 0.4))
            out.append(
                _ev(
                    ToolRole.SINK,
                    f"schema: URL param '{prop}' (GET can carry data)",
                    0.25,
                    SinkSeverity.NETWORK_EGRESS,
                )
            )
        if prop in SCHEMA_SQL:
            out.append(_ev(ToolRole.PRIVATE_DATA, f"schema: SQL param '{prop}'", 0.5))
        if prop in SCHEMA_PATH:
            out.append(_ev(ToolRole.PRIVATE_DATA, f"schema: path param '{prop}'", 0.3))
    return out


def role_score(evidence: Iterable[RoleEvidence], role: ToolRole) -> float:
    """Noisy-OR of all evidence weights for ``role``."""
    miss = 1.0
    for ev in evidence:
        if ev.role is role:
            miss *= 1.0 - ev.weight
    return round(1.0 - miss, 6)


def sink_severity(evidence: Iterable[RoleEvidence]) -> SinkSeverity | None:
    sevs = [e.sink_severity for e in evidence if e.role is ToolRole.SINK and e.sink_severity]
    return min(sevs, key=lambda s: s.rank) if sevs else None


def select_roles(evidence: list[RoleEvidence]) -> tuple[RoleEvidence, ...]:
    """Keep evidence only for roles whose noisy-OR score reaches the threshold."""
    kept = [e for e in evidence if role_score(evidence, e.role) >= ROLE_THRESHOLD]
    return tuple(sorted(kept, key=lambda e: (e.role, -e.weight, e.reason)))


def classify_tool(
    name: str, server: str, description: str = "", input_schema: dict[str, Any] | None = None
) -> ToolSpec:
    schema = input_schema or {}
    evidence = _name_evidence(name) + _desc_evidence(description) + _schema_evidence(schema)
    return ToolSpec(
        name=name,
        server=server,
        description=description,
        input_schema=schema,
        roles=select_roles(evidence),
    )


def assigned_roles(tool: ToolSpec) -> set[ToolRole]:
    return {e.role for e in tool.roles}
