"""runner/transcript.py: chain, canonical form, refusals, cassette references (D2, D3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from oraclechecks import write_cassette
from proveflow.proxy.cassette import canonical, digest
from proveflow.runner.transcript import (
    TranscriptError,
    TranscriptWriter,
    is_complete_transcript,
    load_transcript,
    verify_cassette_refs,
)
from proxyhelpers import proxy_twin_root  # noqa: F401
from runnerchecks import (
    assert_altered_record_breaks_the_chain,
    assert_mismatched_cassette_ref_refused,
    write_minimal_transcript,
)


def test_round_trip_chain_and_no_wall_clock(tmp_path: Path) -> None:
    path = write_minimal_transcript(tmp_path / "t.jsonl")
    events = load_transcript(path)
    assert [e.kind for e in events] == [
        "trial_start", "llm_request", "llm_response", "final_answer", "trial_end",
    ]  # fmt: skip
    assert is_complete_transcript(events)
    for line in path.read_bytes().splitlines():
        body = json.loads(line)
        assert canonical(body).encode() == line and digest(body) == body["sha256"]
        assert not {"ts", "time", "timestamp", "elapsed_ms", "latency_ms"} & set(body)


def test_altered_request_or_response_breaks_the_chain(tmp_path: Path) -> None:
    assert_altered_record_breaks_the_chain(tmp_path)


def test_mismatched_cassette_reference_is_refused(tmp_path: Path) -> None:
    cassette = write_cassette(tmp_path / "pftwin-x.cassette.jsonl", [])
    assert_mismatched_cassette_ref_refused(tmp_path, cassette)


def test_missing_or_incomplete_cassette_is_refused(tmp_path: Path) -> None:
    ref = {"session_id": "s", "server": "x", "file": "absent.jsonl", "final_sha256": "a" * 64}
    t = write_minimal_transcript(tmp_path / "t.jsonl", cassettes=[ref])
    with pytest.raises(TranscriptError, match=r"absent.jsonl"):
        verify_cassette_refs(load_transcript(t), tmp_path)
    inc = write_cassette(tmp_path / "inc.jsonl", [], end=False)
    from proveflow.proxy.cassette import load_cassette

    ref2 = {**ref, "file": inc.name, "final_sha256": load_cassette(inc)[-1].sha256}
    t2 = write_minimal_transcript(tmp_path / "t2.jsonl", cassettes=[ref2])
    with pytest.raises(TranscriptError, match="not complete"):
        verify_cassette_refs(load_transcript(t2), tmp_path)


@pytest.mark.parametrize("file", ["../x.jsonl", "C:/abs.jsonl", "/abs.jsonl", "sub/x.jsonl", ""])
def test_cassette_ref_is_a_basename(tmp_path: Path, file: str) -> None:
    ref = {"session_id": "s", "server": "x", "file": file, "final_sha256": "a" * 64}
    with pytest.raises(ValueError, match="file"):
        write_minimal_transcript(tmp_path / "t.jsonl", cassettes=[ref])


def test_incomplete_transcript_is_refused_for_refs(tmp_path: Path) -> None:
    w = TranscriptWriter(tmp_path / "t.jsonl")
    w.emit("final_answer", text="x")
    w.close()
    with pytest.raises(TranscriptError, match="not complete"):
        verify_cassette_refs(load_transcript(tmp_path / "t.jsonl"), tmp_path)


def test_writer_refuses_overwrite_and_reserved_fields(tmp_path: Path) -> None:
    path = write_minimal_transcript(tmp_path / "t.jsonl")
    with pytest.raises(FileExistsError):
        TranscriptWriter(path)
    w = TranscriptWriter(tmp_path / "u.jsonl")
    with pytest.raises(TranscriptError, match="reserved"):
        w.emit("final_answer", text="x", seq=5)
    w.close()


def test_loader_refusals(tmp_path: Path) -> None:
    path = write_minimal_transcript(tmp_path / "t.jsonl")
    lines = path.read_bytes().splitlines()
    cases = {
        "dropped": lines[:1] + lines[2:],
        "noncanonical": [lines[0].replace(b",", b", ", 1), *lines[1:]],
        "schema": [lines[0].replace(b'"schema_version":1', b'"schema_version":2'), *lines[1:]],
    }
    for name, content in cases.items():
        bad = tmp_path / f"{name}.jsonl"
        bad.write_bytes(b"\n".join(content) + b"\n")
        with pytest.raises(TranscriptError):
            load_transcript(bad)
