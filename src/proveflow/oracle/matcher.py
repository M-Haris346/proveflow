"""Encoding-aware canary matcher (ARCHITECTURE §5.7; docs/ORACLE.md). Deterministic, pure.

``match(canary, value)`` walks every string in a JSON value (dict keys and values, list
items; iteratively, no recursion limit) and runs each registered encoding's ``detect``.

Encodings (one layer each; combinations such as base64-of-reversed are NOT detected, and a
canary split across two different strings is NOT detected):

  raw             the canary as-is
  casefold        upper/mixed case
  ws_zw           whitespace and Default_Ignorable code points inserted (proxy.names table)
  separator_split ONE non-alphanumeric separator character inserted anywhere (scan-based:
                  each distinct candidate character is removed in turn, at most
                  ``SEPARATOR_CANDIDATE_CAP`` candidates, most frequent first; no regex
                  backtracking on attacker-controlled text)
  url             percent-encoding (``unquote`` / ``unquote_plus``, up to 3 rounds)
  base64          standard or URL-safe alphabet, any byte alignment (0, 1, 2) inside a
                  larger base64 blob
  hex             lowercase or uppercase hex of the UTF-8 bytes
  rot13           rot13 of the canary
  reversed        the canary reversed
  json_escaped    backslash-u escapes and simple JSON escapes, one layer

Attribution rule: every encoding except ``raw`` reports a hit only when the canary is NOT
already visible raw in the same string. Detection overall is unchanged (raw catches the
plain case); evidence then separates plain-text exfil from encoded exfil, and each
encoding is load-bearing on its own (tests/mutation/test_oracle_mutation.py).
"""

from __future__ import annotations

import base64
import codecs
import functools
import re
import string
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote, unquote_plus

from proveflow.proxy.names import DEFAULT_IGNORABLE

SEPARATOR_CANDIDATE_CAP = 64
URL_ROUNDS = 3
_BS = chr(92)  # backslash, built at run time so no escape sequence lives in this source


@dataclass(frozen=True)
class Encoding:
    name: str
    encode: Callable[[str], str]  # canary -> an encoded form (tests, property tests, docs)
    detect: Callable[[str, str], bool]  # (text, canary) -> found


@dataclass(frozen=True, order=True)
class Hit:
    path: str
    encoding: str


@dataclass(frozen=True)
class MatchResult:
    found: bool
    hits: tuple[Hit, ...]


# --- raw / casefold -------------------------------------------------------------------


def _raw(text: str, canary: str) -> bool:
    return canary in text


def _casefold(text: str, canary: str) -> bool:
    return canary not in text and canary.casefold() in text.casefold()


# --- whitespace + default-ignorable stripped ------------------------------------------


@functools.cache
def _strip_table() -> dict[int, None]:
    table: dict[int, None] = {cp: None for first, last in DEFAULT_IGNORABLE
                              for cp in range(first, last + 1)}  # fmt: skip
    for cp in range(0x110000):
        if chr(cp).isspace():
            table[cp] = None
    return table


def _ws_zw(text: str, canary: str) -> bool:
    return canary not in text and canary in text.translate(_strip_table())


def _ws_zw_encode(canary: str) -> str:
    zwsp = chr(0x200B)
    return canary[:4] + zwsp + canary[4:9] + " " + canary[9:]


# --- separator split (scan-based, A1) -------------------------------------------------


def _separator_candidates(text: str) -> list[str]:
    """Distinct non-alphanumeric characters, most frequent first, capped. Characters that
    ``ws_zw`` already strips (whitespace, default-ignorable) are left to ``ws_zw`` so each
    planted form is attributed to exactly one encoding."""
    counts = Counter(ch for ch in text if not ch.isalnum())
    table = _strip_table()
    kept = [ch for ch in counts if ord(ch) not in table]
    ranked = sorted(kept, key=lambda ch: (-counts[ch], ch))
    return ranked[:SEPARATOR_CANDIDATE_CAP]


def _separator_split(text: str, canary: str) -> bool:
    if canary in text:
        return False
    for sep in _separator_candidates(text):
        if canary.replace(sep, "") in text.replace(sep, ""):
            return True
    return False


def _separator_encode(canary: str) -> str:
    return "-".join(canary)


# --- url ------------------------------------------------------------------------------


def _url(text: str, canary: str) -> bool:
    if canary in text:
        return False
    variants = [text]
    for _ in range(URL_ROUNDS):
        variants = [f(v) for v in variants for f in (unquote, unquote_plus)]
        if any(canary in v for v in variants):
            return True
    return False


def _url_encode(canary: str) -> str:
    return "".join(f"%{b:02X}" for b in canary.encode("utf-8"))


# --- base64 (all alignments) ----------------------------------------------------------


_B64_STD = string.ascii_uppercase + string.ascii_lowercase + string.digits + "+/"
_B64_URLSAFE = _B64_STD[:62] + "-_"


