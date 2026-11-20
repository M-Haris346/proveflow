"""Mutation: a pass-through network guard -> the NAMED guard check fails (it sees the
resolver reached; the resolver is a spy, so no real lookup happens)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from netguard import assert_provider_hosts_are_refused


def _pass_through(underlying: Callable[..., Any]) -> Callable[..., Any]:
    return underlying


def test_a_pass_through_guard_fails_the_named_check() -> None:
    assert_provider_hosts_are_refused()
    with pytest.raises(AssertionError, match=r"let api.groq.com through|reached the resolver"):
        assert_provider_hosts_are_refused(_pass_through)
