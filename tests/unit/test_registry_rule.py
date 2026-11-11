"""The MCP Registry selection rule (scripts/eval_registry_select.py), on synthetic entries."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "eval_registry_select.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("eval_registry_select", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sel = _load()


def entry(**pkg_over: Any) -> dict[str, Any]:
    pkg = {
        "registryType": "npm",
        "identifier": "x-mcp",
        "version": "1.0.0",
        "transport": {"type": "stdio"},
    }
    pkg.update(pkg_over)
    return {
        "server": {"name": "io.example/x", "packages": [pkg]},
        "_meta": {
            "io.modelcontextprotocol.registry/official": {
                "status": "active",
                "isLatest": True,
                "publishedAt": "2026-09-01T00:00:00Z",
            }
        },
    }


def test_ok() -> None:
    pkg, reason = sel.rule_filter(entry())
    assert reason == "ok"
    assert pkg["identifier"] == "x-mcp"


@pytest.mark.parametrize(
    ("over", "reason"),
    [
        ({"transport": {"type": "streamable-http"}}, "R3"),
        ({"registryType": "oci"}, "R3"),
        ({"environmentVariables": [{"name": "K", "isRequired": True, "isSecret": True}]}, "R4"),
        ({"environmentVariables": [{"name": "P", "isRequired": True}]}, "R4"),
        ({"packageArguments": [{"type": "positional", "isRequired": True}]}, "R5"),
    ],
)
def test_excluded(over: dict[str, Any], reason: str) -> None:
    pkg, why = sel.rule_filter(entry(**over))
    assert pkg is None
    assert why.startswith(reason)


def test_optional_or_defaulted_inputs_are_fine() -> None:
    e = entry(
        environmentVariables=[{"name": "OPT", "isSecret": True}, {"name": "D", "isRequired": True,
                                                                  "default": "x"}],
        packageArguments=[{"type": "named", "isRequired": True, "default": "a"}],
    )  # fmt: skip
    assert sel.rule_filter(e)[1] == "ok"


def test_too_new_and_inactive() -> None:
    e = entry()
    meta = e["_meta"]["io.modelcontextprotocol.registry/official"]
    meta["publishedAt"] = "2026-11-05T00:00:00Z"
    assert sel.rule_filter(e)[1].startswith("R2")
    meta["publishedAt"] = "2026-09-01T00:00:00Z"
    meta["isLatest"] = False
    assert sel.rule_filter(e)[1].startswith("R1")
