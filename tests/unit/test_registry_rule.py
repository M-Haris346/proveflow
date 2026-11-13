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


# --- v2 held-out options (checkpoint 1c) -------------------------------------------


def test_cutoff_parameter_moves_r2() -> None:
    from datetime import UTC, datetime

    e = entry()
    e["_meta"]["io.modelcontextprotocol.registry/official"]["publishedAt"] = "2026-10-29T00:00:00Z"
    assert sel.rule_filter(e)[1].startswith("R2")  # default cutoff 2026-10-28
    assert sel.rule_filter(e, datetime(2026, 10, 30, tzinfo=UTC))[1] == "ok"


def test_newest_stable_before_skips_prereleases_and_new_versions() -> None:
    from datetime import UTC, datetime

    times = {
        "1.2.0": "2026-10-01T00:00:00Z",
        "1.10.0": "2026-10-20T00:00:00Z",  # numeric, not lexical, ordering
        "1.11.0-rc.1": "2026-10-21T00:00:00Z",  # pre-release never wins
        "2.0.0": "2026-11-10T00:00:00Z",  # after the cutoff
    }
    assert sel.newest_stable_before(times, datetime(2026, 10, 30, tzinfo=UTC)) == "1.10.0"
    assert sel.newest_stable_before(times, datetime(2026, 9, 1, tzinfo=UTC)) is None


def test_excluded_packages_reads_an_eval_server_set(tmp_path: Path) -> None:
    import json

    p = tmp_path / "s.json"
    p.write_text(json.dumps({"servers": [
        {"id": "a", "package": {"registry": "npm", "name": "pkg-a", "version": "1"}},
        {"id": "b"},
    ]}), encoding="utf-8")  # fmt: skip
    assert sel.excluded_packages(p) == {"pkg-a"}
    assert sel.excluded_packages(None) == set()


def test_sample_seed_changes_selection() -> None:
    survivors = [{"name": f"io.example/s{i:02d}"} for i in range(30)]
    a = sel.sample(survivors, k=8, seed=20261111)
    b = sel.sample(survivors, k=8, seed=20261201)
    assert a == sel.sample(survivors, k=8, seed=20261111)  # deterministic
    assert a != b