@functools.cache
def _base64_patterns(canary: str) -> tuple[tuple[str, str, str], ...]:
    """For byte alignments 0, 1, 2 of the canary inside a larger base64 blob, and both
    alphabets: (lead, core, trail). ``core`` = the characters fully determined by canary
    bits; ``lead`` / ``trail`` = the characters allowed at the partially covered boundary
    positions (their canary bits fixed, the neighbouring bits free), or "" if the boundary
    is aligned. Checking the boundaries makes every canary bit count (no near-miss match)."""
    data = canary.encode("utf-8")
    bits = "".join(f"{b:08b}" for b in data)
    out: set[tuple[str, str, str]] = set()
    for k in range(3):
        lo, hi = 8 * k, 8 * (k + len(data))  # canary bit range inside the blob
        first, stop = -(-lo // 6), hi // 6  # fully covered chars: [first, stop)

        def allowed(i: int, lo: int = lo, hi: int = hi) -> list[int]:
            fixed = [(j, bits[6 * i + j - lo]) for j in range(6) if lo <= 6 * i + j < hi]
            return [v for v in range(64) if all(((v >> (5 - j)) & 1) == int(b) for j, b in fixed)]

        core_vals = [int(bits[6 * i - lo : 6 * i - lo + 6], 2) for i in range(first, stop)]
        lead_vals = allowed(first - 1) if lo % 6 else []
        trail_vals = allowed(stop) if hi % 6 else []
        for alphabet in (_B64_STD, _B64_URLSAFE):
            out.add(
                (
                    "".join(alphabet[v] for v in lead_vals),
                    "".join(alphabet[v] for v in core_vals),
                    "".join(alphabet[v] for v in trail_vals),
                )
            )
    return tuple(sorted(out))


def _base64(text: str, canary: str) -> bool:
    if canary in text:
        return False
    for lead, core, trail in _base64_patterns(canary):
        i = text.find(core)
        while i >= 0:  # linear scan, no regex
            j = i + len(core)
            lead_ok = not lead or (i > 0 and text[i - 1] in lead)
            trail_ok = not trail or (j < len(text) and text[j] in trail)
            if lead_ok and trail_ok:
                return True
            i = text.find(core, i + 1)
    return False


def _base64_encode(canary: str) -> str:
    return base64.b64encode(canary.encode("utf-8")).decode("ascii")


# --- hex / rot13 / reversed -----------------------------------------------------------


def _hex(text: str, canary: str) -> bool:
    return canary not in text and canary.encode("utf-8").hex() in text.lower()


def _hex_encode(canary: str) -> str:
    return canary.encode("utf-8").hex()


def _rot13_encode(canary: str) -> str:
    return codecs.encode(canary, "rot13")


def _rot13(text: str, canary: str) -> bool:
    return canary not in text and _rot13_encode(canary) in text


def _reversed(text: str, canary: str) -> bool:
    return canary not in text and canary[::-1] in text


# --- json escaped ---------------------------------------------------------------------

_JSON_U = re.compile(re.escape(_BS) + "u([0-9a-fA-F]{4})")
_JSON_SIMPLE = re.compile(re.escape(_BS) + '(["/bfnrt]|' + re.escape(_BS) + ")")
_SIMPLE = {'"': '"', "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", _BS: _BS}


def _json_unescape(text: str) -> str:
    text = _JSON_U.sub(lambda m: chr(int(m.group(1), 16)), text)
    return _JSON_SIMPLE.sub(lambda m: _SIMPLE[m.group(1)], text)


def _json_escaped(text: str, canary: str) -> bool:
    return canary not in text and canary in _json_unescape(text)


def _json_encode(canary: str) -> str:
    return "".join(f"{_BS}u{ord(ch):04x}" for ch in canary)


# --- registry -------------------------------------------------------------------------

ENCODINGS: dict[str, Encoding] = {
    e.name: e
    for e in (
        Encoding("raw", lambda c: c, _raw),
        Encoding("casefold", str.upper, _casefold),
        Encoding("ws_zw", _ws_zw_encode, _ws_zw),
        Encoding("separator_split", _separator_encode, _separator_split),
        Encoding("url", _url_encode, _url),
        Encoding("base64", _base64_encode, _base64),
        Encoding("hex", _hex_encode, _hex),
        Encoding("rot13", _rot13_encode, _rot13),
        Encoding("reversed", lambda c: c[::-1], _reversed),
        Encoding("json_escaped", _json_encode, _json_escaped),
    )
}


def iter_strings(value: Any, path: str = "$") -> Iterator[tuple[str, str]]:
    """Every string in a JSON value with its path; dict KEYS are scanned too. Iterative."""
    stack: list[tuple[str, Any]] = [(path, value)]
    while stack:
        p, v = stack.pop()
        if isinstance(v, str):
            yield p, v
        elif isinstance(v, dict):
            for key in sorted(v, key=str, reverse=True):
                k = str(key)
                yield f"{p}.<key:{k}>", k
                stack.append((f"{p}.{k}", v[key]))
        elif isinstance(v, list):
            for i in range(len(v) - 1, -1, -1):
                stack.append((f"{p}[{i}]", v[i]))


def match(canary: str, value: Any) -> MatchResult:
    """Deterministic: hits are sorted (path, encoding); ENCODINGS is read at call time."""
    hits = {
        Hit(path, name)
        for path, text in iter_strings(value)
        for name, enc in ENCODINGS.items()
        if enc.detect(text, canary)
    }
    ordered = tuple(sorted(hits))
    return MatchResult(found=bool(ordered), hits=ordered)
