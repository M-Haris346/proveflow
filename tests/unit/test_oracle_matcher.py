"""Encoding-aware matcher (oracle/matcher.py): one block per encoding, attribution rule,
JSON walk, determinism, and the A1 performance bound on a pathological input."""

from __future__ import annotations

import base64
import random
import time

import pytest

from oraclechecks import BS, UNIQUE_SAMPLES
from proveflow.oracle.matcher import (
    ENCODINGS,
    SEPARATOR_CANDIDATE_CAP,
    iter_strings,
    match,
)
from proxyhelpers import CANARY

OTHER = "cnry_0123456789ac"  # one hex digit different


def encodings_of(value: object, canary: str = CANARY) -> set[str]:
    return {h.encoding for h in match(canary, value).hits}


def test_registry_is_exactly_the_documented_encodings() -> None:
    # Set, not order: monkeypatch.delitem (mutation tests) re-inserts restored keys at the
    # end, and nothing depends on the registry order (hits are sorted).
    assert set(ENCODINGS) == {
        "raw", "casefold", "ws_zw", "separator_split", "url", "base64", "hex", "rot13",
        "reversed", "json_escaped",
    }  # fmt: skip
    assert len(ENCODINGS) == 10


@pytest.mark.parametrize("name", sorted(UNIQUE_SAMPLES))
def test_each_unique_sample_is_detected_by_exactly_its_encoding(name: str) -> None:
    assert encodings_of({"body": UNIQUE_SAMPLES[name]}) == {name}


@pytest.mark.parametrize("name", sorted(UNIQUE_SAMPLES))
def test_a_different_canary_is_not_detected(name: str) -> None:
    assert encodings_of({"body": UNIQUE_SAMPLES[name]}, canary=OTHER) == set()


@pytest.mark.parametrize("name", list(ENCODINGS))
def test_each_encoder_round_trips_through_its_detector(name: str) -> None:
    enc = ENCODINGS[name]
    assert enc.detect("x " + enc.encode(CANARY) + " y", CANARY)


# --- raw / attribution rule -----------------------------------------------------------


def test_plain_canary_is_attributed_to_raw_only() -> None:
    assert encodings_of({"body": f"to: a@example.invalid {CANARY}"}) == {"raw"}


def test_raw_and_encoded_in_different_strings_are_both_reported() -> None:
    value = {"a": CANARY, "b": CANARY.encode().hex()}
    hits = match(CANARY, value).hits
    assert {(h.path, h.encoding) for h in hits} == {("$.a", "raw"), ("$.b", "hex")}


# --- casefold -----------------------------------------------------------------------------


@pytest.mark.parametrize("text", [CANARY.upper(), "CnRy_0123456789Ab", "cnry_0123456789AB"])
def test_casefold_variants(text: str) -> None:
    assert encodings_of(text) == {"casefold"}


# --- ws_zw --------------------------------------------------------------------------------


@pytest.mark.parametrize("cp", [0x200B, 0x200D, 0xFEFF, 0x00AD, 0x2060, 0xE0041, 0xFE0F])
def test_ws_zw_default_ignorables(cp: int) -> None:
    assert encodings_of(CANARY[:6] + chr(cp) + CANARY[6:]) == {"ws_zw"}


def test_ws_zw_mixed_whitespace() -> None:
    text = "cnry_01\t23 45\n6789" + chr(0x3000) + "ab"  # ideographic space
    assert encodings_of(text) == {"ws_zw"}


# --- separator_split ----------------------------------------------------------------------


@pytest.mark.parametrize("sep", ["-", ".", "|", "/", "_", ",", chr(0x2022)])
def test_separator_split_single_separator(sep: str) -> None:
    assert "separator_split" in encodings_of(sep.join(CANARY))


def test_separator_split_with_two_different_separators_is_not_detected() -> None:
    """Documented limit: only single-separator splits are detected."""
    text = "-".join(CANARY[:8]) + "-" + ".".join(CANARY[8:])
    assert "separator_split" not in encodings_of(text)


def test_separator_candidates_are_capped() -> None:
    assert SEPARATOR_CANDIDATE_CAP == 64


# --- url ----------------------------------------------------------------------------------


def test_url_single_and_double_and_partial() -> None:
    once = "".join(f"%{b:02X}" for b in CANARY.encode())
    assert encodings_of(once) == {"url"}
    assert encodings_of(once.replace("%", "%25")) == {"url"}  # double-encoded
    assert encodings_of("cnry%5F0123456789ab") == {"url"}  # only the underscore encoded


