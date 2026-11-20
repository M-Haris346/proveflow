"""runner/routing.py (D4): route by the table; refuse to start on any collision or an invalid
function name (cited OpenAI rule), naming the tools; never rename."""

from __future__ import annotations

import pytest

from proveflow.runner.routing import FUNCTION_NAME, RoutingError, RoutingTable
from runnerchecks import assert_cross_server_collision_refused, tool


def test_routes_to_the_advertising_proxy() -> None:
    table = RoutingTable.build(
        [("web", "s-web", [tool("fetch")]), ("fs", "s-fs", [tool("read_file"), tool("write_file")])]
    )
    route = table.route("write_file")
    assert route is not None and (route.server, route.session_id) == ("fs", "s-fs")
    assert table.route("nope") is None
    assert [t["function"]["name"] for t in table.openai_tools()] == [
        "fetch", "read_file", "write_file",
    ]  # fmt: skip
    assert table.openai_tools()[0] == {
        "type": "function",
        "function": {"name": "fetch", "description": "d", "parameters": {"type": "object"}},
    }


def test_cross_server_collisions_refuse_to_start() -> None:
    assert_cross_server_collision_refused()


@pytest.mark.parametrize("name", ["a.b", "has space", "x" * 65, "ünï", "a/b"])
def test_invalid_function_names_are_refused_not_renamed(name: str) -> None:
    with pytest.raises(RoutingError, match="not a valid function name"):
        RoutingTable.build([("s", "s1", [tool(name)])])


def test_function_name_rule_matches_the_cited_spec() -> None:
    for ok in ("a", "A-z_09", "x" * 64):
        assert FUNCTION_NAME.fullmatch(ok)
    for bad in ("", "x" * 65, "a.b", "a b"):
        assert not FUNCTION_NAME.fullmatch(bad)
