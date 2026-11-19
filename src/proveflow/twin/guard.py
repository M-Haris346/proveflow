"""No-I/O guard for twin source code (Phase 4, rulings R-C1 to R-C5). AST only, pure.

``check_no_io(source)`` returns None or raises ``TwinGuardError(reason, lineno)`` at the FIRST
violation in source order.

What it is for (R-C1): the guard is NOT a spawn gate. A twin that fails it still starts. Its
only consequence is that a failing twin never gets dual-role forwarding (ADR-007).

HONESTY: this guard stops accidental I/O and casual misuse. It is NOT a sandbox against a
hostile script. Anyone who can write into TWIN_ROOT can already execute code on that machine,
so the attacker model in twin mode is "our own generator", not "arbitrary hostile script".

Rules (everything not explicitly allowed is refused):
* imports: exactly ``import json``, ``import anyio``, ``import mcp_types as types``,
  ``from mcp.server.lowlevel import Server``, ``from mcp.server.stdio import stdio_server``.
* ``module.ATTR`` only for ``ALLOWED_MODULE_ATTRS`` (one level: no ``json.x.y`` chains);
  ``anyio.run`` is the only anyio attribute.
* attributes on any other expression only from ``ALLOWED_OBJECT_ATTRS``.
* every dunder name or attribute is refused, and ``EXPLICIT_DUNDERS`` by name as well.
* ``FORBIDDEN_BUILTINS`` are refused as names.
* the five imported names cannot be rebound (assignment, parameter, function name, loop or
  with target), so the module-attribute rule cannot be sidestepped.
No ``if __name__ == "__main__"`` is possible (dunder), so a twin calls ``anyio.run(main)`` at
module level.

The rule tables are module globals read at call time (tests/mutation weakens one of them).
"""

from __future__ import annotations

import ast

ALLOWED_IMPORTS: frozenset[tuple[str, str | None]] = frozenset(
    {("json", None), ("anyio", None), ("mcp_types", "types")}
)
ALLOWED_FROM_IMPORTS: frozenset[tuple[str, str, str | None]] = frozenset(
    {("mcp.server.lowlevel", "Server", None), ("mcp.server.stdio", "stdio_server", None)}
)
# Names bound by the allowed imports that refer to MODULES (their attributes are restricted).
ALLOWED_MODULE_ATTRS: dict[str, frozenset[str]] = {
    "json": frozenset({"dumps"}),
    "anyio": frozenset({"run"}),
    "types": frozenset({"Tool", "ListToolsResult", "CallToolResult", "TextContent"}),
}
ALLOWED_OBJECT_ATTRS: frozenset[str] = frozenset(
    {"name", "arguments", "run", "create_initialization_options"}
)
EXPLICIT_DUNDERS: frozenset[str] = frozenset(
    {"__subclasses__", "__mro__", "__globals__", "__class__", "__dict__"}
)
FORBIDDEN_BUILTINS: frozenset[str] = frozenset(
    {"open", "exec", "eval", "compile", "__import__", "getattr", "setattr", "delattr",
     "globals", "locals", "vars", "input", "breakpoint",
     # stdout IS the MCP transport on a stdio server: one stray write corrupts the session.
     "print",  # writes to stdout
     "help",  # imports pydoc and writes to stdout (_sitebuiltins._Helper.__call__)
     "exit", "quit",  # site Quitter.__call__ runs sys.stdin.close(): stdin is the transport
     "license", "credits", "copyright",  # site _Printer: open()s files, print()s to stdout
     }
)  # fmt: skip
# Every other builtin was checked (Python 3.12) and has no path to a file, socket,
# subprocess or stdout on its own: the remaining ones only compute on their arguments
# (abs, len, sorted, isinstance, ...), build objects (dict, list, type, object, ...) or are
# reachable to the dunder protocol only through dunder names/attributes, which are refused.


class TwinGuardError(ValueError):
    def __init__(self, reason: str, lineno: int | None) -> None:
        super().__init__(f"{reason} (line {lineno})")
        self.reason = reason
        self.lineno = lineno


def _is_dunder(name: str) -> bool:
    return name in EXPLICIT_DUNDERS or (len(name) > 4 and name[:2] == "__" and name[-2:] == "__")


def _bound_names() -> frozenset[str]:
    names = {alias or mod for mod, alias in ALLOWED_IMPORTS}
    names |= {alias or name for _, name, alias in ALLOWED_FROM_IMPORTS}
    return frozenset(names)


def _root_name(node: ast.expr) -> str | None:
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


class _Checker(ast.NodeVisitor):
    def __init__(self) -> None:
        self.bound = _bound_names()

    def fail(self, reason: str, node: ast.AST) -> None:
        raise TwinGuardError(reason, getattr(node, "lineno", None))

    # --- imports --------------------------------------------------------------------
    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if (alias.name, alias.asname) not in ALLOWED_IMPORTS:
                shown = alias.name + (f" as {alias.asname}" if alias.asname else "")
                self.fail(f"import not allowed: import {shown}", node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        if node.level != 0:
            self.fail(f"relative import not allowed: from {'.' * node.level}{module}", node)
        for alias in node.names:
            if (module, alias.name, alias.asname) not in ALLOWED_FROM_IMPORTS:
                self.fail(f"import not allowed: from {module} import {alias.name}", node)

    # --- names / rebinding ------------------------------------------------------------
    def visit_Name(self, node: ast.Name) -> None:
        if node.id in FORBIDDEN_BUILTINS:
            self.fail(f"forbidden builtin: {node.id}", node)
        if _is_dunder(node.id):
            self.fail(f"dunder name refused: {node.id}", node)
        if not isinstance(node.ctx, ast.Load) and node.id in self.bound:
            self.fail(f"rebinding an imported name refused: {node.id}", node)

    def visit_arg(self, node: ast.arg) -> None:
        if _is_dunder(node.arg) or node.arg in self.bound:
            self.fail(f"parameter name refused: {node.arg}", node)
        self.generic_visit(node)

    def _check_def_name(self, name: str, node: ast.AST) -> None:
        if _is_dunder(name) or name in self.bound:
            self.fail(f"definition name refused: {name}", node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check_def_name(node.name, node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._check_def_name(node.name, node)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._check_def_name(node.name, node)
        self.generic_visit(node)

    # --- attributes -------------------------------------------------------------------
    def visit_Attribute(self, node: ast.Attribute) -> None:
        if _is_dunder(node.attr):
            self.fail(f"dunder attribute refused: .{node.attr}", node)
        value = node.value
        modules = ALLOWED_MODULE_ATTRS
        if isinstance(value, ast.Name) and value.id in modules:
            if node.attr not in modules[value.id]:
                self.fail(f"module attribute refused: {value.id}.{node.attr}", node)
        elif _root_name(value) in modules:
            self.fail(f"attribute chain on a module refused: .{node.attr}", node)
        elif node.attr not in ALLOWED_OBJECT_ATTRS:
            self.fail(f"attribute refused: .{node.attr}", node)
        self.generic_visit(node)


def check_no_io(source: str) -> None:
    """Raise ``TwinGuardError`` at the first construct outside the allowlist; else None."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise TwinGuardError(f"syntax error: {exc.msg}", exc.lineno) from None
    _Checker().visit(tree)
