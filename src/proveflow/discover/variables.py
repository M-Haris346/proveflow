"""Per-client variable syntax in MCP configs (docs/CLIENT_CONFIGS.md §Variables).

proveflow never expands variables. A server whose launch values contain ANY variable
reference is not launched (status ``unresolved_variables``): its real command/args/env
are only known to the client. Each client's documented syntax is recognised by name; any
other ``${...}`` is reported as ``undocumented`` (still not launched: fail safe).

Only variable NAMES are recorded, never ``:-default`` values (a default may be a secret).

Documented syntax (official docs, accessed 2026-11-11):
- Claude Code ``.mcp.json``/``~/.claude.json``: ``${VAR}``, ``${VAR:-default}`` in command,
  args, env, url, headers (code.claude.com/docs/en/mcp).
- Cursor: ``${env:NAME}``, ``${userHome}``, ``${workspaceFolder}``,
  ``${workspaceFolderBasename}``, ``${pathSeparator}``, ``${/}`` in command, args, env,
  url, headers (cursor.com/docs/context/mcp).
- VS Code: ``${input:...}``, ``${env:...}``, predefined ``${workspaceFolder}`` etc.,
  ``${command:...}``; portable files ``${NAME}`` / ``${NAME:-default}``
  (code.visualstudio.com/docs/copilot/reference/mcp-configuration).
- Windsurf: ``${env:VAR}`` in command, args, env, serverUrl, url, headers
  (docs.devin.ai/windsurf/plugins/cascade/mcp).
- Claude Desktop and ``--servers`` files: no expansion documented -> ``undocumented``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from enum import StrEnum


class VarSyntax(StrEnum):
    CLAUDE_CODE = "claude_code"
    CURSOR = "cursor"
    VSCODE = "vscode"
    WINDSURF = "windsurf"
    NONE_DOCUMENTED = "none_documented"


_NAME = r"[A-Za-z_][A-Za-z0-9_]*"
_PATTERNS: dict[VarSyntax, re.Pattern[str]] = {
    VarSyntax.CLAUDE_CODE: re.compile(rf"\$\{{({_NAME})(?::-[^}}]*)?\}}"),
    VarSyntax.CURSOR: re.compile(
        r"\$\{(env:[^}]+|userHome|workspaceFolder|workspaceFolderBasename|pathSeparator|/)\}"
    ),
    VarSyntax.VSCODE: re.compile(
        rf"\$\{{((?:input|env|command|config):[^}}]+|{_NAME})(?::-[^}}]*)?\}}"
    ),
    VarSyntax.WINDSURF: re.compile(r"\$\{(env:[^}]+)\}"),
}
_ANY = re.compile(r"\$\{[^}]*\}")
UNDOCUMENTED = "<undocumented ${...} syntax>"


def find_variables(values: Iterable[str], syntax: VarSyntax) -> tuple[str, ...]:
    """Variable names referenced in ``values`` (sorted, unique, no defaults)."""
    found: set[str] = set()
    pattern = _PATTERNS.get(syntax)
    for value in values:
        rest = value
        if pattern is not None:
            for match in pattern.finditer(value):
                found.add(match.group(1))
            rest = pattern.sub("", value)
        if _ANY.search(rest):
            found.add(UNDOCUMENTED)
    return tuple(sorted(found))
