"""Dev-only: mechanical hand-pick of held-out v2 eval servers (checkpoint 1c, Stage C).

Usage:
    uv run python scripts/eval_handpick.py <registry_cache_dir> <downloads_snapshot.json> <out.json>

<registry_cache_dir> is the output dir of scripts/eval_registry_select.py (seed 20261201):
it holds pages-latest/page-*.json and selection.json. It is NOT committed; its sha256 and
fetch date are recorded in docs/eval/SERVERS_V2.md.
<downloads_snapshot.json> is data/eval/roles/handpick_downloads_snapshot.json (npm last-month
download counts + fetch time). If a package is missing from it, the run stops (pass
--fetch-missing to look it up and add it).

The rule is RULE below, verbatim as used by run 3 (it is also written into the output). Not
part of proveflow; it makes network calls only to read package LICENSE/README files (and,
with --fetch-missing, npm download counts). Nothing downloaded is executed.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

# Run 3's rule text, verbatim (including its original usage line), so the output is
# byte-identical to the run that selected servers_v2.json.
RULE = """Mechanical hand-pick for the v2 held-out set (author's rule, 2026-11-13).

usage: mechanical_pick.py <registry_v2_dir> <out.json>

Rule (exact):
  1. Universe: R1-R5 survivors of the cached registry snapshot (cutoff 2026-10-30), minus
     every package in data/eval/roles/servers.json, minus the seed-20261201 registry sample.
  2. Category = keyword regex (CATS below, in this order) on "<server part of the registry
     name, i.e. after the last '/'> <description> <package id>", lower-cased (the
     'io.github.<owner>' namespace is NOT matched). One server can match several categories.
  3. Per category, candidates are ranked by npm last-month downloads (npm downloads API;
     429/5xx retried with backoff, still-unknown counts = -1, ranked last), descending; ties
     broken by package name. PyPI candidates are used only if no npm
     candidate of that category passes.
  4. Walk the ranking; the first candidate that passes L (LICENSE file text) and T (no README
     telemetry hit) is picked. A candidate already picked for an earlier category is skipped.
     Every skipped candidate is recorded with its reason.
  5. One pick per category, no second round (definition fix 1, author, before picks: a round 2
     starting at "browser" would favour v2, whose rules were mostly fit on dev browser tools).
     Total = registry-sample passes + one pick per category.
