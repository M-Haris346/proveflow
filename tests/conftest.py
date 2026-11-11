"""Shared test guards: tests never read the real host environment."""

from __future__ import annotations

import pytest

from proveflow.discover.hostenv import HostEnv


def _refuse() -> HostEnv:
    raise AssertionError("tests must not read the real host environment; use fakehome")


@pytest.fixture(autouse=True)
def _no_real_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(HostEnv, "current", staticmethod(_refuse))
    # Wide terminal so Rich never wraps a value across lines in output assertions.
    monkeypatch.setenv("COLUMNS", "400")
