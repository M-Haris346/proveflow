"""ProxySession / ProxyLimits validation and load_session (schema 2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from proveflow.proxy.session import (
    CALL_TIMEOUT_S,
    MAX_AGENT_MESSAGES,
    MAX_CALLS,
    MAX_CASSETTE_BYTES,
    MAX_UPSTREAM_MESSAGES,
    SESSION_TIMEOUT_S,
    ProxyLimits,
    ProxySession,
    SessionFileError,
    load_session,
)
from proxyhelpers import (  # noqa: F401
    make_attack,
    make_session,
    proxy_twin_root,
    twin_specs,
    write_session,
)


def test_defaults_are_the_limits() -> None:
    limits = ProxyLimits()
    assert (limits.call_timeout_s, limits.session_timeout_s, limits.max_calls) == (30, 600, 200)
    assert (CALL_TIMEOUT_S, SESSION_TIMEOUT_S, MAX_CALLS) == (30, 600, 200)
    assert (limits.max_agent_messages, limits.max_upstream_messages) == (1000, 2000)
    assert limits.max_cassette_bytes == MAX_CASSETTE_BYTES == 32 * 1024 * 1024
    assert (MAX_AGENT_MESSAGES, MAX_UPSTREAM_MESSAGES) == (1000, 2000)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"call_timeout_s": 31},
        {"session_timeout_s": 601},
        {"max_calls": 201},
        {"call_timeout_s": 0},
        {"session_timeout_s": -1},
        {"max_calls": 0},
        {"max_agent_messages": 1001},
        {"max_upstream_messages": 2001},
        {"max_cassette_bytes": 32 * 1024 * 1024 + 1},
    ],
)
def test_limits_can_only_be_tightened(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValidationError):
        ProxyLimits(**kwargs)  # type: ignore[arg-type]


def test_small_limits_allowed() -> None:
    assert ProxyLimits(call_timeout_s=1, session_timeout_s=2, max_calls=3).max_calls == 3


def test_round_trip(tmp_path: Path) -> None:
    session = make_session(tmp_path, attack=make_attack())
    path = write_session(tmp_path, session)
    assert load_session(path) == session


def test_policy_key_is_rejected(tmp_path: Path) -> None:
    """H1: a session cannot carry allow/deny decisions, only classified tools."""
    data = json.loads(make_session(tmp_path).model_dump_json())
    data["policy"] = {"send_email": {"forward": True, "inject": False}}
    path = tmp_path / "s.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValidationError, match="policy"):
        load_session(path)


def test_policy_is_computed_from_tools(tmp_path: Path) -> None:
    session = make_session(tmp_path)
    assert session.policy["send_email"].forward is False
    assert session.policy["query_db"].forward is True
    assert "policy" not in json.loads(session.model_dump_json())


def test_duplicate_tool_names_rejected(tmp_path: Path) -> None:
    data = json.loads(make_session(tmp_path).model_dump_json())
    data["tools"].append(data["tools"][0])
    with pytest.raises(ValidationError, match="duplicate"):
        ProxySession.model_validate(data)


def test_twin_sha256_required_and_hex(tmp_path: Path) -> None:
    data = json.loads(make_session(tmp_path).model_dump_json())
    data["twin_sha256"] = "not-a-hash"
    with pytest.raises(ValidationError):
        ProxySession.model_validate(data)
    del data["twin_sha256"]
    with pytest.raises(ValidationError):
        ProxySession.model_validate(data)


def test_extra_fields_rejected(tmp_path: Path) -> None:
    data = json.loads(make_session(tmp_path).model_dump_json())
    data["sandbox"] = False  # there is no switch; an attempt must not be silently ignored
    with pytest.raises(ValidationError):
        ProxySession.model_validate(data)


@pytest.mark.parametrize("version", [1, 2, 4])
def test_schema_version_must_be_3(tmp_path: Path, version: int) -> None:
    """Schema 3 (Phase 4, honey). Schemas 1 and 2 are refused, as is any future one."""
    data = json.loads(make_session(tmp_path).model_dump_json())
    data["schema_version"] = version
    with pytest.raises(ValidationError):
        ProxySession.model_validate(data)


def test_relative_cassette_path_rejected(tmp_path: Path) -> None:
    data = json.loads(make_session(tmp_path).model_dump_json())
    data["cassette_path"] = "cassette.jsonl"
    with pytest.raises(ValidationError, match="absolute"):
        ProxySession.model_validate(data)


def test_bad_canary_rejected(tmp_path: Path) -> None:
    data = json.loads(make_session(tmp_path, attack=make_attack()).model_dump_json())
    data["attack"]["canary"] = "cnry_NOTHEX000000"
    with pytest.raises(ValidationError):
        ProxySession.model_validate(data)


def test_non_twin_upstream_rejected_in_session_file(tmp_path: Path) -> None:
    data = json.loads(make_session(tmp_path).model_dump_json())
    data["upstream"]["argv"] = ["npx", "-y", "some-server"]
    path = tmp_path / "s.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValidationError, match=r"sys\.executable"):
        load_session(path)


def test_existing_cassette_is_not_overwritten(tmp_path: Path) -> None:
    session = make_session(tmp_path)
    session.cassette_path.write_text("keep", encoding="utf-8")
    with pytest.raises(SessionFileError, match="already exists"):
        load_session(write_session(tmp_path, session))
    assert session.cassette_path.read_text(encoding="utf-8") == "keep"


def test_oversized_session_file_rejected(tmp_path: Path) -> None:
    path = tmp_path / "s.json"
    path.write_bytes(b" " * (1024 * 1024 + 1))
    with pytest.raises(SessionFileError, match="larger"):
        load_session(path)


def test_session_id_pattern(tmp_path: Path) -> None:
    data = json.loads(make_session(tmp_path).model_dump_json())
    data["session_id"] = "../escape"
    with pytest.raises(ValidationError):
        ProxySession.model_validate(data)
    assert twin_specs()
