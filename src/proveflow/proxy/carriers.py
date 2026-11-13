"""Carriers: embed an attack payload into a source tool's text result (D7). Pure.

Every function is deterministic and only APPENDS to the original text (except JSON_STRING
on a JSON object/array, which re-serializes the parsed value with the payload added).
Properties tested (tests/property/test_proxy_properties.py): a canary inside the payload
appears in the output exactly once more than in the input, for every carrier; non-JSON
carriers keep the original text as a prefix; JSON_STRING on an object/array yields valid
JSON whose injected value equals the payload. A JSON scalar or non-JSON text falls back
to PLAIN with ``json.dumps(payload)`` (documented limitation).
"""

from __future__ import annotations

import json
from typing import Any

from proveflow.core.attacks import Carrier

NOTE_KEY = "_note"


def plain(text: str, payload: str) -> str:
    return text + "\n\n" + payload


def html_comment(text: str, payload: str) -> str:
    return text + "\n<!-- " + payload.replace("--", "- -") + " -->"


def markdown(text: str, payload: str) -> str:
    return text + "\n\n> **Note:** " + payload


def code_comment(text: str, payload: str) -> str:
    return text + "\n```\n# " + payload.replace("\n", "\n# ") + "\n```"


def _free_key(obj: dict[str, Any]) -> str:
    if NOTE_KEY not in obj:
        return NOTE_KEY
    n = 2
    while f"{NOTE_KEY}_{n}" in obj:
        n += 1
    return f"{NOTE_KEY}_{n}"


def json_fallback(text: str, payload: str) -> str:
    """JSON_STRING on anything but a JSON object/array: PLAIN with the payload JSON-quoted."""
    return plain(text, json.dumps(payload, ensure_ascii=False))


def json_string(text: str, payload: str) -> str:
    try:
        value = json.loads(text)
    except (ValueError, RecursionError):
        value = None
    else:
        if isinstance(value, dict):
            value[_free_key(value)] = payload
            return json.dumps(value, sort_keys=False, ensure_ascii=False)
        if isinstance(value, list):
            value.append(payload)
            return json.dumps(value, sort_keys=False, ensure_ascii=False)
    return json_fallback(text, payload)  # module global: tests/mutation can break it alone


_CARRIERS = {
    Carrier.PLAIN: plain,
    Carrier.HTML_COMMENT: html_comment,
    Carrier.MARKDOWN: markdown,
    Carrier.CODE_COMMENT: code_comment,
    Carrier.JSON_STRING: json_string,
}


def apply_carrier(carrier: Carrier, text: str, payload: str) -> str:
    return _CARRIERS[carrier](text, payload)
