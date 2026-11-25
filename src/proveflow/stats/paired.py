"""Paired comparison of two halves on the SAME cells (Phase 8, paired verify).

Exact two-sided McNemar test. Over n paired binary outcomes, only the discordant pairs carry
information: ``b`` = cells positive in the first half only, ``c`` = cells positive in the second
half only. Under H0 (no difference) each discordant pair is either way with probability 1/2, so

    m = b + c,  k = min(b, c)
    p = min(1, 2 * sum_{i=0..k} C(m, i) / 2^m)        (p = 1 when m == 0)

Exact integer arithmetic (``math.comb``) until the final division, so the value for small m is
exact: b = 10, c = 0 gives 2 / 2^10 = 0.001953125.

Newcombe's interval for the paired difference is NOT built (Phase 8): it needs reference values
from its paper, not memory (docs/ARCHITECTURE.md §5.10).
"""

from __future__ import annotations

import math
from fractions import Fraction


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value from the two discordant counts."""
    if b < 0 or c < 0:
        raise ValueError("discordant counts must be >= 0")
    m = b + c
    if m == 0:
        return 1.0
    tail = sum(math.comb(m, i) for i in range(min(b, c) + 1))
    return float(min(Fraction(1), Fraction(2 * tail, 2**m)))
