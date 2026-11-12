"""Dev-only: select extra eval servers from the official MCP Registry BY RULE.

Usage:  uv run python scripts/eval_registry_select.py <out_dir>

Not part of proveflow (it makes network calls). Nothing downloaded is executed or extracted
to disk: tarballs/sdists are read in memory only, to look at LICENSE and README files.

Listing (registry OpenAPI, accessed 2026-11-12, GET /v0/servers): "Use version=latest to
return only the latest version of each matching server." Query: limit=100, cursor, version=latest.

Rule (Haris, 2026-11-11/12; schema: static.modelcontextprotocol.io/schemas/2025-12-11):
  R1  registry status "active" and isLatest
  R2  published (registry publishedAt) on or before CUTOFF (>= 14 days old)
  R3  a package with transport.type == "stdio" and registryType in {npm, pypi}
  R4  no environment variable that is required without a default, and no required secret
  R5  no package argument that is required without a default/value
  S   deterministic random sample of at most SAMPLE_MAX survivors (seed SEED, input sorted
      by registry name): random.Random(SEED).sample(sorted_survivors, k)
  L   license verified from the LICENSE file inside the pinned npm tarball / PyPI sdist
      (or wheel): the text must match a PERMISSIVE license; metadata alone is not enough
  T   README of the same package grepped for telemetry / analytics / usage statistics
Output: <out_dir>/selection.json and selection.md.
"""

from __future__ import annotations

import hashlib
import io
import json
import random
import re
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REGISTRY = "https://registry.modelcontextprotocol.io/v0/servers"
CUTOFF = datetime(2026, 10, 28, tzinfo=UTC)
SEED = 20261111
SAMPLE_MAX = 8
MAX_ARCHIVE = 50 * 1024 * 1024
UA = {"User-Agent": "proveflow-eval-selection (dev script)"}
TELEMETRY = re.compile(
    r"telemetry|analytics|usage[ -]statistic|usage data|tracking|posthog|mixpanel|segment\.io|"
    r"google analytics|opt[ -]?out",
    re.IGNORECASE,
)
# License text signatures (the license texts themselves, not metadata).
LICENSE_SIGNATURES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Apache-2.0", ("apache license", "version 2.0")),
    ("MIT", ("permission is hereby granted, free of charge",)),
    ("ISC", ("permission to use, copy, modify, and/or distribute this software for any purpose",)),
    ("BSD-3-Clause", ("redistribution and use in source and binary forms", "neither the name")),
    ("BSD-2-Clause", ("redistribution and use in source and binary forms",)),
    ("Unlicense", ("this is free and unencumbered software released into the public domain",)),
)


def get_bytes(url: str, attempts: int = 6) -> bytes:
    """GET with retries (5xx / network only; a 4xx is final)."""
    last: Exception | None = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers=UA)  # noqa: S310 - fixed https hosts
            with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
                return bytes(resp.read(MAX_ARCHIVE + 1))
        except urllib.error.HTTPError as exc:
            if exc.code < 500:
                raise
            last = exc
        except OSError as exc:
            last = exc
        time.sleep(min(30.0, 1.5 * 2**i))
    raise RuntimeError(f"GET failed after {attempts} attempts: {url}") from last


def get_json(url: str) -> Any:
    return json.loads(get_bytes(url).decode("utf-8"))


