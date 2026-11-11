"""Normalize one client's server mapping into redacted ``ServerSpec``s.

Shapes per client are documented in docs/CLIENT_CONFIGS.md. Raw values exist only
inside this module's local variables while a ``ServerSpec`` is built; env and header
values are redacted completely, free text by ``redact_rules``. Error messages name
fields, never values.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from proveflow.core.client import ConfigScope, ServerSpec, TransportKind
from proveflow.core.redact import RedactedValue
from proveflow.discover.redact_rules import redact_args, redact_text
from proveflow.discover.variables import VarSyntax, find_variables

KNOWN_KEYS = frozenset({"command", "args", "env", "headers", "type", "envFile"})
# Present => the server needs credentials/OAuth proveflow will not handle in Phase 1.
# `headersHelper` is a command; proveflow never runs it.
AUTH_KEYS = frozenset({"oauth", "headersHelper", "authServerMetadataUrl"})
_TYPE_MAP = {
    "stdio": TransportKind.STDIO,
    "http": TransportKind.HTTP,
    "sse": TransportKind.SSE,
    "ws": TransportKind.WS,
}
_TYPE_SHAPE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


class EntryError(ValueError):
    """A malformed server entry. The message names fields only, never values."""


def scalar_to_str(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, bool | int | float):
        return json.dumps(value)
    return None


def _redact_mapping(name: str, field: str, value: Any) -> dict[str, RedactedValue]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise EntryError(f"server {name!r}: {field!r} must be an object")
    out: dict[str, RedactedValue] = {}
    for key in sorted(value):
        text = scalar_to_str(value[key])
        if text is None:
            raise EntryError(f"server {name!r}: {field}.{key} must be a string")
        out[key] = RedactedValue.from_secret(text)
    return out


def parse_entry(
    name: str,
    entry: Any,
    *,
    url_keys: tuple[str, ...],
    source_file: Path,
    scope: ConfigScope,
    project: str | None,
    var_syntax: VarSyntax = VarSyntax.NONE_DOCUMENTED,
) -> ServerSpec:
    if not isinstance(entry, dict):
        raise EntryError(f"server {name!r}: entry must be an object")

    command_raw = entry.get("command")
    if command_raw is not None and not isinstance(command_raw, str):
        raise EntryError(f"server {name!r}: 'command' must be a string")

    args_raw = entry.get("args", [])
    if not isinstance(args_raw, list) or not all(isinstance(a, str) for a in args_raw):
        raise EntryError(f"server {name!r}: 'args' must be a list of strings")

    url_raw: str | None = None
    for key in url_keys:
        candidate = entry.get(key)
        if candidate is None:
            continue
        if not isinstance(candidate, str):
            raise EntryError(f"server {name!r}: {key!r} must be a string")
        url_raw = candidate
        break

    env_file_raw = entry.get("envFile")
    if env_file_raw is not None and not isinstance(env_file_raw, str):
        raise EntryError(f"server {name!r}: 'envFile' must be a string")

    type_raw = entry.get("type")
    declared_type: str | None = None
    if type_raw is not None:
        if not isinstance(type_raw, str):
            raise EntryError(f"server {name!r}: 'type' must be a string")
        declared_type = type_raw if _TYPE_SHAPE.match(type_raw) else "<invalid>"
        transport = _TYPE_MAP.get(type_raw, TransportKind.UNKNOWN)
    elif command_raw is not None:
        transport = TransportKind.STDIO
    elif url_raw is not None:
        transport = TransportKind.HTTP
    else:
        raise EntryError(f"server {name!r}: neither 'command' nor a url field is set")

    env = _redact_mapping(name, "env", entry.get("env"))
    headers = _redact_mapping(name, "headers", entry.get("headers"))
    known = KNOWN_KEYS | set(url_keys)
    raw_values = [v for v in (command_raw, url_raw, env_file_raw) if v is not None] + list(args_raw)
    for mapping_key in ("env", "headers"):
        mapping = entry.get(mapping_key) or {}
        raw_values += [t for t in (scalar_to_str(v) for v in mapping.values()) if t is not None]
    variables = find_variables(raw_values, var_syntax)
    del raw_values
    return ServerSpec(
        name=name,
        transport=transport,
        declared_type=declared_type,
        command=redact_text(command_raw) if command_raw is not None else None,
        args=redact_args(args_raw),
        url=redact_text(url_raw) if url_raw is not None else None,
        env=env,
        headers=headers,
        env_file=redact_text(env_file_raw) if env_file_raw is not None else None,
        auth_hint=bool(headers) or any(k in entry for k in AUTH_KEYS),
        ignored_keys=tuple(sorted(k for k in entry if k not in known)),
        source_file=source_file,
        scope=scope,
        project=project,
        variables=variables,
    )


def parse_servers(
    mapping: Any,
    *,
    key_name: str,
    url_keys: tuple[str, ...],
    source_file: Path,
    scope: ConfigScope,
    project: str | None = None,
    var_syntax: VarSyntax = VarSyntax.NONE_DOCUMENTED,
) -> tuple[tuple[ServerSpec, ...], tuple[str, ...]]:
    """Return (servers, entry_errors). A bad entry never hides the good ones."""
    if mapping is None:
        return (), ()
    if not isinstance(mapping, dict):
        return (), (f"{key_name!r} must be an object",)
    servers: list[ServerSpec] = []
    errors: list[str] = []
    for name in sorted(mapping):
        try:
            servers.append(
                parse_entry(
                    name,
                    mapping[name],
                    url_keys=url_keys,
                    source_file=source_file,
                    scope=scope,
                    project=project,
                    var_syntax=var_syntax,
                )
            )
        except EntryError as exc:
            errors.append(str(exc))
    return tuple(servers), tuple(errors)
