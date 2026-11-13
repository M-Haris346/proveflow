"""Layer A (``TwinUpstream``) and layer B (default-deny ``ToolPolicy``). ADR-006.

Layer A: the upstream is described ONLY as ``argv == [sys.executable, <existing .py>, ...]``.
There is deliberately no conversion from a discovered ``ServerSpec``/``LaunchSpec``: the
proxy package cannot import them (import guard), so a real configured server cannot be
handed to the proxy by construction.

Layer B: ``build_policy`` forwards a tool only if ALL hold:
  * it has at least one role (unclassified -> deny),
  * none of its roles is ``sink`` (sink, or source+sink -> deny),
  * every piece of role evidence is tool-granularity (server-level guesses -> deny),
  * its name is not ``"*"`` (the "all tools of this server" placeholder -> deny).
Anything not in the policy at all (unknown tool) is denied by ``decide``.

Residual (ADR-006): a real sink the classifier labels as source/private only is forwarded
TO THE TWIN. Harmless in twin mode (the twin is our own script); must be closed before any
``--real-reads`` mode exists.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from enum import StrEnum
from pathlib import Path

from pydantic import Field, model_validator

from proveflow.core._base import FrozenModel
from proveflow.core.tools import Granularity, ToolRole, ToolSpec

UPSTREAM_NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$"


class TwinUpstreamError(ValueError):
    """The upstream is not a twin this proxy may launch."""


def check_twin_argv(argv: Sequence[str]) -> None:
    """Raise ``TwinUpstreamError`` unless ``argv`` is this interpreter running a .py file.

    ``argv[0]`` must equal ``sys.executable`` exactly (no ``python`` lookup on PATH, no
    ``npx``/``uvx``/``node``/``docker``/URL), and ``argv[1]`` must be an absolute path to an
    existing ``.py`` file (so ``-c``/``-m`` and relative paths, which would resolve against
    the proxy's empty temp cwd, are refused). Checked at model validation AND again right
    before spawn.
    """
    if len(argv) < 2:
        raise TwinUpstreamError("twin argv must be [sys.executable, /abs/path/to/twin.py, ...]")
    if argv[0] != sys.executable:
        raise TwinUpstreamError(
            "twin argv[0] must be this interpreter (sys.executable); "
            "real servers (npx, uvx, node, docker, URLs, other commands) are refused"
        )
    script = Path(argv[1])
    if not script.is_absolute():
        raise TwinUpstreamError("twin argv[1] must be an absolute path to a .py file")
    if script.suffix != ".py":
        raise TwinUpstreamError("twin argv[1] must be a .py file")
    if not script.is_file():
        raise TwinUpstreamError("twin argv[1] does not exist or is not a file")


class TwinUpstream(FrozenModel):
    """The only upstream the proxy can launch: ``[sys.executable, <twin.py>, *args]``."""

    name: str = Field(pattern=UPSTREAM_NAME_PATTERN)
    argv: tuple[str, ...]

    @model_validator(mode="after")
    def _python_twin_only(self) -> TwinUpstream:
        check_twin_argv(self.argv)
        return self


class ToolPolicy(FrozenModel):
    forward: bool
    inject: bool


def tool_policy(tool: ToolSpec) -> ToolPolicy:
    roles = {ev.role for ev in tool.roles}
    forward = (
        bool(tool.roles)
        and ToolRole.SINK not in roles
        and all(ev.granularity == Granularity.TOOL for ev in tool.roles)
        and tool.name != "*"
    )
    return ToolPolicy(forward=forward, inject=ToolRole.UNTRUSTED_SOURCE in roles)


def build_policy(tools: Sequence[ToolSpec]) -> dict[str, ToolPolicy]:
    """Policy per tool name. Duplicate names are refused (the upstream is one server)."""
    policy: dict[str, ToolPolicy] = {}
    for tool in tools:
        if tool.name in policy:
            raise ValueError(f"duplicate tool name in policy input: {tool.name!r}")
        policy[tool.name] = tool_policy(tool)
    return policy


class Decision(StrEnum):
    FORWARD = "forward"
    SANDBOX = "sandbox"


class SandboxReason(StrEnum):
    POLICY_DENY = "policy_deny"  # in policy with forward=False (sink, unclassified, server-level)
    UNKNOWN_TOOL = "unknown_tool"  # not in the policy at all
    NOT_ADVERTISED = "not_advertised"  # forward=True but absent from the upstream tools/list


def decide(
    policy: Mapping[str, ToolPolicy], advertised: frozenset[str], name: str
) -> tuple[Decision, SandboxReason | None]:
    """The handler's decision for one ``tools/call``. Default deny."""
    entry = policy.get(name)
    if entry is None:
        return Decision.SANDBOX, SandboxReason.UNKNOWN_TOOL
    if not entry.forward:
        return Decision.SANDBOX, SandboxReason.POLICY_DENY
    if name not in advertised:
        return Decision.SANDBOX, SandboxReason.NOT_ADVERTISED
    return Decision.FORWARD, None
