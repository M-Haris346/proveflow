"""Rendered-text assertions do not depend on the path, the terminal or the console width
(Phase 4 finding; tests/widths.py explains the mechanism and the bound)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from widths import assert_long_command_prompt_is_exact, assert_render_width_is_pinned

TESTS = Path(__file__).resolve().parents[1]

# EXACT set of test files that may name the COLUMNS variable (keys compared with ==), each
# with its reason. A future narrow-width rendering test goes here, with a reason.
COLUMNS_USERS = {
    "conftest.py": "sets the pinned TEST_COLUMNS for every test",
    "widths.py": "defines the pin and its named check",
    "unit/test_render_width.py": "this guard",
    "mutation/test_render_width_mutation.py": "restores the old 400 to prove the checks bite",
    # The ONLY test helper allowed to NARROW the width: it verifies that redaction survives
    # hard wrapping, a property that exists only when wrapping happens (F7).
    "narrowchecks.py": "narrow-width redaction check (only allowed narrowing)",
}


def test_render_width_is_pinned_above_the_path_bound() -> None:
    assert_render_width_is_pinned()


def test_a_very_long_command_line_prompt_is_exact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert_long_command_prompt_is_exact(tmp_path, monkeypatch)


def test_no_test_sets_its_own_width() -> None:
    """Regression guard: no test sets COLUMNS itself, and every Console(width=...) in the
    suite uses TEST_COLUMNS (never a literal such as 250 or 400)."""
    users: set[str] = set()
    literal_widths: list[str] = []
    for path in sorted(TESTS.rglob("*.py")):
        rel = path.relative_to(TESTS).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value == "COLUMNS":
                users.add(rel)
            if isinstance(node, ast.Call) and ast.unparse(node.func).endswith("Console"):
                for kw in node.keywords:
                    if kw.arg == "width" and ast.unparse(kw.value) != "TEST_COLUMNS":
                        literal_widths.append(f"{rel}:{node.lineno}")
    assert users == set(COLUMNS_USERS)
    assert literal_widths == []


def test_the_narrow_width_opt_out_is_the_only_one() -> None:
    """Only narrowchecks.py sets COLUMNS to anything but the pin, and it narrows it."""
    import narrowchecks

    assert int(narrowchecks.NARROW_COLUMNS) <= 80  # a real narrow terminal or narrower
    narrowing = []
    for path in sorted(TESTS.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and ast.unparse(node.func).endswith("setenv")
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "COLUMNS"
                and ast.unparse(node.args[1]) not in ("str(TEST_COLUMNS)",)
            ):
                narrowing.append((path.relative_to(TESTS).as_posix(), ast.unparse(node.args[1])))
    assert narrowing == [
        ("mutation/test_render_width_mutation.py", "'400'"),  # the pre-fix value, mutation
        ("narrowchecks.py", "NARROW_COLUMNS"),
    ]
