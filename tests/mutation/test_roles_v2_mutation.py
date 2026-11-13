"""Mutation: disable each v2 rule; its synthetic positive case must lose the role.

Proves every rule in tests/unit/test_roles_v2.py is load-bearing (no rule is dead code).
"""

from __future__ import annotations

import re
from typing import Any

import pytest

import proveflow.flows.roles as R
from proveflow.core.tools import ToolRole

S, P, K = ToolRole.UNTRUSTED_SOURCE, ToolRole.PRIVATE_DATA, ToolRole.SINK
NEVER = re.compile(r"(?!x)x")


def _roles(name: str, desc: str = "", props: dict[str, Any] | None = None) -> set[ToolRole]:
    return R.assigned_roles(R.classify_tool(name, "srv", desc, {"properties": props or {}}))


CASES: list[tuple[str, str, Any, tuple[str, str, dict[str, Any] | None], ToolRole]] = [
    ("C1", "_SAVE_PHRASE", NEVER,
     ("render_chart", "", {"outputPath": {"description": "Where it is saved."}}), K),
    ("C3", "VCS_WRITE_VERBS", frozenset(), ("vcs_revert", "", None), K),
    ("C2", "SCHEMA_REPO", frozenset(), ("vcs_blame", "", {"repository": {}}), P),
    ("C4", "SCHEMA_ENTERED_TEXT", frozenset(),
     ("respond_prompt", "Answer the dialog on the page.", {"prompt_text": {}}), K),
    ("C8", "URL_SINK_WEIGHT", 0.25, ("ping_endpoint", "Ping it.", {"url": {}}), K),
    ("C9", "SCHEMA_MODEL", frozenset(), ("ask_assistant", "", {"model": {}, "prompt": {}}), K),
    ("C11a", "CAPTURE_NOUNS", frozenset(), ("page_snapshot", "", None), S),
    ("C11c", "_UNTRUSTED_PHRASE", NEVER, ("lookup_rows", "Rows are untrusted data.", None), S),
    ("C11d", "_ARBITRARY_CODE_PHRASE", NEVER,
     ("sandbox_tool", "Executes arbitrary code in the worker.", None), P),
    ("C12", "SCHEMA_HEADER_WORD", "zz-none", ("configure_client", "", {"customHeaders": {}}), K),
]  # fmt: skip


@pytest.mark.parametrize(
    ("rule", "attr", "mutant", "tool", "role"), CASES, ids=[c[0] for c in CASES]
)
def test_disabling_rule_drops_its_role(
    monkeypatch: pytest.MonkeyPatch,
    rule: str,
    attr: str,
    mutant: Any,
    tool: tuple[str, str, dict[str, Any] | None],
    role: ToolRole,
) -> None:
    assert role in _roles(*tool), f"{rule}: positive case must hold before the mutation"
    monkeypatch.setattr(R, attr, mutant)
    assert role not in _roles(*tool), f"{rule}: still assigned with the rule disabled"


def test_c5_mutant_restoring_hover_makes_it_a_sink_again(monkeypatch: pytest.MonkeyPatch) -> None:
    assert K not in _roles("browser_hover_item")
    monkeypatch.setattr(R, "BROWSER_ACTION_VERBS", R.BROWSER_ACTION_VERBS | {"hover"})
    assert K in _roles("browser_hover_item")
    monkeypatch.setattr(R, "UI_NOUNS", frozenset())
    assert K in _roles("close_tab")


def test_c6_mutant_keeps_write_tool_description_private(monkeypatch: pytest.MonkeyPatch) -> None:
    desc = "Update a file in the personal document store."
    assert P not in _roles("update_notes", desc)
    monkeypatch.setattr(R, "_write_tool_desc", lambda _toks, desc_ev: desc_ev)
    assert P in _roles("update_notes", desc)


def test_c7_mutant_navigate_as_source_verb(monkeypatch: pytest.MonkeyPatch) -> None:
    assert S not in _roles("navigate_history")
    monkeypatch.setattr(R, "SOURCE_VERBS", R.SOURCE_VERBS | {"navigate"})
    assert S in _roles("navigate_history")
