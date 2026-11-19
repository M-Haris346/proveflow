"""Count dual-role (untrusted_source + sink) tools in the stored labeled sets (ADR-007).

Usage: uv run python tools/count_dual_role.py

Reads only committed files (no network):
* data/eval/roles/split/labels_dev.csv   (60 tools; author-reviewed LLM pre-labels, ``_a``)
* data/eval/roles/split/labels_test.csv  (40 tools; ``_final``)
* data/eval/roles/heldout_v2/labels_heldout_v2.csv (55 tools; single blind human, ``_final``)
and prints how many the v2 classifier (``flows.roles.classify_tool``) and the human labels
mark untrusted_source + sink, and the overlap.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from proveflow.flows.roles import classify_tool

ROOT = Path(__file__).resolve().parents[1] / "data" / "eval" / "roles"
SETS = (
    (ROOT / "split" / "labels_dev.csv", "_a"),
    (ROOT / "split" / "labels_test.csv", "_final"),
    (ROOT / "heldout_v2" / "labels_heldout_v2.csv", "_final"),
)
DUAL = {"untrusted_source", "sink"}


def counts() -> dict[str, object]:
    labeled: list[tuple[str, str, bool, bool]] = []
    for path, suffix in SETS:
        with path.open(encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                human = r["untrusted_source" + suffix] == "yes" and r["sink" + suffix] == "yes"
                spec = classify_tool(
                    r["tool_name"],
                    r.get("server_id") or "eval",
                    r["description"],
                    json.loads(r["input_schema"]),
                )
                v2 = DUAL <= {ev.role.value for ev in spec.roles}
                labeled.append((r["tool_id"], r["tool_name"], human, v2))
    return {
        "labeled": len(labeled),
        "v2": sorted(n for _, n, _, v in labeled if v),
        "human": sorted(n for _, n, h, _ in labeled if h),
        "both": sorted(n for _, n, h, v in labeled if h and v),
        "v2_only": sorted(n for _, n, h, v in labeled if v and not h),
        "human_only": sorted(n for _, n, h, v in labeled if h and not v),
        "union": sorted(n for _, n, h, v in labeled if h or v),
    }


def main() -> None:
    c = counts()
    n = c["labeled"]
    both, union = c["both"], c["union"]
    if not isinstance(both, list) or not isinstance(union, list):  # pragma: no cover
        raise TypeError("counts")
    print(f"jaccard: {len(both)}/{len(union)} = {len(both) / len(union):.4f}")
    for key in ("v2", "human", "both", "v2_only", "human_only"):
        names = c[key]
        if not isinstance(names, list):  # pragma: no cover - counts() always returns lists
            raise TypeError(key)
        print(f"{key:>5}: {len(names)}/{n}  {', '.join(names)}")


if __name__ == "__main__":
    main()
