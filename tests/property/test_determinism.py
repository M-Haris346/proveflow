"""Determinism: same configs in any key order -> byte-identical JSON and SARIF."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest import mock

from hypothesis import given, settings
from hypothesis import strategies as st
from typer.testing import CliRunner

import proveflow.cli as cli
from fakehome import FIXTURES, make_host

runner = CliRunner()
BASE: dict[str, dict[str, object]] = {}
for name in ("claude_desktop_config.json", "windsurf_mcp_config.json", "dot_mcp.json"):
    BASE.update(json.loads((FIXTURES / name).read_text(encoding="utf-8"))["mcpServers"])


def _run(tmp: Path, servers: dict[str, object]) -> tuple[str, str]:
    host = make_host(tmp)
    project = tmp / "project"
    project.mkdir(exist_ok=True)
    explicit = tmp / "servers.json"
    explicit.write_text(json.dumps({"mcpServers": servers}), encoding="utf-8")
    sarif = tmp / "out.sarif"
    with mock.patch.object(cli, "_host", lambda: host):
        result = runner.invoke(
            cli.app,
            [
                "scan",
                "--no-launch",
                "--json",
                "--sarif",
                str(sarif),
                "--project",
                str(project),
                "--servers",
                str(explicit),
            ],
        )
    assert result.exit_code == 0, result.output
    return result.stdout, sarif.read_text(encoding="utf-8")


@settings(max_examples=25, deadline=None)
@given(order=st.permutations(sorted(BASE)), inner=st.randoms(use_true_random=False))
def test_shuffled_input_gives_identical_output(order: list[str], inner: object) -> None:
    shuffled: dict[str, object] = {}
    for name in order:
        entry = dict(BASE[name])  # type: ignore[call-overload]
        keys = list(entry)
        inner.shuffle(keys)  # type: ignore[attr-defined]
        shuffled[name] = {k: entry[k] for k in keys}
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        first = _run(tmp, {k: BASE[k] for k in sorted(BASE)})
        second = _run(tmp, shuffled)
        third = _run(tmp, shuffled)
    assert first == second == third
    assert json.loads(first[0])["flows"]
