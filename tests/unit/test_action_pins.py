"""The GitHub Action (Phase 9): every action reference pinned by commit SHA; the scan is
--no-launch and --fail-on (tests/shipchecks.py)."""

from __future__ import annotations

import shipchecks


def test_the_action_is_pinned_static_and_gating() -> None:
    shipchecks.assert_the_action_is_pinned_static_and_gating()
