"""R2 and R3 driven by a PAYLOAD (Phase 6, step 1): the same rules as Phase 3b, now woken by
an instantiated corpus payload with a goal clause, on real in-process proxy sessions, and the
injected text rebuilt from the cassette alone."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from corpuschecks import (
    assert_injected_text_rebuilds_from_the_cassette,
    assert_payload_driven_r2_fires,
    assert_payload_driven_r3_fires_and_quoting_does_not,
    assert_r2_quoting_is_not_a_hit,
    assert_the_sandbox_never_echoes_sink_arguments,
    delivered_exfil_canary_counts,
)
from proxyhelpers import proxy_twin_root  # noqa: F401


def test_injected_text_rebuilds_from_the_cassette(tmp_path: Path, proxy_twin_root: Any) -> None:  # noqa: F811
    assert_injected_text_rebuilds_from_the_cassette(tmp_path)


def test_payload_driven_r2_fires(tmp_path: Path, proxy_twin_root: Any) -> None:  # noqa: F811
    assert_payload_driven_r2_fires(tmp_path)


def test_payload_driven_r3_fires_and_quoting_does_not(
    tmp_path: Path,
    proxy_twin_root: Any,  # noqa: F811
) -> None:
    assert_payload_driven_r3_fires_and_quoting_does_not(tmp_path)


def test_r2_quoting_is_not_a_hit(tmp_path: Path, proxy_twin_root: Any) -> None:  # noqa: F811
    """Holds for goal arg "body" (the default case) and "to", since the split (Phase 6)."""
    assert_r2_quoting_is_not_a_hit(tmp_path)


def test_the_sandbox_never_echoes_sink_arguments(tmp_path: Path, proxy_twin_root: Any) -> None:  # noqa: F811
    assert_the_sandbox_never_echoes_sink_arguments(tmp_path)


def test_the_delivered_exfil_canary_count(tmp_path: Path, proxy_twin_root: Any) -> None:  # noqa: F811
    """MEASURED (not a ruling): on an instantiated exfil attack, the canary occurs exactly
    ONCE in the tool result the agent received (the cassette's agent_response), for every
    carrier and both source tools; that one occurrence is the goal clause's (the payload
    carries no canary). Pinned so the reported number is reproducible by one command."""
    counts = delivered_exfil_canary_counts(tmp_path)
    assert len(counts) == 10 and set(counts.values()) == {1}, counts
