"""`discover` and `scan --no-launch` never import the MCP SDK (fresh interpreter)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = r"""
import json, sys
sys.path.insert(0, {tests!r})
from fakehome import full_setup
from pathlib import Path
from typer.testing import CliRunner
import proveflow.cli as cli
s = full_setup(Path({tmp!r}))
cli._host = lambda: s.host
r = CliRunner()
p = str(s.project)
codes = [
    r.invoke(cli.app, ["discover", "--project", p]).exit_code,
    r.invoke(cli.app, ["scan", "--no-launch", "--json", "--project", p]).exit_code,
]
loaded = sorted(m for m in sys.modules if m == "mcp" or m.startswith(("mcp.", "mcp_types")))
print(json.dumps({{"codes": codes, "mcp": loaded}}))
"""


def test_mcp_not_imported_without_launch(tmp_path: Path) -> None:
    tests_dir = str(Path(__file__).resolve().parents[1])
    code = SCRIPT.format(tests=tests_dir, tmp=str(tmp_path))
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120, check=True
    )
    result = json.loads(out.stdout.strip().splitlines()[-1])
    assert result["codes"] == [0, 0]
    assert result["mcp"] == []
