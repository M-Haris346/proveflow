"""The corpus for a campaign, from the LOCAL cache only (Phase 7.3a). A campaign run never fetches:
every pinned file must already be in the cache (``tools/ingest_corpus.py`` fills it), with the
sha256 it is pinned to (corpus.fetch verifies that). A missing or wrong-hash file is REFUSED
here instead of being refetched, so a preflight, a dry run and a paid run make no network call
for the corpus. Records are deduplicated exactly as ingest does."""

from __future__ import annotations

from pathlib import Path

from proveflow.corpus.fetch import fetch_pinned
from proveflow.corpus.ingest import ingest
from proveflow.corpus.loaders import Reader
from proveflow.corpus.records import CorpusRecord
from proveflow.corpus.sources import Source


class CorpusNotCached(RuntimeError):
    """A pinned corpus file is not in the local cache with its pinned sha256."""


def _refuse(url: str) -> bytes:
    raise CorpusNotCached(
        "a pinned corpus file is missing from the local cache or has the wrong sha256; a "
        "campaign never fetches: run `uv run python tools/ingest_corpus.py` first"
    )


def cached_records(cache_dir: Path) -> list[CorpusRecord]:
    """Every deduplicated record, read from ``cache_dir`` with any network fetch refused."""

    def reader_for(source: Source) -> Reader:
        return lambda path: fetch_pinned(source, path, cache_dir, get=_refuse)

    return list(ingest(cache_dir, reader_for=reader_for).dedup.kept)
