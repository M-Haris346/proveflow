"""twin/data.py (D7, R8): every synthetic word passes t4_violations and contains no real
provider key prefix; helpers produce obviously fake values only."""

from __future__ import annotations

import pytest

from proveflow.core.honey import t4_violations
from proveflow.twin import data
from proveflow.twin.rng import Rng
from twinchecks import PROVIDER_PREFIXES, provider_prefix_in


@pytest.mark.parametrize("list_name", sorted(data.WORD_LISTS))
def test_no_word_list_entry_contains_a_provider_prefix(list_name: str) -> None:
    for word in data.WORD_LISTS[list_name]:
        assert provider_prefix_in(word) is None, (list_name, word)


@pytest.mark.parametrize("list_name", sorted(data.WORD_LISTS))
def test_no_word_list_entry_breaks_t4(list_name: str) -> None:
    for word in data.WORD_LISTS[list_name]:
        assert t4_violations(word) == (), (list_name, word)


def test_provider_prefix_list_is_the_ruled_one() -> None:
    assert PROVIDER_PREFIXES == ("sk-", "sk_live", "AKIA", "ghp_", "xoxb-", "ya29", "eyJ")
    assert provider_prefix_in("x SK-abc") == "sk-"  # case-insensitive


def test_helpers_are_fake_and_t4_clean() -> None:
    for i in range(200):
        r = Rng(str(i))
        name, addr = data.person(r)
        assert addr.endswith("@example.invalid")
        assert data.url(r).startswith("https://example.invalid/")
        ident = data.short_id(r, "obj")
        assert sum(c.isdigit() for c in ident) <= 6
        for s in (name, addr, ident, data.sentence(r), data.title(r)):
            assert t4_violations(s) == () and provider_prefix_in(s) is None, s


def test_orgs_are_marked_fictional() -> None:
    assert all(o.endswith("(fictional)") for o in data.ORGS)
