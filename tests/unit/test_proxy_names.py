"""L1: name_key / colliding_names, and the Default_Ignorable_Code_Point table itself."""

from __future__ import annotations

import itertools
import unicodedata

import pytest

from proveflow.proxy.names import (
    DEFAULT_IGNORABLE,
    DEFAULT_IGNORABLE_TOTAL,
    colliding_names,
    is_default_ignorable,
    name_key,
)

# General category stated in each UCD data line's comment (DerivedCoreProperties-15.0.0.txt),
# in the same order as DEFAULT_IGNORABLE.
UCD_CATEGORIES = (
    "Cf", "Mn", "Cf", "Lo", "Mn", "Mn", "Cf", "Mn", "Cf", "Cf", "Cf", "Cn", "Cf", "Lo", "Mn",
    "Cf", "Lo", "Cn", "Cf", "Cf", "Cn", "Cf", "Cn", "Cf", "Cn", "Mn", "Cn",
)  # fmt: skip


def test_table_total_matches_ucd() -> None:
    assert sum(last - first + 1 for first, last in DEFAULT_IGNORABLE) == DEFAULT_IGNORABLE_TOTAL
    assert DEFAULT_IGNORABLE_TOTAL == 4174


def test_table_is_sorted_and_disjoint() -> None:
    for (a_first, a_last), (b_first, _b_last) in itertools.pairwise(DEFAULT_IGNORABLE):
        assert a_first <= a_last < b_first


def test_table_categories_match_pythons_unicode_15_data() -> None:
    """Independent cross-check of the copied table against Python's own UCD 15.0.0."""
    assert unicodedata.unidata_version == "15.0.0"
    assert len(UCD_CATEGORIES) == len(DEFAULT_IGNORABLE)
    for (first, last), category in zip(DEFAULT_IGNORABLE, UCD_CATEGORIES, strict=True):
        for cp in range(first, last + 1):
            assert unicodedata.category(chr(cp)) == category, hex(cp)


def test_neighbours_are_not_ignorable() -> None:
    for cp in (0x00AC, 0x00AE, 0x200A, 0x2010, 0xFEFE, 0xFF00, 0x0041):
        assert not is_default_ignorable(chr(cp))


@pytest.mark.parametrize(
    "variant",
    [
        "send\u200bemail_",  # different letters
        "send\u200bemail",  # the ZWSP replaces "_": keys to "sendemail" (no fold)
    ],
)
def test_different_names_do_not_collide(variant: str) -> None:
    assert colliding_names(["send_email", variant]) == frozenset()


@pytest.mark.parametrize(
    "variant",
    [
        "send_email\u200b",
        "send\u200b_email",
        "SEND_EMAIL",
        "\uff53\uff45\uff4e\uff44_email",  # fullwidth "send"
        "send_e\u00admail",  # soft hyphen
        "send_email\ufe0f",  # variation selector
        "send_email\U000e0041",  # tag character
    ],
)
def test_variants_collide(variant: str) -> None:
    assert name_key(variant) == name_key("send_email")
    assert colliding_names(["send_email", variant, "query_db"]) == {"send_email", variant}


def test_identical_names_are_not_a_collision() -> None:
    assert colliding_names(["a", "a", "b"]) == frozenset()
