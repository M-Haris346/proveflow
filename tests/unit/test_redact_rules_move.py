"""C1: redaction rules moved to core; discover's module is the same object (re-export)."""

from __future__ import annotations

import proveflow.core.redact_rules as core_rules
import proveflow.discover.redact_rules as discover_rules
from proveflow.introspect import limits, transport


def test_redact_text_is_the_same_function() -> None:
    assert discover_rules.redact_text is core_rules.redact_text


def test_discover_module_is_an_alias_so_patches_apply_to_both() -> None:
    assert discover_rules is core_rules
    assert discover_rules.RULES is core_rules.RULES


def test_max_line_moved_to_limits() -> None:
    assert transport.MAX_LINE is limits.MAX_LINE
    assert limits.MAX_LINE == 16 * 1024 * 1024
