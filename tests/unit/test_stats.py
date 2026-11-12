"""Wilson interval and Cohen's kappa against HAND-COMPUTED values."""

from __future__ import annotations

import pytest

from proveflow.stats.intervals import cohens_kappa, wilson


@pytest.mark.parametrize(
    ("k", "n", "low", "high"),
    [
        # 8/10: p = 0.8, z^2 = 3.841459; denom = 1.384146;
        # centre = (0.8 + 0.192073) / 1.384146 = 0.716740;
        # half = 1.959964 * sqrt(0.016 + 0.009604) / 1.384146 = 0.226578
        (8, 10, 0.490162, 0.943318),
        (0, 10, 0.0, 0.277533),
        (10, 10, 0.722467, 1.0),
        (45, 50, 0.786398, 0.956524),
    ],
)
def test_wilson_hand_values(k: int, n: int, low: float, high: float) -> None:
    ci = wilson(k, n)
    assert ci.low == pytest.approx(low, abs=1e-6)
    assert ci.high == pytest.approx(high, abs=1e-6)


@pytest.mark.parametrize(("k", "n"), [(1, 0), (-1, 5), (6, 5)])
def test_wilson_rejects_bad_input(k: int, n: int) -> None:
    with pytest.raises(ValueError):
        wilson(k, n)


def test_kappa_hand_computed_2x2() -> None:
    """A/B: yes/yes 20, yes/no 5, no/yes 10, no/no 15 (n = 50).
    p_o = (20 + 15) / 50 = 0.70
    P(A yes) = 25/50 = 0.5, P(B yes) = 30/50 = 0.6
    p_e = 0.5 * 0.6 + 0.5 * 0.4 = 0.50
    kappa = (0.70 - 0.50) / (1 - 0.50) = 0.40"""
    a = [True] * 20 + [True] * 5 + [False] * 10 + [False] * 15
    b = [True] * 20 + [False] * 5 + [True] * 10 + [False] * 15
    assert cohens_kappa(a, b) == pytest.approx(0.40)


def test_kappa_perfect_and_chance_and_undefined() -> None:
    assert cohens_kappa([True, False, True, False], [True, False, True, False]) == pytest.approx(
        1.0
    )
    # p_o = 0.5, P(A yes) = P(B yes) = 0.5 -> p_e = 0.5 -> kappa 0
    assert cohens_kappa([True, True, False, False], [True, False, True, False]) == pytest.approx(
        0.0
    )
    assert cohens_kappa([True, True], [True, True]) is None  # p_e = 1: undefined
    assert cohens_kappa([], []) is None
    with pytest.raises(ValueError):
        cohens_kappa([True], [True, False])
