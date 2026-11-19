"""No test may import a generated twin module (R-C4): a twin has no ``if __name__`` guard,
so importing one would start an MCP server. AST scan of every test file:

* no ``runpy`` anywhere;
* no ``import``/``from`` of a module whose name starts with ``pftwin`` (generated twins are
  named ``pftwin-<server>.py``, which is not even an importable identifier);
* ``importlib.util.spec_from_file_location`` only in the three existing by-path loaders, each
  for its own named script under ``scripts/``. A new by-path loader must be added here on
  purpose.
"""

from __future__ import annotations

import ast
from pathlib import Path

TESTS = Path(__file__).resolve().parents[1]
ALLOWED_BY_PATH_LOADERS = {
    ("unit/test_handpick.py", "eval_handpick"),
    ("unit/test_leak_check.py", "leak_check"),
    ("unit/test_registry_rule.py", "eval_registry_select"),
    ("unit/test_t4_space.py", "count_t4_space"),  # R10: tools/count_t4_space.py
    ("unit/test_dual_role_count.py", "count_dual_role"),  # ADR-007: tools/count_dual_role.py
}


def test_no_test_imports_a_generated_twin_module() -> None:
    by_path: set[tuple[str, str]] = set()
    for f in sorted(TESTS.rglob("*.py")):
        rel = f.relative_to(TESTS).as_posix()
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    assert a.name.split(".")[0] != "runpy", rel
                    assert not a.name.startswith("pftwin"), rel
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                assert mod.split(".")[0] != "runpy", rel
                assert not mod.startswith("pftwin"), rel
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in ("spec_from_file_location", "SourceFileLoader", "run_path"):
                    first = node.args[0] if node.args else None
                    name = first.value if isinstance(first, ast.Constant) else "<dynamic>"
                    by_path.add((rel, str(name)))
    assert by_path == ALLOWED_BY_PATH_LOADERS
