"""Unit tests for every redaction rule (docs/REDACTION.md)."""

from __future__ import annotations

from pathlib import Path

import pytest

from proveflow.core.redact import RedactedText, RedactedValue
from proveflow.discover.redact_rules import (
    ENTROPY_MIN_BITS,
    RULES,
    Rule,
    raw_secret_segments,
    redact_args,
    redact_text,
    shannon_bits,
)

DOC = Path(__file__).resolve().parents[2] / "docs" / "REDACTION.md"


def rendered(args: tuple[str, ...]) -> str:
    return " ".join(str(a) for a in redact_args(args))


@pytest.mark.parametrize("rule", RULES, ids=lambda r: r.id)
def test_positive_examples_are_redacted(rule: Rule) -> None:
    assert rule.examples, f"{rule.id} has no positive example"
    for ex in rule.examples:
        out = rendered(ex.args)
        assert ex.planted not in out
        assert "<redacted:sha256-" in out
        assert any(ex.planted in seg for seg in raw_secret_segments(ex.args))


@pytest.mark.parametrize("rule", RULES, ids=lambda r: r.id)
def test_negative_examples_untouched(rule: Rule) -> None:
    for args in rule.negatives:
        out = redact_args(args)
        assert not any(a.is_redacted for a in out), (rule.id, args)
        assert rendered(args) == " ".join(args)


def test_rule_ids_unique_and_documented() -> None:
    ids = [r.id for r in RULES]
    assert len(ids) == len(set(ids))
    doc = DOC.read_text(encoding="utf-8")
    for rule_id in ids:
        assert f"`{rule_id}`" in doc, f"{rule_id} missing from docs/REDACTION.md"


def test_known_limitation_short_unflagged_positional_not_caught() -> None:
    """Documented limitation (docs/REDACTION.md): short, low-entropy, unflagged
    positional secrets are NOT redacted. This test pins that honestly."""
    out = redact_args(("myapp", "hunter2pass"))
    assert not any(a.is_redacted for a in out)


def test_flag_value_starting_with_dash_is_not_consumed() -> None:
    out = redact_args(("--token", "--verbose"))
    assert [str(a) for a in out] == ["--token", "--verbose"]


def test_multiple_spans_in_one_string() -> None:
    text = "https://u:PLANTEDa1@h.example/x?token=PLANTEDb2&page=1"
    red = redact_text(text)
    out = str(red)
    assert "PLANTEDa1" not in out
    assert "PLANTEDb2" not in out
    assert "page=1" in out
    assert sum(isinstance(p, RedactedValue) for p in red.parts) == 2


def test_redacted_text_round_trip_and_plain_segments() -> None:
    red = redact_text("--api-key=PLANTEDzz99")
    assert RedactedText.model_validate_json(red.model_dump_json()) == red
    assert red.plain_segments() == ("--api-key=",)
    assert "PLANTEDzz99" not in red.model_dump_json()
    assert "PLANTEDzz99" not in repr(red)


def test_shannon_bits() -> None:
    assert shannon_bits("") == 0.0
    assert shannon_bits("aaaa") == 0.0
    assert shannon_bits("abcd") == pytest.approx(2.0)
    entropy_rule = next(r for r in RULES if r.id == "R-ENTROPY")
    assert shannon_bits(entropy_rule.examples[0].planted) >= ENTROPY_MIN_BITS


def test_hex_digest_like_and_uuid_tokens_redacted_is_accepted_tradeoff() -> None:
    # Over-redaction is harmless; this pins the documented trade-off.
    out = rendered(("a3f1c9e07b2d4e6f8a1b3c5d7e9f0a2b4c6d8e0f",))
    assert "<redacted:" in out
