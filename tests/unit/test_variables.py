"""Per-client variable syntax (P0-3): any variable => the server is never launched."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fakehome import make_host
from proveflow.core.client import ClientKind, ConfigScope
from proveflow.discover import run_discovery
from proveflow.discover.readers import read_explicit
from proveflow.discover.variables import UNDOCUMENTED, VarSyntax, find_variables


@pytest.mark.parametrize(
    ("syntax", "value", "expected"),
    [
        (VarSyntax.CLAUDE_CODE, "${PLAIN}", ("PLAIN",)),
        (VarSyntax.CLAUDE_CODE, "Bearer ${API_KEY:-PLANTEDdefault01}", ("API_KEY",)),
        (VarSyntax.CLAUDE_CODE, "${env:X}", (UNDOCUMENTED,)),
        (VarSyntax.CURSOR, "${env:GITHUB_TOKEN}", ("env:GITHUB_TOKEN",)),
        (VarSyntax.CURSOR, "${workspaceFolder}/.env", ("workspaceFolder",)),
        (VarSyntax.CURSOR, "${/}", ("/",)),
        (VarSyntax.CURSOR, "${PLAIN}", (UNDOCUMENTED,)),
        (VarSyntax.VSCODE, "${input:api-key}", ("input:api-key",)),
        (VarSyntax.VSCODE, "${env:HOME}", ("env:HOME",)),
        (VarSyntax.VSCODE, "${workspaceFolder}", ("workspaceFolder",)),
        (VarSyntax.VSCODE, "${NAME:-x}", ("NAME",)),
        (VarSyntax.WINDSURF, "Bearer ${env:AUTH_TOKEN}", ("env:AUTH_TOKEN",)),
        (VarSyntax.WINDSURF, "${PLAIN}", (UNDOCUMENTED,)),
        (VarSyntax.NONE_DOCUMENTED, "${APPDATA}", (UNDOCUMENTED,)),
        (VarSyntax.CLAUDE_CODE, "$HOME and %APPDATA% are not ${}-syntax", (UNDOCUMENTED,)),
        (VarSyntax.CLAUDE_CODE, "$HOME and %APPDATA%", ()),
    ],
)
def test_find_variables(syntax: VarSyntax, value: str, expected: tuple[str, ...]) -> None:
    assert find_variables([value], syntax) == expected


def test_defaults_are_never_recorded() -> None:
    names = find_variables(["${K:-PLANTEDdefault99}"], VarSyntax.CLAUDE_CODE)
    assert "PLANTED" not in json.dumps(names)


def test_reader_records_variables_per_client(tmp_path: Path) -> None:
    host = make_host(tmp_path)
    project = tmp_path / "p"
    (project / ".cursor").mkdir(parents=True)
    (project / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"cc": {"command": "npx", "args": ["${PKG}"]}}}), "utf-8"
    )
    (project / ".cursor" / "mcp.json").write_text(
        json.dumps({"mcpServers": {"cu": {"command": "npx", "env": {"T": "${env:TOKEN}"}}}}),
        "utf-8",
    )
    configs = run_discovery(host, project)
    by = {(c.kind, c.scope): c for c in configs}
    [cc] = by[(ClientKind.CLAUDE_CODE, ConfigScope.PROJECT)].servers
    [cu] = by[(ClientKind.CURSOR, ConfigScope.PROJECT)].servers
    assert cc.variables == ("PKG",)
    assert cu.variables == ("env:TOKEN",)


def test_explicit_file_any_braces_is_undocumented(tmp_path: Path) -> None:
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"mcpServers": {"x": {"command": "${CMD}"}}}), "utf-8")
    [cfg] = read_explicit(p)
    assert cfg.servers[0].variables == (UNDOCUMENTED,)
