"""Sandbox response shape (D6) and the fail-closed error shape."""

from __future__ import annotations

import json

import mcp_types
import pytest

from proveflow.proxy.sandbox import (
    error_result_dict,
    sandbox_id,
    sandbox_result_dict,
    sandbox_text,
)


def test_sandbox_result_shape() -> None:
    result = mcp_types.CallToolResult.model_validate(sandbox_result_dict(1))
    assert result.is_error is False
    assert result.structured_content is None
    assert len(result.content) == 1
    item = result.content[0]
    assert isinstance(item, mcp_types.TextContent)
    assert json.loads(item.text) == {"ok": True, "id": "sbx_0001"}
    assert item.text == '{"ok": true, "id": "sbx_0001"}'


@pytest.mark.parametrize(("seq", "sid"), [(1, "sbx_0001"), (42, "sbx_0042"), (9999, "sbx_9999")])
def test_sandbox_ids(seq: int, sid: str) -> None:
    assert sandbox_id(seq) == sid
    assert json.loads(sandbox_text(seq))["id"] == sid


@pytest.mark.parametrize("seq", [0, -1, 10000])
def test_sandbox_seq_out_of_range(seq: int) -> None:
    with pytest.raises(ValueError):
        sandbox_id(seq)


def test_error_result_shape() -> None:
    result = mcp_types.CallToolResult.model_validate(error_result_dict("upstream call timed out"))
    assert result.is_error is True
    item = result.content[0]
    assert isinstance(item, mcp_types.TextContent)
    assert item.text == "proveflow proxy: upstream call timed out"
