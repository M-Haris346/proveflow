"""Dev-only: select extra eval servers from the official MCP Registry BY RULE.

Usage:  uv run python scripts/eval_registry_select.py <out_dir>

Not part of proveflow (it makes network calls). It lists every server of the official
registry (GET https://registry.modelcontextprotocol.io/v0/servers?limit=100&cursor=...),
applies the rule below to the registry metadata, and then checks the license of each
survivor's package in its own package registry (npm / PyPI JSON).

Rule (Haris, 2026-11-11; schema: static.modelcontextprotocol.io/schemas/2025-12-11):
  R1  registry status "active" and isLatest
  R2  published (registry publishedAt) on or before CUTOFF (>= 14 days old)
  R3  a package with transport.type == "stdio" and registryType in {npm, pypi}
      (launchable with npx/uvx; oci/docker, nuget, cargo, mcpb are not run by proveflow)
  R4  no environment variable with isRequired true and no default, and none with isSecret
      true and isRequired true (no credential or required setting to supply)
  R5  no package argument with isRequired true and no default/value
  R6  package license (npm `license` / PyPI license_expression or license) is one of
      PERMISSIVE; anything else (missing, unclear, copyleft) -> excluded
Output: candidates.json + a markdown table. Tool counts are NOT known before collection.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REGISTRY = "https://registry.modelcontextprotocol.io/v0/servers"
CUTOFF = datetime(2026, 10, 28, tzinfo=UTC)
PERMISSIVE = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "0BSD", "Unlicense"}
UA = {"User-Agent": "proveflow-eval-selection (dev script)"}


def get_json(url: str, attempts: int = 6) -> Any:
    """GET with retries and exponential backoff (the registry drops idle connections)."""
    last: Exception | None = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers=UA)  # noqa: S310 - fixed https hosts
            with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
                return json.loads(resp.read().decode("utf-8"))
        except (OSError, ValueError) as exc:
            last = exc
            time.sleep(min(30.0, 1.5 * 2**i))
    raise RuntimeError(f"GET failed after {attempts} attempts: {url}") from last


def all_servers(cache_dir: Path) -> list[dict[str, Any]]:
    """All registry entries; every page is cached so an interrupted run resumes."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    out: list[dict[str, Any]] = []
    cursor: str | None = None
    for n in range(10_000):
        page_file = cache_dir / f"page-{n:05d}.json"
        if page_file.exists():
            page = json.loads(page_file.read_text(encoding="utf-8"))
        else:
            q = "?limit=100" + (f"&cursor={urllib.parse.quote(cursor)}" if cursor else "")
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


def package_license(pkg: dict[str, Any]) -> str | None:
    ident, version = pkg["identifier"], pkg.get("version")
    try:
        if pkg["registryType"] == "npm":
            # Per-version manifest (small) instead of the full packument.
            name = urllib.parse.quote(ident, safe="@")
            ver = get_json(f"https://registry.npmjs.org/{name}/{urllib.parse.quote(str(version))}")
            lic = ver.get("license")
            return lic if isinstance(lic, str) else None
        data = get_json(f"https://pypi.org/pypi/{ident}/{version}/json")
        info = data.get("info") or {}
        lic = info.get("license_expression") or info.get("license")
        return lic.strip() if isinstance(lic, str) and len(lic) < 40 else None
    except Exception:
        return None


def main() -> int:
    out_dir = Path(sys.argv[1])
    out_dir.mkdir(parents=True, exist_ok=True)
    entries = all_servers(out_dir / "pages")
    reasons: dict[str, int] = {}
    passed: list[dict[str, Any]] = []
    for e in entries:
        pkg, reason = rule_filter(e)
        reasons[reason] = reasons.get(reason, 0) + 1
        if pkg is not None:
            passed.append(
                {
                    "name": e["server"]["name"],
                    "pkg": pkg,
                    "repo": (e["server"].get("repository") or {}).get("url"),
                    "published": e["_meta"]["io.modelcontextprotocol.registry/official"][
                        "publishedAt"
                    ],
                }
            )
    rows = []
    for c in passed:
        lic = package_license(c["pkg"])
        ok = lic in PERMISSIVE
        reasons["R6 license not permissive/unknown" if not ok else "selected"] = (
            reasons.get("R6 license not permissive/unknown" if not ok else "selected", 0) + 1
        )
        if ok:
            reasons["ok"] -= 1
            rows.append({**c, "license": lic})
        else:
            reasons["ok"] -= 1
        time.sleep(0.1)
    rows.sort(key=lambda r: r["name"])
    (out_dir / "candidates.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    print(f"registry entries: {len(entries)}")
    for k in sorted(reasons):
        print(f"  {k}: {reasons[k]}")
    print("| registry name | package | version | license | repo | published |")
    print("|---|---|---|---|---|---|")
    for r in rows:
        p = r["pkg"]
        print(
            f"| {r['name']} | {p['registryType']}:{p['identifier']} | {p.get('version')} | "
            f"{r['license']} | {r['repo']} | {r['published'][:10]} |"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
