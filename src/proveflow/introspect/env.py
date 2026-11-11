"""Child environment for a launched server: minimal allow-list + the config's own env.

The allow-list mirrors the MCP Python SDK 2.3.0 default (``mcp/client/stdio.py:41-91``,
docs/MCP_SDK.md): the user's full shell environment is NOT inherited, so secrets that
live only in the user's shell never reach an untrusted server. Values starting with
``()`` (exported shell functions) are skipped, as in the SDK.
"""

from __future__ import annotations

from collections.abc import Mapping

WINDOWS_ALLOWED = (
    "APPDATA",
    "HOMEDRIVE",
    "HOMEPATH",
    "LOCALAPPDATA",
    "PATH",
    "PATHEXT",
    "PROCESSOR_ARCHITECTURE",
    "SYSTEMDRIVE",
    "SYSTEMROOT",
    "TEMP",
    "USERNAME",
    "USERPROFILE",
)
POSIX_ALLOWED = ("HOME", "LOGNAME", "PATH", "SHELL", "TERM", "USER")


def child_env(
    parent: Mapping[str, str], config_env: Mapping[str, str], *, windows: bool
) -> dict[str, str]:
    allowed = WINDOWS_ALLOWED if windows else POSIX_ALLOWED
    base = {k: parent[k] for k in allowed if k in parent and not parent[k].startswith("()")}
    return base | dict(config_env)