Reads only registry metadata, npm download counts, and the package's LICENSE/README files.
"""

CUTOFF = datetime(2026, 10, 30, tzinfo=UTC)
CATS = {
    "browser": r"\b(browser|playwright|puppeteer|selenium|chrom(e|ium))\b",
    # definition fix 2 (author, written before the author or reviewer saw run-1 picks):
    # providers / API phrasing only; "claude", "gpt", "llm" alone matched servers that merely
    # mention an MCP client.
    "llm-proxy": (
        r"\b(openai|anthropic|gemini|ollama|openrouter|deepseek|mistral|groq|"
        r"together ?ai|litellm)\b"
        r"|\b(llm|model|chat) ?(api|completion|completions|gateway|proxy)\b"
    ),
    "vcs-hosting": r"\b(github|gitlab|bitbucket|gitea|codeberg)\b",
    "database": r"\b(postgres(ql)?|mysql|sqlite|mongo(db)?|redis|database|duckdb|sql)\b",
    "messaging": r"\b(slack|discord|telegram|e-?mail|gmail|whatsapp|imap|smtp|matrix|mattermost)\b",
    "web": r"\b(fetch|scrap(e|er|ing)|web ?search|search engine|crawl(er)?|duckduckgo|searxng)\b",
    "file": r"\b(file ?system|files|pdf|markdown|documents?|docx|excel|csv)\b",
    "dev-tools": r"\b(docker|kubernetes|k8s|npm|eslint|lint|terraform|sentry|jira)\b",
}
SELECT_SCRIPT = Path(__file__).resolve().parent / "eval_registry_select.py"
UA = {"User-Agent": "proveflow-eval-selection (dev script)"}


def load_select() -> ModuleType:
    spec = importlib.util.spec_from_file_location("eval_registry_select", SELECT_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {SELECT_SCRIPT}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def categories(text: str) -> list[str]:
    return [c for c, rx in CATS.items() if re.search(rx, text)]


def server_part(registry_name: str) -> str:
    """'io.github.owner/server' -> 'server' (the namespace is not about the server's topic;
    run 1 matched every 'io.github.*' name as vcs-hosting)."""
    return registry_name.rsplit("/", 1)[-1]


def package_identifier(package: str) -> str:
    """'npm:@x/diagram@1.0.0' -> '@x/diagram'; 'pypi:foo@2' -> 'foo'.

    Label fix after run 3 (picks unchanged): registry-sample rows carry the package as
    '<registry>:<identifier>@<version>', and the 'npm:' prefix matched the dev-tools regex
    (\\bnpm\\b). Sample rows are now categorised on the same bare identifier as hand-picks."""
    ident = package.split(":", 1)[1] if ":" in package else package
    head, sep, _ = ident.rpartition("@")
    return head if sep and head else ident


def downloads(pkg: str) -> int:
    """npm last-month downloads; 429/5xx/network retried with backoff; -1 if still unknown."""
    url = "https://api.npmjs.org/downloads/point/last-month/" + urllib.parse.quote(pkg, safe="@/")
    for attempt in range(8):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
                return int(json.loads(r.read()).get("downloads", 0))
        except urllib.error.HTTPError as exc:
            if exc.code != 429 and exc.code < 500:  # e.g. 404: unknown, not retried
                return -1
        except (OSError, ValueError):
            pass
        time.sleep(min(60.0, 2.0 * 2**attempt))
    return -1


def build_universe(
    entries: list[dict[str, Any]],
    rule_filter: Callable[..., tuple[dict[str, Any] | None, str]],
    skip_pkgs: set[str],
    sample_names: set[str],
    cutoff: datetime = CUTOFF,
) -> list[dict[str, Any]]:
    universe: list[dict[str, Any]] = []
    for e in entries:
        pkg, _ = rule_filter(e, cutoff)
        if pkg is None or pkg["identifier"] in skip_pkgs or e["server"]["name"] in sample_names:
            continue
        s = e["server"]
        text = (
            f"{server_part(s.get('name', ''))} {s.get('description', '')} {pkg['identifier']}"
        ).lower()
        cats = categories(text)
        if cats:
            meta = e["_meta"]["io.modelcontextprotocol.registry/official"]
            universe.append(
                {
                    "name": s["name"],
                    "description": s.get("description") or "",
                    "repo": (s.get("repository") or {}).get("url"),
                    "pkg": pkg,
                    "cats": cats,
                    "published": meta["publishedAt"],
                }
            )
    return universe


def build(
    entries: list[dict[str, Any]],
    sample_rows: list[dict[str, Any]],
    skip_pkgs: set[str],
    dl: dict[str, int],
    inspect_fn: Callable[[dict[str, Any]], dict[str, Any]],
    rule_filter: Callable[..., tuple[dict[str, Any] | None, str]],
    cutoff: datetime = CUTOFF,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Pure selection: returns (output document, human summary). ``dl`` must cover every npm
    candidate (main() guarantees that)."""
    sample_names = {r["name"] for r in sample_rows}
    universe = build_universe(entries, rule_filter, skip_pkgs, sample_names, cutoff)
    for c in universe:
        c["downloads"] = (
            dl.get(c["pkg"]["identifier"]) if c["pkg"]["registryType"] == "npm" else None
        )

    # registry-sample rows: category by the same regex, pass = L and T
    sample_out = []
    for r in sample_rows:
        e = next((x for x in entries if x["server"]["name"] == r["name"]), None)
        s = e["server"] if e else {}
        text = (
            f"{server_part(s.get('name', ''))} {s.get('description', '')} "
            f"{package_identifier(r.get('package', ''))}"
        ).lower()
        cats = categories(text)
        sample_out.append(
            r
            | {
                "category": cats[0] if cats else "other",
                "all_categories": cats,
                "pass": r["decision"] == "propose",
            }
        )

    inspected: dict[str, dict[str, Any]] = {}

    def check(c: dict[str, Any]) -> dict[str, Any]:
        key = c["pkg"]["identifier"]
        if key not in inspected:
            inspected[key] = inspect_fn(
                {"name": c["name"], "repo": c["repo"], "published": c["published"], "pkg": c["pkg"]}
            )
        return inspected[key]

    ranked: dict[str, tuple[list[dict[str, Any]], list[dict[str, Any]]]] = {}
    for cat in CATS:
        rows = [c for c in universe if cat in c["cats"]]
        npm = sorted(
            [c for c in rows if c["pkg"]["registryType"] == "npm"],
            key=lambda c: (-c["downloads"], c["pkg"]["identifier"]),
        )
        pypi = sorted(
            [c for c in rows if c["pkg"]["registryType"] == "pypi"],
            key=lambda c: c["pkg"]["identifier"],
        )
        ranked[cat] = (npm, pypi)

    picked: list[dict[str, Any]] = []
    log: dict[str, list[tuple[dict[str, Any] | None, str]]] = {cat: [] for cat in CATS}
    picked_ids: set[str] = set()
    cursor = dict.fromkeys(CATS, 0)  # index into npm+pypi walk

    def pick_one(cat: str) -> bool:
        npm, pypi = ranked[cat]
        walk = npm + pypi
        while cursor[cat] < len(walk):
            c = walk[cursor[cat]]
            cursor[cat] += 1
            if c["pkg"]["registryType"] == "pypi" and any(
                x["pkg"]["registryType"] == "npm"
                and check(x)["decision"] == "propose"
                and x["pkg"]["identifier"] not in picked_ids
                for x in npm
            ):
                log[cat].append((c, "skipped: pypi used only if no npm candidate passes"))
                continue
            ident = c["pkg"]["identifier"]
            if ident in picked_ids:
                log[cat].append((c, "skipped: already picked for an earlier category"))
                continue
            row = check(c)
            if row["decision"] != "propose":
                log[cat].append((c, f"skipped: {row['decision']}: {row['reason']}"))
                continue
            picked_ids.add(ident)
            picked.append(c | {"category": cat, "inspect": row})
            log[cat].append((c, f"PICKED (round {sum(p['category'] == cat for p in picked)})"))
            return True
        return False

    for cat in CATS:
        if not pick_one(cat):
            log[cat].append((None, "no passing candidate"))
    total = sum(r["pass"] for r in sample_out) + len(picked)

    out = {
        "rule": RULE,
        "cutoff": cutoff.date().isoformat(),
        "registry_sample": sample_out,
        "picked": [
            {
                "category": p["category"],
                "name": p["name"],
                "package": p["inspect"]["package"],
                "license": p["inspect"].get("license"),
                "downloads": p["downloads"],
                "repo": p["repo"],
                "archive_sha256": p["inspect"].get("archive_sha256"),
            }
            for p in picked
        ],
        "ranked": {
            cat: [
                {
                    "name": c["name"],
                    "package": f"{c['pkg']['registryType']}:{c['pkg']['identifier']}"
                    f"@{c['pkg'].get('version')}",
                    "downloads": c["downloads"],
                }
                for c in ranked[cat][0] + ranked[cat][1]
            ]
            for cat in CATS
        },
        "walk_log": {
            cat: [
                {
                    "name": c["name"] if c else None,
                    "package": c["pkg"]["identifier"] if c else None,
                    "downloads": c["downloads"] if c else None,
                    "outcome": why,
                }
                for c, why in log[cat]
            ]
            for cat in CATS
        },
        "total": total,
    }
    summary = {
        "total": total,
        "sample_pass": [(r["name"], r["category"]) for r in sample_out if r["pass"]],
        "sample_fail": [(r["name"], r["reason"]) for r in sample_out if not r["pass"]],
        "picked": [(p["category"], p["name"], p["inspect"]["package"]) for p in picked],
        "log": {
            cat: [
                (c["pkg"]["identifier"] if c else "-", c["downloads"] if c else "-", why)
                for c, why in log[cat]
            ]
            for cat in CATS
        },
        "sizes": {cat: (len(ranked[cat][0]), len(ranked[cat][1])) for cat in CATS},
    }
    return out, summary


