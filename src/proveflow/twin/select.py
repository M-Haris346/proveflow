"""Archetype selection (D6): keyword heuristic over tool name, description and inputSchema
property names; overridable per tool (``[[twin_override]]`` in proveflow.toml, step 11).

Each rule is ``(archetype, keywords)``. The archetype with the most keyword hits wins; ties go
to the earlier rule in ``RULES`` (priority order); no hit at all gives ``generic_json``.
``RULES`` is a module global read at call time (tests/mutation removes rules one by one).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from proveflow.twin.archetypes import ARCHETYPES

FALLBACK = "generic_json"

RULES: list[tuple[str, frozenset[str]]] = [
    ("email_list", frozenset({"email", "emails", "mail", "inbox", "message", "messages"})),
    ("issue_ticket", frozenset({"issue", "issues", "ticket", "tickets", "bug", "bugs", "pull"})),
    (
        "db_rows",
        frozenset({"sql", "query", "db", "database", "table", "tables", "row", "rows", "record",
                   "records"}),
    ),
    (
        "web_page",
        frozenset({"fetch", "url", "web", "page", "browser", "navigate", "http", "html",
                   "snapshot", "scrape", "website"}),
    ),
    (
        "document_text",
        frozenset({"file", "files", "read", "document", "documents", "doc", "docs", "text",
                   "note", "notes", "directory"}),
    ),
]  # fmt: skip

_TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(name: str, description: str, input_schema: Mapping[str, Any]) -> list[str]:
    props = input_schema.get("properties")
    prop_names = " ".join(props) if isinstance(props, dict) else ""
    # split camelCase too: "readFile" -> "read file"
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", f"{name} {description} {prop_names}")
    return _TOKEN.findall(text.lower().replace("_", " "))


def choose_archetype(
    name: str,
    description: str,
    input_schema: Mapping[str, Any],
    *,
    overrides: Mapping[str, str] | None = None,
) -> tuple[str, str]:
    """(archetype, reason). An override must name a known archetype."""
    if overrides and name in overrides:
        chosen = overrides[name]
        if chosen not in ARCHETYPES:
            raise ValueError(f"override for {name!r}: unknown archetype {chosen!r}")
        return chosen, "override"
    tokens = _tokens(name, description, input_schema)
    best, best_hits = FALLBACK, 0
    for archetype, keywords in RULES:
        hits = sum(1 for t in tokens if t in keywords)
        if hits > best_hits:
            best, best_hits = archetype, hits
    reason = f"heuristic ({best_hits} keyword hits)" if best_hits else "no keyword hit"
    return best, reason
