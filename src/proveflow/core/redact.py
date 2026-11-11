"""Redaction primitives. Security-critical.

A ``RedactedValue`` stores only a SHA-256 prefix and the original length —
the type makes it impossible to carry a raw secret into logs, cassettes,
reports, or LLM prompts. Build one with ``RedactedValue.from_secret`` and
discard the raw value immediately.

A ``RedactedText`` is a string in which every secret segment exists only as a
``RedactedValue`` (used for args, URLs, and commands, where most of the text
is harmless and only some segments are secret).
"""

from __future__ import annotations

import hashlib

from pydantic import Field

from proveflow.core._base import FrozenModel

SHA256_PREFIX_LEN = 12


class RedactedValue(FrozenModel):
    """Irreversible fingerprint of a secret: sha256 prefix + length, nothing else."""

    sha256_prefix: str = Field(pattern=rf"^[0-9a-f]{{{SHA256_PREFIX_LEN}}}$")
    length: int = Field(ge=0)

    @classmethod
    def from_secret(cls, secret: str) -> RedactedValue:
        digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()
        return cls(sha256_prefix=digest[:SHA256_PREFIX_LEN], length=len(secret))

    def __str__(self) -> str:
        return f"<redacted:sha256-{self.sha256_prefix}>"

    def __repr__(self) -> str:
        return str(self)


class RedactedText(FrozenModel):
    """Text whose secret segments are stored only as ``RedactedValue``."""

    parts: tuple[str | RedactedValue, ...] = ()

    @classmethod
    def plain(cls, text: str) -> RedactedText:
        """Wrap text known to contain no secret (e.g. built by proveflow itself)."""
        return cls(parts=(text,) if text else ())

    @property
    def is_redacted(self) -> bool:
        return any(isinstance(p, RedactedValue) for p in self.parts)

    def plain_segments(self) -> tuple[str, ...]:
        """Only the non-secret segments (used for role heuristics)."""
        return tuple(p for p in self.parts if isinstance(p, str))

    def __str__(self) -> str:
        return "".join(str(p) for p in self.parts)

    def __repr__(self) -> str:
        return f"RedactedText({str(self)!r})"
