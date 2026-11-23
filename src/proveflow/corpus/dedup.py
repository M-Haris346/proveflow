"""Dedup and corpus statistics (Phase 6 step 3). Deterministic.

THE DEDUP RULE, stated:
* Two records are DUPLICATES iff their ``dedup_key`` is equal: the text Unicode-normalized to
  NFC, every run of whitespace collapsed to one space, leading and trailing whitespace
  removed. Case, punctuation and wording are NOT normalized: texts that differ in any of
  those are different payloads. The record's own text is never changed by this; the key is
  only for comparison.
* The WINNER of a duplicate group is the record whose source comes first in
  ``sources.SOURCE_PRIORITY`` (the order of docs/DATASETS.md's table), then the smallest
  ``source_id`` (string order) within that source. Every other member is dropped and listed
  in ``DedupResult.dropped`` with the winner's id.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from proveflow.corpus.records import CorpusRecord
from proveflow.corpus.sources import SOURCE_PRIORITY

_WS = re.compile(r"\s+")


def dedup_key(text: str) -> str:
    return _WS.sub(" ", unicodedata.normalize("NFC", text)).strip()


def _rank(record: CorpusRecord) -> tuple[int, str]:
    return SOURCE_PRIORITY.index(record.source_dataset), record.source_id


@dataclass
class DedupResult:
    kept: list[CorpusRecord] = field(default_factory=list)
    dropped: list[tuple[str, str]] = field(default_factory=list)  # (dropped id, winner id)


def dedup(records: Sequence[CorpusRecord]) -> DedupResult:
    groups: dict[str, list[CorpusRecord]] = {}
    for r in records:
        groups.setdefault(dedup_key(r.text), []).append(r)
    out = DedupResult()
    for members in groups.values():
        ordered = sorted(members, key=_rank)
        out.kept.append(ordered[0])
        out.dropped += [(m.id, ordered[0].id) for m in ordered[1:]]
    out.kept.sort(key=_rank)
    out.dropped.sort()
    return out


def _counts(records: Sequence[CorpusRecord]) -> dict[str, Any]:
    return {
        "records": len(records),
        "per_source": dict(sorted(Counter(r.source_dataset for r in records).items())),
        "per_attack_family": dict(
            sorted(Counter(f"{r.source_dataset}/{r.attack_family}" for r in records).items())
        ),
        "per_language": dict(sorted(Counter(r.language for r in records).items())),
        "per_license": dict(sorted(Counter(r.license for r in records).items())),
    }


def corpus_stats(records: Sequence[CorpusRecord], result: DedupResult,
                 unresolved: Sequence[str]) -> dict[str, Any]:  # fmt: skip
    """MEASURED statistics, before and after dedup, from the records themselves."""
    before = len(records)
    return {
        "before_dedup": _counts(records),
        "after_dedup": _counts(result.kept),
        "duplicates_dropped": len(result.dropped),
        "dedup_rate": (len(result.dropped) / before) if before else 0.0,
        "dropped": [{"dropped": d, "winner": w} for d, w in result.dropped],
        "unresolved": list(unresolved),
        "licenses_present": sorted({r.license for r in records}),
    }
