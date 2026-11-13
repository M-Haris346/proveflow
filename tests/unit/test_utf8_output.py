"""Machine-readable output is UTF-8 whatever the stdout encoding (author's real-machine bug:
`scan --json > file` on Windows wrote an em dash as cp1252 byte 0x97).

stdout is simulated as ``io.TextIOWrapper(BytesIO, encoding="cp1252")``, which is what a
redirected stdout is on a Windows machine with ANSI code page 1252. Fixture configs only;
nothing is launched (introspection is replaced by a canned result).
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

import proveflow.cli as cli
from fakehome import make_host
from proveflow.discover.readers import read_explicit
from proveflow.introspect.cache import spec_key
from proveflow.report.models import IntrospectionResult, IntrospectionStatus, RawTool

EM_DASH = "—"  # cp1252 encodes it as 0x97
NON_BMP = "\U0001d11e"  # musical G clef; cp1252 cannot encode it at all
DESCRIPTION = f"Run a query {EM_DASH} read-only {NON_BMP} done"


def _cp1252_stdout(monkeypatch: pytest.MonkeyPatch) -> io.BytesIO:
    """Call inside the test body: pytest re-installs its own capture stream as sys.stdout
    at the start of the call phase, so a fixture's replacement would be discarded."""
    raw = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(raw, encoding="cp1252", newline=None))
    return raw


def _servers(tmp_path: Path, name: str = "db") -> Path:
    path = tmp_path / "servers.json"
    path.write_text(
        json.dumps({"mcpServers": {name: {"command": sys.executable, "args": ["-c", "0"]}}}),
        encoding="utf-8",
    )
    return path


def _patch_scan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, servers: Path) -> Path:
    host = make_host(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    [cfg] = read_explicit(servers)
    [spec] = cfg.servers
    result = IntrospectionResult(
        status=IntrospectionStatus.OK,
        tools=(
            RawTool(
                name="run_query",
                description=DESCRIPTION,
                input_schema={"properties": {"sql": {"description": f"SQL {EM_DASH} {NON_BMP}"}}},
            ),
        ),
        baseline="cache_disabled",
    )
    monkeypatch.setattr(cli, "_host", lambda: host)
    monkeypatch.setattr(cli, "_introspect", lambda *_a, **_k: {spec_key(spec): result})
    return project


def _decoded(raw: io.BytesIO) -> str:
    sys.stdout.flush()
    data = raw.getvalue()
    assert b"\x97" not in data  # the cp1252 em dash byte
    assert b"\r\n" not in data  # LF only, as to_json promises
    return data.decode("utf-8")  # raises if not valid UTF-8


def test_scan_json_is_utf8_on_cp1252_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    servers = _servers(tmp_path)
    project = _patch_scan(tmp_path, monkeypatch, servers)
    sarif = tmp_path / "scan.sarif"
    cp1252_stdout = _cp1252_stdout(monkeypatch)
    cli.scan(project=project, servers=servers, json_output=True, sarif=sarif)
    data = json.loads(_decoded(cp1252_stdout))
    [srv] = [s for p in data["profiles"] for s in p["servers"]]
    [tool] = srv["tools"]
    assert tool["description"] == DESCRIPTION
    # SARIF file: also UTF-8 (written with an explicit encoding)
    json.loads(sarif.read_bytes().decode("utf-8"))


def test_discover_json_is_utf8_on_cp1252_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    name = f"db {EM_DASH} {NON_BMP}"
    servers = _servers(tmp_path, name)
    host = make_host(tmp_path)
    monkeypatch.setattr(cli, "_host", lambda: host)
    project = tmp_path / "project"
    project.mkdir()
    cp1252_stdout = _cp1252_stdout(monkeypatch)
    cli.discover(project=project, servers=servers, json_output=True)
    data = json.loads(_decoded(cp1252_stdout))
    names = [s["name"] for c in data["configs"] for s in c["servers"]]
    assert name in names


def test_terminal_output_keeps_the_stream_encoding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Rich table path is unchanged: it still writes through the text stream."""
    servers = _servers(tmp_path, f"db {EM_DASH} x")  # cp1252-encodable on purpose
    project = _patch_scan(tmp_path, monkeypatch, servers)
    cp1252_stdout = _cp1252_stdout(monkeypatch)
    cli.scan(project=project, servers=servers, json_output=False)
    sys.stdout.flush()
    text = cp1252_stdout.getvalue().decode("cp1252")
    assert f"db {EM_DASH} x" in text
    assert "Toxic flows" in text


def test_machine_output_falls_back_for_text_only_streams(monkeypatch: pytest.MonkeyPatch) -> None:
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    cli._emit_machine_output(f'{{"d": "{EM_DASH}{NON_BMP}"}}\n')
    assert json.loads(buf.getvalue()) == {"d": EM_DASH + NON_BMP}
