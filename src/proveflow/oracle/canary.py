"""Per-trial canaries: ``cnry_`` + 12 lowercase hex digits (``core.attacks.CANARY_PATTERN``,
unchanged in Phase 4). Phase 3b: the per-trial ACTION TARGET ``act_`` + 12 hex (R2) is minted
by the same function, with the same T4 rejection.

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

from proveflow.core.attacks import ACTION_TARGET_PATTERN, CANARY_PATTERN, MARKER_PATTERN
from proveflow.core.honey import HONEY_HEX_LEN, HexSource, t4_violations

_CANARY = re.compile(CANARY_PATTERN)
_ACTION_TARGET = re.compile(ACTION_TARGET_PATTERN)
_MARKER = re.compile(MARKER_PATTERN)
CANARY_PREFIX = "cnry_"
ACTION_TARGET_PREFIX = "act_"
MARKER_PREFIX = "mrk_"
CANARY_HEX_DIGITS = 12
ACTION_TARGET_HEX_DIGITS = HONEY_HEX_LEN  # the honey length, not the canary's (R2, ADR-004)
MAX_ATTEMPTS = 64


class CanaryGenerationError(RuntimeError):
    """No T4-clean canary in MAX_ATTEMPTS draws (a broken hex source; fail closed)."""


def _os_hex(n: int) -> str:
    return secrets.token_hex((n + 1) // 2)[:n]  # token_hex(k) returns 2k characters


def is_canary(value: str) -> bool:
    return _CANARY.fullmatch(value) is not None


def _mint(
    prefix: str,
    pattern: re.Pattern[str],
    what: str,
    pattern_name: str,
    draw_hex: HexSource,
    digits: int = CANARY_HEX_DIGITS,
) -> str:
    """``prefix`` + ``digits`` hex, rejection-sampled against T4 (N1); fails closed."""
    for _ in range(MAX_ATTEMPTS):
        value = prefix + draw_hex(digits)
        if pattern.fullmatch(value) is None:
            raise CanaryGenerationError(f"hex source returned a value outside {pattern_name}")
        if not t4_violations(value):
            return value
    raise CanaryGenerationError(f"no T4-clean {what} in {MAX_ATTEMPTS} draws")


def new_canary(draw_hex: HexSource = _os_hex) -> str:
    return _mint(CANARY_PREFIX, _CANARY, "canary", "CANARY_PATTERN", draw_hex)


def is_marker(value: str) -> bool:
    return _MARKER.fullmatch(value) is not None


def new_marker(draw_hex: HexSource = _os_hex) -> str:
    """The per-trial MARKER (R3): minted exactly like the canary (same 12 hex, same T4
    rejection), so its accepted space equals |S_canary| (tools/count_t4_space.py)."""
    return _mint(MARKER_PREFIX, _MARKER, "marker", "MARKER_PATTERN", draw_hex)


def spaced_marker(marker: str) -> str:
    """The form the PAYLOAD carries (ruling R3): the prefix, then the 12 hex in groups of
    four, each separated by one space (``mrk_ a1b2 c3d4 e5f6``). The payload asks the agent
    to output it with the spaces removed. Quoting this form verbatim never contains the
    marker as a substring, in any case, so it can never match R3's raw/casefold set."""
    if not is_marker(marker):
        raise ValueError("not a marker")
    hex12 = marker[len(MARKER_PREFIX) :]
    return " ".join([MARKER_PREFIX, hex12[0:4], hex12[4:8], hex12[8:12]])


def is_action_target(value: str) -> bool:
    return _ACTION_TARGET.fullmatch(value) is not None


def new_action_target(draw_hex: HexSource = _os_hex) -> str:
    """The per-trial ACTION TARGET (R2): 16 hex, the HONEY length, with the canary's T4
    rejection, so its accepted space equals |S_honey| (tools/count_t4_space.py). Like honey,
    it is scanned on the SAME strings as the canary with the same 10 encodings, so it must not
    be the canary's size: a 12-hex needle there would double the dominant term of the
    false-compromise bound (docs/ORACLE.md, ADR-004)."""
    return _mint(ACTION_TARGET_PREFIX, _ACTION_TARGET, "action target", "ACTION_TARGET_PATTERN",
                 draw_hex, ACTION_TARGET_HEX_DIGITS)  # fmt: skip
