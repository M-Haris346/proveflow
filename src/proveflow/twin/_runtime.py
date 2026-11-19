"""Twin runtime: argument validation + dispatch. Its SOURCE TEXT is embedded into every
generated twin (Phase 4, D8), so this file must itself pass ``twin.guard.check_no_io`` (R5):
no imports, no method calls, no dunders. It imports nothing from proveflow.

Validated subset of JSON Schema: ``type``, ``required``, ``properties``, ``enum``. Every other
keyword is NOT enforced here; ``twin.schema_subset.skipped_keywords`` lists them at generation
time so no report ever claims an argument was validated against a keyword it skipped.
"""

JSON_TYPES = ["object", "array", "string", "number", "integer", "boolean", "null"]


def _type_ok(value: object, expected: object) -> bool:
    if isinstance(expected, list):
        return any(_type_ok(value, t) for t in expected)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    if expected == "integer":
        if isinstance(value, bool):
            return False
        if isinstance(value, int):
            return True
        return isinstance(value, float) and value % 1 == 0
    if expected == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    return True  # unknown type name: not enforced (reported by schema_subset)


def _json_equal(a: object, b: object) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, dict) and isinstance(b, dict):
        if len(a) != len(b):
            return False
        return all(k in b and _json_equal(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_json_equal(a[i], b[i]) for i in range(len(a)))
    return a == b


def validate(value: object, schema: object, path: str = "$") -> list[str]:
    """Errors for ``value`` against the supported subset of ``schema`` (empty = no error)."""
    if not isinstance(schema, dict):
        return []
    errors: list[str] = []
    if "type" in schema and not _type_ok(value, schema["type"]):
        return [f"{path}: expected type {schema['type']!r}"]
    if "enum" in schema:
        options = schema["enum"]
        if isinstance(options, list) and not any(_json_equal(value, o) for o in options):
            errors = [*errors, f"{path}: not one of the allowed values"]
    if isinstance(value, dict):
        required = schema["required"] if "required" in schema else []
        if isinstance(required, list):
            for key in required:
                if isinstance(key, str) and key not in value:
                    errors = [*errors, f"{path}: missing required property {key!r}"]
        props = schema["properties"] if "properties" in schema else {}
        if isinstance(props, dict):
            for key in sorted(k for k in value if isinstance(k, str)):
                if key in props:
                    errors = [*errors, *validate(value[key], props[key], f"{path}.{key}")]
    return errors


def _joined(parts: list[str]) -> str:
    text = ""
    for part in parts:
        text = part if text == "" else text + "; " + part
    return text


def dispatch(table: object, name: object, arguments: object) -> tuple[bool, list[object]]:
    """(is_error, content items) for one call. ``table`` maps tool name -> {"schema": ...,
    "content": [...]}; ``arguments`` None means {}."""
    if not isinstance(table, dict) or not isinstance(name, str) or name not in table:
        return True, [{"type": "text", "text": f"unknown tool: {name!r}"}]
    entry = table[name]
    if not isinstance(entry, dict) or "content" not in entry:
        return True, [{"type": "text", "text": "twin table entry malformed"}]
    args = {} if arguments is None else arguments
    schema = entry["schema"] if "schema" in entry else {}
    errors = validate(args, schema)
    if errors:
        return True, [{"type": "text", "text": "invalid arguments: " + _joined(errors)}]
    content = entry["content"]
    return False, content if isinstance(content, list) else []
