"""Exact size of the T4-accepted space for canary / honey hex parts (R10; ADR-004).

Counts, with no sampling, how many strings of ``length`` characters over ``alphabet`` pass
``proveflow.core.honey.t4_violations`` when used as the hex part of a generated value.

Predicate (imported, never re-declared here): reject iff
  * a run of >= ``MAX_DIGIT_RUN`` ASCII digits, or
  * a UK NINO shape: [NINO_FIRST][NINO_SECOND] digit x NINO_DIGITS [NINO_SUFFIX], any case.
The fixed prefix of a generated value (``cnry_`` / ``pfhoney_<kind>_``) ends in ``_``, so no
digit run or NINO window can span into it; the brute-force cross-check in
tests/unit/test_t4_space.py runs the real ``t4_violations`` on the FULL value to confirm that.

Method: dynamic programming over positions. State = (current digit-run length, set of NINO
pattern-prefix lengths currently matched). Run:

    uv run python tools/count_t4_space.py
"""

from __future__ import annotations

import math
import string
from collections import defaultdict

from proveflow.core.honey import (
    MAX_DIGIT_RUN,
    NINO_DIGITS,
    NINO_FIRST,
    NINO_SECOND,
    NINO_SUFFIX,
)

HEX = "".join(sorted(set(string.hexdigits.lower())))  # the generation alphabet [0-9a-f]
DIGITS = frozenset(string.digits)
NINO_LEN = 2 + NINO_DIGITS + 1
V_MAX = 91  # matcher variant checks per string (docs/ORACLE.md)


def _nino_sets(alphabet: str) -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    """The NINO letter classes restricted to ``alphabet`` (case-insensitive, as the regex)."""

    def pick(letters: str) -> frozenset[str]:
        return frozenset(c for c in alphabet if c.upper() in letters)

    return pick(NINO_FIRST), pick(NINO_SECOND), pick(NINO_SUFFIX)


def accepted(length: int, alphabet: str = HEX) -> int:
    """Number of strings of ``length`` chars over ``alphabet`` with no T4 violation."""
    first, second, suffix = _nino_sets(alphabet)

    def fits(pos: int, ch: str) -> bool:
        if pos == 0:
            return ch in first
        if pos == 1:
            return ch in second
        if pos < 2 + NINO_DIGITS:
            return ch in DIGITS
        return ch in suffix

    states: dict[tuple[int, frozenset[int]], int] = {(0, frozenset()): 1}
    for _ in range(length):
        nxt: dict[tuple[int, frozenset[int]], int] = defaultdict(int)
        for (run, active), count in states.items():
            for ch in alphabet:
                new_run = run + 1 if ch in DIGITS else 0
                if new_run >= MAX_DIGIT_RUN:
                    continue
                matched = False
                progress = {1} if fits(0, ch) else set()
                for k in active:
                    if fits(k, ch):
                        if k + 1 == NINO_LEN:
                            matched = True
                        else:
                            progress.add(k + 1)
                if matched:
                    continue
                nxt[(new_run, frozenset(progress))] += count
        states = nxt
    return sum(states.values())


def bound(n: int, h: int, s_canary: int, s_honey: int, v: int = V_MAX) -> float:
    """ADR-004 union bound on a false match in a string of n chars: n*V/|S_c| + H*n*V/|S_h|."""
    return n * v / s_canary + h * n * v / s_honey


def main() -> None:
    s_c, s_h = accepted(12), accepted(16)
    for name, s, length in (("canary", s_c, 12), ("honey", s_h, 16)):
        total = len(HEX) ** length
        print(f"|S_{name}| = {s:,}  log2 = {math.log2(s):.4f} bits  "
              f"rejection = {(total - s) / total:.4e}")  # fmt: skip
    for n, label in ((1024, "1 KiB"), (1024 * 1024, "1 MiB")):
        old = n * V_MAX / 2**48
        for h in (0, 32):
            b = bound(n, h, s_c, s_h)
            print(f"{label} H={h:2}: bound = {b:.4e}  old = {old:.4e}  ratio = {b / old:.4f}")


if __name__ == "__main__":
    main()
