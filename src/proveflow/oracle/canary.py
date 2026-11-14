"""Per-trial canaries: ``cnry_`` + 12 lowercase hex digits (``core.attacks.CANARY_PATTERN``).

The 12 hex digits are 48 bits from the ``secrets`` module (OS CSPRNG). Pure functions.
"""

from __future__ import annotations

import re
import secrets

from proveflow.core.attacks import CANARY_PATTERN

_CANARY = re.compile(CANARY_PATTERN)
CANARY_PREFIX = "cnry_"
CANARY_HEX_DIGITS = 12


def is_canary(value: str) -> bool:
    return _CANARY.fullmatch(value) is not None


def new_canary() -> str:
    canary = CANARY_PREFIX + secrets.token_hex(CANARY_HEX_DIGITS // 2)
    if not is_canary(canary):  # pragma: no cover - token_hex is always lowercase hex
        raise AssertionError("generated canary does not match CANARY_PATTERN")
    return canary
