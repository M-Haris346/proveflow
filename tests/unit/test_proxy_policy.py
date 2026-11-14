"""Layer A (TwinUpstream: interpreter + script under TWIN_ROOT) and layer B (build_policy
truth table, L1 collisions, decide incl. the proxy's second opinion)."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import mcp
import pytest
from pydantic import ValidationError

from proveflow.core.tools import Granularity, ToolRole, ToolSpec
from proveflow.proxy import policy as policy_module
from proveflow.proxy.policy import (
    Decision,
    SandboxReason,
    ToolPolicy,
    TwinUpstream,
    _default_twin_root,
    build_policy,
    decide,
    tool_policy,
)
from proxyhelpers import (  # noqa: F401
    LOOKALIKE,
    evidence,
    make_escape_link,
    proxy_twin_root,
    twin_script,
)

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


# --- L1: look-alike names are all denied --------------------------------------------------


def test_lookalike_of_a_sink_is_denied_with_it() -> None:
    policy = build_policy([spec("send_email", SINK), spec(LOOKALIKE, PRIVATE)])
    assert policy["send_email"].forward is False
    assert policy[LOOKALIKE].forward is False


@pytest.mark.parametrize(
    "other",
    ["SEND_EMAIL", "\uff53end_email", "send_email\u00ad", "send\u2060_email", "Send_Email\ufe0f"],
    ids=["case", "fullwidth", "soft-hyphen", "word-joiner", "variation-selector"],
)
def test_collision_variants_deny_every_member(other: str) -> None:
    policy = build_policy([spec("send_email", PRIVATE), spec(other, PRIVATE), spec("ok", PRIVATE)])
    assert policy["send_email"].forward is False
    assert policy[other].forward is False
    assert policy["ok"].forward is True  # unrelated names are untouched


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


def test_decide_second_opinion_and_advertised_collision() -> None:
    policy = build_policy([spec("send_email", PRIVATE), spec(LOOKALIKE, PRIVATE)])
    policy = {**policy, "send_email": ToolPolicy(forward=True, inject=False)}  # forged
    assert decide(
        policy, frozenset({"send_email"}), "send_email", proxy_sinks=frozenset({"send_email"})
    ) == (Decision.SANDBOX, SandboxReason.PROXY_CLASSIFIER_SINK)
    only_lookalike = build_policy([spec(LOOKALIKE, PRIVATE)])
    assert decide(only_lookalike, frozenset({"send_email", LOOKALIKE}), LOOKALIKE) == (
        Decision.SANDBOX,
        SandboxReason.NAME_COLLISION,
    )


# --- layer A ---------------------------------------------------------------------------


def test_twin_upstream_accepts_a_script_under_twin_root() -> None:
    up = TwinUpstream(name="twin", argv=(sys.executable, str(twin_script()), "--log", "x"))
    assert up.argv[1] == str(twin_script())


@pytest.mark.parametrize(
    "argv",
    [
        ("npx", "-y", "@modelcontextprotocol/server-everything"),
        ("uvx", "mcp-server-fetch"),
        ("node", "server.js"),
        ("docker", "run", "-i", "mcp/github"),
        ("https://example.invalid/mcp",),
        ("python", "TWIN"),  # bare name, not sys.executable
        (sys.executable,),
        (sys.executable, "-c", "print(1)"),
        (sys.executable, "-m", "some_server"),
        (sys.executable, "fake_twin.py"),  # relative
    ],
    ids=["npx", "uvx", "node", "docker", "url", "bare-python", "no-script", "-c", "-m", "rel"],
)
def test_twin_upstream_refuses_everything_else(argv: tuple[str, ...]) -> None:
    argv = tuple(str(twin_script()) if a == "TWIN" else a for a in argv)
    with pytest.raises(ValidationError):
        TwinUpstream(name="twin", argv=argv)


def test_twin_upstream_refuses_missing_and_non_py() -> None:
    root = policy_module.TWIN_ROOT
    with pytest.raises(ValidationError, match="does not exist"):
        TwinUpstream(name="twin", argv=(sys.executable, str(root / "missing.py")))
    other = root / "server.js"
    other.write_text("", encoding="utf-8")
    with pytest.raises(ValidationError, match=r"\.py"):
        TwinUpstream(name="twin", argv=(sys.executable, str(other)))
    folder = root / "dir.py"
    folder.mkdir()
    with pytest.raises(ValidationError, match="not a file"):
        TwinUpstream(name="twin", argv=(sys.executable, str(folder)))


def test_installed_package_module_is_refused() -> None:
    """H2: e.g. the MCP SDK's own server entry point (a real installed .py) is refused."""
    target = Path(mcp.__file__).parent / "server" / "__main__.py"
    assert target.is_file()
    with pytest.raises(ValidationError, match="TWIN_ROOT"):
        TwinUpstream(name="twin", argv=(sys.executable, str(target)))


def test_py_file_outside_twin_root_is_refused(tmp_path: Path) -> None:
    outside = tmp_path / "server.py"
    shutil.copyfile(twin_script(), outside)  # same content, wrong place
    with pytest.raises(ValidationError, match="TWIN_ROOT"):
        TwinUpstream(name="twin", argv=(sys.executable, str(outside)))


def test_symlink_escaping_twin_root_is_refused(tmp_path: Path) -> None:
    root = policy_module.TWIN_ROOT
    outside = tmp_path / "outside"
    outside.mkdir()
    link = make_escape_link(root, outside)
    assert link.is_file()
    assert str(link).startswith(str(root))  # lexically inside...
    with pytest.raises(ValidationError, match="TWIN_ROOT"):  # ...but resolves outside
        TwinUpstream(name="twin", argv=(sys.executable, str(link)))


def test_twin_upstream_has_no_extra_fields() -> None:
    with pytest.raises(ValidationError):
        TwinUpstream.model_validate(
            {"name": "twin", "argv": [sys.executable, str(twin_script())], "env": {"A": "1"}}
        )


def test_default_twin_root_location(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    if sys.platform == "win32":
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        assert _default_twin_root() == tmp_path / "proveflow" / "twins"
    else:
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        assert _default_twin_root() == tmp_path / "proveflow" / "twins"
        monkeypatch.setenv("XDG_DATA_HOME", "relative/dir")  # invalid -> ignored
        assert _default_twin_root() == Path.home() / ".local" / "share" / "proveflow" / "twins"


def test_twin_root_is_a_module_constant_not_read_at_check_time(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Changing the environment after import does not move TWIN_ROOT (no env override)."""
    before = policy_module.TWIN_ROOT
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert policy_module.TWIN_ROOT == before
