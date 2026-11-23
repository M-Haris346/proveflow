"""Fetch a pinned corpus file (Phase 6 step 3). Runtime only: never called by a test (the suite's
network guard, tests/netguard.py, refuses every non-loopback host, and a named check proves
this fetcher hits it).

Order of checks, each fail-closed, for ``fetch_pinned(source, path)``:
1. BIPIA context paths are REFUSED BY NAME (``ShareAlikeContextRefused``), before anything
   else: a path under any ``sources.BIPIA_REFUSED_CONTEXTS`` directory, in any case and with
   either separator, is refused even if someone later lists it as a file.
2. The path must be a file the source PINS (``NotPinned``); nothing else is fetched.
3. The bytes must have the pinned sha256 (``FetchChecksumMismatch``), whether read from the
   cache or downloaded; a mismatching cache entry is never trusted.
The cache (``cache_dir/<source>/<revision>/<path>``) holds raw upstream bytes and is never
committed (its one path is in .gitignore).

TWO INDEPENDENT LAYERS keep a BIPIA context file out, and NEITHER SUBSUMES THE OTHER:
* layer 1, by NAME (check 1): any path under ``benchmark/<context>/`` is refused as
  share-alike, even if a source spec someday lists it as pinned. It catches that shape only.
* layer 2, by ALLOWLIST (check 2): any path that is not one of the pinned files is refused,
  which also catches a context file in a shape layer 1 does not name (e.g. a bare
  ``table/train.jsonl`` with no ``benchmark/`` prefix) but would let a LISTED context file in.
``ingestchecks.assert_bipia_refuses_every_context_path`` pins layer 1 (with a listed context
file, so layer 2 cannot be what refuses it) and, separately, that layer 2 refuses the
unprefixed shape; its mutation removes layer 1.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from pathlib import Path, PurePosixPath

import httpx2

from proveflow.corpus.sources import BIPIA_REFUSED_CONTEXTS, Source

log = logging.getLogger(__name__)
FETCH_TIMEOUT_S = 60.0


class CorpusFetchError(RuntimeError):
    """A corpus file could not be fetched as pinned; nothing is ingested from it."""


class ShareAlikeContextRefused(CorpusFetchError):
    """A BIPIA context path: refused by name (docs/DATASETS.md, CC BY-SA upstreams)."""


class NotPinned(CorpusFetchError):
    """A path the source does not pin."""


class FetchChecksumMismatch(CorpusFetchError):
    """The bytes do not have the pinned sha256."""


def _parts(path: str) -> tuple[str, ...]:
    return PurePosixPath(path.replace(chr(92), "/")).parts


def check_path(source: Source, path: str) -> None:
    """Raise unless ``path`` may be fetched for ``source`` (checks 1 and 2 above)."""
    if source.name == "bipia":
        parts = tuple(p.casefold() for p in _parts(path) if p not in (".", ""))
        if len(parts) >= 2 and parts[0] == "benchmark" and parts[1] in BIPIA_REFUSED_CONTEXTS:
            raise ShareAlikeContextRefused(
                f"BIPIA context path {path!r} is refused by name: the context datasets carry "
                "their own licences (CC BY-SA 4.0 upstreams); only the attack files are used"
            )
    if path not in source.files:
        raise NotPinned(f"{source.name}: {path!r} is not a pinned file")


def _http_get(url: str) -> bytes:
    with httpx2.Client(timeout=FETCH_TIMEOUT_S, follow_redirects=False) as client:
        response = client.get(url, headers={"User-Agent": "proveflow-corpus-fetch"})
    if response.status_code != 200:
        raise CorpusFetchError(f"HTTP {response.status_code} for {url}")
    return response.content


def fetch_pinned(source: Source, path: str, cache_dir: Path,
                 get: Callable[[str], bytes] = _http_get) -> bytes:  # fmt: skip
    """The bytes of ``path`` at the source's pinned revision, checksum-verified."""
    check_path(source, path)
    want = source.files[path]
    cached = cache_dir / source.name / source.revision / Path(*_parts(path))
    if cached.is_file():
        data = cached.read_bytes()
        if hashlib.sha256(data).hexdigest() == want:
            return data
        log.warning("cached corpus file has the wrong sha256; refetching",
                    extra={"source": source.name, "path": path})  # fmt: skip
    data = get(source.raw_url(path))
    got = hashlib.sha256(data).hexdigest()
    if got != want:
        raise FetchChecksumMismatch(
            f"{source.name}:{path} has sha256 {got[:12]}..., pinned {want[:12]}..."
        )
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(data)
    return data
