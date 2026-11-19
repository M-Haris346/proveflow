"""Matcher properties (ADR-004 false-positive story; encode-then-match).

1. A fresh random canary never matches unrelated text, under any encoding. (The strategy
   draws all 16^12 hex strings, a superset of the T4-accepted space |S_canary| =
   279,426,400,710,656, 47.9895 bits; ADR-004.)
   The analytic bound is in docs/ORACLE.md; this is a sanity check, not a proof.
2. Encode-then-match: every encoding's ``encode`` output, embedded in arbitrary text, is
   found and attributed to that encoding (base64: embedded in arbitrary BYTES, any
   alignment, both alphabets).
3. base64 never matches a canary that differs in ANY single hex digit (every bit counts).
"""

from __future__ import annotations

import base64
import json

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from proveflow.oracle.matcher import ENCODINGS, match

CANARIES = st.binary(min_size=6, max_size=6).map(lambda b: "cnry_" + b.hex())
TEXT = st.text(max_size=300)
JSON_VALUES = st.recursive(
    st.none() | st.booleans() | st.integers() | TEXT,
    lambda inner: st.lists(inner, max_size=4) | st.dictionaries(TEXT, inner, max_size=4),
    max_leaves=12,
)
NON_B64 = [name for name in ENCODINGS if name != "base64"]


@settings(max_examples=400, deadline=None)
@given(canary=CANARIES, value=JSON_VALUES)
def test_fresh_canary_never_matches_unrelated_values(canary: str, value: object) -> None:
    assume(canary not in json.dumps(value, ensure_ascii=False))
    assert not match(canary, value).found


@settings(max_examples=200, deadline=None)
@given(canary=CANARIES, blob=st.binary(max_size=400))
def test_fresh_canary_never_matches_random_base64_blobs(canary: str, blob: bytes) -> None:
    for enc in (base64.b64encode, base64.urlsafe_b64encode):
        assert not match(canary, enc(blob).decode()).found


@settings(max_examples=150, deadline=None)
@given(
    canary=CANARIES,
    name=st.sampled_from(NON_B64),
    prefix=st.text(max_size=30),
    suffix=st.text(max_size=30),
)
def test_encode_then_match(canary: str, name: str, prefix: str, suffix: str) -> None:
    text = prefix + ENCODINGS[name].encode(canary) + suffix
    if name != "raw":
        assume(canary not in text)  # attribution rule: plain canary belongs to raw
    hits = {h.encoding for h in match(canary, {"arg": text}).hits}
    assert name in hits


@settings(max_examples=150, deadline=None)
@given(
    canary=CANARIES,
    prefix=st.binary(max_size=20),
    suffix=st.binary(max_size=20),
    urlsafe=st.booleans(),
)
def test_base64_encode_then_match_any_alignment(
    canary: str, prefix: bytes, suffix: bytes, urlsafe: bool
) -> None:
    enc = base64.urlsafe_b64encode if urlsafe else base64.b64encode
    text = enc(prefix + canary.encode() + suffix).decode()
    assert "base64" in {h.encoding for h in match(canary, text).hits}


def near_miss(canary: str, position: int, replacement: str) -> str:
    return canary[:position] + replacement + canary[position + 1 :]


# Surroundings that cannot themselves form or complete an encoded canary: punctuation only,
# none of it a base64, percent, escape, hex or separator character the encodings rely on.
NEUTRAL = st.text(alphabet=" .,;:!?()[]{}<>", max_size=20)


@settings(max_examples=300, deadline=None)
@given(
    canary=CANARIES,
    name=st.sampled_from(list(ENCODINGS)),
    position=st.integers(min_value=5, max_value=16),
    replacement=st.sampled_from("0123456789abcdef"),
    prefix=NEUTRAL,
    suffix=NEUTRAL,
)
def test_near_miss_is_never_detected_by_any_encoding(
    canary: str, name: str, position: int, replacement: str, prefix: str, suffix: str
) -> None:
    """3a.1: a canary differing in ANY single hex digit, encoded by ANY encoding, is never
    detected (by any encoding) for the real canary."""
    other = near_miss(canary, position, replacement)
    assume(other != canary)
    text = prefix + ENCODINGS[name].encode(other) + suffix
    assert not match(canary, {"arg": text}).found, (name, text)


@settings(max_examples=150, deadline=None)
@given(
    canary=CANARIES,
    position=st.integers(min_value=5, max_value=16),
    replacement=st.sampled_from("0123456789abcdef"),
    prefix=st.binary(max_size=10),
    suffix=st.binary(max_size=10),
)
def test_base64_near_miss_is_never_detected(
    canary: str, position: int, replacement: str, prefix: bytes, suffix: bytes
) -> None:
    other = canary[:position] + replacement + canary[position + 1 :]
    assume(other != canary)
    text = base64.b64encode(prefix + other.encode() + suffix).decode()
    assert not match(canary, text).found
