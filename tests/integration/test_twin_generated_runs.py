"""A generated twin actually runs (step 6): launched as its own subprocess (no proxy yet) and
driven by an SDK ClientSession. It serves the advertised tools, answers with its own
per-tool marker (R-C2 liveness evidence), and validates arguments (D8). The script is run,
never imported."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import anyio
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from proveflow.twin.generator import generate_twin, write_twin
from twinchecks import stored_tools


def run_twin(script: Path, body: Any) -> Any:
    params = StdioServerParameters(command=sys.executable, args=[str(script)], env=dict(os.environ))
    box: dict[str, Any] = {}

    async def main() -> None:
        with (script.parent / "twin.stderr").open("w", encoding="utf-8") as errlog:
            async with stdio_client(params, errlog=errlog) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    box["r"] = await body(session)

    anyio.run(main)
    return box["r"]


def test_generated_filesystem_twin_serves_marks_and_validates(tmp_path: Path) -> None:
    tools = stored_tools("filesystem")
    build = generate_twin("filesystem", tools, seed="run")  # type: ignore[arg-type]
    script = write_twin(build, tmp_path)

    async def body(session: ClientSession) -> Any:
        listed = await session.list_tools()
        ok = await session.call_tool("read_text_file", {"path": "/notes.txt"})
        bad = await session.call_tool("read_text_file", {})
        return listed, ok, bad

    listed, ok, bad = run_twin(script, body)
    assert {t.name for t in listed.tools} == {t.name for t in tools}  # type: ignore[attr-defined]
    texts = [c.text for c in ok.content]
    assert ok.is_error is False
    assert texts[-1] == f"twin-marker: {build.markers['read_text_file']}"
    honey_ids = {h.value for h in build.honey}
    assert any(v in " ".join(texts) for v in honey_ids)  # read_text_file is private_data
    assert bad.is_error is True
    assert "missing required property 'path'" in bad.content[0].text