# --- base64 -------------------------------------------------------------------------------


@pytest.mark.parametrize("prefix", [b"", b"a", b"ab", b"abc", b"abcd"])
@pytest.mark.parametrize("urlsafe", [False, True])
def test_base64_every_alignment_and_alphabet(prefix: bytes, urlsafe: bool) -> None:
    blob = prefix + CANARY.encode() + b"tail"
    text = (base64.urlsafe_b64encode if urlsafe else base64.b64encode)(blob).decode()
    assert encodings_of(text) == {"base64"}


def test_base64_of_a_different_canary_is_not_detected() -> None:
    assert encodings_of(base64.b64encode(OTHER.encode()).decode()) == set()


# --- hex / rot13 / reversed ---------------------------------------------------------------


def test_hex_lower_and_upper() -> None:
    h = CANARY.encode().hex()
    assert encodings_of(h) == {"hex"}
    assert encodings_of(h.upper()) == {"hex"}


def test_rot13_and_reversed() -> None:
    import codecs

    assert encodings_of(codecs.encode(CANARY, "rot13")) == {"rot13"}
    assert encodings_of(CANARY[::-1]) == {"reversed"}


# --- json_escaped -------------------------------------------------------------------------


def test_json_escaped_lower_and_upper_hex_digits() -> None:
    lower = "".join(f"{BS}u{ord(c):04x}" for c in CANARY)
    upper = "".join(f"{BS}u{ord(c):04X}" for c in CANARY)
    assert encodings_of(lower) == {"json_escaped"}
    assert encodings_of(upper) == {"json_escaped"}


def test_json_escaped_partial() -> None:
    text = "cnry" + BS + "u005f" + "0123456789ab"
    assert encodings_of(text) == {"json_escaped"}


# --- JSON walk ----------------------------------------------------------------------------


def test_iter_strings_covers_keys_nesting_and_skips_scalars() -> None:
    value = {"a": [1, 2.5, True, None, {"k": "v"}], "b": {"c": "d"}}
    found = dict(iter_strings(value))
    assert found == {
        "$.<key:a>": "a",
        "$.a[4].<key:k>": "k",
        "$.a[4].k": "v",
        "$.<key:b>": "b",
        "$.b.<key:c>": "c",
        "$.b.c": "d",
    }


def test_canary_in_a_dict_key_is_found() -> None:
    assert match(CANARY, {CANARY: "x"}).found


def test_deep_nesting_has_no_recursion_limit() -> None:
    value: object = CANARY
    for _ in range(20_000):
        value = [value]
    assert match(CANARY, value).found


def test_none_and_empty_arguments() -> None:
    assert not match(CANARY, None).found
    assert not match(CANARY, {}).found


def test_hits_are_sorted_and_deterministic() -> None:
    value = {"z": CANARY.upper(), "a": CANARY, "m": CANARY.encode().hex()}
    first = match(CANARY, value)
    assert first == match(CANARY, value)
    assert list(first.hits) == sorted(first.hits)


# --- A1: pathological input, time bound ---------------------------------------------------

PERF_BOUND_S = 15.0  # measured 2.19 s locally (Windows, i5 12th gen) for this input


def test_pathological_one_mib_input_completes_within_bound() -> None:
    seps = [chr(cp) for cp in range(0x21, 0x2000)
            if not chr(cp).isalnum() and not chr(cp).isspace()][:300]  # fmt: skip
    rnd = random.Random(0)  # noqa: S311 - deterministic test data, not crypto
    parts: list[str] = []
    size = 0
    while size < 1024 * 1024:  # near-misses for raw, url and base64 + 300 distinct separators
        a, b, c = rnd.choice(seps), rnd.choice(seps), rnd.choice(seps)
        part = CANARY[:-1] + a + "%6" + b + "Y25yeV" + c
        parts.append(part)
        size += len(part)
    text = "".join(parts)[: 1024 * 1024]
    assert len({c for c in text if not c.isalnum()}) > SEPARATOR_CANDIDATE_CAP
    started = time.perf_counter()
    result = match(CANARY, {"body": text})
    elapsed = time.perf_counter() - started
    assert not result.found
    assert elapsed < PERF_BOUND_S, f"matcher took {elapsed:.2f}s on 1 MiB"
