"""Dev/test split of the collected eval tools (docs/eval/SERVERS.md §4b, approved 2026-11-12).

    python -m proveflow.eval.split --tools out/tools.jsonl [--tools pg.json ...] \\
        --out-dir data/eval/roles/split

Rules (fixed BEFORE any label exists):
- CAP = 15 tools per server. A server with more keeps a deterministic sample: servers in
  sorted id order, each server's sorted tool names, ``random.Random(SEED).sample(names, CAP)``
  from ONE generator seeded with SEED = 20261111. Capped-out tools are listed in split.json.
- Variant A grouping: servers whose tool-name sets have Jaccard similarity >= 0.3 are in the
  same group (union-find, transitive). Nothing else groups servers.
- Assignment: over all subsets of non-forced groups, choose the test set minimising
  |test_tools / total - 0.40| subject to: every test group <= 50% of test tools, >= 2 groups
  in test and in dev. Ties: lowest sha256 of the comma-joined sorted group ids. Forced-dev
  servers (default: pg-mcp-guard) never enter test.
- Outputs: split.json (all parameters, counts, shares, input sha256s), dev_tools.jsonl,
  test_tools.jsonl, labels_dev.csv, labels_test.csv. The test CSV has NO server id, NO
  proposal and NO classifier column (blind labeling, docs/eval/LABELING_GUIDE.md).

Input: collector JSONL (``proveflow.eval.collect``) and/or the pg-mcp-guard in-process JSON
(``scripts/eval_pg_mcp_guard_list_tools.py``). No network, no server is launched.

Held-out v2 (checkpoint 1c Stage D, docs/eval/SERVERS_V2.md):

    python -m proveflow.eval.split --heldout --tools out/v2/tools.jsonl \\
        --out-dir data/eval/roles/heldout_v2

Same code path as the v1 split (load_tools -> apply_cap -> _row/_csv with TEST_COLUMNS, rows
sorted by tool_id), CAP 15, seed HELDOUT_SEED = 20261201 (pre-registered in the Stage D
plan). No grouping or dev/test assignment: every kept tool is a held-out row. No extra
redaction here (as in v1): records were scrubbed at collection. Writes
labels_heldout_v2.csv (blind: TEST_COLUMNS, every label cell empty), heldout_tools.jsonl,
heldout.json, and metrics_runs.json with heldout_evaluations = 0 (created once, never reset).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import itertools
import json
import random
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.text import Text

from proveflow import __version__

SEED = 20261111
CAP = 15
JACCARD_THRESHOLD = 0.3
TEST_SHARE_TARGET = 0.40
MAX_GROUP_SHARE = 0.50
FORCED_DEV_DEFAULT = ("pg-mcp-guard",)
ROLES = ("untrusted_source", "private_data", "sink")
HELDOUT_SEED = 20261201
HELDOUT_CSV = "labels_heldout_v2.csv"
HELDOUT_COUNTER_KEY = "heldout_evaluations"

DEV_COLUMNS = [
    "tool_id", "server_id", "tool_name", "description", "input_schema",
    *(f"{r}_a" for r in ROLES), "uncertain_a", "note_a", "labeler_a",
    *(f"proposal_{r}" for r in ROLES), "matched_proposal",
]  # fmt: skip
TEST_COLUMNS = [
    "tool_id", "tool_name", "description", "input_schema",
    *(f"{r}_a" for r in ROLES), "uncertain_a", "note_a", "labeler_a",
    *(f"{r}_b" for r in ROLES), "uncertain_b", "note_b", "labeler_b",
    *(f"{r}_final" for r in ROLES), "resolution_note",
]  # fmt: skip


class SplitError(RuntimeError):
    pass


@dataclass(frozen=True)
class Tool:
    server_id: str
    source: str
    name: str
    description: str
    input_schema: dict[str, Any]
    record: dict[str, Any] = field(compare=False, hash=False)

    @property
    def tool_id(self) -> str:
        digest = hashlib.sha256(f"{self.server_id}\x00{self.name}".encode()).hexdigest()
        return "t-" + digest[:12]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_tools(paths: Sequence[Path]) -> list[Tool]:
    tools: dict[tuple[str, str], Tool] = {}
    for path in paths:
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".jsonl":
            records = [json.loads(line) for line in text.splitlines() if line.strip()]
        else:
            data = json.loads(text)
            if "tools" not in data or "source" not in data:
                raise SplitError(f"{path}: not a collector JSONL or pg-mcp-guard JSON")
            records = [
                {
                    "server_id": data["source"],
                    "tool_name": t["name"],
                    "description": t.get("description") or "",
                    "input_schema": t.get("input_schema") or {},
                    "provenance": {
                        "source": "own",
                        "collected_by": data.get("provenance"),
                        "commit": data.get("commit"),
                    },
                }
                for t in data["tools"]
            ]
        for r in records:
            key = (r["server_id"], r["tool_name"])
            if key in tools:
                raise SplitError(f"duplicate tool {key} across inputs")
            tools[key] = Tool(
                server_id=r["server_id"],
                source=str((r.get("provenance") or {}).get("source", "unknown")),
                name=r["tool_name"],
                description=r.get("description") or "",
                input_schema=r.get("input_schema") or {},
                record=r,
            )
    return [tools[k] for k in sorted(tools)]


def apply_cap(
    tools: Sequence[Tool], cap: int = CAP, seed: int = SEED
) -> tuple[list[Tool], dict[str, list[str]]]:
    rng = random.Random(seed)  # noqa: S311 - reproducible sampling, not security
    by_server: dict[str, list[Tool]] = {}
    for t in tools:
        by_server.setdefault(t.server_id, []).append(t)
    kept: list[Tool] = []
    capped_out: dict[str, list[str]] = {}
    for sid in sorted(by_server):
        group = sorted(by_server[sid], key=lambda t: t.name)
        if len(group) > cap:
            names = rng.sample([t.name for t in group], cap)
            keep = set(names)
            capped_out[sid] = sorted(t.name for t in group if t.name not in keep)
            group = [t for t in group if t.name in keep]
        kept.extend(group)
    return kept, capped_out


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def group_servers(
    names_by_server: dict[str, set[str]], threshold: float = JACCARD_THRESHOLD
) -> dict[str, str]:
    """server_id -> group id (the sorted-first server of its group)."""
    parent = {s: s for s in names_by_server}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    servers = sorted(names_by_server)
    for a, b in itertools.combinations(servers, 2):
        if jaccard(names_by_server[a], names_by_server[b]) >= threshold:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)
    return {s: find(s) for s in servers}


def assign(group_sizes: dict[str, int], forced_dev: set[str]) -> tuple[list[str], dict[str, Any]]:
    """Return (test group ids, feasibility info). Raises SplitError if infeasible."""
    total = sum(group_sizes.values())
    free = sorted(g for g in group_sizes if g not in forced_dev)
    best: tuple[tuple[float, str], tuple[str, ...]] | None = None
    candidates = 0
    for r in range(2, len(free) + 1):
        for test in itertools.combinations(free, r):
            dev = [g for g in group_sizes if g not in test]
            if len(dev) < 2:
                continue
            t = sum(group_sizes[g] for g in test)
            if t == 0 or max(group_sizes[g] for g in test) > MAX_GROUP_SHARE * t:
                continue
            candidates += 1
            key = (
                abs(t / total - TEST_SHARE_TARGET),
                hashlib.sha256(",".join(test).encode()).hexdigest(),
            )
            if best is None or key < best[0]:
                best = (key, test)
    if best is None:
        raise SplitError(
            f"no split satisfies the rule (groups={group_sizes}, forced dev={sorted(forced_dev)})"
        )
    test_groups = list(best[1])
    t = sum(group_sizes[g] for g in test_groups)
    dev_groups = [g for g in group_sizes if g not in test_groups]
    d = total - t
    info = {
        "feasible_subsets": candidates,
        "test_tools": t,
        "dev_tools": d,
        "test_share": round(t / total, 4),
        "max_group_share_test": round(max(group_sizes[g] for g in test_groups) / t, 4),
        "max_group_share_dev": round(max(group_sizes[g] for g in dev_groups) / d, 4) if d else None,
    }
    return test_groups, info


def _csv(rows: list[dict[str, str]], columns: list[str]) -> str:
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({c: row.get(c, "") for c in columns})
    return buf.getvalue()


def _row(t: Tool, *, dev: bool) -> dict[str, str]:
    row = {
        "tool_id": t.tool_id,
        "tool_name": t.name,
        "description": t.description,
        "input_schema": json.dumps(t.input_schema, sort_keys=True, ensure_ascii=False),
    }
    if dev:
        row["server_id"] = t.server_id
    return row


def make_split(
    inputs: Sequence[Path], out_dir: Path, forced_dev: Sequence[str] = FORCED_DEV_DEFAULT
) -> dict[str, Any]:
    tools = load_tools(inputs)
    if not tools:
        raise SplitError("no tools in inputs")
    full_names: dict[str, set[str]] = {}
    for t in tools:
        full_names.setdefault(t.server_id, set()).add(t.name)
    kept, capped_out = apply_cap(tools)
    group_of = group_servers(full_names)
    sizes: dict[str, int] = {}
    for t in kept:
        sizes[group_of[t.server_id]] = sizes.get(group_of[t.server_id], 0) + 1
    forced_groups = {group_of[s] for s in forced_dev if s in group_of}
    test_groups, info = assign(sizes, forced_groups)
    test = [t for t in kept if group_of[t.server_id] in test_groups]
    dev = [t for t in kept if group_of[t.server_id] not in test_groups]

    out_dir.mkdir(parents=True, exist_ok=True)

    def jsonl(rows: list[Tool]) -> str:
        return "".join(
            json.dumps({**t.record, "tool_id": t.tool_id, "source": t.source}, sort_keys=True,
                       ensure_ascii=False) + "\n"
            for t in rows
        )  # fmt: skip

    files = {
        "dev_tools.jsonl": jsonl(dev),
        "test_tools.jsonl": jsonl(test),
        "labels_dev.csv": _csv([_row(t, dev=True) for t in dev], DEV_COLUMNS),
        "labels_test.csv": _csv([_row(t, dev=False) for t in sorted(test, key=lambda t: t.tool_id)],
                                TEST_COLUMNS),
    }  # fmt: skip
    for name, body in files.items():
        (out_dir / name).write_text(body, encoding="utf-8", newline="\n")
    groups: dict[str, list[str]] = {}
    for s, g in group_of.items():
        groups.setdefault(g, []).append(s)
    meta = {
        "schema_version": 1,
        "proveflow_version": __version__,
        "seed": SEED,
        "cap": CAP,
        "jaccard_threshold": JACCARD_THRESHOLD,
        "test_share_target": TEST_SHARE_TARGET,
        "max_group_share": MAX_GROUP_SHARE,
        "forced_dev": sorted(forced_dev),
        "inputs": {p.name: _sha256(p) for p in inputs},
        "groups": {g: sorted(v) for g, v in sorted(groups.items())},
        "group_sizes_after_cap": dict(sorted(sizes.items())),
        "test_groups": sorted(test_groups),
        "dev_groups": sorted(g for g in sizes if g not in test_groups),
        "capped_out": capped_out,
        "tools_before_cap": len(tools),
        "tools_after_cap": len(kept),
        "per_source": {
            split: dict(sorted(_count_by(rows, "source").items()))
            for split, rows in (("dev", dev), ("test", test))
        },
        **info,
    }
    (out_dir / "split.json").write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    return meta


LABEL_COLUMNS = [c for c in TEST_COLUMNS if c not in ("tool_id", "tool_name", "description",
                                                     "input_schema")]  # fmt: skip


def _has_any_label(csv_path: Path) -> bool:
    with csv_path.open(encoding="utf-8", newline="") as fh:
        return any(row.get(c, "").strip() for row in csv.DictReader(fh) for c in LABEL_COLUMNS)


def make_heldout(
    inputs: Sequence[Path], out_dir: Path, cap: int = CAP, seed: int = HELDOUT_SEED
) -> dict[str, Any]:
    """Blind held-out label sheet from collected tools (same rules as the v1 test CSV)."""
    tools = load_tools(inputs)
    if not tools:
        raise SplitError("no tools in inputs")
    csv_path = out_dir / HELDOUT_CSV
    if csv_path.exists() and _has_any_label(csv_path):
        raise SplitError(f"{csv_path} already contains labels; refusing to overwrite")
    kept, capped_out = apply_cap(tools, cap=cap, seed=seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    body = _csv([_row(t, dev=False) for t in sorted(kept, key=lambda t: t.tool_id)],
                TEST_COLUMNS)  # fmt: skip
    csv_path.write_text(body, encoding="utf-8", newline="\n")
    (out_dir / "heldout_tools.jsonl").write_text(
        "".join(
            json.dumps({**t.record, "tool_id": t.tool_id, "source": t.source}, sort_keys=True,
                       ensure_ascii=False) + "\n"
            for t in kept
        ),
        encoding="utf-8",
        newline="\n",
    )  # fmt: skip
    counter = out_dir / "metrics_runs.json"
    if not counter.exists():  # created once; never reset
        counter.write_text(
            json.dumps({HELDOUT_COUNTER_KEY: 0}, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
    categories = {
        t.server_id: str((t.record.get("provenance") or {}).get("category")) for t in kept
    }
    meta = {
        "schema_version": 1,
        "proveflow_version": __version__,
        "kind": "heldout_v2",
        "seed": seed,
        "cap": cap,
        "inputs": {p.name: _sha256(p) for p in inputs},
        "tools_before_cap": len(tools),
        "tools_after_cap": len(kept),
        "capped_out": capped_out,
        "per_server": dict(sorted(_count_by(kept, "server_id").items())),
        "per_category": dict(sorted(
            {c: sum(1 for t in kept if categories[t.server_id] == c)
             for c in set(categories.values())}.items())),
        "labels_csv": HELDOUT_CSV,
        "labels_csv_sha256": _sha256(csv_path),
    }  # fmt: skip
    (out_dir / "heldout.json").write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    return meta


def _count_by(rows: Sequence[Tool], attr: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for t in rows:
        key = str(getattr(t, attr))
        out[key] = out.get(key, 0) + 1
    return out


def main(argv: Sequence[str] | None = None) -> int:
    console = Console(stderr=True)
    parser = argparse.ArgumentParser(prog="python -m proveflow.eval.split")
    parser.add_argument("--tools", type=Path, action="append", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--force-dev", action="append", default=None)
    parser.add_argument("--heldout", action="store_true", help="build the blind held-out sheet")
    ns = parser.parse_args(argv)
    if ns.heldout:
        try:
            hm = make_heldout(ns.tools, ns.out_dir)
        except SplitError as exc:
            console.print(Text(f"error: {exc}", style="red"))
            return 1
        console.print(Text(f"held-out {hm['tools_after_cap']} rows (of {hm['tools_before_cap']}) "
                           f"-> {ns.out_dir / HELDOUT_CSV}"))  # fmt: skip
        return 0
    try:
        meta = make_split(
            ns.tools, ns.out_dir, tuple(ns.force_dev) if ns.force_dev else FORCED_DEV_DEFAULT
        )
    except SplitError as exc:
        console.print(Text(f"error: {exc}", style="red"))
        return 1
    console.print(Text(
        f"dev {meta['dev_tools']} / test {meta['test_tools']} tools "
        f"(test share {meta['test_share']}; max group share test {meta['max_group_share_test']}, "
        f"dev {meta['max_group_share_dev']}) -> {ns.out_dir}"
    ))  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(main())
