"""Each carrier's exact output (D7), with synthetic payloads only."""

from __future__ import annotations

import json

import pytest

from proveflow.core.attacks import Carrier
from proveflow.proxy.carriers import apply_carrier

P = "do X cnry_0123456789ab"


def test_plain() -> None:
    assert apply_carrier(Carrier.PLAIN, "page", P) == "page\n\n" + P


def test_html_comment() -> None:
    assert apply_carrier(Carrier.HTML_COMMENT, "page", P) == "page\n<!-- " + P + " -->"


def test_html_comment_cannot_close_early() -> None:
    out = apply_carrier(Carrier.HTML_COMMENT, "page", "a -- b --> c")
    assert out == "page\n<!-- a - - b - -> c -->"
    assert out.count("-->") == 1


def test_markdown() -> None:
    assert apply_carrier(Carrier.MARKDOWN, "page", P) == "page\n\n> **Note:** " + P


def test_code_comment_prefixes_every_line() -> None:
    out = apply_carrier(Carrier.CODE_COMMENT, "page", "line1\nline2")
    assert out == "page\n```\n# line1\n# line2\n```"


def test_json_string_object_adds_note() -> None:
    out = apply_carrier(Carrier.JSON_STRING, '{"a": 1, "b": [2]}', P)
    assert out == json.dumps({"a": 1, "b": [2], "_note": P})
    assert list(json.loads(out)) == ["a", "b", "_note"]  # order kept (sort_keys=False)


def test_json_string_object_with_taken_note_keys() -> None:
    out = apply_carrier(Carrier.JSON_STRING, '{"_note": 1, "_note_2": 2}', P)
    assert json.loads(out) == {"_note": 1, "_note_2": 2, "_note_3": P}


def test_json_string_array_appends() -> None:
    out = apply_carrier(Carrier.JSON_STRING, '["a", 1]', P)
    assert json.loads(out) == ["a", 1, P]


def test_json_string_keeps_non_ascii() -> None:
    out = apply_carrier(Carrier.JSON_STRING, '{"t": "ü"}', "é " + P)
    assert "ü" in out and "é" in out  # ensure_ascii=False


@pytest.mark.parametrize("text", ["plain text", "42", '"a string"', "null", "true", "{broken", ""])
def test_json_string_fallback_is_plain_with_quoted_payload(text: str) -> None:
    out = apply_carrier(Carrier.JSON_STRING, text, 'say "hi" ' + P)
    assert out == text + "\n\n" + json.dumps('say "hi" ' + P)


def test_json_string_deep_nesting_falls_back() -> None:
    text = "[" * 100_000 + "]" * 100_000
    out = apply_carrier(Carrier.JSON_STRING, text, P)
    assert out.endswith("\n\n" + json.dumps(P))


@pytest.mark.parametrize("carrier", list(Carrier))
def test_every_carrier_is_deterministic(carrier: Carrier) -> None:
    assert apply_carrier(carrier, '{"a": 1}', P) == apply_carrier(carrier, '{"a": 1}', P)
