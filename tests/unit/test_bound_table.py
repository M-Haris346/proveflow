"""THE false-compromise bound table (tools/count_t4_space.py SCAN_LOCATIONS, Phase 3b) says
exactly what the oracle scans: measured, not asserted, over every location x needle kind x
encoding of the one matcher list."""

from __future__ import annotations

from pathlib import Path

from boundchecks import assert_scan_locations_match_the_bound_table, load_counter


def test_scan_locations_match_the_bound_table(tmp_path: Path) -> None:
    assert_scan_locations_match_the_bound_table(tmp_path, load_counter())
