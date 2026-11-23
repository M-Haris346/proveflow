"""No module under tools/ is imported by src/ or tests/ (Phase 7.0e). tools/ scripts are DEV-ONLY
(several reach the network or real files, e.g. tools/ingest_corpus.py fetches the corpus), so
the suite and the package must never run them by import. The tool list is SCANNED from tools/,
never hand-written; the one sanctioned by-path loader (boundchecks.load_counter,
tools/count_t4_space.py) loads by file path, not by import.

DO NOT ADD THE TWO MISSING TOOL NAMES: the evidence replay tool and the transcript author script
are deliberately absent from this source because two guards forbid them in tests/
(runnerchecks.assert_no_test_reaches_the_evidence_replay; test_runner_safety's
test_the_author_mode_is_unreachable_from_tests); their coverage comes from the filesystem scan
(tool_stems, measured 2026-11-24 to hold both), which every assertion here prints on failure.
Naming them broke the gate twice in Phase 7.0."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def tool_stems() -> set[str]:
    return {p.stem for p in (ROOT / "tools").glob("*.py") if p.stem != "__init__"}


def imports_of(source: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names |= {f"{node.module}.{a.name}" for a in node.names}
    return names


def tool_imports(sources: dict[str, str] | None = None) -> list[str]:
    """(file, imported name) for every import of a tools/ module in src/ and tests/."""
    stems = tool_stems()
    files = sources if sources is not None else {
        str(p.relative_to(ROOT)): p.read_text(encoding="utf-8")
        for d in ("src", "tests") for p in sorted((ROOT / d).rglob("*.py"))
    }  # fmt: skip
    hits: list[str] = []
    for name, source in files.items():
        for imported in imports_of(source):
            parts = imported.split(".")
            if parts[0] == "tools" or parts[0] in stems:
                hits.append(f"{name}: {imported}")
    return sorted(hits)  # deterministic: imports_of is a set


def test_the_tool_list_is_scanned_not_listed() -> None:
    scanned = sorted(tool_stems())
    assert {"ingest_corpus", "count_t4_space"} <= set(scanned), f"scanned: {scanned}"
    assert len(scanned) > 2, f"scanned: {scanned}"  # the others: scanned, never named here


def test_no_tool_is_imported_by_src_or_tests() -> None:
    hits = tool_imports()
    assert hits == [], f"{hits}; scanned tools: {sorted(tool_stems())}"


def test_a_planted_tool_import_fails() -> None:
    """Mutation: a test that imports a tool by name is caught."""
    planted = {"tests/planted.py": "import ingest_corpus" + chr(10),
               "src/planted.py": "from tools.count_t4_space import main" + chr(10)}  # fmt: skip
    assert tool_imports(planted) == ["src/planted.py: tools.count_t4_space",
                                     "src/planted.py: tools.count_t4_space.main",
                                     "tests/planted.py: ingest_corpus"]  # fmt: skip
