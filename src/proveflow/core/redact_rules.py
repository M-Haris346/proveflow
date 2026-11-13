"""Pattern-based redaction for args, URLs, commands, and paths. Security-critical.

Env and header values are always redacted *completely* (see ``_common.py``); the
rules here cover free text where only some segments are secret. Every rule is
documented in docs/REDACTION.md with its examples. Each rule carries a positive
example (with the planted secret that must disappear) and negative examples
(args that must stay untouched); ``tests/mutation`` removes each rule in turn and
asserts its positive example then leaks.

Known limitation (stated in docs/REDACTION.md and THREAT_MODEL T2): a short,
low-entropy, unflagged positional secret (``myapp hunter2pass``) is NOT caught.

Lives in ``core`` (moved from ``discover`` in Phase 2, unchanged) so ``proveflow.proxy`` can
use it without importing ``proveflow.discover``; ``proveflow.discover.redact_rules`` is an
alias of this module.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Literal

from proveflow.core.redact import RedactedText, RedactedValue

# Words that mark a flag / parameter / variable name as secret-bearing.
# A regex of secret-bearing *names*, not a password:
_SENSITIVE_NAME_WORDS = (
    r"(?:api[_-]?key|apikey|access[_-]?key|private[_-]?key|key|token|secret|"
    r"password|passwd|pwd|passphrase|auth|credential|bearer|session|cookie|signature|sig)"
)
_NAME_CHARS = r"[A-Za-z0-9_.-]"

ENTROPY_MIN_LEN = 32
ENTROPY_MIN_BITS = 3.5


@dataclass(frozen=True)
class Example:
    """``args`` as they appear in a config; ``planted`` must not survive redaction."""

    args: tuple[str, ...]
    planted: str


@dataclass(frozen=True)
class Rule:
    """One redaction rule.

    ``kind="span"``: ``pattern`` group ``group`` of every match in a single string is
    redacted (optionally filtered by ``predicate``). ``kind="next"``: a string that
    fully matches ``pattern`` is a secret flag, and the *following* arg is redacted.
    """

    id: str
    description: str
    kind: Literal["span", "next"]
    pattern: re.Pattern[str]
    examples: tuple[Example, ...]
    negatives: tuple[tuple[str, ...], ...] = ()
    group: str | int = "v"
    predicate: Callable[[str], bool] | None = field(default=None, compare=False)


def shannon_bits(text: str) -> float:
    """Shannon entropy of ``text`` in bits per character."""
    if not text:
        return 0.0
    counts = Counter(text)
    n = len(text)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def _looks_random(token: str) -> bool:
    has_digit = any(ch.isdigit() for ch in token)
    has_alpha = any(ch.isalpha() for ch in token)
    return has_digit and has_alpha and shannon_bits(token) >= ENTROPY_MIN_BITS


RULES: tuple[Rule, ...] = (
    Rule(
        id="R-ARG-EQ",
        description="`--<name>=<value>` where <name> contains a secret word",
        kind="span",
        pattern=re.compile(
            rf"^-{{1,2}}{_NAME_CHARS}*{_SENSITIVE_NAME_WORDS}{_NAME_CHARS}*=(?P<v>.+)$",
            re.IGNORECASE,
        ),
        examples=(Example(("--api-key=PLANTEDargeq0001",), "PLANTEDargeq0001"),),
        negatives=(("--port=8080",), ("--verbose",)),
    ),
    Rule(
        id="R-ARG-NEXT",
        description="secret flag as its own arg (`--token X`): the next arg is redacted",
        kind="next",
        pattern=re.compile(
            rf"^-{{1,2}}{_NAME_CHARS}*{_SENSITIVE_NAME_WORDS}{_NAME_CHARS}*$", re.IGNORECASE
        ),
        examples=(Example(("--token", "PLANTEDargnext01"), "PLANTEDargnext01"),),
        negatives=(("--port", "8080"), ("--token", "--verbose")),
    ),
    Rule(
        id="R-ARG-ENVSTYLE",
        description="`NAME=value` arg where NAME contains a secret word (e.g. `-e GITHUB_TOKEN=x`)",
        kind="span",
        pattern=re.compile(
            rf"^[A-Za-z_][A-Za-z0-9_]*{_SENSITIVE_NAME_WORDS}[A-Za-z0-9_]*=(?P<v>.+)$",
            re.IGNORECASE,
        ),
        examples=(Example(("-e", "GITHUB_TOKEN=PLANTEDenvstyle1"), "PLANTEDenvstyle1"),),
        negatives=(("-e", "LOG_LEVEL=debug"),),
    ),
    Rule(
        id="R-ARG-HEADER",
        description="header-style arg `<Name>: <value>` where Name contains a secret word",
        kind="span",
        pattern=re.compile(
            rf"^[A-Za-z0-9_-]*{_SENSITIVE_NAME_WORDS}[A-Za-z0-9_-]*\s*:\s*(?P<v>.+)$", re.IGNORECASE
        ),
        examples=(Example(("--header", "X-Api-Key: PLANTEDheader001"), "PLANTEDheader001"),),
        negatives=(("--header", "Accept: application/json"),),
    ),
    Rule(
        id="R-URL-USERINFO",
        description="userinfo in a URL (`scheme://user:pass@host`)",
        kind="span",
        pattern=re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://(?P<v>[^/@\s?#]+)@"),
        examples=(Example(("https://admin:PLANTEDuserinfo@db.example.com/x",), "PLANTEDuserinfo"),),
        negatives=(("https://example.com/path",),),
    ),
    Rule(
        id="R-URL-QUERY",
        description="URL query parameter whose name contains a secret word (`?token=`)",
        kind="span",
        pattern=re.compile(
            rf"[?&;][^=&#\s]*{_SENSITIVE_NAME_WORDS}[^=&#\s]*=(?P<v>[^&#\s]+)", re.IGNORECASE
        ),
        examples=(
            Example(("https://mcp.example.com/mcp?api_key=PLANTEDquery0001",), "PLANTEDquery0001"),
        ),
        negatives=(("https://mcp.example.com/mcp?region=eu&page=2",),),
    ),
    Rule(
        id="R-BEARER",
        description="`Bearer <token>` / `Basic <token>` / `Token <token>` anywhere",
        kind="span",
        pattern=re.compile(r"\b(?:Bearer|Basic|Token)\s+(?P<v>[A-Za-z0-9._~+/=-]+)", re.IGNORECASE),
        examples=(Example(("Bearer PLANTEDbearer0001",), "PLANTEDbearer0001"),),
        negatives=(("bearer",), ("Basic",)),
    ),
    Rule(
        id="R-ENTROPY",
        description=(
            f"standalone token of >= {ENTROPY_MIN_LEN} chars from [A-Za-z0-9_-+/=] containing "
            f"letters and digits with Shannon entropy >= {ENTROPY_MIN_BITS} bits/char"
        ),
        kind="span",
        pattern=re.compile(rf"(?<![A-Za-z0-9_+/=-])[A-Za-z0-9_+/=-]{{{ENTROPY_MIN_LEN},}}"),
        group=0,
        predicate=_looks_random,
        examples=(
            Example(
                ("serve", "PLANTEDx9Kq2mZ7vR4tY8wB3nL6pD1sF5hJ0"),
                "PLANTEDx9Kq2mZ7vR4tY8wB3nL6pD1sF5hJ0",
            ),
        ),
        negatives=(
            ("-y", "@modelcontextprotocol/server-filesystem"),
            ("C:\\Users\\example\\Desktop",),
            ("mcp-server-fetch==2026.1.14",),
        ),
    ),
)


def _rules(rules: Sequence[Rule] | None) -> Sequence[Rule]:
    # Read the module global at call time so the mutation tests can monkeypatch it.
    return RULES if rules is None else rules


def secret_spans(text: str, rules: Sequence[Rule] | None = None) -> list[tuple[int, int]]:
    """Merged, sorted ``(start, end)`` spans of ``text`` that span-rules mark secret."""
    spans: list[tuple[int, int]] = []
    for rule in _rules(rules):
        if rule.kind != "span":
            continue
        for match in rule.pattern.finditer(text):
            start, end = match.span(rule.group)
            if start == end:
                continue
            if rule.predicate is not None and not rule.predicate(text[start:end]):
                continue
            spans.append((start, end))
    spans.sort()
    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def redact_text(text: str, rules: Sequence[Rule] | None = None) -> RedactedText:
    """Redact the secret segments of one string."""
    parts: list[str | RedactedValue] = []
    cursor = 0
    for start, end in secret_spans(text, rules):
        if start > cursor:
            parts.append(text[cursor:start])
        parts.append(RedactedValue.from_secret(text[start:end]))
        cursor = end
    if cursor < len(text):
        parts.append(text[cursor:])
    return RedactedText(parts=tuple(parts))


def next_arg_secret_indexes(args: Sequence[str], rules: Sequence[Rule] | None = None) -> set[int]:
    """Indexes of args that are values of a preceding secret flag (``--token X``)."""
    flag_rules = [r for r in _rules(rules) if r.kind == "next"]
    out: set[int] = set()
    for i, arg in enumerate(args[:-1]):
        nxt = args[i + 1]
        if nxt.startswith("-"):
            continue
        if any(r.pattern.fullmatch(arg) for r in flag_rules):
            out.add(i + 1)
    return out


def redact_args(
    args: Sequence[str], rules: Sequence[Rule] | None = None
) -> tuple[RedactedText, ...]:
    """Redact a full argv list (handles flag/value pairs across args)."""
    whole = next_arg_secret_indexes(args, rules)
    out: list[RedactedText] = []
    for i, arg in enumerate(args):
        if i in whole:
            out.append(RedactedText(parts=(RedactedValue.from_secret(arg),)))
        else:
            out.append(redact_text(arg, rules))
    return tuple(out)


def raw_secret_segments(args: Sequence[str], rules: Sequence[Rule] | None = None) -> list[str]:
    """The raw segments the rules would redact. Used ONLY by the leak checker and tests,
    to know what must not appear in outputs; never logged or rendered."""
    whole = next_arg_secret_indexes(args, rules)
    segs: list[str] = []
    for i, arg in enumerate(args):
        if i in whole:
            segs.append(arg)
        else:
            segs.extend(arg[s:e] for s, e in secret_spans(arg, rules))
    return segs
