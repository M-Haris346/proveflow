"""Mutations of the tool-call id echo check (ruling after the first real run, Groq
2026-11-21). The request-side tool-call id paths are excluded from the D7 shape scan; that
exclusion is safe only because the echo check proves each value there is an id a provider
response minted earlier. Each mutant below weakens that proof, and a named check must fail.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import runnerchecks
from runnerchecks import (
    TOOL_CALL_ID_ECHOES,
    TOOL_CALL_ID_MINTED,
    UNMINTED,
    _values_at,
    assert_an_echo_before_its_mint_is_refused,
    assert_every_constructed_exclusion_is_echo_checked,
    assert_unminted_tool_call_id_is_caught,
)


def test_without_the_echo_check_an_unminted_id_passes_the_evidence_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutant: no echo check. The crafted request echoes an id no response minted, D7 skips
    both request paths, so the evidence check passes it and the named check fails."""
    assert_unminted_tool_call_id_is_caught(tmp_path / "ok")
    monkeypatch.setattr(runnerchecks, "tool_call_id_echo_problems", lambda events: [])
    with pytest.raises(AssertionError, match=f"request {UNMINTED}"):
        assert_unminted_tool_call_id_is_caught(tmp_path / "mut")


def _order_blind(events: list[Any]) -> list[str]:
    """Mutant: an id minted ANYWHERE in the transcript counts, not only earlier."""
    minted = {v for e in events for k, x in e.model_dump(mode="json").items()
              for _, v in _values_at(x, (e.kind, k), frozenset({TOOL_CALL_ID_MINTED}))}  # fmt: skip
    return [f"seq {e.seq}: request {UNMINTED}" for e in events
            for k, x in e.model_dump(mode="json").items()
            for _, v in _values_at(x, (e.kind, k), TOOL_CALL_ID_ECHOES)
            if v not in minted]  # fmt: skip


def test_an_order_blind_echo_check_fails_the_named_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert_an_echo_before_its_mint_is_refused(tmp_path / "ok")
    monkeypatch.setattr(runnerchecks, "tool_call_id_echo_problems", _order_blind)
    with pytest.raises(AssertionError, match="before the response that minted it"):
        assert_an_echo_before_its_mint_is_refused(tmp_path / "mut")


def test_an_excluded_request_path_the_echo_check_skips_fails_the_named_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mutant: tool_call_id stays excluded from D7 but drops out of the echo check."""
    assert_every_constructed_exclusion_is_echo_checked()
    dropped = ("llm_request", "body", "messages", runnerchecks.LIST, "tool_call_id")
    monkeypatch.setattr(runnerchecks, "TOOL_CALL_ID_ECHOES", TOOL_CALL_ID_ECHOES - {dropped})
    with pytest.raises(AssertionError, match="not echo-checked"):
        assert_every_constructed_exclusion_is_echo_checked()
