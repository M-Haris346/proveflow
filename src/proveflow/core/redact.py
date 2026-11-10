"""Redaction primitive. Security-critical.

A ``RedactedValue`` stores only a SHA-256 prefix and the original length —
the type makes it impossible to carry a raw secret into logs, cassettes,
reports, or LLM prompts. Build one with ``RedactedValue.from_secret`` and
discard the raw value immediately.
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
