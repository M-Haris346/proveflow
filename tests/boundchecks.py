"""Named checks for THE false-compromise bound table (tools/count_t4_space.py SCAN_LOCATIONS,
Phase 3b): the threshold holds at every scanned-string location, and the table says exactly
what the oracle scans there. Shared by unit and mutation tests."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
COUNTER_PATH = ROOT / "tools" / "count_t4_space.py"


def load_counter() -> ModuleType:
    spec = importlib.util.spec_from_file_location("count_t4_space", COUNTER_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def assert_every_location_under_the_threshold(counter: ModuleType, n: int, h: int) -> None:
    """Named check (R-N1b, on the claimed quantity): every scanned-string location's bound on a
    false COMPROMISE, through ``bound_terms`` from the table, is below the limit."""
    for location in counter.SCAN_LOCATIONS:
        b = counter.location_bound(n, h, location)
        if not b < counter.threshold(n):
            raise AssertionError(
                f"false-compromise bound over the R-N1b limit at {location}: {b:.4e} >= "
                f"{counter.threshold(n):.4e} (n={n}, H={h})"
            )


def measured_scan_map(tmp_path: Path) -> dict[str, dict[str, set[str]]]:
    """What the oracle ACTUALLY does: for each location, each needle kind and each encoding of
    the one matcher list, plant that encoding of the trial's value there and record whether
    the trial is COMPROMISED. location -> kind -> encodings that raise a compromise."""
    from oraclechecks import (
        ACTION_TARGET,
        ENCODINGS_AT_IMPORT,
        HONEY,
        HONEY_BODY,
        action_attack_body,
        evaluate_trial_of,
        write_cassette,
    )
    from proveflow.oracle.rules import evaluate_trial
    from proxyhelpers import CANARY, MARKER

    values = {"canary": CANARY, "honey": HONEY.value, "action_target": ACTION_TARGET,
              "marker": MARKER}  # fmt: skip
    out: dict[str, dict[str, set[str]]] = {}
    counter = 0
    for location in ("sink_argument", "goal_argument", "final_answer"):
        out[location] = {}
        for kind, value in values.items():
            attack: Any = "default" if kind == "marker" else action_attack_body()
            fired: set[str] = set()
            for name, enc in ENCODINGS_AT_IMPORT.items():
                counter += 1
                planted = f"x {enc.encode(value)} y"
                path = tmp_path / f"m{counter}.jsonl"
                if location == "final_answer":
                    write_cassette(path, [], attack=attack, honey=[HONEY_BODY], session_id="s")
                    end = {"seq": 1, "kind": "trial_end", "reason": "final_answer"}
                    transcript = [{"seq": 0, "kind": "final_answer", "text": planted}, end]
                    f = evaluate_trial([path], trial_id="t", transcript=transcript)
                else:
                    tool, arg = (("send_email", "to") if location == "goal_argument"
                                 else ("post_message", "body"))  # fmt: skip
                    call = {"tool": tool, "arguments": {arg: planted}}
                    write_cassette(path, [call], attack=attack, honey=[HONEY_BODY], session_id="s")
                    f = evaluate_trial_of([path])
                if f.compromised:
                    fired.add(name)
            if fired:
                out[location][kind] = fired
    return out


def assert_scan_locations_match_the_bound_table(tmp_path: Path, counter: ModuleType) -> None:
    """Named check: THE bound table says exactly what the oracle scans. A rule that starts
    scanning a needle kind at a location (or with more encodings) without the table being
    updated fails here, so the threshold test can never again measure a smaller set of terms
    than the oracle actually uses."""
    expected = {loc: {kind: set(encs) for kind, encs in kinds.items()}
                for loc, (_, kinds) in counter.SCAN_LOCATIONS.items()}  # fmt: skip
    measured = measured_scan_map(tmp_path)
    if measured != expected:
        diff = {loc: (measured.get(loc), expected.get(loc)) for loc in expected
                if measured.get(loc) != expected.get(loc)}  # fmt: skip
        raise AssertionError(f"the bound table does not match what the oracle scans: {diff}")
