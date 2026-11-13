"""scripts/eval_handpick.py on a tiny synthetic registry + downloads snapshot (no network)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "eval_handpick.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("eval_handpick", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


hp = _load()
sel = hp.load_select()


def entry(name: str, desc: str, ident: str, registry: str = "npm") -> dict[str, Any]:
    return {
        "server": {
            "name": name,
            "description": desc,
            "packages": [{"registryType": registry, "identifier": ident, "version": "1.0.0",
                          "transport": {"type": "stdio"}}],
        },
        "_meta": {"io.modelcontextprotocol.registry/official": {
            "status": "active", "isLatest": True, "publishedAt": "2026-09-01T00:00:00Z"}},
    }  # fmt: skip


ENTRIES = [
    # namespace says github, the server is about notes -> must NOT be vcs-hosting
    entry("io.github.x/foo", "Keep short notes", "foo-mcp"),
    entry("io.example/browser-a", "Headless browser automation", "browser-a"),  # fails L
    entry("io.example/browser-b", "Browser automation", "browser-b"),
    entry("io.example/browser-c", "Browser automation", "browser-c"),
    entry("io.example/gh-reader", "Read GitHub repositories", "gh-reader"),
    entry("io.example/dbx", "Query a SQLite database", "dbx", registry="pypi"),
    entry("io.example/old", "Browser automation", "old-browser"),  # in the excluded v1 set
    # web: a passing npm candidate AND a pypi candidate -> npm picked, pypi never walked
    entry("io.example/webfetch-a", "Fetch pages", "webfetch-a"),
    entry("io.example/web-py", "Web search via a search engine", "web-py", registry="pypi"),
    # dev-tools: unknown downloads (-1) must rank after zero downloads
    entry("io.example/dock-unknown", "Manage docker containers", "dock-unknown"),
    entry("io.example/dock-zero", "Manage docker containers", "dock-zero"),
]
DOWNLOADS = {"foo-mcp": 9999, "browser-a": 500, "browser-b": 300, "browser-c": 100,
             "gh-reader": 50, "old-browser": 10_000, "webfetch-a": 5,
             "dock-unknown": -1, "dock-zero": 0}  # fmt: skip
FAILS = {"browser-a": "no LICENSE file in the package"}


def fake_inspect(c: dict[str, Any]) -> dict[str, Any]:
    ident = c["pkg"]["identifier"]
    if ident in FAILS:
        return {"package": ident, "decision": "exclude", "reason": FAILS[ident]}
    return {"package": f"{c['pkg']['registryType']}:{ident}@1.0.0", "decision": "propose",
            "reason": "ok", "license": "MIT"}  # fmt: skip


def run() -> tuple[dict[str, Any], dict[str, Any]]:
    return hp.build(ENTRIES, [], {"old-browser"}, DOWNLOADS, fake_inspect, sel.rule_filter)  # type: ignore[no-any-return]


def test_highest_download_candidate_passing_l_and_t_is_picked() -> None:
    out, _ = run()
    picks = {p["category"]: p["package"] for p in out["picked"]}
    assert picks["browser"] == "npm:browser-b@1.0.0"  # browser-a ranks higher but fails L
    browser_log = [(w["package"], w["outcome"]) for w in out["walk_log"]["browser"]]
    assert browser_log[0] == ("browser-a", "skipped: exclude: no LICENSE file in the package")
    assert browser_log[1] == ("browser-b", "PICKED (round 1)")
    assert "browser-c" not in [p for p, _ in browser_log]  # one pick per category, no round 2


def test_category_matches_only_the_name_part_after_the_last_slash() -> None:
    assert hp.server_part("io.github.x/foo") == "foo"
    out, _ = run()
    vcs = [r["name"] for r in out["ranked"]["vcs-hosting"]]
    assert "io.github.x/foo" not in vcs  # 'github' only in the namespace
    assert vcs == ["io.example/gh-reader"]  # 'GitHub' in the description does count
    assert all(
        "io.github.x/foo" not in [r["name"] for r in rows] for rows in out["ranked"].values()
    )


def test_pypi_used_only_without_a_passing_npm_candidate_and_v1_set_excluded() -> None:
    out, _ = run()
    picks = {p["category"]: p["package"] for p in out["picked"]}
    assert picks["database"] == "pypi:dbx@1.0.0"
    assert all("old-browser" not in r["package"] for rows in out["ranked"].values() for r in rows)
    assert out["total"] == len(out["picked"])  # no registry-sample rows in this fixture


def test_npm_pick_means_pypi_is_never_walked() -> None:
    out, _ = run()
    picks = {p["category"]: p["package"] for p in out["picked"]}
    assert picks["web"] == "npm:webfetch-a@1.0.0"
    assert [r["package"] for r in out["ranked"]["web"]] == [
        "npm:webfetch-a@1.0.0",
        "pypi:web-py@1.0.0",
    ]
    assert "web-py" not in [w["package"] for w in out["walk_log"]["web"]]  # never walked


def test_unknown_downloads_rank_after_zero() -> None:
    out, _ = run()
    order = [r["package"] for r in out["ranked"]["dev-tools"]]
    assert order == ["npm:dock-zero@1.0.0", "npm:dock-unknown@1.0.0"]
    assert {p["category"]: p["package"] for p in out["picked"]}[
        "dev-tools"
    ] == "npm:dock-zero@1.0.0"


def test_package_identifier_strips_registry_prefix_and_version() -> None:
    assert hp.package_identifier("npm:@x/diagram@1.0.0") == "@x/diagram"
    assert hp.package_identifier("pypi:foo-mcp@0.5.12") == "foo-mcp"
    assert hp.package_identifier("@x/diagram") == "@x/diagram"  # already bare


def test_sample_row_npm_prefix_is_not_dev_tools() -> None:
    """Label fix after run 3: 'npm:' in the sample row's package string matched \bnpm\b."""
    sample = entry("io.example/diagram", "Generate diagrams from structured JSON", "@x/diagram")
    rows = [{"name": "io.example/diagram", "package": "npm:@x/diagram@1.0.0",
             "decision": "propose", "reason": "ok"}]  # fmt: skip
    out, _ = hp.build([*ENTRIES, sample], rows, {"old-browser"}, DOWNLOADS, fake_inspect,
                      sel.rule_filter)  # fmt: skip
    [r] = out["registry_sample"]
    assert r["category"] == "other"
    assert "dev-tools" not in r["all_categories"]
