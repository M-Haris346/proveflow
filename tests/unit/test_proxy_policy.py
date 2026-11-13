"""Layer A (TwinUpstream refusals) and layer B (build_policy truth table, decide)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from proveflow.core.tools import Granularity, ToolRole, ToolSpec
from proveflow.proxy.policy import (
    Decision,
    SandboxReason,
    ToolPolicy,
    TwinUpstream,
    build_policy,
    decide,
    tool_policy,
)
from proxyhelpers import TWIN, evidence

SOURCE, PRIVATE, SINK = ToolRole.UNTRUSTED_SOURCE, ToolRole.PRIVATE_DATA, ToolRole.SINK


def spec(name: str, *roles: ToolRole, granularity: Granularity = Granularity.TOOL) -> ToolSpec:
    return ToolSpec(name=name, server="twin", roles=tuple(evidence(r, granularity) for r in roles))


@pytest.mark.parametrize(
    ("tool", "forward", "inject"),
    [
        (spec("src", SOURCE), True, True),
        (spec("priv", PRIVATE), True, False),
        (spec("src_priv", SOURCE, PRIVATE), True, True),
        (spec("sink", SINK), False, False),
        (spec("src_sink", SOURCE, SINK), False, True),
        (spec("priv_sink", PRIVATE, SINK), False, False),
        (spec("none"), False, False),
        (spec("*", SOURCE), False, True),
        (spec("*", PRIVATE), False, False),
        (spec("srv_src", SOURCE, granularity=Granularity.SERVER), False, True),
        (spec("srv_priv", PRIVATE, granularity=Granularity.SERVER), False, False),
    ],
    ids=lambda v: v.name if isinstance(v, ToolSpec) else str(v),
)
def test_build_policy_truth_table(tool: ToolSpec, forward: bool, inject: bool) -> None:
    assert tool_policy(tool) == ToolPolicy(forward=forward, inject=inject)
    assert build_policy([tool]) == {tool.name: ToolPolicy(forward=forward, inject=inject)}


def test_mixed_granularity_is_denied() -> None:
    tool = ToolSpec(
        name="mixed",
        server="twin",
        roles=(evidence(PRIVATE), evidence(SOURCE, Granularity.SERVER)),
    )
    assert tool_policy(tool).forward is False


def test_build_policy_refuses_duplicate_names() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        build_policy([spec("a", PRIVATE), spec("a", SINK)])


def test_decide_default_deny() -> None:
    policy = build_policy([spec("priv", PRIVATE), spec("sink", SINK), spec("ghost", PRIVATE)])
    advertised = frozenset({"priv", "sink"})
    assert decide(policy, advertised, "priv") == (Decision.FORWARD, None)
    assert decide(policy, advertised, "sink") == (Decision.SANDBOX, SandboxReason.POLICY_DENY)
    assert decide(policy, advertised, "nope") == (Decision.SANDBOX, SandboxReason.UNKNOWN_TOOL)
    assert decide(policy, advertised, "ghost") == (
        Decision.SANDBOX,
        SandboxReason.NOT_ADVERTISED,
    )


# --- layer A ---------------------------------------------------------------------------


def test_twin_upstream_accepts_this_interpreter_and_a_py_file() -> None:
    up = TwinUpstream(name="twin", argv=(sys.executable, str(TWIN), "--log", "x"))
    assert up.argv[1] == str(TWIN)


@pytest.mark.parametrize(
    "argv",
    [
        ("npx", "-y", "@modelcontextprotocol/server-everything"),
        ("uvx", "mcp-server-fetch"),
        ("node", "server.js"),
        ("docker", "run", "-i", "mcp/github"),
        ("https://example.invalid/mcp",),
        ("python", str(TWIN)),  # bare name, not sys.executable
        (sys.executable,),
        (sys.executable, "-c", "print(1)"),
        (sys.executable, "-m", "some_server"),
        (sys.executable, "fake_twin.py"),  # relative
    ],
    ids=["npx", "uvx", "node", "docker", "url", "bare-python", "no-script", "-c", "-m", "rel"],
)
def test_twin_upstream_refuses_everything_else(argv: tuple[str, ...]) -> None:
    with pytest.raises(ValidationError):
        TwinUpstream(name="twin", argv=argv)


def test_twin_upstream_refuses_missing_and_non_py(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="does not exist"):
        TwinUpstream(name="twin", argv=(sys.executable, str(tmp_path / "missing.py")))
    other = tmp_path / "server.js"
    other.write_text("", encoding="utf-8")
    with pytest.raises(ValidationError, match=r"\.py"):
        TwinUpstream(name="twin", argv=(sys.executable, str(other)))
    folder = tmp_path / "dir.py"
    folder.mkdir()
    with pytest.raises(ValidationError, match="not a file"):
        TwinUpstream(name="twin", argv=(sys.executable, str(folder)))


def test_twin_upstream_has_no_extra_fields() -> None:
    with pytest.raises(ValidationError):
        TwinUpstream.model_validate(
            {"name": "twin", "argv": [sys.executable, str(TWIN)], "env": {"A": "1"}}
        )
