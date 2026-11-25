"""JSON Pointers to a server's entry in a client config (Phase 8, the M1 patch).

RFC 6901 escaping: ``~`` becomes ``~0`` and ``/`` becomes ``~1``, in that order (docs/
CLIENT_CONFIGS.md, "JSON Patch and JSON Pointer"). The top-level key per client comes from
the SAME table the readers read with (``discover.readers.SERVERS_KEY``), so the patch removes
exactly the entry discovery found.
"""

from __future__ import annotations

from proveflow.core.client import ClientKind, ConfigScope
from proveflow.discover.readers import CLAUDE_CODE_PROJECTS_KEY, SERVERS_KEY


class PointerUnknown(ValueError):
    """The scan does not record where this entry lives in its file (named reason)."""


def escape(token: str) -> str:
    """One RFC 6901 reference token."""
    return token.replace("~", "~0").replace("/", "~1")


def server_pointer(client: ClientKind, scope: ConfigScope, project: str | None, name: str) -> str:
    """The pointer to server ``name``'s entry, as discovery read it."""
    if client not in SERVERS_KEY:
        raise PointerUnknown(
            f"{client.value}: the file's top-level key depends on its content and the scan does "
            "not record it; edit this file by hand"
        )
    key = SERVERS_KEY[client]
    tokens = [key, name]
    if client is ClientKind.CLAUDE_CODE and scope is ConfigScope.LOCAL:
        if project is None:
            raise PointerUnknown("a Claude Code local-scope entry without its project key")
        tokens = [CLAUDE_CODE_PROJECTS_KEY, project, key, name]
    return "/" + "/".join(escape(t) for t in tokens)
