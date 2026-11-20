"""Shared test guards: tests never read the real host environment."""

from __future__ import annotations

import pytest

from netguard import install as install_network_guard
from proveflow.discover.hostenv import HostEnv
from widths import TEST_COLUMNS


def _refuse() -> HostEnv:
    raise AssertionError("tests must not read the real host environment; use fakehome")


@pytest.fixture(autouse=True)
def _no_real_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(HostEnv, "current", staticmethod(_refuse))
    # One pinned render width, far above any line a test can produce (tests/widths.py):
    # rendered-text assertions must not depend on the path, the terminal or the width.
    monkeypatch.setenv("COLUMNS", str(TEST_COLUMNS))
    # No test reaches the network, and so none can call an LLM provider (tests/netguard.py).
    install_network_guard(monkeypatch)
