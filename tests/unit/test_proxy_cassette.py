"""Cassette (D9): write/read, hash chain, tamper, size limits, truncation, no overwrite."""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest

from proveflow.introspect.limits import MAX_LINE
from proveflow.proxy import cassette
from proveflow.proxy.cassette import (
    GENESIS,
    CassetteError,
    CassetteWriter,
    canonical,
    digest,
    load_cassette,
)


def write_sample(path: Path) -> None:
    w = CassetteWriter(path)
    w.emit(
        "session_start",
        session_id="s",
        proveflow_version="0",
        upstream={"name": "twin"},
        policy={},
        attack=None,
        limits={},
    )
    w.emit("agent_request", message={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    w.emit("sandboxed_call", tool="send_email", arguments={"to": "ü"}, sandbox_id="sbx_0001",
           reason="policy_deny")  # fmt: skip
    w.emit("error", error_kind="upstream_timeout", detail="slow")
    w.emit(
        "session_end",
        reason="agent_closed",
        tool_calls=1,
        forwarded_calls=0,
        sandboxed_calls=1,
        upstream_stderr="",
        upstream_stderr_truncated=False,
    )
    w.close()


def test_round_trip_and_chain(tmp_path: Path) -> None:
    path = tmp_path / "c.jsonl"
    write_sample(path)
    events = load_cassette(path)
    assert [e.seq for e in events] == [0, 1, 2, 3, 4]
    assert [e.kind for e in events] == [
        "session_start",
        "agent_request",
        "sandboxed_call",
        "error",
        "session_end",
    ]
    assert events[0].prev_sha256 == GENESIS
    for prev, cur in itertools.pairwise(events):
        assert cur.prev_sha256 == prev.sha256
    lines = path.read_bytes().splitlines()
    for line, event in zip(lines, events, strict=True):
        body = json.loads(line)
        assert digest(body) == event.sha256
        assert canonical(body).encode() == line
        assert "ts" not in body and "time" not in body  # no wall clock


def test_writer_refuses_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "c.jsonl"
    path.write_text("", encoding="utf-8")
    with pytest.raises(FileExistsError):
        CassetteWriter(path)


def test_writer_refuses_unknown_kind_and_reserved_fields(tmp_path: Path) -> None:
    w = CassetteWriter(tmp_path / "c.jsonl")
    with pytest.raises(ValueError):
        w.emit("not_a_kind", foo=1)
    with pytest.raises(CassetteError, match="reserved"):
        w.emit("error", error_kind="x", detail="y", seq=5)
    w.close()
    assert (tmp_path / "c.jsonl").read_bytes() == b""  # nothing invalid was written


@pytest.mark.parametrize("offset", [10, 60, 200, -30])
def test_tamper_one_byte_is_rejected(tmp_path: Path, offset: int) -> None:
    path = tmp_path / "c.jsonl"
    write_sample(path)
    data = bytearray(path.read_bytes())
    lines = data.split(b"\n")
    target = lines[2]  # the sandboxed_call line
    pos = offset % len(target)
    # flip one byte to another printable, JSON-legal-ish character
    target[pos] = ord("x") if target[pos] != ord("x") else ord("y")
    lines[2] = target
    path.write_bytes(b"\n".join(lines))
    with pytest.raises(CassetteError):
        load_cassette(path)


def test_tamper_with_recomputed_hash_breaks_the_chain(tmp_path: Path) -> None:
    path = tmp_path / "c.jsonl"
    write_sample(path)
    lines = path.read_bytes().splitlines()
    body = json.loads(lines[2])
    body["arguments"] = {"to": "attacker"}
    body["sha256"] = digest(body)  # attacker fixes this line's own hash
    lines[2] = canonical(body).encode()
    path.write_bytes(b"\n".join(lines) + b"\n")
    with pytest.raises(CassetteError, match="hash chain broken"):
        load_cassette(path)


def test_deleted_line_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "c.jsonl"
    write_sample(path)
    lines = path.read_bytes().splitlines()
    del lines[1]
    path.write_bytes(b"\n".join(lines) + b"\n")
    with pytest.raises(CassetteError, match="seq"):
        load_cassette(path)


def test_non_canonical_whitespace_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "c.jsonl"
    write_sample(path)
    lines = path.read_bytes().splitlines()
    lines[0] = lines[0].replace(b'":', b'": ', 1)
    path.write_bytes(b"\n".join(lines) + b"\n")
    with pytest.raises(CassetteError, match="canonical"):
        load_cassette(path)


def test_extra_field_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "c.jsonl"
    write_sample(path)
    lines = path.read_bytes().splitlines()
    body = json.loads(lines[0])
    body["extra"] = 1
    body["sha256"] = digest(body)
    lines[0] = canonical(body).encode()
    path.write_bytes(b"\n".join(lines) + b"\n")
    with pytest.raises(CassetteError, match="invalid event"):
        load_cassette(path)


def test_limits_default_to_spec() -> None:
    assert cassette.MAX_CASSETTE == 64 * 1024 * 1024
    assert cassette.TEXT_CAP == 1024 * 1024
    assert MAX_LINE == 16 * 1024 * 1024
    assert load_cassette.__kwdefaults__ == {
        "max_line": MAX_LINE,
        "max_bytes": cassette.MAX_CASSETTE,
    }


def test_oversized_line_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "c.jsonl"
    write_sample(path)
    longest = max(len(x) for x in path.read_bytes().splitlines())
    load_cassette(path, max_line=longest)  # exactly at the limit: fine
    with pytest.raises(CassetteError, match="longer than"):
        load_cassette(path, max_line=longest - 1)


def test_oversized_line_without_newline_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "c.jsonl"
    path.write_bytes(b"x" * 200)
    with pytest.raises(CassetteError, match="longer than"):
        load_cassette(path, max_line=100)


def test_oversized_file_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "c.jsonl"
    write_sample(path)
    size = path.stat().st_size
    load_cassette(path, max_bytes=size)
    with pytest.raises(CassetteError, match="larger than"):
        load_cassette(path, max_bytes=size - 1)


def test_missing_trailing_newline_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "c.jsonl"
    write_sample(path)
    path.write_bytes(path.read_bytes().rstrip(b"\n"))
    with pytest.raises(CassetteError, match="newline"):
        load_cassette(path)


def test_large_values_are_truncated_and_flagged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cassette, "TEXT_CAP", 50)
    path = tmp_path / "c.jsonl"
    w = CassetteWriter(path)
    small = w.emit("error", error_kind="k", detail="short")
    big = w.emit("upstream_response", tool="t", result={"content": "x" * 500})
    w.close()
    assert small.truncated is False
    assert big.truncated is True
    assert isinstance(big.result, str) and len(big.result.encode()) <= 50  # type: ignore[union-attr]
    load_cassette(path)


def test_truncation_never_splits_utf8(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cassette, "TEXT_CAP", 7)
    w = CassetteWriter(tmp_path / "c.jsonl")
    event = w.emit("error", error_kind="k", detail="üüüüüü")
    w.close()
    assert event.detail == "üüü"  # type: ignore[union-attr]
    assert event.truncated is True
