"""The sandbox response for every ``tools/call`` that is not forwarded (D6).

Shape (fixed, so an agent cannot tell a sandboxed sink from a cheap success):
``CallToolResult(isError=false, content=[TextContent('{"ok": true, "id": "sbx_0001"}')])``.
Ids are sequential per session starting at ``sbx_0001``.
"""

from __future__ import annotations

import json
from typing import Any

MAX_SANDBOX_SEQ = 9999


def sandbox_id(seq: int) -> str:
    if not 1 <= seq <= MAX_SANDBOX_SEQ:
        raise ValueError(f"sandbox seq out of range: {seq}")
    return f"sbx_{seq:04d}"


def sandbox_text(seq: int) -> str:
    return json.dumps({"ok": True, "id": sandbox_id(seq)})


def sandbox_result_dict(seq: int) -> dict[str, Any]:
    """Wire form (camelCase) of the sandbox ``CallToolResult``."""
    return {"content": [{"type": "text", "text": sandbox_text(seq)}], "isError": False}


def error_result_dict(reason: str) -> dict[str, Any]:
    """Wire form of the fail-closed tool error: ``isError=true``, nothing forwarded."""
    return {"content": [{"type": "text", "text": f"proveflow proxy: {reason}"}], "isError": True}
