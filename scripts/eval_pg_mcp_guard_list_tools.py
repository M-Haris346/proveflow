"""In-process tools/list for pg-mcp-guard @ b7a6dce with a stub executor and stub principal.

Run with pg-mcp-guard's OWN venv python, from the pg-mcp-guard repo root:
    .venv\\Scripts\\python.exe <this file> <out.json>
No DB, no token, no network: the stub executor raises on ANY attribute access, so the run
fails loudly if construction or tools/list touches it; the principal source returns None
and also records whether it was ever called.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path.cwd()
sys.path.insert(0, str(REPO))
GIT = shutil.which("git")
if GIT is None:
    sys.exit("git not found")


def git(*args: str) -> str:
    """Read-only git query of the repo being read."""
    return subprocess.run(  # noqa: S603 - fixed git subcommands, resolved git path
        [GIT, *args], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.strip()


head = git("rev-parse", "HEAD")
if not head.startswith("b7a6dce"):
    sys.exit(f"expected pg-mcp-guard at b7a6dce, found {head}")
if git("status", "--porcelain"):
    sys.exit("pg-mcp-guard working tree is not clean")


class StubExecutor:
    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"executor touched: {name!r}")


principal_calls = 0


def stub_principal() -> None:
    global principal_calls
    principal_calls += 1
    return None


async def main() -> None:
    from app.server import create_server
    from mcp import Client

    server = create_server(StubExecutor(), stub_principal)  # type: ignore[arg-type]
    async with Client(server) as client:
        result = await client.list_tools()
    tools = [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": t.input_schema,
            "annotations": t.annotations.model_dump(exclude_none=True) if t.annotations else None,
        }
        for t in result.tools
    ]
    out = {
        "source": "pg-mcp-guard",
        "commit": head,
        "provenance": "in-process list_tools, stub executor",
        "principal_source_calls": principal_calls,
        "next_cursor": result.next_cursor,
        "tools": tools,
    }
    Path(sys.argv[1]).write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "tools"}, indent=2))
    for t in tools:
        print(f"- {t['name']}: params={sorted((t['input_schema'] or {}).get('properties', {}))}")


asyncio.run(main())
