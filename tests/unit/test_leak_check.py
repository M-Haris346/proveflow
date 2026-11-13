"""Self-test of scripts/leak_check.py `files` mode: it must catch a planted raw config value
in (a) scan JSON tool metadata, (b) a SARIF file, (c) a tool-cache file; and report 0 hits
on clean outputs. Values are never printed, only locations."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

from fakehome import full_setup

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "leak_check.py"
# A value that IS in the fixture configs (cursor_mcp.json env API_KEY).
PLANTED = "PLANTEDcursorEnv00001"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("leak_check", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


lc = _load()


def _scan_json(description: str) -> str:
    return json.dumps(
        {
            "profiles": [
                {
                    "id": "p",
                    "servers": [
                        {
                            "key": "srv",
                            "tools": [
                                {"name": "send_email", "description": description,
                                 "input_schema": {"properties": {"to": {"type": "string"}}}},
                            ],
                        }
                    ],
                }
            ]
        }
    )  # fmt: skip


@pytest.fixture
def setup(tmp_path: Path):  # type: ignore[no-untyped-def]
    s = full_setup(tmp_path)
    outputs = tmp_path / "out"
    cache = tmp_path / "cache"
    (outputs).mkdir()
    (cache / "tools").mkdir(parents=True)
    (outputs / "scan.json").write_text(_scan_json("Send an email."), encoding="utf-8")
    (outputs / "scan.sarif").write_text('{"runs": []}', encoding="utf-8")
    (cache / "tools" / "k.json").write_text('{"tools": {}}', encoding="utf-8")
    return s, outputs, cache


def test_clean_outputs_have_no_hits(setup) -> None:  # type: ignore[no-untyped-def]
    s, outputs, cache = setup
    result = lc.check_files(s.host, s.project, outputs, cache)
    assert result["hits"] == []
    assert result["values_checked"] > 0
    assert result["cache_files"] == 1


@pytest.mark.parametrize(
    "where",
    ["scan_json_tool_description", "scan_json_tool_schema", "sarif", "cache"],
)
def test_planted_value_is_caught(setup, where: str) -> None:  # type: ignore[no-untyped-def]
    s, outputs, cache = setup
    if where == "scan_json_tool_description":
        (outputs / "scan.json").write_text(_scan_json(f"Send. key={PLANTED}"), encoding="utf-8")
        target = "scan.json"
    elif where == "scan_json_tool_schema":
        doc = json.loads(_scan_json("Send."))
        doc["profiles"][0]["servers"][0]["tools"][0]["input_schema"]["default"] = PLANTED
        (outputs / "scan.json").write_text(json.dumps(doc), encoding="utf-8")
        target = "scan.json"
    elif where == "sarif":
        (outputs / "scan.sarif").write_text(
            json.dumps({"runs": [{"results": [{"message": {"text": PLANTED}}]}]}), "utf-8"
        )
        target = "scan.sarif"
    else:
        (cache / "tools" / "k.json").write_text(json.dumps({"leak": PLANTED}), "utf-8")
        target = "k.json"
    result = lc.check_files(s.host, s.project, outputs, cache)
    assert any(h.endswith(target) for h in result["hits"]), result["hits"]
    assert all(PLANTED not in h for h in result["hits"])  # locations only, never values


def test_suspicious_tool_tokens_reports_locations_only(setup) -> None:  # type: ignore[no-untyped-def]
    s, outputs, cache = setup
    token = "Zq8xK2mP9vR4tY7wB3nL"
    (outputs / "scan.json").write_text(_scan_json(f"Use {token} please"), encoding="utf-8")
    result = lc.check_files(s.host, s.project, outputs, cache)
    assert result["suspicious_tool_tokens"] == [
        f"scan.json: p / srv / send_email / description (len {len(token)})"
    ]
    assert token not in json.dumps(result["suspicious_tool_tokens"])


def _scan_json_with_schema(schema_value: str) -> str:
    doc = json.loads(_scan_json("Send an email."))
    doc["profiles"][0]["servers"][0]["tools"][0]["input_schema"]["$schema"] = schema_value
    return json.dumps(doc)


@pytest.mark.parametrize(
    "uri",
    [
        "http://json-schema.org/draft-07/schema#",
        "http://json-schema.org/draft-04/schema#",
        "https://json-schema.org/draft/2019-09/schema",
        "https://json-schema.org/draft/2020-12/schema",
        "https://json-schema.org/draft-07/schema",  # scheme / '#' variants
    ],
)
def test_meta_schema_uri_is_not_a_review_hit(setup, uri: str) -> None:  # type: ignore[no-untyped-def]
    s, outputs, cache = setup
    (outputs / "scan.json").write_text(_scan_json_with_schema(uri), encoding="utf-8")
    assert lc.check_files(s.host, s.project, outputs, cache)["suspicious_tool_tokens"] == []


@pytest.mark.parametrize(
    "value",
    [
        "http://json-schema.org/draft-07/schema#Zq8xK2mP9vR4tY7wB3nL",  # extra text after it
        "http://evil.example/org/draft-07/schema#",  # same token, other host
        "Zq8xK2mP9vR4tY7wB3nL",  # a token directly in $schema
    ],
)
def test_anything_else_in_schema_is_still_reported(setup, value: str) -> None:  # type: ignore[no-untyped-def]
    s, outputs, cache = setup
    (outputs / "scan.json").write_text(_scan_json_with_schema(value), encoding="utf-8")
    hits = lc.check_files(s.host, s.project, outputs, cache)["suspicious_tool_tokens"]
    assert hits and all("send_email / schema" in h for h in hits)


def test_cli_exit_codes(setup, monkeypatch: pytest.MonkeyPatch, capsys) -> None:  # type: ignore[no-untyped-def]
    s, outputs, cache = setup
    monkeypatch.setattr(lc.HostEnv, "current", staticmethod(lambda: s.host))
    args = [
        "files",
        "--outputs",
        str(outputs),
        "--cache-dir",
        str(cache),
        "--project",
        str(s.project),
    ]
    assert lc.main(args) == 0
    (cache / "tools" / "k.json").write_text(json.dumps({"leak": PLANTED}), "utf-8")
    assert lc.main(args) == 1
    printed = capsys.readouterr().out
    assert "LEAK at" in printed
    assert PLANTED not in printed


@pytest.mark.parametrize("encoding", ["utf-16", "utf-8-sig", "utf-8"])
def test_planted_value_caught_in_any_bom_encoding(setup, encoding: str) -> None:  # type: ignore[no-untyped-def]
    """PowerShell 5.1 `>` writes UTF-16LE with a BOM; it must not hide a leak."""
    s, outputs, cache = setup
    (outputs / "scan.json").write_text(_scan_json(f"k={PLANTED}"), encoding=encoding)
    result = lc.check_files(s.host, s.project, outputs, cache)
    assert any(h.endswith("scan.json") for h in result["hits"]), (encoding, result["hits"])
