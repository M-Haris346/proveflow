"""Corpus ingest (Phase 6 step 3): every pinned source through its loader, then dedup and
measured statistics. Offline except for the pinned fetch (``fetch.fetch_pinned``), which a
test never reaches. Raw bytes stay in the cache dir (gitignored); nothing raw is committed.

``ingest(cache_dir)`` returns the kept records and the stats; ``reader`` is injectable so the
whole pipeline runs on committed synthetic fixtures in tests.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from proveflow.corpus.dedup import DedupResult, corpus_stats, dedup
from proveflow.corpus.fetch import fetch_pinned
from proveflow.corpus.loaders import LOADERS, Reader
from proveflow.corpus.records import CorpusRecord
from proveflow.corpus.sources import SOURCES, Source

INGESTED: tuple[str, ...] = ("injecagent", "bipia", "agentdojo")  # LLMail-Inject: not yet


class SourceNotIngested(ValueError):
    """A source that is not (yet) approved for ingest, e.g. LLMail-Inject."""


@dataclass
class IngestResult:
    records: list[CorpusRecord]  # before dedup
    dedup: DedupResult
    stats: dict[str, Any]


def pinned_reader(source: Source, cache_dir: Path) -> Reader:
    return lambda path: fetch_pinned(source, path, cache_dir)


def ingest(cache_dir: Path, *, sources: Sequence[str] = INGESTED,
           reader_for: Callable[[Source], Reader] | None = None) -> IngestResult:  # fmt: skip
    records: list[CorpusRecord] = []
    unresolved: list[str] = []
    notes: dict[str, Any] = {}
    for name in sources:
        if name not in INGESTED:
            raise SourceNotIngested(f"{name!r} is not approved for ingest (docs/DATASETS.md)")
        source = SOURCES[name]
        read = reader_for(source) if reader_for else pinned_reader(source, cache_dir)
        loaded = LOADERS[name](read)
        records += loaded.records
        unresolved += [f"{name}:{u}" for u in loaded.unresolved]
        if loaded.notes:
            notes[name] = loaded.notes
    result = dedup(records)
    stats = corpus_stats(records, result, unresolved)
    stats["loader_notes"] = notes
    return IngestResult(records, result, stats)
