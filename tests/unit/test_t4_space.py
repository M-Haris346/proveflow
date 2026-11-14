"""R10: the committed T4 space counter, pinned, and its DP verified against brute force.

ADR-004 cites |S_canary| and |S_honey|. If the predicate in core/honey.py changes, the pinned
numbers below break: recompute with ``uv run python tools/count_t4_space.py`` and update
ADR-004 together with this test.
"""

from __future__ import annotations

import importlib.util
import itertools
from pathlib import Path
from types import ModuleType

import pytest

from proveflow.core.honey import HONEY_PATTERN, t4_violations

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "count_t4_space.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("count_t4_space", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


COUNTER = _load()

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
    assert b / (1024 * 1024 * 91 / 2**48) < 2.0  # R-N1b stop condition
