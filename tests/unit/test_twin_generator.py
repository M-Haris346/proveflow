"""twin/generator.py (D1): self-contained, five imports, no proveflow import, embedded
runtime, byte-determinism, honey/marker/skipped bookkeeping, write refusals. The generated
module is NEVER imported here (it would start a server); it is parsed with ``ast``."""

from __future__ import annotations

import ast
import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from proveflow.core.honey import t4_violations
from proveflow.core.tools import ToolRole, ToolSpec
from proveflow.twin import _runtime, generator
from proveflow.twin.generator import (
    MAX_HONEY,
    TwinGenerationError,
    generate_twin,
    literal,
    twin_filename,
    write_twin,
)
from proveflow.twin.guard import TwinGuardError, check_no_io
from proveflow.twin.schema_subset import skipped_keywords
from twinchecks import stored_servers, stored_tools

EXPECTED_IMPORTS = [
    ("import", "json", None),
    ("import", "anyio", None),
    ("import", "mcp_types", "types"),
    ("from", "mcp.server.lowlevel", "Server"),
    ("from", "mcp.server.stdio", "stdio_server"),
]


def imports_of(source: str) -> list[tuple[str, str, str | None]]:
    out: list[tuple[str, str, str | None]] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            out += [("import", a.name, a.asname) for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            out += [("from", node.module or "", a.name) for a in node.names]
    return out


def assigned_literal(source: str, name: str) -> object:
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not assigned")


@pytest.fixture(scope="module")
def builds() -> dict[str, generator.TwinBuild]:
    return {s: generate_twin(s, stored_tools(s), seed="unit") for s in stored_servers()}  # type: ignore[arg-type]


def test_every_stored_server_generates_a_guard_clean_ascii_twin(builds) -> None:  # type: ignore[no-untyped-def]
    assert len(builds) == 13
    for server, b in builds.items():
        check_no_io(b.source)
        assert b.source.isascii(), server


def test_exactly_the_five_imports_and_no_proveflow(builds) -> None:  # type: ignore[no-untyped-def]
    for b in builds.values():
        assert imports_of(b.source) == EXPECTED_IMPORTS
        assert "proveflow" not in {name.split(".")[0] for _, name, _ in imports_of(b.source)}


def test_runtime_is_embedded_verbatim(builds) -> None:  # type: ignore[no-untyped-def]
    runtime = Path(_runtime.__file__).read_text(encoding="utf-8")
    for b in builds.values():
        assert runtime in b.source


def test_advertised_schemas_equal_the_stored_ones(builds) -> None:  # type: ignore[no-untyped-def]
    """R9 through the generated literal (parsed, not imported)."""
    for server, b in builds.items():
        tools = {t.name: t for t in stored_tools(server)}  # type: ignore[attr-defined]
        advertised = assigned_literal(b.source, "TOOLS")
        assert isinstance(advertised, list)
        assert {t["name"] for t in advertised} == set(tools)
        for t in advertised:
            assert t["inputSchema"] == tools[t["name"]].input_schema, (server, t["name"])
            assert t["description"] == tools[t["name"]].description


def test_byte_deterministic_and_seed_sensitive() -> None:
    tools = stored_tools("filesystem")
    a = generate_twin("filesystem", tools, seed="s")  # type: ignore[arg-type]
    b = generate_twin("filesystem", tools, seed="s")  # type: ignore[arg-type]
    assert a.source == b.source and a.sha256 == b.sha256
    assert generate_twin("filesystem", tools, seed="t").sha256 != a.sha256  # type: ignore[arg-type]
    shuffled = list(reversed(tools))
    assert generate_twin("filesystem", shuffled, seed="s").sha256 == a.sha256  # type: ignore[arg-type]


def test_same_sha_in_fresh_interpreters_with_different_hash_seeds() -> None:
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]); from twinchecks import stored_tools; "
        "from proveflow.twin.generator import generate_twin; "
        "print(generate_twin('filesystem', stored_tools('filesystem'), seed='s').sha256)"
    )
    tests_dir = str(Path(__file__).resolve().parents[1])
    shas = {
        subprocess.run(
            [sys.executable, "-c", code, tests_dir],
            capture_output=True, text=True, check=True,
            env={**os.environ, "PYTHONHASHSEED": seed},
        ).stdout.strip()
        for seed in ("0", "1", "4242")
    }  # fmt: skip
    expected = generate_twin("filesystem", stored_tools("filesystem"), seed="s").sha256  # type: ignore[arg-type]
    assert shas == {expected}


