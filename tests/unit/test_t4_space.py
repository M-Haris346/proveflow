"""R10: the committed T4 space counter, pinned, and its DP verified against brute force.

ADR-004 cites |S_canary| and |S_honey|. If the predicate in core/honey.py changes, the pinned
numbers below break: recompute with ``uv run python tools/count_t4_space.py`` and update
ADR-004 together with this test.
"""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from boundchecks import load_counter
from proveflow.core.honey import HONEY_PATTERN, t4_violations

ROOT = Path(__file__).resolve().parents[2]

# The suite's ONE by-path loader of tools/count_t4_space.py (tests/safety/test_no_twin_imports.py
# allowlists exactly boundchecks.py for it).
COUNTER = load_counter()

S_CANARY = 279_426_400_710_656
S_HONEY = 18_145_465_120_237_551_616


def test_canary_space_is_pinned() -> None:
    assert COUNTER.accepted(12) == S_CANARY


def test_honey_space_is_pinned() -> None:
    assert COUNTER.accepted(16) == S_HONEY


def test_counter_imports_the_predicate_constants_instead_of_redeclaring_them() -> None:
    import proveflow.core.honey as honey

    for name in ("MAX_DIGIT_RUN", "NINO_DIGITS", "NINO_FIRST", "NINO_SECOND", "NINO_SUFFIX"):
        assert getattr(COUNTER, name) is getattr(honey, name), name
    assert COUNTER.HEX == "0123456789abcdef"


@pytest.mark.parametrize(
    ("alphabet", "length", "prefix"),
    [
        ("ab12", 9, "cnry_"),  # NINO bites: a,b are valid NINO letters/suffixes; 1,2 digits
        ("a0", 13, "cnry_"),  # the 12-digit-run ban bites
        ("ab12", 9, "pfhoney_token_"),  # same, under the honey prefix
        ("ab12", 9, "act_"),  # Phase 3b: the action target's prefix (R2)
        ("a0", 13, "act_"),
        ("ab12", 9, "mrk_"),  # Phase 3b: the marker's prefix (R3)
        ("a0", 13, "mrk_"),
    ],
)
def test_dp_matches_brute_force_on_the_full_value(alphabet: str, length: int, prefix: str) -> None:
    """The DP is verified, not trusted: every string is checked with the REAL t4_violations on
    the full generated value (prefix included), and the predicate must actually bite."""
    total = len(alphabet) ** length
    brute = sum(
        1
        for chars in itertools.product(alphabet, repeat=length)
        if not t4_violations(prefix + "".join(chars))
    )
    assert brute < total, "predicate did not bite at this length/alphabet"
    assert COUNTER.accepted(length, alphabet) == brute


def test_hex_alphabet_is_the_honey_alphabet() -> None:
    import re

    assert re.fullmatch(HONEY_PATTERN, "pfhoney_token_" + COUNTER.HEX)


def test_bound_formula_and_numbers() -> None:
    b = COUNTER.bound(1024 * 1024, 32, S_CANARY, S_HONEY)
    assert f"{b:.4e}" == "3.4166e-07"
    # The R-N1b threshold is no longer asserted on this two-term bound: it measured something
    # other than the claim once (Phase 3b). It is asserted per scanned-string location below.


def test_bound_terms_extends_bound_exactly() -> None:
    """Phase 3b: four needle kinds with different encoding counts (R3's marker: raw +
    casefold, V=2). ``bound`` is ``bound_terms`` with the two Phase 4 terms, bit for bit."""
    n = 1024 * 1024
    assert COUNTER.bound(n, 32, S_CANARY, S_HONEY) == COUNTER.bound_terms(
        n, [(1, S_CANARY, 91), (32, S_HONEY, 91)]
    )
    assert COUNTER.bound_terms(n, [(3, 7, 2)]) == 3 * n * 2 / 7
    assert COUNTER.V_R3 == 2 and COUNTER.V_MAX == 91


MIB = 1024 * 1024
KIB = 1024


@pytest.mark.parametrize("n", [KIB, MIB])
@pytest.mark.parametrize("h", [0, 32, 256])
def test_every_scan_location_is_under_the_threshold(n: int, h: int) -> None:
    """R-N1b, on the quantity actually claimed: the bound on a false COMPROMISE in each
    scanned-string location (the union over every rule that can raise a compromise THERE,
    never per rule), computed through ``bound_terms`` from THE table, stays below
    ``THRESHOLD_RATIO`` x n * 91 * 2^-48."""
    from boundchecks import assert_every_location_under_the_threshold

    assert_every_location_under_the_threshold(COUNTER, n, h)


