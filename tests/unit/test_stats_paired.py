"""The exact McNemar test (Phase 8) against hand-computed reference values."""

from __future__ import annotations

import verifychecks


def test_mcnemar_matches_hand_values() -> None:
    verifychecks.assert_mcnemar_matches_hand_values()
