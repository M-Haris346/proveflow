"""Compatibility alias: the redaction rules live in ``proveflow.core.redact_rules``.

Moved to ``core`` in Phase 2 so the proxy can scrub upstream stderr without importing
``proveflow.discover`` (ADR-006, import guard). This module object IS
``proveflow.core.redact_rules`` (it replaces itself in ``sys.modules``), so a monkeypatch
of ``RULES`` through either name changes the same global: the Phase 1 mutation tests keep
their meaning unedited.
"""

from __future__ import annotations

import sys

from proveflow.core import redact_rules as _core_redact_rules

# Explicit re-exports for static analysis (mypy cannot follow the sys.modules swap below).
from proveflow.core.redact_rules import (
    ENTROPY_MIN_BITS as ENTROPY_MIN_BITS,
)
from proveflow.core.redact_rules import (
    ENTROPY_MIN_LEN as ENTROPY_MIN_LEN,
)
from proveflow.core.redact_rules import (
    RULES as RULES,
)
from proveflow.core.redact_rules import (
    Example as Example,
)
from proveflow.core.redact_rules import (
    Rule as Rule,
)
from proveflow.core.redact_rules import (
    raw_secret_segments as raw_secret_segments,
)
from proveflow.core.redact_rules import (
    redact_args as redact_args,
)
from proveflow.core.redact_rules import (
    redact_text as redact_text,
)
from proveflow.core.redact_rules import (
    secret_spans as secret_spans,
)
from proveflow.core.redact_rules import (
    shannon_bits as shannon_bits,
)

sys.modules[__name__] = _core_redact_rules
