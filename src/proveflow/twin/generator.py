"""Twin generator (Phase 4, D1): ONE self-contained ``.py`` per server.

Self-contained: the script imports exactly the five modules ``twin.guard`` allows (json,
anyio, mcp_types, mcp.server.lowlevel, mcp.server.stdio) and NEVER proveflow. Tool
definitions and response data are Python literals in the script, and ``twin._runtime``'s
source text is embedded verbatim. A proveflow library change therefore cannot alter twin
behaviour behind the sha256 that layer A pins.

Deterministic: same tools + same seed -> byte-identical script (twin.rng only; literals
emitted with sorted keys and ``ascii()`` strings, so the file is ASCII-only).

Per tool (from the session's classified ``ToolSpec``):
* archetype: ``select.choose_archetype`` (heuristic or override);
* private_data tools: ``honey_per_private`` honey values (default 1); total per session is
  hard-capped at ``MAX_HONEY`` (32): the R1 bound is stated with H <= 32 (ADR-004);
* a deterministic per-tool marker ``pfmark_<hex>`` derived from (server, tool, seed), in its
  own last text block: liveness evidence that the twin itself answered (R-C2);
* ``skipped`` = the inputSchema keywords the runtime does NOT validate (D8), recorded on the
  build so no report claims a skipped keyword was validated.

Limitation (F3): ONE canned response per tool. ``TABLE[tool]["content"]`` does not depend on
the arguments: they are validated (D8) but never varied on, so reading two different paths
returns identical content. Utility realism is therefore limited to calling tools correctly,
not to distinguishing their targets (docs/BACKLOG.md: argument-dependent responses).

The per-tool markers live only in the script and in ``TwinBuild.markers``; they are never
put into the proxy session or the cassette's session_start (F4), so a marker in an
upstream_response is evidence the twin itself answered.

``write_twin`` runs ``check_no_io`` on the source before writing and refuses to overwrite.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from proveflow.core.honey import HoneyKind, HoneyValue, new_honey, t4_violations
from proveflow.core.tools import ToolRole, ToolSpec
from proveflow.twin import _runtime
from proveflow.twin.archetypes import render
from proveflow.twin.guard import check_no_io
from proveflow.twin.rng import Rng
from proveflow.twin.schema_subset import skipped_keywords
from proveflow.twin.select import choose_archetype

TWIN_FORMAT = 1
MAX_HONEY = 32
MARKER_PREFIX = "pfmark_"
MARKER_HEX = 10  # <= 11 so no 12-digit run is possible; NINO-checked below
_KINDS = (HoneyKind.APIKEY, HoneyKind.TOKEN, HoneyKind.PASSWORD)
_SLUG = re.compile(r"[^a-z0-9]+")

HEADER = '''"""proveflow schema twin for server {server!s} (twin format {fmt}).

Generated; do not edit (its sha256 is pinned by the proxy session). Synthetic data only.
Imports exactly the five modules the proveflow twin guard allows; imports no proveflow.
"""
import json
import anyio
import mcp_types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

'''

FOOTER = """

async def list_tools(ctx, params):
    return types.ListToolsResult(
        tools=[
            types.Tool(name=t["name"], description=t["description"], input_schema=t["inputSchema"])
            for t in TOOLS
        ]
    )


async def call_tool(ctx, params):
    is_error, items = dispatch(TABLE, params.name, params.arguments)
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=i["text"]) for i in items],
        is_error=is_error,
    )


async def main():
    server = Server(SERVER_NAME, on_list_tools=list_tools, on_call_tool=call_tool)
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


