"""Server-level role inference for ``scan --no-launch`` (tools unknown). LOW CONFIDENCE.

Only non-secret text is used: server name, the plain (unredacted) segments of the
command and args, and URL host words. Each matched category contributes evidence
with weight ``SERVER_WEIGHT`` and ``granularity="server"``; the result is a pseudo
tool named ``*`` standing for "all tools of this server".
"""

from __future__ import annotations

from dataclasses import dataclass

from proveflow.core.client import ServerSpec
from proveflow.core.tools import (
    Granularity,
    RoleEvidence,
    RoleSource,
    SinkSeverity,
    ToolRole,
    ToolSpec,
)
from proveflow.flows.roles import tokenize

SERVER_WEIGHT = 0.35
SERVER_TOOL_NAME = "*"

S, P, K = ToolRole.UNTRUSTED_SOURCE, ToolRole.PRIVATE_DATA, ToolRole.SINK
NET, REMOTE, LOCAL = (
    SinkSeverity.NETWORK_EGRESS,
    SinkSeverity.REMOTE_WRITE,
    SinkSeverity.LOCAL_WRITE,
)


@dataclass(frozen=True)
class Category:
    name: str
    words: frozenset[str]
    roles: frozenset[ToolRole]
    severity: SinkSeverity | None


def _cat(name: str, words: str, roles: set[ToolRole], severity: SinkSeverity | None) -> Category:
    return Category(name, frozenset(words.split()), frozenset(roles), severity)


CATEGORIES: tuple[Category, ...] = (
    _cat("email", "gmail email mail outlook imap smtp inbox", {S, P, K}, NET),
    _cat("chat", "slack discord teams telegram whatsapp matrix mattermost", {S, P, K}, NET),
    _cat(
        "code hosting / issue tracker",
        "github gitlab bitbucket jira linear asana trello notion confluence",
        {S, P, K},
        REMOTE,
    ),
    _cat(
        "web content",
        "fetch search brave tavily exa firecrawl web scrape crawl perplexity",
        {S},
        None,
    ),
    _cat("browser automation", "browser puppeteer playwright selenium", {S, K}, NET),
    _cat("filesystem", "filesystem fs file", {P, K}, LOCAL),
    _cat(
        "database",
        "postgres postgresql mysql sqlite mongo mongodb redis supabase database db sql "
        "bigquery snowflake",
        {P, K},
        REMOTE,
    ),
    _cat("cloud documents", "gdrive drive dropbox onedrive sharepoint gdoc", {P, K}, REMOTE),
    _cat("git", "git", {P, K}, LOCAL),
    _cat("memory", "memory", {P, K}, LOCAL),
    _cat("shell / exec", "shell terminal exec commander", {P, K}, NET),
    _cat("http / automation", "http api webhook zapier", {S, K}, NET),
)


def server_tokens(spec: ServerSpec) -> list[str]:
    texts = [spec.name]
    if spec.command is not None:
        texts.extend(spec.command.plain_segments())
    for arg in spec.args:
        texts.extend(arg.plain_segments())
    if spec.url is not None:
        texts.extend(spec.url.plain_segments())
    seen: list[str] = []
    for text in texts:
        for tok in tokenize(text):
            if tok not in seen:
                seen.append(tok)
    return seen


def classify_server(key: str, spec: ServerSpec) -> ToolSpec:
    toks = server_tokens(spec)
    evidence: list[RoleEvidence] = []
    for cat in CATEGORIES:
        word = next((t for t in toks if t in cat.words), None)
        if word is None:
            continue
        for role in sorted(cat.roles):
            evidence.append(
                RoleEvidence(
                    role=role,
                    source=RoleSource.HEURISTIC,
                    reason=f"server-level: '{word}' suggests {cat.name} (tools unknown)",
                    weight=SERVER_WEIGHT,
                    granularity=Granularity.SERVER,
                    sink_severity=cat.severity if role is K else None,
                )
            )
    return ToolSpec(
        name=SERVER_TOOL_NAME,
        server=key,
        roles=tuple(sorted(evidence, key=lambda e: (e.role, e.reason))),
    )
