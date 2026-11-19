"""twin/_runtime.py: the embedded validator/dispatcher (D8), and R5 (it passes the guard)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from proveflow.twin import _runtime
from proveflow.twin._runtime import dispatch, validate
from proveflow.twin.guard import check_no_io

RUNTIME_SOURCE = Path(_runtime.__file__).read_text(encoding="utf-8")


def test_runtime_source_passes_the_guard_directly() -> None:
    """R5: the embedded text itself, not only via a full generated twin."""
    check_no_io(RUNTIME_SOURCE)


def test_runtime_has_no_imports_at_all() -> None:
    tree = ast.parse(RUNTIME_SOURCE)
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.Import | ast.ImportFrom)]


@pytest.mark.parametrize(
    ("value", "type_", "ok"),
    [
        ({}, "object", True), ([], "object", False),
        ([], "array", True), ("x", "array", False),
        ("x", "string", True), (1, "string", False),
        (3, "integer", True), (3.0, "integer", True), (3.5, "integer", False),
        (True, "integer", False), (float("inf"), "integer", False),
        (float("nan"), "integer", False),
        (2.5, "number", True), (2, "number", True), (False, "number", False),
        (True, "boolean", True), (1, "boolean", False),
        (None, "null", True), (0, "null", False),
        ("x", ["string", "null"], True), (None, ["string", "null"], True),
        (1, ["string", "null"], False),
        ("anything", "unknown-type", True),
    ],
)  # fmt: skip
def test_type_keyword(value: object, type_: object, ok: bool) -> None:
    assert (validate(value, {"type": type_}) == []) is ok


def test_required_and_nested_properties_with_paths() -> None:
    schema = {
        "type": "object",
        "required": ["path", "opts"],
        "properties": {
            "path": {"type": "string"},
            "opts": {"type": "object", "required": ["mode"],
                     "properties": {"mode": {"enum": ["r", "w"]}}},
        },
    }  # fmt: skip
    assert validate({"path": "a", "opts": {"mode": "r"}}, schema) == []
    assert validate({"opts": {"mode": "x"}}, schema) == [
        "$: missing required property 'path'",
        "$.opts.mode: not one of the allowed values",
    ]
    assert validate({"path": 1, "opts": {}}, schema) == [
        "$.opts: missing required property 'mode'",
        "$.path: expected type 'string'",
    ]


def test_enum_distinguishes_json_types() -> None:
    assert validate(True, {"enum": [1]}) != []
    assert validate(1, {"enum": [True]}) != []
    assert validate(1, {"enum": [1.0]}) == []
    assert validate({"a": [1]}, {"enum": [{"a": [1]}]}) == []


def test_unsupported_keywords_are_not_enforced() -> None:
    """Documented: these are SKIPPED (and reported by schema_subset), never enforced."""
    assert validate("", {"type": "string", "minLength": 5}) == []
    assert validate({"x": 1}, {"type": "object", "additionalProperties": False}) == []


def test_dispatch() -> None:
    table = {"t": {"schema": {"type": "object", "required": ["q"]},
                   "content": [{"type": "text", "text": "ok"}]}}  # fmt: skip
    assert dispatch(table, "t", {"q": 1}) == (False, [{"type": "text", "text": "ok"}])
    is_error, content = dispatch(table, "t", None)  # None means {}
    assert is_error and content == [
        {"type": "text", "text": "invalid arguments: $: missing required property 'q'"}
    ]
    assert dispatch(table, "nope", {}) == (True, [{"type": "text", "text": "unknown tool: 'nope'"}])
    assert dispatch(table, 5, {})[0] is True


JSON = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats(allow_nan=True) | st.text(max_size=8),
    lambda inner: (
        st.lists(inner, max_size=3) | st.dictionaries(st.text(max_size=5), inner, max_size=3)
    ),
    max_leaves=10,
)  # fmt: skip


@settings(max_examples=300, deadline=None)
@given(value=JSON, schema=JSON)
def test_validate_never_raises_on_arbitrary_json(value: object, schema: object) -> None:
    errors = validate(value, schema)
    assert isinstance(errors, list) and all(isinstance(e, str) for e in errors)