anyio.run(main)
"""


class TwinGenerationError(ValueError):
    pass


@dataclass(frozen=True)
class TwinBuild:
    server: str
    source: str
    sha256: str
    honey: tuple[HoneyValue, ...]
    archetypes: dict[str, tuple[str, str]] = field(default_factory=dict)  # tool -> (name, why)
    markers: dict[str, str] = field(default_factory=dict)
    skipped: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def filename(self) -> str:
        return twin_filename(self.server)


def twin_slug(server: str) -> str:
    """Lowercase alphanumerics and hyphens, at most 48 characters."""
    slug = _SLUG.sub("-", server.lower()).strip("-")[:48].strip("-")
    if not slug:
        raise TwinGenerationError(f"server name {server!r} has no usable characters")
    return slug


def twin_filename(server: str) -> str:
    """``pftwin-<slug>.py``: the hyphen makes it non-importable by name (R-C4)."""
    return f"pftwin-{twin_slug(server)}.py"


def literal(value: Any) -> str:
    """Deterministic Python literal for JSON-like data: sorted dict keys, ``ascii()`` strings
    (ASCII-only output), True/False/None, ints, finite floats."""
    if value is None or isinstance(value, bool):
        return repr(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise TwinGenerationError("non-finite float in twin data")
        return repr(value)
    if isinstance(value, str):
        return ascii(value)
    if isinstance(value, list | tuple):
        return "[" + ", ".join(literal(v) for v in value) + "]"
    if isinstance(value, dict):
        items = sorted(value.items(), key=lambda kv: str(kv[0]))
        return "{" + ", ".join(f"{str(k)!a}: {literal(v)}" for k, v in items) + "}"
    raise TwinGenerationError(f"unsupported value type in twin data: {type(value).__name__}")


def _marker(rng: Rng) -> str:
    for _ in range(64):
        value = MARKER_PREFIX + rng.draw_hex(MARKER_HEX)
        if not t4_violations(value):
            return value
    raise TwinGenerationError("no T4-clean marker in 64 draws")  # pragma: no cover


def _roles(tool: ToolSpec) -> set[ToolRole]:
    return {ev.role for ev in tool.roles}


def generate_twin(
    server: str,
    tools: Sequence[ToolSpec],
    *,
    seed: str,
    honey_per_private: int = 1,
    overrides: Mapping[str, str] | None = None,
) -> TwinBuild:
    if honey_per_private < 1:
        raise TwinGenerationError("honey_per_private must be >= 1")
    names = [t.name for t in tools]
    if len(set(names)) != len(names):
        raise TwinGenerationError("duplicate tool names")
    if not tools or any(n == "*" for n in names):
        raise TwinGenerationError(
            "no tool list (server-level '*' only, e.g. scan --no-launch): cannot build a twin"
        )
    ordered = sorted(tools, key=lambda t: t.name)
    private = [t for t in ordered if ToolRole.PRIVATE_DATA in _roles(t)]
    if len(private) * honey_per_private > MAX_HONEY:
        raise TwinGenerationError(
            f"{len(private) * honey_per_private} honey values needed, cap is {MAX_HONEY}"
        )
    root = Rng(seed).derive("twin", server)
    honey: list[HoneyValue] = []
    table: dict[str, Any] = {}
    advertised: list[dict[str, Any]] = []
    build_archetypes: dict[str, tuple[str, str]] = {}
    markers: dict[str, str] = {}
    skipped: dict[str, tuple[str, ...]] = {}
    for tool in ordered:
        tool_honey: list[HoneyValue] = []
        if tool in private:
            for _ in range(honey_per_private):
                index = len(honey) + 1
                value = new_honey(
                    root.derive("honey", tool.name, str(index)).draw_hex,
                    _KINDS[(index - 1) % len(_KINDS)],
                    id=f"h{index:02d}",
                )
                honey.append(value)
                tool_honey.append(value)
        archetype, why = choose_archetype(
            tool.name, tool.description, tool.input_schema, overrides=overrides
        )
        content = render(archetype, root.derive("content", tool.name), tool.name, tool_honey)
        marker = _marker(root.derive("marker", tool.name))
        content = [*content, {"type": "text", "text": f"twin-marker: {marker}"}]
        table[tool.name] = {"schema": tool.input_schema, "content": content}
        advertised.append(
            {"name": tool.name, "description": tool.description, "inputSchema": tool.input_schema}
        )
        build_archetypes[tool.name] = (archetype, why)
        markers[tool.name] = marker
        skipped[tool.name] = skipped_keywords(tool.input_schema)

    runtime = Path(_runtime.__file__).read_text(encoding="utf-8")
    source = (
        HEADER.format(server=ascii(server), fmt=TWIN_FORMAT)
        + "# --- runtime: embedded verbatim from proveflow.twin._runtime ---\n"
        + runtime
        + "\n# --- data ---\n"
        + f"SERVER_NAME = {server!a}\n"
        + f"TOOLS = {literal(advertised)}\n"
        + f"TABLE = {literal(table)}\n"
        + FOOTER
    )
    return TwinBuild(
        server=server,
        source=source,
        sha256=hashlib.sha256(source.encode("utf-8")).hexdigest(),
        honey=tuple(honey),
        archetypes=build_archetypes,
        markers=markers,
        skipped=skipped,
    )


def write_twin(build: TwinBuild, root: Path) -> Path:
    """Guard-check the source, then write ``root/pftwin-<slug>.py``; never overwrite."""
    check_no_io(build.source)
    root.mkdir(parents=True, exist_ok=True)
    path = root / build.filename
    data = build.source.encode("utf-8")
    if hashlib.sha256(data).hexdigest() != build.sha256:  # pragma: no cover - frozen build
        raise TwinGenerationError("source does not match the build's sha256")
    with path.open("xb") as fh:  # FileExistsError if it already exists
        fh.write(data)
    return path
