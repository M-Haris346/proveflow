"""twin/guard.py: one test per refused construct, plus what must pass (R-C3 to R-C5)."""

from __future__ import annotations

import pytest

from proveflow.twin.guard import (
    ALLOWED_MODULE_ATTRS,
    EXPLICIT_DUNDERS,
    FORBIDDEN_BUILTINS,
    TwinGuardError,
    check_no_io,
)
from twinchecks import VALID_TWIN

HEADER = (
    "import json\nimport anyio\nimport mcp_types as types\n"
    "from mcp.server.lowlevel import Server\nfrom mcp.server.stdio import stdio_server\n"
)


def refused(src: str, match: str) -> TwinGuardError:
    with pytest.raises(TwinGuardError, match=match) as exc:
        check_no_io(src)
    return exc.value


def test_the_representative_twin_passes() -> None:
    check_no_io(VALID_TWIN)


def test_exactly_the_five_imports_pass() -> None:
    check_no_io(HEADER)


@pytest.mark.parametrize(
    "line",
    [
        "import os", "import sys", "import typing", "import dataclasses", "import mcp",
        "import mcp_types", "import mcp_types as mt", "import json as j", "import anyio as a",
        "import mcp.types", "import importlib", "from __future__ import annotations",
        "from json import dumps", "from anyio import run",
        "from mcp.client.stdio import stdio_client",
        "from mcp.server.lowlevel import Server as S", "from mcp.server.lowlevel import *",
        "from mcp.server import lowlevel", "from mcp.os.win32 import utilities",
        "from mcp.server.streamable_http import x", "from . import x", "from .x import y",
    ],
)  # fmt: skip
def test_every_other_import_is_refused(line: str) -> None:
    refused(line + "\n", "import")


@pytest.mark.parametrize("name", sorted(FORBIDDEN_BUILTINS))
def test_forbidden_builtins_are_refused(name: str) -> None:
    refused(f"{name}('x')\n", "forbidden builtin|dunder")
    refused(f"f = {name}\n", "forbidden builtin|dunder")


@pytest.mark.parametrize("name", ["__name__", "__builtins__", "__file__", "__loader__", "__spec__"])
def test_dunder_names_are_refused(name: str) -> None:
    refused(f"x = {name}\n", "dunder name")


def test_main_guard_is_impossible() -> None:
    refused('if __name__ == "__main__":\n    pass\n', "dunder name")


@pytest.mark.parametrize("attr", [*sorted(EXPLICIT_DUNDERS), "__init__", "__reduce__", "__code__"])
def test_dunder_attributes_are_refused(attr: str) -> None:
    refused(f"x = (1).{attr}\n", "dunder attribute")
    refused(HEADER + f"x = json.{attr}\n", "dunder attribute")


def test_explicit_dunders_are_listed_by_name() -> None:
    assert {"__subclasses__", "__mro__", "__globals__", "__class__", "__dict__"} <= EXPLICIT_DUNDERS


@pytest.mark.parametrize(
    "expr", ["json.loads", "json.codecs", "json.decoder", "anyio.open_process", "anyio.Path",
             "anyio.to_thread", "types.ImageContent", "types.Notification"],
)  # fmt: skip
def test_module_attributes_outside_the_allowlist_are_refused(expr: str) -> None:
    refused(HEADER + f"x = {expr}\n", "module attribute refused")


def test_allowed_module_attributes() -> None:
    assert ALLOWED_MODULE_ATTRS["anyio"] == frozenset({"run"})
    check_no_io(HEADER + "a = json.dumps\nb = anyio.run\nc = types.Tool\nd = types.TextContent\n")


@pytest.mark.parametrize("expr", ["json.dumps.x", "types.Tool.model_validate", "anyio.run.y"])
def test_attribute_chains_on_modules_are_refused(expr: str) -> None:
    refused(HEADER + f"x = {expr}\n", "attribute chain")


@pytest.mark.parametrize(
    "expr", ["x.items()", "x.get('k')", "''.join([])", "x.append(1)", "b''.decode()",
             "Server.something", "stdio_server.x", "x.write_text('y')"],
)  # fmt: skip
def test_object_attributes_outside_the_four_are_refused(expr: str) -> None:
    refused(HEADER + f"x = {{}}\ny = {expr}\n", "attribute refused")


def test_the_four_object_attributes_pass() -> None:
    check_no_io(
        HEADER + "def f(params, server):\n"
        "    a = params.name, params.arguments\n"
        "    return a, server.run, server.create_initialization_options\n"
    )


@pytest.mark.parametrize(
    "src",
    [
        "json = 1\n", "types = None\n", "for anyio in []:\n    pass\n",
        "def f(json):\n    pass\n", "def Server():\n    pass\n", "class stdio_server:\n    pass\n",
        "with x as types:\n    pass\n", "import json\njson = 2\n",
    ],
)  # fmt: skip
def test_rebinding_an_imported_name_is_refused(src: str) -> None:
    refused(src, "refused")


def test_syntax_error_is_a_guard_error() -> None:
    err = refused("def (:\n", "syntax error")
    assert err.lineno == 1


def test_first_violation_in_source_order_with_line_number() -> None:
    err = refused(HEADER + "x = 1\nimport os\nopen('y')\n", "import not allowed: import os")
    assert err.lineno == 7
