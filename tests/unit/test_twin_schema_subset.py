"""twin/schema_subset.py (D8) and R9: stored eval schemas round-trip unchanged."""

from __future__ import annotations

import json
from pathlib import Path

import mcp_types
import pytest

from proveflow.twin.schema_subset import skipped_keywords

EVAL = Path(__file__).resolve().parents[2] / "data" / "eval" / "roles" / "collected"


def stored_schemas() -> list[tuple[str, dict[str, object]]]:
    rows = [json.loads(line) for line in (EVAL / "tools.jsonl").read_text(encoding="utf-8")
            .splitlines() if line.strip()]  # fmt: skip
    pg = json.loads((EVAL / "pg-mcp-guard.json").read_text(encoding="utf-8"))["tools"]
    return [(f"{r['server_id']}/{r['tool_name']}", r["input_schema"]) for r in rows] + [
        (f"pg-mcp-guard/{t['name']}", t["input_schema"]) for t in pg
    ]


def test_supported_only_schema_skips_nothing() -> None:
    schema = {
        "type": "object", "required": ["a"], "description": "d", "$schema": "x",
        "properties": {"a": {"type": ["string", "null"], "enum": ["x", None], "title": "A"}},
    }  # fmt: skip
    assert skipped_keywords(schema) == ()


def test_unsupported_keywords_are_reported_with_paths() -> None:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "n": {"type": "integer", "minimum": 0},
            "xs": {"type": "array", "items": {"type": "string"}},
            "r": {"$ref": "#/defs/x"},
            "u": {"anyOf": [{"type": "string"}]},
            "f": {"type": "file"},
        },
    }
    assert skipped_keywords(schema) == (
        "$.additionalProperties",
        "$.properties.f.type='file'",
        "$.properties.n.minimum",
        "$.properties.r.$ref",
        "$.properties.u.anyOf",
        "$.properties.xs.items",
    )


def test_malformed_parts_are_reported() -> None:
    assert skipped_keywords({"enum": "x", "required": "a", "properties": []}) == (
        "$.enum (not a list)",
        "$.properties (not an object)",
        "$.required (not a list)",
    )
    assert skipped_keywords(False) == ("$ (non-object schema)",)
    assert skipped_keywords(True) == ()


def test_stored_eval_schemas_are_reported_deterministically() -> None:
    for _, schema in stored_schemas():
        assert skipped_keywords(schema) == skipped_keywords(json.loads(json.dumps(schema)))


def test_stored_eval_schemas_round_trip_unchanged() -> None:
    """R9: for every stored eval schema, a literal inputSchema round-trips unchanged through
    mcp_types.Tool and ListToolsResult (JSON). If pydantic ever normalises a schema, this
    fails instead of a twin silently advertising something different from the real server."""
    schemas = stored_schemas()
    assert len(schemas) == 139
    for label, schema in schemas:
        tool = mcp_types.Tool(name="x", input_schema=schema)
        wire = json.loads(mcp_types.ListToolsResult(tools=[tool]).model_dump_json(by_alias=True))
        assert wire["tools"][0]["inputSchema"] == schema, label


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("filesystem/read_text_file", ()),
        (
            "fetch/fetch",
            (
                "$.properties.max_length.maximum",
                "$.properties.max_length.minimum",
                "$.properties.start_index.minimum",
                "$.properties.url.format",
                "$.properties.url.minLength",
            ),
        ),
    ],
)
def test_known_stored_schemas_have_exactly_these_gaps(
    label: str, expected: tuple[str, ...]
) -> None:
    """Pinned against real stored metadata: a change to the supported subset breaks this."""
    schemas = dict(stored_schemas())
    assert skipped_keywords(schemas[label]) == expected
