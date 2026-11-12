"""Wilson score interval and Cohen's kappa.

Wilson 95% interval for a binomial proportion with ``successes`` out of ``n`` trials:

    p = successes / n, z = 1.959963984540054 (two-sided 95%)
    centre = (p + z^2 / (2n)) / (1 + z^2 / n)
    half   = z * sqrt(p (1 - p) / n + z^2 / (4 n^2)) / (1 + z^2 / n)
    interval = [centre - half, centre + half]

Cohen's kappa for two raters on binary labels:

    p_o = observed agreement
    p_e = P(A yes) P(B yes) + P(A no) P(B no)
    kappa = (p_o - p_e) / (1 - p_e)          (undefined when p_e == 1)
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

Z95 = 1.959963984540054


@dataclass(frozen=True)
class Interval:
    low: float
    high: float


def wilson(successes: int, n: int, z: float = Z95) -> Interval:
    if n <= 0 or not 0 <= successes <= n:
        raise ValueError("need 0 <= successes <= n and n > 0")
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return Interval(max(0.0, centre - half), min(1.0, centre + half))


def cohens_kappa(a: Sequence[bool], b: Sequence[bool]) -> float | None:
    """None when undefined (no rows, or both raters constant on the same value)."""
    if len(a) != len(b):
        raise ValueError("raters labeled different numbers of items")
    n = len(a)
    if n == 0:
        return None
    p_o = sum(x == y for x, y in zip(a, b, strict=True)) / n
    pa, pb = sum(a) / n, sum(b) / n
    p_e = pa * pb + (1 - pa) * (1 - pb)
    if math.isclose(p_e, 1.0):
        return None
    return (p_o - p_e) / (1 - p_e)
