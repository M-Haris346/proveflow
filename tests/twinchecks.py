"""Named checks for the twin guard, shared by safety and mutation tests."""

from __future__ import annotations

from proveflow.twin.guard import TwinGuardError, check_no_io

# Representative of what the generator emits: the five allowed imports, literal data,
# handlers reading params.name / params.arguments, anyio.run(main) at module level.
VALID_TWIN = """\
import json
import anyio
import mcp_types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

TOOLS = [{"name": "t", "description": "d", "inputSchema": {"type": "object"}}]


async def list_tools(ctx, params):
    return types.ListToolsResult(
        tools=[types.Tool(name=t["name"], description=t["description"],
                          input_schema=t["inputSchema"]) for t in TOOLS]
    )


async def call_tool(ctx, params):
    text = json.dumps({"tool": params.name, "args": params.arguments})
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)])


async def main():
    server = Server("twin", on_list_tools=list_tools, on_call_tool=call_tool)
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


anyio.run(main)
"""

# Each one does (or sets up) I/O; every one must be refused.
IO_SCRIPTS: dict[str, str] = {
    "subprocess_run": "from subprocess import run\nrun(['x'])\n",
    "os_remove": "import os\nos.remove('x')\n",
    "open_write": "open('x', 'w')\n",
    "socket": "import socket\nsocket.create_connection(('example.invalid', 80))\n",
    "pathlib_write": "from pathlib import Path\nPath('x').write_text('y')\n",
    "dunder_import": "__import__('os').remove('x')\n",
    # No attribute access at all: only the dunder-NAME rule stops this one.
    "builtins_subscript": "__builtins__['open']('x', 'w')\n",
    "subclass_walk": "().__class__.__mro__[1].__subclasses__()\n",
    "mcp_client_spawn": "from mcp.client.stdio import stdio_client\n",
    # stdout is the MCP transport: any write corrupts the session (correctness, F1).
    "print_to_stdout": "print('x')\n",
    "help_imports_pydoc": "help(str)\n",
    "quit_closes_stdin": "quit()\n",
    "license_reads_files": "license()\n",
}


# Real provider key prefixes. They live HERE, in tests, as an assertion about output (R8):
# the restricted alphabet means generated values cannot contain them; tests prove it.
PROVIDER_PREFIXES = ("sk-", "sk_live", "AKIA", "ghp_", "xoxb-", "ya29", "eyJ")


def provider_prefix_in(text: str) -> str | None:
    low = text.lower()
    return next((p for p in PROVIDER_PREFIXES if p.lower() in low), None)


def sample_honey() -> tuple[object, ...]:
    from proveflow.core.honey import HoneyKind, new_honey
    from proveflow.twin.rng import Rng

    return (
        new_honey(Rng("sample").derive("h1").draw_hex, HoneyKind.APIKEY, id="h01"),
        new_honey(Rng("sample").derive("h2").draw_hex, HoneyKind.PASSWORD, id="h02"),
    )


def assert_archetype_guarantees(name: str) -> None:
    """Named check: archetype ``name`` returns a text block, carries every honey value given,
    and breaks no T4 rule (render verifies; a broken archetype surfaces here)."""
    from proveflow.twin.archetypes import ArchetypeError, render
    from proveflow.twin.rng import Rng

    honey = sample_honey()
    try:
        content = render(name, Rng("check").derive(name), "tool", honey)  # type: ignore[arg-type]
    except ArchetypeError as exc:
        raise AssertionError(f"archetype {name} broke a guarantee: {exc}") from None
    texts = [c["text"] for c in content]
    for h in honey:
        if not any(h.value in t for t in texts):  # type: ignore[attr-defined]
            raise AssertionError(f"archetype {name} lost honey {h.id}")  # type: ignore[attr-defined]


SELECTION_SAMPLES: dict[str, tuple[str, str, dict[str, object]]] = {
    "email_list": ("list_inbox_messages", "List the emails in the inbox.", {}),
    "issue_ticket": ("create_issue", "Create a new issue.", {}),
    "db_rows": ("run_sql_query", "Run a SQL query.", {"properties": {"sql": {}}}),
    "web_page": ("fetch", "Fetch a URL.", {"properties": {"url": {}}}),
    "document_text": ("read_text_file", "Read a file.", {"properties": {"path": {}}}),
}


def assert_selection_samples() -> None:
    """Named check: each selection rule's sample tool gets that rule's archetype."""
    from proveflow.twin.select import choose_archetype

    for expected, (name, desc, schema) in SELECTION_SAMPLES.items():
        got, _ = choose_archetype(name, desc, schema)
        if got != expected:
            raise AssertionError(f"selection sample {name}: got {got}, want {expected}")


def stored_tools(server: str) -> list[object]:
    """ToolSpecs for a stored eval server (data/eval), classified by v2 (no network)."""
    import json
    from pathlib import Path

    from proveflow.flows.roles import classify_tool

    root = Path(__file__).resolve().parents[1] / "data" / "eval" / "roles" / "collected"
    if server == "pg-mcp-guard":
        raw = json.loads((root / "pg-mcp-guard.json").read_text(encoding="utf-8"))["tools"]
        rows = [(t["name"], t.get("description", ""), t["input_schema"]) for t in raw]
    else:
        lines = (root / "tools.jsonl").read_text(encoding="utf-8").splitlines()
        rows = [
            (r["tool_name"], r["description"], r["input_schema"])
            for r in (json.loads(line) for line in lines if line.strip())
            if r["server_id"] == server
        ]
    return [classify_tool(n, server, d, s) for n, d, s in rows]


def stored_servers() -> list[str]:
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "data" / "eval" / "roles" / "collected"
    lines = (root / "tools.jsonl").read_text(encoding="utf-8").splitlines()
    servers = sorted({json.loads(line)["server_id"] for line in lines if line.strip()})
    return [*servers, "pg-mcp-guard"]


def assert_write_refuses_guard_failing_source(root: object) -> None:
    """Named check: write_twin never writes a source the guard refuses."""
    import contextlib
    import hashlib
    from pathlib import Path

    from proveflow.twin.generator import TwinBuild, write_twin

    target = Path(str(root))
    source = VALID_TWIN + "\nopen('x', 'w')\n"
    sha = hashlib.sha256(source.encode("utf-8")).hexdigest()
    bad = TwinBuild(server="bad", source=source, sha256=sha, honey=())
    with contextlib.suppress(TwinGuardError):
        write_twin(bad, target)
    if (target / bad.filename).exists():
        raise AssertionError("write_twin wrote a guard-failing twin")


def assert_guard_refuses_io_scripts() -> None:
    """Named safety check: every I/O script is refused, and the valid twin passes."""
    check_no_io(VALID_TWIN)
    for name, src in IO_SCRIPTS.items():
        try:
            check_no_io(src)
        except TwinGuardError:
            continue
        raise AssertionError(f"guard let an I/O script through: {name}")
