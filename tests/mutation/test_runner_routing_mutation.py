"""Mutation: routing that ignores cross-server collisions -> the NAMED collision check fails."""

from __future__ import annotations

import pytest

from proveflow.runner import routing
from runnerchecks import assert_cross_server_collision_refused


def test_ignoring_collisions_fails_the_named_check(monkeypatch: pytest.MonkeyPatch) -> None:
    assert_cross_server_collision_refused()
    monkeypatch.setattr(routing, "colliding_names", lambda names: frozenset())
    with pytest.raises(AssertionError, match="was routed"):
        assert_cross_server_collision_refused()