def all_latest_servers(cache_dir: Path) -> list[dict[str, Any]]:
    """Every server's latest version; pages are cached so an interrupted run resumes."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    out: list[dict[str, Any]] = []
    cursor: str | None = None
    for n in range(10_000):
        page_file = cache_dir / f"page-{n:05d}.json"
        if page_file.exists():
            page = json.loads(page_file.read_text(encoding="utf-8"))
        else:
            q = "?limit=100&version=latest"
            if cursor:
                q += f"&cursor={urllib.parse.quote(cursor)}"
            page = get_json(REGISTRY + q)
            page_file.write_text(json.dumps(page), encoding="utf-8")
            time.sleep(0.2)
        out.extend(page.get("servers", []))
        cursor = (page.get("metadata") or {}).get("nextCursor")
        if n % 20 == 0:
            print(f"  page {n}: {len(out)} entries", file=sys.stderr, flush=True)
        if not cursor:
            break
    return out


def _required_without_default(items: list[dict[str, Any]] | None) -> bool:
    return any(
        i.get("isRequired") and i.get("default") in (None, "") and i.get("value") in (None, "")
        for i in items or []
    )


def rule_filter(entry: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    """Apply R1-R5 to one registry entry. Returns (package, reason)."""
    server = entry.get("server", {})
    meta = (entry.get("_meta") or {}).get("io.modelcontextprotocol.registry/official", {})
    if meta.get("status") != "active" or not meta.get("isLatest"):
        return None, "R1 not active/latest"
    published = meta.get("publishedAt")
    if not published or datetime.fromisoformat(published.replace("Z", "+00:00")) > CUTOFF:
        return None, "R2 too new"
    for pkg in server.get("packages") or []:
        if (pkg.get("transport") or {}).get("type") != "stdio":
            continue
        if pkg.get("registryType") not in ("npm", "pypi"):
            continue
        env = pkg.get("environmentVariables")
        if _required_without_default(env) or any(
            e.get("isSecret") and e.get("isRequired") for e in env or []
        ):
            return None, "R4 required env var / secret"
        if _required_without_default(pkg.get("packageArguments")):
            return None, "R5 required argument"
        return pkg, "ok"
    return None, "R3 no npm/pypi stdio package"


def sample(survivors: list[dict[str, Any]], k: int = SAMPLE_MAX, seed: int = SEED) -> list[Any]:
    ordered = sorted(survivors, key=lambda c: c["name"])
    return random.Random(seed).sample(ordered, min(k, len(ordered)))  # noqa: S311 - not crypto


def classify_license(text: str) -> str | None:
    low = " ".join(text.lower().split())
    for spdx, needles in LICENSE_SIGNATURES:
        if all(n in low for n in needles):
            return spdx
    return None


def _archive_members(data: bytes) -> dict[str, bytes]:
    """name -> bytes for LICENSE*/README* files at depth <= 2, read in memory only."""
    wanted = re.compile(r"^(licen[cs]e|copying|readme)", re.IGNORECASE)
    out: dict[str, bytes] = {}
    if data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for name in zf.namelist():
                base = name.rsplit("/", 1)[-1]
                if wanted.match(base) and name.count("/") <= 3:
                    out[name] = zf.read(name)[:2_000_000]
        return out
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tf:
        for member in tf.getmembers():
            base = member.name.rsplit("/", 1)[-1]
            if member.isfile() and wanted.match(base) and member.name.count("/") <= 2:
                fh = tf.extractfile(member)
                if fh is not None:
                    out[member.name] = fh.read(2_000_000)
    return out


def package_archive(pkg: dict[str, Any]) -> tuple[str, bytes]:
    ident, version = pkg["identifier"], str(pkg.get("version"))
    if pkg["registryType"] == "npm":
        manifest = get_json(
            f"https://registry.npmjs.org/{urllib.parse.quote(ident, safe='@')}/"
            f"{urllib.parse.quote(version)}"
        )
        url = manifest["dist"]["tarball"]
        return url, get_bytes(url)
    data = get_json(f"https://pypi.org/pypi/{ident}/{version}/json")
    files = data.get("urls") or []
    pick = next((f for f in files if f["packagetype"] == "sdist"), None) or next(
        (f for f in files if f["packagetype"] == "bdist_wheel"), None
    )
    if pick is None:
        raise RuntimeError("no sdist or wheel")
    return pick["url"], get_bytes(pick["url"])


def inspect(candidate: dict[str, Any]) -> dict[str, Any]:
    row: dict[str, Any] = {k: candidate[k] for k in ("name", "repo", "published")}
    pkg = candidate["pkg"]
    row["package"] = f"{pkg['registryType']}:{pkg['identifier']}@{pkg.get('version')}"
    try:
        url, data = package_archive(pkg)
    except Exception as exc:
        row.update(decision="exclude", reason=f"archive not readable: {type(exc).__name__}")
        return row
    row["archive"] = url
    row["archive_sha256"] = hashlib.sha256(data).hexdigest()
    members = _archive_members(data)
    licenses = {
        n: b for n, b in members.items() if not n.rsplit("/", 1)[-1].lower().startswith("readme")
    }
    readmes = {
        n: b for n, b in members.items() if n.rsplit("/", 1)[-1].lower().startswith("readme")
    }
    found = {n: classify_license(b.decode("utf-8", "replace")) for n, b in licenses.items()}
    row["license_files"] = {n: (spdx or "unrecognized") for n, spdx in sorted(found.items())}
    spdx_ids = {s for s in found.values() if s}
    telemetry: list[str] = []
    for name, body in sorted(readmes.items()):
        for i, line in enumerate(body.decode("utf-8", "replace").splitlines(), 1):
            if TELEMETRY.search(line):
                telemetry.append(f"{name}:{i}: {line.strip()[:160]}")
    row["telemetry_hits"] = telemetry
    if not licenses:
        row.update(decision="exclude", reason="no LICENSE file in the package")
    elif len(spdx_ids) != 1 or any(s is None for s in found.values()):
        row.update(
            decision="exclude", reason="LICENSE text not recognized as one permissive license"
        )
    elif telemetry:
        row.update(
            license=spdx_ids.pop(),
            decision="ask",
            reason="README mentions telemetry/analytics: needs a documented opt-out",
        )
    else:
        row.update(
            license=spdx_ids.pop(),
            decision="propose",
            reason="license verified from file; no telemetry mention",
        )
    return row


def main() -> int:
    out_dir = Path(sys.argv[1])
    out_dir.mkdir(parents=True, exist_ok=True)
    entries = all_latest_servers(out_dir / "pages-latest")
    reasons: Counter[str] = Counter()
    survivors: list[dict[str, Any]] = []
    for e in entries:
        pkg, reason = rule_filter(e)
        reasons[reason.split(" ")[0]] += 1
        if pkg is not None:
            meta = e["_meta"]["io.modelcontextprotocol.registry/official"]
            survivors.append({"name": e["server"]["name"], "pkg": pkg,
                              "repo": (e["server"].get("repository") or {}).get("url"),
                              "published": meta["publishedAt"]})  # fmt: skip
    picked = sample(survivors)
    rows = [inspect(c) for c in picked]
    result = {
        "entries": len(entries),
        "reasons": dict(sorted(reasons.items())),
        "survivors": len(survivors),
        "seed": SEED,
        "sample_max": SAMPLE_MAX,
        "rows": rows,
    }
    (out_dir / "selection.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=2))
    for r in rows:
        print(f"- {r['name']} | {r['package']} | {r.get('license', '-')} | {r['decision']}: "
              f"{r['reason']} | telemetry hits: {len(r.get('telemetry_hits', []))}")  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(main())