def read_snapshot(path: Path) -> dict[str, int]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    counts = doc["npm_last_month"] if "npm_last_month" in doc else doc
    return {str(k): int(v) for k, v in counts.items()}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="eval_handpick.py")
    ap.add_argument("registry_cache_dir", type=Path)
    ap.add_argument("downloads_snapshot", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--servers", type=Path, default=Path("data/eval/roles/servers.json"))
    ap.add_argument("--fetch-missing", action="store_true")
    ns = ap.parse_args(argv)
    sel = load_select()
    root: Path = ns.registry_cache_dir
    skip_pkgs = sel.excluded_packages(ns.servers)
    sample_rows = json.loads((root / "selection.json").read_text(encoding="utf-8"))["rows"]
    entries: list[dict[str, Any]] = []
    for f in sorted((root / "pages-latest").glob("page-*.json")):
        entries += json.loads(f.read_text(encoding="utf-8")).get("servers", [])
    universe = build_universe(entries, sel.rule_filter, skip_pkgs, {r["name"] for r in sample_rows})
    npm_ids = sorted(
        {c["pkg"]["identifier"] for c in universe if c["pkg"]["registryType"] == "npm"}
    )
    dl = read_snapshot(ns.downloads_snapshot) if ns.downloads_snapshot.exists() else {}
    missing = [p for p in npm_ids if p not in dl]
    if missing and not ns.fetch_missing:
        print(f"{len(missing)} npm packages missing from the snapshot; use --fetch-missing",
              file=sys.stderr)  # fmt: skip
        return 1
    if missing:
        with ThreadPoolExecutor(max_workers=3) as pool:
            dl.update(zip(missing, pool.map(downloads, missing), strict=True))
        ns.downloads_snapshot.write_text(
            json.dumps(
                {"source": "https://api.npmjs.org/downloads/point/last-month/<package>",
                 "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
                 "npm_last_month": dict(sorted(dl.items()))},
                indent=1,
            ) + "\n",
            encoding="utf-8",
        )  # fmt: skip
    out, summary = build(entries, sample_rows, skip_pkgs, dl, sel.inspect, sel.rule_filter)
    ns.out.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("total", "sample_pass", "sample_fail", "picked")},
                     indent=1))  # fmt: skip
    for cat in CATS:
        npm_n, pypi_n = summary["sizes"][cat]
        print(f"\n## {cat}: {npm_n} npm + {pypi_n} pypi candidates")
        for ident, n, why in summary["log"][cat]:
            print(f"  {ident} dl={n} -> {why}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
