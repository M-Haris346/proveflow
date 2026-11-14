"""Newline-delimited framing with a BYTE limit (L2).

``LineSplitter.feed(chunk)`` returns the complete lines in ``chunk`` (without ``\\n``) and
keeps the unfinished tail. Only the NEW chunk is scanned for ``\\n`` (no re-split of the
buffered tail: linear time even for a line near the limit). A line, finished or not, longer
than ``max_line`` bytes raises ``LineTooLong``; the caller fails closed.
"""

from __future__ import annotations


class LineTooLong(ValueError):
    pass


class LineSplitter:
    def __init__(self, max_line: int) -> None:
        self._max = max_line
        self._tail = bytearray()

    def feed(self, chunk: bytes) -> list[bytes]:
        lines: list[bytes] = []
        start = 0
        while True:
            end = chunk.find(b"\n", start)
            if end < 0:
                self._tail += chunk[start:]
                if len(self._tail) > self._max:
                    raise LineTooLong(f"line longer than {self._max} bytes")
                return lines
            if len(self._tail) + (end - start) > self._max:
                raise LineTooLong(f"line longer than {self._max} bytes")
            lines.append(bytes(self._tail) + chunk[start:end])
            self._tail.clear()
            start = end + 1

    def rest(self) -> bytes:
        """The unfinished tail (e.g. at EOF)."""
        return bytes(self._tail)
