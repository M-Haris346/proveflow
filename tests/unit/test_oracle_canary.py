"""Canary generation (oracle/canary.py)."""

from __future__ import annotations

import re

import pytest

from proveflow.core.attacks import CANARY_PATTERN
from proveflow.oracle.canary import is_canary, new_canary


def test_new_canary_matches_the_pattern() -> None:
    for _ in range(200):
        c = new_canary()
        assert re.fullmatch(CANARY_PATTERN, c)
        assert is_canary(c)
        assert len(c) == 17


def test_new_canaries_are_unique() -> None:
    assert len({new_canary() for _ in range(2000)}) == 2000


@pytest.mark.parametrize(
    "value",
    ["cnry_0123456789AB", "cnry_0123456789a", "cnry_0123456789abc", "CNRY_0123456789ab",
     "xnry_0123456789ab", "cnry-0123456789ab", " cnry_0123456789ab", ""],
)  # fmt: skip
def test_is_canary_rejects(value: str) -> None:
    assert not is_canary(value)
