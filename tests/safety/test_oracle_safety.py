"""Oracle import guard (A4): ``proveflow.oracle`` may import ``proveflow.proxy.cassette``,
``proveflow.proxy.names`` and ``proveflow.core.*``; never ``proveflow.proxy.server``,
``proveflow.proxy.upstream``, the MCP SDK (``mcp*``, ``mcp_types*``) or a network client.
Checked in a fresh ``python -I`` interpreter (import-time closure) and by an AST scan.

Note: ``socket`` IS present in the fresh interpreter, loaded by the stdlib through
``proveflow/__init__.py`` (importlib.metadata -> email.utils), not by the oracle; it is not
asserted absent. ``http.client``, ``urllib.request`` and ``ssl`` are.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import proveflow.oracle

ORACLE_DIR = Path(proveflow.oracle.__file__).parent
FORBIDDEN_EXACT = ("proveflow.proxy.server", "proveflow.proxy.upstream")
FORBIDDEN_TOP = ("mcp", "mcp_types")
NETWORK = ("http.client", "urllib.request", "ssl")
ALLOWED_PROVEFLOW = ("proveflow.core", "proveflow.proxy.cassette", "proveflow.proxy.names",
                     "proveflow.oracle")  # fmt: skip


def _forbidden(name: str) -> bool:
    return (
        name in FORBIDDEN_EXACT
        or name.split(".")[0] in FORBIDDEN_TOP
        or name in NETWORK
        or name.startswith(tuple(n + "." for n in NETWORK))
    )


def test_fresh_interpreter_oracle_import_guard() -> None:
    code = (
        "import importlib, json, pkgutil, sys\n"
        "import proveflow.oracle as o\n"
        "mods = sorted(m.name for m in pkgutil.iter_modules(o.__path__, 'proveflow.oracle.'))\n"
        "for m in mods: importlib.import_module(m)\n"
        "print(json.dumps({'mods': mods, 'loaded': sorted(sys.modules)}))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-I", "-c", code], capture_output=True, timeout=120, check=True
    )
    data = json.loads(proc.stdout)
    assert {"proveflow.oracle.matcher", "proveflow.oracle.rules"} <= set(data["mods"])
    assert [m for m in data["loaded"] if _forbidden(m)] == []


def test_oracle_sources_import_only_allowed_proveflow_modules() -> None:
    files = sorted(ORACLE_DIR.glob("*.py"))
    assert {f.name for f in files} >= {"canary.py", "matcher.py", "rules.py"}
    for f in files:
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                assert not _forbidden(name), (f.name, name)
                if name.startswith("proveflow"):
                    assert name.startswith(ALLOWED_PROVEFLOW), (f.name, name)


def test_guard_flags_what_it_should() -> None:
    for name in (*FORBIDDEN_EXACT, "mcp", "mcp.client.session", "mcp_types", "http.client"):
        assert _forbidden(name)
    assert not _forbidden("proveflow.proxy.cassette")
