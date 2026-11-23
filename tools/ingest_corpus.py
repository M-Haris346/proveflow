"""DEV-ONLY: ingest the pinned corpus sources and write the MEASURED statistics.

    uv run python tools/ingest_corpus.py [--cache DIR] [--stats docs/results/corpus-stats.json]

Fetches each pinned file (docs/DATASETS.md; src/proveflow/corpus/sources.py) at its pinned
revision, verifies its sha256, and caches the raw bytes in ``.proveflow-corpus/`` (the one
gitignored path; raw data is NEVER committed). Writes the statistics, never a record's text,
to ``--stats``. Network: public GitHub raw files only; no key, no provider, nothing paid.
Never imported by src/ or tests/ (tests reach no network; tests/netguard.py).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from proveflow.corpus.ingest import ingest
from proveflow.corpus.sources import SOURCES


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="python tools/ingest_corpus.py")
    p.add_argument("--cache", type=Path, default=Path(".proveflow-corpus"))
    p.add_argument("--stats", type=Path, default=Path("docs/results/corpus-stats.json"))
    args = p.parse_args(argv)
    result = ingest(args.cache)
    pins = {name: {"repo": s.repo, "revision": s.revision, "files": s.files}
            for name, s in SOURCES.items()}  # fmt: skip
    body = {"_note": ("MEASURED by tools/ingest_corpus.py; statistics only, no record text. "
                      "dedup_rate measures CROSS-SOURCE overlap only: AgentDojo's superseded "
                      "revisions are retired by upstream's version rule BEFORE dedup runs "
                      "(loader_notes.agentdojo.agentdojo_superseded_revisions). With three "
                      "sources, 0 duplicates is a measurement with a small n of sources, not "
                      "a property of the corpus; dedup exists for sources added later."),
            "pins": pins, **result.stats}  # fmt: skip
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    # bytes, so the file is LF on every OS (write_text would write CRLF on Windows)
    args.stats.write_bytes((json.dumps(body, indent=2, sort_keys=True) + chr(10)).encode("utf-8"))
    keys = ("before_dedup", "after_dedup", "duplicates_dropped", "dedup_rate", "unresolved",
            "licenses_present")  # fmt: skip
    summary = {k: result.stats[k] for k in keys}
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
