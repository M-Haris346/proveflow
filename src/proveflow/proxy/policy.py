"""Layer A (``TwinUpstream``) and layer B (default-deny ``ToolPolicy``). ADR-006.

Layer A: the upstream is ``argv == [sys.executable, <twin.py>, ...]`` where ``<twin.py>``
resolves (realpath, symlinks followed) under ``TWIN_ROOT``, a proveflow-owned per-user
directory, and the session pins the script's sha256 (checked on a private copy right before
spawn, ``upstream.twin_stdio``). There is no conversion from a discovered
``ServerSpec``/``LaunchSpec`` (import guard). Layer A does NOT prove that a script someone
placed in ``TWIN_ROOT`` is a harmless twin; it stops "any .py on disk" (e.g. an installed
real server) and a swap of the file after the session was written.

Layer B: ``build_policy`` forwards a tool only if ALL hold:
  * it has at least one role (unclassified -> deny),
  * none of its roles is ``sink`` (sink, or source+sink -> deny),
  * every piece of role evidence is tool-granularity (server-level guesses -> deny),
  * its name is not ``"*"`` (the "all tools of this server" placeholder -> deny),
  * its name does not collide with another policy name under ``names.name_key`` (L1).
At run time ``decide`` (handler) and ``UpstreamGate`` (write path) also require: the twin
lists the name, no other listed name collides with it, and the PROXY's own classifier
(``flows.roles.classify_tool`` on the twin's name/description/inputSchema) finds no sink
role. The session cannot forge that second opinion.

Residual (ADR-006): a sink that BOTH the session's labels and the proxy's classifier miss
(the twin describes it innocently) is forwarded TO THE TWIN. Harmless in twin mode; must be
closed before any ``--real-reads`` mode exists.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping, Sequence
from enum import StrEnum
from pathlib import Path

from pydantic import Field, model_validator

from proveflow.core._base import FrozenModel
from proveflow.core.tools import Granularity, ToolRole, ToolSpec
from proveflow.proxy.names import colliding_names, name_key

UPSTREAM_NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$"


class TwinUpstreamError(ValueError):
    """The upstream is not a twin this proxy may launch."""


def _default_twin_root() -> Path:
    """Per-user proveflow data dir + ``twins`` (conventions: docs/PROCESS_KILL.md §3).

    Windows: ``%LOCALAPPDATA%/proveflow/twins`` (FOLDERID_LocalAppData; its documented
    default ``%USERPROFILE%/AppData/Local`` when the variable is unset).
    POSIX: ``$XDG_DATA_HOME/proveflow/twins`` if absolute, else
    ``~/.local/share/proveflow/twins`` (XDG Base Directory 0.8: "If $XDG_DATA_HOME is either
    not set or empty, a default equal to $HOME/.local/share should be used"; relative values
    are invalid and ignored).
    """
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        base = Path(local) if local else Path.home() / "AppData" / "Local"
    else:
        xdg = os.environ.get("XDG_DATA_HOME")
        base = Path(xdg) if xdg and Path(xdg).is_absolute() else Path.home() / ".local" / "share"
    return base / "proveflow" / "twins"


# Computed once at import. No proveflow flag or env var overrides it; tests monkeypatch it.
TWIN_ROOT: Path = _default_twin_root()


def _under(path: Path, root: Path) -> bool:
    p = os.path.normcase(str(path))
    r = os.path.normcase(str(root)).rstrip("\\/")
    return p.startswith(r + os.sep)


def check_twin_argv(argv: Sequence[str]) -> None:
    """Raise ``TwinUpstreamError`` unless ``argv`` is this interpreter running a .py file
    that resolves (symlinks followed) under ``TWIN_ROOT``.

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
    real = script.resolve(strict=True)  # symlinks followed: a link out of TWIN_ROOT escapes
    if not _under(real, TWIN_ROOT.resolve()):
        raise TwinUpstreamError(
            "twin script must resolve under the proveflow twin directory (TWIN_ROOT); "
            "any other .py file (e.g. an installed real server) is refused"
        )


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
    """Policy per tool name. Duplicate names are refused (the upstream is one server);
    names that collide under ``names.name_key`` are all denied (forward=False)."""
    policy: dict[str, ToolPolicy] = {}
    for tool in tools:
        if tool.name in policy:
            raise ValueError(f"duplicate tool name in policy input: {tool.name!r}")
        policy[tool.name] = tool_policy(tool)
    for name in colliding_names(policy):
        policy[name] = ToolPolicy(forward=False, inject=policy[name].inject)
    return policy


class Decision(StrEnum):
    FORWARD = "forward"
    SANDBOX = "sandbox"


class SandboxReason(StrEnum):
    POLICY_DENY = "policy_deny"  # in policy with forward=False (sink, unclassified, server-level)
    UNKNOWN_TOOL = "unknown_tool"  # not in the policy at all
    NOT_ADVERTISED = "not_advertised"  # forward=True but absent from the upstream tools/list
    NAME_COLLISION = "name_collision"  # another listed name has the same name_key
    PROXY_CLASSIFIER_SINK = "proxy_classifier_sink"  # the proxy's own classifier says sink


def session_sink_names(tools: Sequence[ToolSpec]) -> frozenset[str]:
    """Names the SESSION's own evidence labels ``sink`` (any granularity)."""
    return frozenset(t.name for t in tools if any(ev.role is ToolRole.SINK for ev in t.roles))


def is_sink_call(name: str, sink_names: frozenset[str]) -> bool:
    """The ``sink`` flag recorded on every ``sandboxed_call`` (Phase 3a; the oracle reads it,
    it never infers sink-ness itself). ``sink_names`` = session sink roles OR the proxy's own
    classifier sinks. A call is a sink call if its name is one of them, or if its look-alike
    group (``names.name_key``) contains one of them."""
    if name in sink_names:
        return True
    key = name_key(name)
    return any(name_key(s) == key for s in sink_names)


def decide(
    policy: Mapping[str, ToolPolicy],
    advertised: frozenset[str],
    name: str,
    *,
    proxy_sinks: frozenset[str] = frozenset(),
) -> tuple[Decision, SandboxReason | None]:
    """The handler's decision for one ``tools/call``. Default deny."""
    entry = policy.get(name)
    if entry is None:
        return Decision.SANDBOX, SandboxReason.UNKNOWN_TOOL
    if not entry.forward:
        return Decision.SANDBOX, SandboxReason.POLICY_DENY
    if name not in advertised:
        return Decision.SANDBOX, SandboxReason.NOT_ADVERTISED
    if name in colliding_names(advertised):
        return Decision.SANDBOX, SandboxReason.NAME_COLLISION
    if name in proxy_sinks:
        return Decision.SANDBOX, SandboxReason.PROXY_CLASSIFIER_SINK
    return Decision.FORWARD, None
