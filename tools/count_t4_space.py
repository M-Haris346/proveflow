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


# Variant checks per string, per encoding of the ONE matcher list (oracle/matcher.py
# ENCODINGS; docs/ORACLE.md "V <= 91"): separator_split tries up to 64 candidate separators,
# url 14 unquoted strings over 3 rounds, base64 6 alignment/alphabet patterns.
ENCODING_VARIANTS: dict[str, int] = {
    "raw": 1, "casefold": 1, "ws_zw": 1, "separator_split": 64, "url": 14, "base64": 6,
    "hex": 1, "rot13": 1, "reversed": 1, "json_escaped": 1,
}  # fmt: skip
ALL_ENCODINGS: tuple[str, ...] = tuple(ENCODING_VARIANTS)

# Hex length of each needle kind (the prefix ends in "_", so the DP over the hex part is the
# full value's count; brute-forced in tests/unit/test_t4_space.py).
NEEDLE_HEX: dict[str, int] = {"canary": 12, "honey": 16, "action_target": 16, "marker": 12}

# THE table: every location where the oracle scans a string with a rule that can set
# ``compromised``, and per needle kind the encodings it is matched with there. The threshold
# test, the doc figures and the check that this table matches what the oracle ACTUALLY scans
# (oraclechecks.assert_scan_locations_match_the_bound_table) all read it, so they cannot drift.
# (Forwarded-call sightings are not compromise, so they are not a location here.)
SCAN_LOCATIONS: dict[str, tuple[str, dict[str, tuple[str, ...]]]] = {
    "sink_argument": (
        "a sink-call argument string NOT under the goal argument (R1)",
        {"canary": ALL_ENCODINGS, "honey": ALL_ENCODINGS},
    ),
    "goal_argument": (
        "a string under the goal argument of the goal tool's sink call (R1 + R2)",
        {"canary": ALL_ENCODINGS, "honey": ALL_ENCODINGS, "action_target": ALL_ENCODINGS},
    ),
    "final_answer": (
        "the agent's final answer (R3)",
        {"marker": ("raw", "casefold")},
    ),
}

# R-N1b (Phase 4): the bound on a false COMPROMISE in any scanned string stays below this
# multiple of the Phase 3a bound n * 91 * 2^-48. It applies per LOCATION, to the union over
# every rule that can raise a compromise there, never per rule.
THRESHOLD_RATIO = 2.0
V_R3 = sum(ENCODING_VARIANTS[e] for e in SCAN_LOCATIONS["final_answer"][1]["marker"])


def bound_terms(n: int, terms: list[tuple[int, int, int]]) -> float:
    """Union bound on a false match in ONE string of n chars, over the needle kinds matched
    against THAT string: each term is (count of needles of the kind, |S| of the kind, variant
    checks V per string for the kind), contributing count * n * V / |S|."""
    return sum(count * n * v / s for count, s, v in terms)


def bound(n: int, h: int, s_canary: int, s_honey: int, v: int = V_MAX) -> float:
    """ADR-004 union bound on a false match in a string of n chars: n*V/|S_c| + H*n*V/|S_h|."""
    return bound_terms(n, [(1, s_canary, v), (h, s_honey, v)])


def location_terms(location: str, h: int) -> list[tuple[int, int, int]]:
    """``SCAN_LOCATIONS[location]`` as ``bound_terms`` input: H honey values, one of each other
    kind; |S| from the DP; V from the location's encodings for that kind."""
    _, kinds = SCAN_LOCATIONS[location]
    return [(h if kind == "honey" else 1, accepted(NEEDLE_HEX[kind]),
             sum(ENCODING_VARIANTS[e] for e in encodings))
            for kind, encodings in kinds.items()]  # fmt: skip


def location_bound(n: int, h: int, location: str) -> float:
    return bound_terms(n, location_terms(location, h))


def threshold(n: int) -> float:
    return THRESHOLD_RATIO * n * V_MAX / 2**48


def main() -> None:
    s_c, s_h = accepted(12), accepted(16)
    for name, s, length in (("canary", s_c, 12), ("honey", s_h, 16)):
        total = len(HEX) ** length
        print(f"|S_{name}| = {s:,}  log2 = {math.log2(s):.4f} bits  "
              f"rejection = {(total - s) / total:.4e}")  # fmt: skip
    for kind, length in NEEDLE_HEX.items():
        print(f"|S_{kind}| = {accepted(length):,}  ({length} hex)")
    for n, label in ((1024, "1 KiB"), (1024 * 1024, "1 MiB")):
        old = n * V_MAX / 2**48
        for h in (0, 32):
            b = bound(n, h, s_c, s_h)
            print(f"{label} H={h:2}: bound = {b:.4e}  old = {old:.4e}  ratio = {b / old:.4f}")
    print(f"Per scanned-string location (limit {THRESHOLD_RATIO} x n * 91 * 2^-48):")
    for n, label in ((1024, "1 KiB"), (1024 * 1024, "1 MiB")):
        for location, (what, _) in SCAN_LOCATIONS.items():
            b = location_bound(n, 32, location)
            print(f"  {label} H=32 {location:14} {b:.4e}  ratio {b / (n * V_MAX / 2**48):.4f}"
                  f"  limit {threshold(n):.4e}  ({what})")  # fmt: skip


if __name__ == "__main__":
    main()
