"""Mutation tests: remove each redaction rule in turn -> its named leak check must fail.

Proves every rule is load-bearing (no rule's example is caught "by accident" by
another rule) and that the leak check actually detects a disabled rule.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from proveflow.core.client import ConfigScope
from proveflow.discover import redact_rules
from proveflow.discover._common import parse_servers
from proveflow.discover.redact_rules import RULES, Example, Rule, redact_args


def assert_no_leak(example: Example) -> None:
    """Named leak check: the planted secret must not survive redaction."""
    out = " ".join(str(a) for a in redact_args(example.args))
    assert example.planted not in out, f"leak: {example.planted!r} survived"


def assert_no_leak_through_reader(example: Example) -> None:
    """Same check through the real config normalizer (what discover uses)."""
    servers, _ = parse_servers(
        {"srv": {"command": "npx", "args": list(example.args)}},
        key_name="mcpServers",
        url_keys=("url",),
        source_file=Path("C:/example/config.json"),
        scope=ConfigScope.USER,
    )
    assert example.planted not in servers[0].model_dump_json(), "leak through reader"


@pytest.mark.parametrize("rule", RULES, ids=lambda r: r.id)
def test_removing_rule_makes_its_examples_leak(rule: Rule, monkeypatch: pytest.MonkeyPatch) -> None:
    for ex in rule.examples:
        assert_no_leak(ex)
        assert_no_leak_through_reader(ex)

    monkeypatch.setattr(redact_rules, "RULES", tuple(r for r in RULES if r is not rule))

    for ex in rule.examples:
        with pytest.raises(AssertionError, match="leak"):
            assert_no_leak(ex)
        with pytest.raises(AssertionError, match="leak through reader"):
            assert_no_leak_through_reader(ex)
