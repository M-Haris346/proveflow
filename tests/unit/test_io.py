"""Config file loading: every failure mode is a status, never a crash or a leak."""

from __future__ import annotations

from pathlib import Path

import pytest

from fakehome import FIXTURES
from proveflow.core.client import ConfigStatus
from proveflow.discover import _io
from proveflow.discover._io import load_json_config


def test_not_found(tmp_path: Path) -> None:
    assert load_json_config(tmp_path / "nope.json").status is ConfigStatus.NOT_FOUND


def test_directory(tmp_path: Path) -> None:
    res = load_json_config(tmp_path)
    assert res.status is ConfigStatus.UNREADABLE


def test_empty() -> None:
    res = load_json_config(FIXTURES / "empty.json")
    assert res.status is ConfigStatus.PARSE_ERROR
    assert res.detail == "empty file"


def test_malformed_detail_has_position_but_no_content() -> None:
    res = load_json_config(FIXTURES / "malformed.json")
    assert res.status is ConfigStatus.PARSE_ERROR
    assert res.detail is not None
    assert "line" in res.detail
    assert "PLANTED" not in res.detail


def test_top_level_array() -> None:
    res = load_json_config(FIXTURES / "toplevel_array.json")
    assert res.status is ConfigStatus.PARSE_ERROR
    assert "expected object" in (res.detail or "")


def test_utf8_bom_accepted(tmp_path: Path) -> None:
    p = tmp_path / "bom.json"
    p.write_bytes(b"\xef\xbb\xbf" + b'{"mcpServers": {}}')
    assert load_json_config(p).status is ConfigStatus.FOUND


def test_invalid_utf8(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_bytes(b'{"a": "\xff\xfePLANTEDbytes"}')
    res = load_json_config(p)
    assert res.status is ConfigStatus.PARSE_ERROR
    assert "PLANTED" not in (res.detail or "")


def test_too_large(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_io, "MAX_CONFIG_BYTES", 10)
    p = tmp_path / "big.json"
    p.write_text('{"mcpServers": {"a": {"command": "x"}}}', encoding="utf-8")
    res = load_json_config(p)
    assert res.status is ConfigStatus.PARSE_ERROR
    assert "larger than" in (res.detail or "")


def test_unreadable_simulated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """SIMULATED: a real unreadable file on Windows needs ACL changes; we inject the
    PermissionError the OS would raise."""
    p = tmp_path / "locked.json"
    p.write_text("{}", encoding="utf-8")

    def deny(path: Path) -> bytes:
        raise PermissionError(13, "Permission denied", str(path))

    monkeypatch.setattr(_io, "read_bytes", deny)
    res = load_json_config(p)
    assert res.status is ConfigStatus.UNREADABLE
    assert res.detail == "PermissionError: Permission denied"


def test_deep_nesting_does_not_crash(tmp_path: Path) -> None:
    p = tmp_path / "deep.json"
    p.write_text("[" * 100_000 + "]" * 100_000, encoding="utf-8")
    res = load_json_config(p)
    assert res.status is ConfigStatus.PARSE_ERROR
