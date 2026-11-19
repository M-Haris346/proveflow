"""Matcher properties for HONEY needles (Phase 4 step 8): the same guarantees the canary has
(tests/property/test_oracle_properties.py), for ``pfhoney_<kind>_`` + 16 lowercase hex.

1. A fresh random honey value never matches unrelated values, under any encoding.
2. Encode-then-match: every encoding's output, embedded in arbitrary text, is found and
   attributed to that encoding (base64: any alignment, both alphabets).
3. Near miss: a value differing in ANY single hex digit, encoded by ANY encoding, is never
   detected for the real honey value (property + exhaustive deterministic sweep).
"""

from __future__ import annotations

import base64
import json

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from proveflow.core.honey import HONEY_HEX_LEN, HONEY_PREFIX, HoneyKind
from proveflow.oracle.matcher import ENCODINGS, match

KINDS = [k.value for k in HoneyKind]
HONEYS = st.tuples(st.sampled_from(KINDS), st.binary(min_size=8, max_size=8)).map(
    lambda kb: f"{HONEY_PREFIX}_{kb[0]}_{kb[1].hex()}"
)
TEXT = st.text(max_size=300)
JSON_VALUES = st.recursive(
    st.none() | st.booleans() | st.integers() | TEXT,
    lambda inner: st.lists(inner, max_size=4) | st.dictionaries(TEXT, inner, max_size=4),
    max_leaves=12,
)
NON_B64 = [name for name in ENCODINGS if name != "base64"]
NEUTRAL = st.text(alphabet=" .,;:!?()[]{}<>", max_size=20)


def hex_positions(value: str) -> range:
    return range(len(value) - HONEY_HEX_LEN, len(value))


@settings(max_examples=300, deadline=None)
@given(honey=HONEYS, value=JSON_VALUES)
def test_fresh_honey_never_matches_unrelated_values(honey: str, value: object) -> None:
    assume(honey not in json.dumps(value, ensure_ascii=False))
    assert not match(honey, value).found


@settings(max_examples=150, deadline=None)
@given(honey=HONEYS, blob=st.binary(max_size=400))
def test_fresh_honey_never_matches_random_base64_blobs(honey: str, blob: bytes) -> None:
    for enc in (base64.b64encode, base64.urlsafe_b64encode):
        assert not match(honey, enc(blob).decode()).found


@settings(max_examples=150, deadline=None)
@given(
    honey=HONEYS,
    name=st.sampled_from(NON_B64),
    prefix=st.text(max_size=30),
    suffix=st.text(max_size=30),
)
def test_honey_encode_then_match(honey: str, name: str, prefix: str, suffix: str) -> None:
    text = prefix + ENCODINGS[name].encode(honey) + suffix
    if name != "raw":
        assume(honey not in text)
    assert name in {h.encoding for h in match(honey, {"arg": text}).hits}


@settings(max_examples=150, deadline=None)
@given(
    honey=HONEYS,
    prefix=st.binary(max_size=20),
    suffix=st.binary(max_size=20),
    urlsafe=st.booleans(),
)
def test_honey_base64_any_alignment(
    honey: str, prefix: bytes, suffix: bytes, urlsafe: bool
) -> None:
    enc = base64.urlsafe_b64encode if urlsafe else base64.b64encode
    text = enc(prefix + honey.encode() + suffix).decode()
    assert "base64" in {h.encoding for h in match(honey, text).hits}


@settings(max_examples=300, deadline=None)
@given(
    honey=HONEYS,
    name=st.sampled_from(list(ENCODINGS)),
    data=st.data(),
    replacement=st.sampled_from("0123456789abcdef"),
    prefix=NEUTRAL,
    suffix=NEUTRAL,
)
def test_honey_near_miss_is_never_detected_by_any_encoding(
    honey: str, name: str, data: st.DataObject, replacement: str, prefix: str, suffix: str
) -> None:
    position = data.draw(st.sampled_from(list(hex_positions(honey))))
    other = honey[:position] + replacement + honey[position + 1 :]
    assume(other != honey)
    text = prefix + ENCODINGS[name].encode(other) + suffix
    assert not match(honey, {"arg": text}).found, (name, text)


@pytest.mark.parametrize(
    "honey",
    [
        "pfhoney_apikey_0123456789abcdef",
        "pfhoney_token_ffffffffffffffff",
        "pfhoney_password_a5a5a5a5a5a5a5a5",
    ],
)
def test_every_single_digit_honey_near_miss_under_every_encoding_is_not_detected(
    honey: str,
) -> None:
    for position in hex_positions(honey):
        for replacement in "0123456789abcdef":
            other = honey[:position] + replacement + honey[position + 1 :]
            if other == honey:
                continue
            for name, enc in ENCODINGS.items():
                for wrap in ("{}", "x {} y", "{}=="):
                    text = wrap.format(enc.encode(other))
                    assert not match(honey, text).found, (name, other, text)
