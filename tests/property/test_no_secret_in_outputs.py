"""Property: planted secrets never appear in discover/scan output in any format —
terminal, JSON, SARIF, or logs (at DEBUG)."""

from __future__ import annotations

import io
import json
import logging
import tempfile
from pathlib import Path
from unittest import mock

from hypothesis import given, settings
from hypothesis import strategies as st
from typer.testing import CliRunner

import proveflow.cli as cli
from fakehome import MARKER, claude_desktop_path, make_host
from proveflow.logging_setup import JsonFormatter

ALNUM = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
    min_size=4,
    max_size=24,
)
# Env / header values: any text at all (they are always fully redacted).
ANY = st.text(min_size=0, max_size=40)

runner = CliRunner()


def secret(suffix: str) -> str:
    return MARKER + suffix


@st.composite
def configs(draw: st.DrawFn) -> dict[str, object]:
    s = [secret(draw(ALNUM)) for _ in range(6)]
    env_val = MARKER + draw(ANY)
    hdr_val = MARKER + draw(ANY)
    flag = draw(st.sampled_from(["--api-key", "--token", "--secret", "--password", "--auth-token"]))
    qname = draw(st.sampled_from(["token", "api_key", "access_token", "apikey", "sig"]))
    return {
        "mcpServers": {
            "gmail": {
                "command": "npx",
                "args": ["-y", "gmail-mcp", f"{flag}={s[0]}", flag, s[1], "-e", f"MY_TOKEN={s[2]}"],
                "env": {"GMAIL_KEY": env_val, "OTHER": MARKER},
            },
            "remote": {
                "type": "http",
                "url": f"https://u:{s[3]}@mcp.example.com/mcp?{qname}={s[4]}&page=1",
                "headers": {"Authorization": hdr_val, "X": f"Bearer {s[5]}"},
            },
            "fetch": {"command": "uvx", "args": ["mcp-server-fetch", "--header", f"Bearer {s[5]}"]},
        }
    }


def _capture_logs() -> tuple[logging.Handler, io.StringIO]:
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(JsonFormatter())
    logging.getLogger("proveflow").addHandler(handler)
    return handler, buf


@settings(max_examples=40, deadline=None)
@given(cfg=configs())
def test_planted_secrets_never_in_any_output(cfg: dict[str, object]) -> None:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        host = make_host(tmp)
        project = tmp / "project"
        project.mkdir()
        desktop = claude_desktop_path(host)
        desktop.parent.mkdir(parents=True)
        desktop.write_text(json.dumps(cfg), encoding="utf-8")
        explicit = tmp / "servers.json"
        explicit.write_text(json.dumps(cfg), encoding="utf-8")
        sarif = tmp / "out.sarif"
        handler, logs = _capture_logs()
        outputs: list[str] = []
        try:
            with mock.patch.object(cli, "_host", lambda: host):
                base = ["--log-level", "DEBUG"]
                common = ["--project", str(project), "--servers", str(explicit)]
                for args in (
                    ["discover", *common],
                    ["discover", "--json", *common],
                    ["scan", "--no-launch", *common],
                    ["scan", "--no-launch", "--json", "--sarif", str(sarif), *common],
                ):
                    result = runner.invoke(cli.app, [*base, *args])
                    assert result.exit_code == 0, result.output
                    outputs += [result.output, result.stderr]
            outputs.append(sarif.read_text(encoding="utf-8"))
        finally:
            logging.getLogger("proveflow").removeHandler(handler)
        outputs.append(logs.getvalue())
        assert logs.getvalue(), "DEBUG logging produced nothing; the log check would be vacuous"
        for out in outputs:
            assert MARKER not in out
            assert MARKER not in "".join(out.split())  # no value split across wrapped lines
