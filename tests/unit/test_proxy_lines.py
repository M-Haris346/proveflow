"""L2: newline framing counts BYTES and scans only each new chunk."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from proveflow.proxy.lines import LineSplitter, LineTooLong


def test_multibyte_line_is_limited_in_bytes_not_chars() -> None:
    # "é" is 2 bytes in UTF-8: 5 chars = 10 bytes fits a 10-byte limit, 6 chars does not.
    ok = LineSplitter(10)
    assert ok.feed("ééééé\n".encode()) == ["ééééé".encode()]
    too_long = LineSplitter(10)
    with pytest.raises(LineTooLong):
        too_long.feed("éééééé\n".encode())  # 6 chars (< 10) but 12 bytes


def test_unfinished_tail_over_limit_is_refused() -> None:
    s = LineSplitter(8)
    s.feed(b"1234")
    s.feed(b"5678")
    with pytest.raises(LineTooLong):
        s.feed(b"9")


def test_tail_across_chunks() -> None:
    s = LineSplitter(100)
    assert s.feed(b'{"a":') == []
    assert s.feed(b' 1}\n{"b"') == [b'{"a": 1}']
    assert s.rest() == b'{"b"'
    assert s.feed(b": 2}\n\n") == [b'{"b": 2}', b""]


def test_line_at_exact_limit_is_allowed() -> None:
    s = LineSplitter(4)
    assert s.feed(b"abcd\n") == [b"abcd"]


@settings(max_examples=200, deadline=None)
@given(
    lines=st.lists(st.binary(max_size=40).map(lambda b: b.replace(b"\n", b"")), max_size=10),
    cuts=st.lists(st.integers(min_value=0, max_value=500), max_size=8),
)
def test_any_chunking_gives_the_same_lines(lines: list[bytes], cuts: list[int]) -> None:
    data = b"".join(line + b"\n" for line in lines)
    points = sorted({c % (len(data) + 1) for c in cuts})
    chunks = [data[a:b] for a, b in zip([0, *points], [*points, len(data)], strict=True)]
    s = LineSplitter(64)
    out: list[bytes] = []
    for chunk in chunks:
        out.extend(s.feed(chunk))
    assert out == lines
    assert s.rest() == b""