def test_the_table_matches_the_code_it_describes() -> None:
    """The table's lengths are the code's patterns; its encodings are the matcher's ONE list,
    with variant counts summing to V_MAX; R3's set on the marker AND R2's set on the action
    target are ``oracle.matcher.SPLIT_VALUE_ENCODINGS`` (Phase 6: one location, goal_argument,
    carries different match sets per needle kind, on purpose)."""
    import re

    from proveflow.core.attacks import ACTION_TARGET_PATTERN, CANARY_PATTERN, MARKER_PATTERN
    from proveflow.oracle import matcher

    assert set(COUNTER.ENCODING_VARIANTS) == set(matcher.ENCODINGS)
    assert sum(COUNTER.ENCODING_VARIANTS.values()) == COUNTER.V_MAX == 91
    hexes = COUNTER.NEEDLE_HEX
    for pattern, prefix, kind in ((CANARY_PATTERN, "cnry_", "canary"),
                                  (ACTION_TARGET_PATTERN, "act_", "action_target"),
                                  (MARKER_PATTERN, "mrk_", "marker")):  # fmt: skip
        assert re.fullmatch(pattern, prefix + "a" * hexes[kind]), kind
        assert not re.fullmatch(pattern, prefix + "a" * (hexes[kind] - 1)), kind
    assert re.fullmatch(HONEY_PATTERN, "pfhoney_token_" + "a" * hexes["honey"])
    assert COUNTER.SCAN_LOCATIONS["final_answer"][1]["marker"] == matcher.SPLIT_VALUE_ENCODINGS
    goal = COUNTER.SCAN_LOCATIONS["goal_argument"][1]
    assert goal["action_target"] == matcher.SPLIT_VALUE_ENCODINGS
    assert goal["canary"] == goal["honey"] == COUNTER.ALL_ENCODINGS  # R1 there: all 10
    assert COUNTER.V_R3 == 2


def test_phase_3b_bounds_are_pinned() -> None:
    """The action target is 16 hex (the honey length) matched with 2 encodings since Phase 6,
    so its term is n*2/|S_honey|; the marker stays 12 hex, matched with 2 encodings on a
    different string."""
    assert COUNTER.accepted(COUNTER.NEEDLE_HEX["action_target"]) == S_HONEY
    assert COUNTER.accepted(COUNTER.NEEDLE_HEX["marker"]) == S_CANARY
    goal = COUNTER.location_bound(MIB, 32, "goal_argument")
    assert f"{goal:.4e}" == "3.4166e-07"
    assert f"{goal / (MIB * 91 / 2**48):.4f}" == "1.0078"
    term = [t for t in COUNTER.location_terms("goal_argument", 32) if t[1] == S_HONEY and t[0] == 1]
    assert term == [(1, S_HONEY, 2)]  # the action target's own term, read from the table
    assert f"{MIB * 2 / S_HONEY:.4e}" == "1.1557e-13"
    assert f"{COUNTER.location_bound(MIB, 32, 'final_answer'):.4e}" == "7.5052e-09"
    assert f"{COUNTER.location_bound(MIB, 32, 'sink_argument'):.4e}" == "3.4166e-07"


def test_the_sighting_is_outside_the_threshold_table() -> None:
    """A sighting is never a compromise, so it is not a SCAN_LOCATIONS row (the threshold
    applies to every row of that table and to nothing else)."""
    assert "sighting" not in " ".join(what for what, _ in COUNTER.SCAN_LOCATIONS.values())
    assert set(COUNTER.SIGHTING_LOCATION[1]) == {"canary", "honey", "action_target"}
    assert all(encs == COUNTER.ALL_ENCODINGS for encs in COUNTER.SIGHTING_LOCATION[1].values())


def test_the_action_target_length_is_justified_by_the_sighting() -> None:
    """Phase 6 (ADR-004): the compromise bound no longer forces 16 hex (goal_argument is
    1.0078 at 12 hex or 16); the SIGHTING bound does: at 16 hex it is the honey-sized 1.0078,
    at the canary's 12 hex it about doubles (2.0152). Pinned so the length is not "optimized"
    back to 12 with nothing failing."""
    base = MIB * 91 / 2**48
    assert f"{COUNTER.sighting_bound(MIB, 32):.4e}" == "3.4166e-07"
    assert f"{COUNTER.sighting_bound(MIB, 32) / base:.4f}" == "1.0078"
    counter = load_counter()
    counter.NEEDLE_HEX["action_target"] = 12
    assert f"{counter.sighting_bound(MIB, 32) / base:.4f}" == "2.0152"
    assert f"{counter.location_bound(MIB, 32, 'goal_argument') / base:.4f}" == "1.0300"


DOCS = ("docs/ORACLE.md", "docs/adr/ADR-004-deterministic-oracle.md", "docs/METHODOLOGY.md")


@pytest.mark.parametrize("doc", DOCS)
def test_doc_bound_figures_are_read_from_the_table(doc: str) -> None:
    """The docs quote each location's bound at 1 MiB, H = 32; this pins every quoted figure to
    THE table (so a doc copied by hand cannot drift), and the superseded 12-hex goal-argument
    figure appears nowhere."""
    text = (ROOT / doc).read_text(encoding="utf-8")
    for location in ("goal_argument", "final_answer"):
        figure = f"{COUNTER.location_bound(MIB, 32, location):.4e}"
        assert figure in text, (doc, location, figure)
    assert "6.8314e-07" not in text, doc
