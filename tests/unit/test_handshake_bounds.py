"""The handshake deadline's pure parts (Phase 7.0): the stage literal, the bounds, schema 4."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from handshakechecks import (
    HANG_MAKERS,
    assert_a_v3_cassette_is_refused,
    assert_the_harness_bound_exceeds_the_proxy_bound_for_a_range,
)
from proveflow.proxy import cassette, server
from proveflow.proxy.session import HANDSHAKE_TIMEOUT_S, SESSION_TIMEOUT_S, ProxyLimits


def test_the_stages_come_from_one_literal() -> None:
    assert cassette.HANDSHAKE_STAGES == ("spawn", "initialize", "tools_list")
    assert set(HANG_MAKERS) == set(cassette.HANDSHAKE_STAGES)


def test_the_handshake_bound_is_separate_shorter_and_tighten_only() -> None:
    assert HANDSHAKE_TIMEOUT_S == 30.0 and HANDSHAKE_TIMEOUT_S < SESSION_TIMEOUT_S
    assert ProxyLimits().handshake_timeout_s == 30.0
    with pytest.raises(ValidationError):
        ProxyLimits(handshake_timeout_s=31.0)


def test_the_stage_deadline_never_outlives_the_session() -> None:
    assert server.handshake_deadline("initialize", 10.0, 100.0, 30.0) == 40.0
    assert server.handshake_deadline("initialize", 90.0, 100.0, 30.0) == 100.0
    assert server.handshake_deadline(None, 10.0, 100.0, 30.0) == 100.0


def test_the_harness_bound_exceeds_the_proxy_bound_for_a_range() -> None:
    assert_the_harness_bound_exceeds_the_proxy_bound_for_a_range()


def test_session_end_names_a_stage_iff_handshake_timeout() -> None:
    base = {"kind": "session_end", "seq": 1, "prev_sha256": "0" * 64, "sha256": "0" * 64,
            "tool_calls": 0, "forwarded_calls": 0, "sandboxed_calls": 0, "upstream_stderr": "",
            "upstream_stderr_truncated": False}  # fmt: skip
    cassette.SessionEnd.model_validate({**base, "reason": "handshake_timeout",
                                        "handshake_outstanding": "initialize"})  # fmt: skip
    cassette.SessionEnd.model_validate({**base, "reason": "agent_closed"})
    with pytest.raises(ValidationError, match="iff reason is handshake_timeout"):
        cassette.SessionEnd.model_validate({**base, "reason": "handshake_timeout"})
    with pytest.raises(ValidationError, match="iff reason is handshake_timeout"):
        cassette.SessionEnd.model_validate({**base, "reason": "session_timeout",
                                            "handshake_outstanding": "spawn"})  # fmt: skip
    with pytest.raises(ValidationError):  # a stage that is not in the literal
        cassette.SessionEnd.model_validate({**base, "reason": "handshake_timeout",
                                            "handshake_outstanding": "ready"})  # fmt: skip


def test_a_stage_event_carries_no_elapsed_time() -> None:
    """ADR-008: no wall-clock value in the hashed chain; the time goes to the timings sidecar."""
    assert set(cassette.HandshakeStage.model_fields) == {
        "schema_version", "seq", "prev_sha256", "sha256", "truncated", "kind", "stage", "status",
    }  # fmt: skip


def test_the_schema_is_4() -> None:
    assert cassette.SCHEMA_VERSION == 4


def test_a_v3_cassette_is_refused(tmp_path: Path) -> None:
    assert_a_v3_cassette_is_refused(tmp_path)
