"""Per-trial canaries: ``cnry_`` + 12 lowercase hex digits (``core.attacks.CANARY_PATTERN``,
unchanged in Phase 4).

N1 (Phase 4): rejection sampling with the SAME structural predicate as honey values,
``core.honey.t4_violations`` (no run of 12 decimal digits, no NINO shape). A draw that
breaks a rule is discarded and redrawn; after ``MAX_ATTEMPTS`` rejected draws generation
fails closed. The accepted space is |S_canary| = 279,426,400,710,656 values (47.9895 bits;
per-draw rejection 7.2780e-3), counted exactly by ``tools/count_t4_space.py`` (ADR-004).
Hex digits come from the ``secrets`` module (OS CSPRNG) by default.
"""

from __future__ import annotations

import re
import secrets

from proveflow.core.attacks import CANARY_PATTERN
from proveflow.core.honey import HexSource, t4_violations

_CANARY = re.compile(CANARY_PATTERN)
CANARY_PREFIX = "cnry_"
CANARY_HEX_DIGITS = 12
MAX_ATTEMPTS = 64


class CanaryGenerationError(RuntimeError):
    """No T4-clean canary in MAX_ATTEMPTS draws (a broken hex source; fail closed)."""


def _os_hex(n: int) -> str:
    return secrets.token_hex((n + 1) // 2)[:n]  # token_hex(k) returns 2k characters


def is_canary(value: str) -> bool:
    return _CANARY.fullmatch(value) is not None


def new_canary(draw_hex: HexSource = _os_hex) -> str:
    for _ in range(MAX_ATTEMPTS):
        canary = CANARY_PREFIX + draw_hex(CANARY_HEX_DIGITS)
        if not is_canary(canary):
            raise CanaryGenerationError("hex source returned a value outside CANARY_PATTERN")
        if not t4_violations(canary):
            return canary
    raise CanaryGenerationError(f"no T4-clean canary in {MAX_ATTEMPTS} draws")
