"""The runner's routing table (Phase 5, D4): tool name -> the proxy that advertised it.

Built from each proxy's own ``tools/list``. FAIL CLOSED, refuse to start, naming the tools:
* two servers advertise the same name, or names whose ``proxy.names.name_key`` collides
  (NFKC + casefold + default-ignorable removal; the proxy's own implementation, reused);
* a name is not a valid function name for an OpenAI-compatible tools list. Rule, verbatim
  from the OpenAI OpenAPI spec (openai/openai-openapi, openapi.yaml, ``FunctionObject.name``,
  fetched 2026-11-19): "Must be a-z, A-Z, 0-9, or contain underscores and dashes, with a
  maximum length of 64." Such a tool is refused, never renamed: a renamed tool would no
  longer match the tool name the proxy records in its cassette.
A misrouted call in a security tool is worse than no run.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import mcp_types

from proveflow.proxy.names import colliding_names

FUNCTION_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class RoutingError(ValueError):
    """The runner refuses to start."""


@dataclass(frozen=True)
class Route:
    server: str
    session_id: str
    tool: mcp_types.Tool


class RoutingTable:
    def __init__(self, routes: Mapping[str, Route]) -> None:
        self._routes = dict(routes)

    @classmethod
    def build(cls, advertised: Sequence[tuple[str, str, Sequence[mcp_types.Tool]]]) -> RoutingTable:
        """``advertised``: (server, session_id, tools) per proxy."""
        owners: dict[str, list[str]] = {}
        routes: dict[str, Route] = {}
        for server, session_id, tools in advertised:
            for tool in tools:
                owners.setdefault(tool.name, []).append(server)
                routes[tool.name] = Route(server, session_id, tool)
        dupes = sorted(n for n, servers in owners.items() if len(servers) > 1)
        if dupes:
            where = "; ".join(f"{n!r} on {', '.join(sorted(owners[n]))}" for n in dupes)
            raise RoutingError(f"tool name advertised by more than one server: {where}")
        look = sorted(colliding_names(owners))
        if look:
            where = ", ".join(f"{n!r} ({owners[n][0]})" for n in look)
            raise RoutingError(f"look-alike tool names across servers: {where}")
        bad = sorted(n for n in owners if not FUNCTION_NAME.fullmatch(n))
        if bad:
            where = ", ".join(f"{n!r} ({owners[n][0]})" for n in bad)
            raise RoutingError(f"not a valid function name (refused, not renamed): {where}")
        return cls(routes)

    def route(self, name: str) -> Route | None:
        return self._routes.get(name)

    def openai_tools(self) -> list[dict[str, Any]]:
        """The union of every proxy's tools, in a stable order, as an OpenAI tools list."""
        return [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": r.tool.description or "",
                    "parameters": dict(r.tool.input_schema),
                },
            }
            for name, r in sorted(self._routes.items())
        ]

    @property
    def names(self) -> frozenset[str]:
        return frozenset(self._routes)
