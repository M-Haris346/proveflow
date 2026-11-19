"""Deterministic randomness for twin generation (R2). No stdlib ``random``.

``random.Random``'s output stream is not guaranteed stable across Python versions, and the
generator claims byte-identical regeneration. So: block ``i`` of the stream is
``sha256(seed || i.to_bytes(8, "big"))``; bytes are consumed in order. Integer draws use
rejection sampling (no modulo bias). ``derive(*labels)`` opens an independent sub-stream
(``sha256(seed || 0xff || label ...)``) so one tool's output does not depend on how many
draws another tool made.

``draw_hex(n)`` returns exactly n lowercase hex characters: a ``core.honey.HexSource``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import TypeVar

T = TypeVar("T")

_COUNTER_BYTES = 8
_DERIVE_TAG = b"\xff"


def _encode(label: str | bytes) -> bytes:
    raw = label if isinstance(label, bytes) else label.encode("utf-8")
    return len(raw).to_bytes(4, "big") + raw  # length-prefixed: no ambiguity between labels


class Rng:
    def __init__(self, seed: str | bytes) -> None:
        self._seed = hashlib.sha256(_encode(seed)).digest()
        self._counter = 0
        self._buffer = b""

    def derive(self, *labels: str) -> Rng:
        """An independent sub-stream; does not consume from this one."""
        child = Rng(b"")
        child._seed = hashlib.sha256(
            self._seed + _DERIVE_TAG + b"".join(_encode(lbl) for lbl in labels)
        ).digest()
        return child

    def read(self, n: int) -> bytes:
        if n < 0:
            raise ValueError("n must be >= 0")
        while len(self._buffer) < n:
            block = hashlib.sha256(
                self._seed + self._counter.to_bytes(_COUNTER_BYTES, "big")
            ).digest()
            self._counter += 1
            self._buffer += block
        out, self._buffer = self._buffer[:n], self._buffer[n:]
        return out

    def draw_hex(self, n: int) -> str:
        """Exactly n lowercase hex characters (a ``core.honey.HexSource``)."""
        return self.read((n + 1) // 2).hex()[:n]

    def randbelow(self, n: int) -> int:
        """Uniform integer in [0, n) by rejection sampling (no modulo bias)."""
        if n <= 0:
            raise ValueError("n must be > 0")
        nbytes = max(1, (n - 1).bit_length() + 7 >> 3)
        limit = (256**nbytes // n) * n
        while True:
            value = int.from_bytes(self.read(nbytes), "big")
            if value < limit:
                return value % n

    def randrange(self, start: int, stop: int) -> int:
        if stop <= start:
            raise ValueError("empty range")
        return start + self.randbelow(stop - start)

    def choice(self, seq: Sequence[T]) -> T:
        if not seq:
            raise ValueError("choice from an empty sequence")
        return seq[self.randbelow(len(seq))]

    def shuffled(self, seq: Sequence[T]) -> list[T]:
        """A new list in a uniformly random order (Fisher-Yates); ``seq`` is not modified."""
        out = list(seq)
        for i in range(len(out) - 1, 0, -1):
            j = self.randbelow(i + 1)
            out[i], out[j] = out[j], out[i]
        return out