def test_honey_for_private_tools_only_and_t4_clean(builds) -> None:  # type: ignore[no-untyped-def]
    for server, b in builds.items():
        tools = stored_tools(server)
        private = [t for t in tools if ToolRole.PRIVATE_DATA in {e.role for e in t.roles}]  # type: ignore[attr-defined]
        assert len(b.honey) == len(private)
        assert len({h.id for h in b.honey}) == len(b.honey)
        table = assigned_literal(b.source, "TABLE")
        assert isinstance(table, dict)
        for t in private:
            texts = " ".join(c["text"] for c in table[t.name]["content"])  # type: ignore[attr-defined]
            assert "pfhoney_" in texts, (server, t.name)  # type: ignore[attr-defined]
        for h in b.honey:
            assert t4_violations(h.value) == ()


def test_markers_unique_t4_clean_and_last_block(builds) -> None:  # type: ignore[no-untyped-def]
    for b in builds.values():
        table = assigned_literal(b.source, "TABLE")
        assert isinstance(table, dict)
        assert len(set(b.markers.values())) == len(b.markers)
        for name, marker in b.markers.items():
            assert marker.startswith("pfmark_") and t4_violations(marker) == ()
            assert table[name]["content"][-1]["text"] == f"twin-marker: {marker}"


def test_every_tool_returns_a_text_block_and_skipped_is_recorded(builds) -> None:  # type: ignore[no-untyped-def]
    for server, b in builds.items():
        table = assigned_literal(b.source, "TABLE")
        assert isinstance(table, dict)
        for t in stored_tools(server):
            content = table[t.name]["content"]  # type: ignore[attr-defined]
            assert content and all(c["type"] == "text" for c in content)
            assert b.skipped[t.name] == skipped_keywords(t.input_schema)  # type: ignore[attr-defined]


def test_honey_cap() -> None:
    def private(i: int) -> ToolSpec:
        from proxyhelpers import evidence

        return ToolSpec(name=f"t{i}", server="s", roles=(evidence(ToolRole.PRIVATE_DATA),))

    generate_twin("s", [private(i) for i in range(MAX_HONEY)], seed="x")
    with pytest.raises(TwinGenerationError, match="cap is 32"):
        generate_twin("s", [private(i) for i in range(MAX_HONEY + 1)], seed="x")
    with pytest.raises(TwinGenerationError, match="cap is 32"):
        generate_twin("s", [private(i) for i in range(17)], seed="x", honey_per_private=2)


@pytest.mark.parametrize(
    "tools",
    [[], [ToolSpec(name="*", server="s")], [ToolSpec(name="a", server="s")] * 2],
    ids=["empty", "server-level", "duplicate"],
)
def test_refuses_unusable_tool_lists(tools: list[ToolSpec]) -> None:
    with pytest.raises(TwinGenerationError):
        generate_twin("s", tools, seed="x")


def test_write_twin_refuses_overwrite_and_matches_sha(tmp_path: Path) -> None:
    b = generate_twin("fetch", stored_tools("fetch"), seed="w")  # type: ignore[arg-type]
    path = write_twin(b, tmp_path)
    assert path.name == "pftwin-fetch.py"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == b.sha256
    with pytest.raises(FileExistsError):
        write_twin(b, tmp_path)


def test_write_twin_runs_the_guard_before_writing(tmp_path: Path) -> None:
    b = generate_twin("fetch", stored_tools("fetch"), seed="w")  # type: ignore[arg-type]
    bad = generator.TwinBuild(
        server="fetch", source=b.source + "\nopen('x')\n", sha256="0" * 64, honey=()
    )
    with pytest.raises(TwinGuardError):
        write_twin(bad, tmp_path)
    assert not (tmp_path / "pftwin-fetch.py").exists()


def test_filenames_are_not_importable_identifiers() -> None:
    assert twin_filename("Pg MCP_Guard") == "pftwin-pg-mcp-guard.py"
    assert not twin_filename("x").removesuffix(".py").isidentifier()
    with pytest.raises(TwinGenerationError):
        twin_filename("!!!")


def test_literal_is_deterministic_and_strict() -> None:
    assert literal({"b": 1, "a": [True, None, "é"]}) == "{'a': [True, None, '\\xe9'], 'b': 1}"
    assert ast.literal_eval(literal({"x": 1.5, "y": "q"})) == {"x": 1.5, "y": "q"}
    with pytest.raises(TwinGenerationError):
        literal(float("nan"))
    with pytest.raises(TwinGenerationError):
        literal({1, 2})
