"""Scrub secrets out of anything a server sends back (THREAT_MODEL T11).

Two layers:
1. Verbatim: every raw LaunchSpec value (>= MIN_SCRUB_LEN chars) is replaced by its
   redacted marker wherever it appears.
2. Defense in depth: the free-text redaction rules (docs/REDACTION.md) are applied to tool
   names, descriptions, schema strings and stderr, so secrets proveflow never saw in the
   config (e.g. read from disk by the server) are caught when they look like secrets.

Not caught (stated in T11): encoded echoes of a value (base64, hex, reversed, split),
short values (< MIN_SCRUB_LEN), and secrets that match no pattern. Layer 2 can also
redact harmless text after words like ``Token``/``Basic``; the count is reported as
``pattern_redactions`` so eval data alterations are visible.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from proveflow.core.redact import RedactedValue
from proveflow.core.redact_rules import redact_text


def scrub_text(text: str, secrets: Sequence[str]) -> str:
    for secret in secrets:  # longest first (LaunchSpec.secret_values sorts)
        if secret and secret in text:
            text = text.replace(secret, str(RedactedValue.from_secret(secret)))
    return text


@dataclass
class Scrubber:
    secrets: Sequence[str]
    pattern_redactions: int = field(default=0)

    def text(self, value: str) -> str:
        verbatim = scrub_text(value, self.secrets)
        red = redact_text(verbatim)
        self.pattern_redactions += sum(isinstance(p, RedactedValue) for p in red.parts)
        return str(red)

    def json(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, list):
            return [self.json(v) for v in value]
        if isinstance(value, dict):
            return {self.text(str(k)): self.json(v) for k, v in value.items()}
        return value


def scrub_json(value: Any, secrets: Sequence[str]) -> Any:
    """Verbatim-only scrub of a JSON value (kept for callers that need no patterns)."""
    if isinstance(value, str):
        return scrub_text(value, secrets)
    if isinstance(value, list):
        return [scrub_json(v, secrets) for v in value]
    if isinstance(value, dict):
        return {scrub_text(str(k), secrets): scrub_json(v, secrets) for k, v in value.items()}
    return value


def scrub_stderr(raw: bytes, secrets: Sequence[str], limit: int = 2000) -> str:
    text = raw.decode("utf-8", errors="replace")
    text = scrub_text(text, secrets)
    text = "\n".join(str(redact_text(line)) for line in text.splitlines())
    return text[-limit:]
