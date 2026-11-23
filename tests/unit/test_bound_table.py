"""THE false-compromise bound table (tools/count_t4_space.py SCAN_LOCATIONS, Phase 3b) says
exactly what the oracle scans: measured, not asserted, over every location x needle kind x
encoding of the one matcher list."""

from __future__ import annotations

from pathlib import Path

from boundchecks import (
    assert_scan_locations_match_the_bound_table,
    assert_sighting_location_matches_the_table,
    load_counter,
)


def test_scan_locations_match_the_bound_table(tmp_path: Path) -> None:
    assert_scan_locations_match_the_bound_table(tmp_path, load_counter())


def test_sighting_location_matches_the_table(tmp_path: Path) -> None:
    """Phase 6: the sighting's row (outside SCAN_LOCATIONS, no threshold) is measured too,
    because it is now the only quantity that justifies the action target's 16-hex length."""
    assert_sighting_location_matches_the_table(tmp_path, load_counter())
