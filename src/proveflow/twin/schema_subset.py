"""Which inputSchema keywords the twin enforces (D8), and which it skips.

The twin's runtime validator (``twin._runtime.validate``) enforces only ``type``,
``required``, ``properties`` and ``enum``. ``skipped_keywords(schema)`` returns the JSON paths
of every other VALIDATING keyword (and of unknown ``type`` names), so the generator can record
them and no report ever claims an argument was validated against a keyword that was skipped.
Pure annotations (``description``, ``title``, ``default``, ``examples``, ``$schema``,
``$comment``, ``$id``, ``deprecated``, ``readOnly``, ``writeOnly``) do not constrain values and
are not reported.
"""

from __future__ import annotations

from typing import Any

SUPPORTED: frozenset[str] = frozenset({"type", "required", "properties", "enum"})
ANNOTATIONS: frozenset[str] = frozenset(
    {"description", "title", "default", "examples", "$schema", "$comment", "$id",
     "deprecated", "readOnly", "writeOnly"}
)  # fmt: skip
KNOWN_TYPES: frozenset[str] = frozenset(
    {"object", "array", "string", "number", "integer", "boolean", "null"}
)


def _walk(schema: Any, path: str, out: list[str]) -> None:
    if not isinstance(schema, dict):
        if schema is not True:  # `true` accepts everything (nothing to skip)
            out.append(f"{path} (non-object schema)")
        return
    for key in schema:
        if key not in SUPPORTED and key not in ANNOTATIONS:
            out.append(f"{path}.{key}")
    if "type" in schema:
        declared = schema["type"]
        for name in declared if isinstance(declared, list) else [declared]:
            if name not in KNOWN_TYPES:
                out.append(f"{path}.type={name!r}")
    if "enum" in schema and not isinstance(schema["enum"], list):
        out.append(f"{path}.enum (not a list)")
    if "required" in schema and not isinstance(schema["required"], list):
        out.append(f"{path}.required (not a list)")
    props = schema.get("properties")
    if props is not None:
        if not isinstance(props, dict):
            out.append(f"{path}.properties (not an object)")
        else:
            for name, sub in props.items():
                _walk(sub, f"{path}.properties.{name}", out)


def skipped_keywords(schema: Any) -> tuple[str, ...]:
    """Sorted, unique JSON paths of what the twin does NOT validate in ``schema``."""
    out: list[str] = []
    _walk(schema, "$", out)
    return tuple(sorted(set(out)))
