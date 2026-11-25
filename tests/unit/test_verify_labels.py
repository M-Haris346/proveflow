"""The paired-verify label rule (Haris's ruling, 2026-11-26), from crafted counts: only FLOW
BLOCKED is a verified fix; DELIVERY REMOVED and CAPABILITY REMOVED are not, whatever the rate."""

from __future__ import annotations

import verifychecks


def test_the_label_rule_matches_the_ruling() -> None:
    verifychecks.assert_the_label_rule_matches_the_ruling()
