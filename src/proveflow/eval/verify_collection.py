"""Fail an eval-collect job whose summary does not cover exactly the chosen server file.

    python -m proveflow.eval.verify_collection --servers <servers.json> --summary <summary.json>

Exit 0 only if the set of ``server_id`` values in the collection summary equals the set of
``id`` values in the server file (and neither has duplicates). Otherwise exit 1 and print
which ids are missing or unexpected. Ids are server names chosen by us, never secrets.

Why: eval-collect run #2 (2026-11-13, commit 016e39d) was dispatched with the default
inputs and silently collected the v1 set instead of servers_v2.json. This check makes a
mismatch between "the file the job was told to use" and "what it collected" fail the job.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from rich.console import Console
from rich.text import Text

from proveflow.eval.collect import CollectError, load_server_set


def check(servers: Path, summary: Path) -> list[str]:
    """Problems found (empty list = the summary matches the server file exactly)."""
    expected = [s.id for s in load_server_set(servers).servers]
    data = json.loads(summary.read_text(encoding="utf-8"))
    got = [str(s["server_id"]) for s in data.get("servers", [])]
    problems: list[str] = []
    for label, ids in (("server file", expected), ("summary", got)):
        dupes = sorted(k for k, n in Counter(ids).items() if n > 1)
        if dupes:
            problems.append(f"duplicate ids in {label}: {dupes}")
    missing = sorted(set(expected) - set(got))
    unexpected = sorted(set(got) - set(expected))
    if missing:
        problems.append(f"in {servers.as_posix()} but not collected: {missing}")
    if unexpected:
        problems.append(f"collected but not in {servers.as_posix()}: {unexpected}")
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    console = Console(stderr=True)
    ap = argparse.ArgumentParser(prog="python -m proveflow.eval.verify_collection")
    ap.add_argument("--servers", type=Path, required=True)
    ap.add_argument("--summary", type=Path, required=True)
    ns = ap.parse_args(argv)
    try:
        problems = check(ns.servers, ns.summary)
    except (CollectError, OSError, ValueError, KeyError) as exc:
        console.print(Text(f"error: {exc}", style="red"))
        return 1
    if problems:
        for p in problems:
            console.print(Text(f"MISMATCH: {p}", style="red"))
        return 1
    console.print(Text(f"ok: summary server ids match {ns.servers.as_posix()}"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
