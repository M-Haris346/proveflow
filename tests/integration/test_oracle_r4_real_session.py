"""R4's ordering assumptions, MEASURED on real in-process proxy sessions (Phase 3b): no
injection precedes its own call; a valid trial (a call over the cap, a session cut by a
message cap, an upstream crash) pairs with its transcript instead of being refused; the
call-cap refusal names the refused tool; and an early stop is terminal."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from oraclechecks import (
    assert_cap_refusal_names_the_refused_tool,
    assert_early_stop_is_terminal,
    assert_real_sessions_order_as_r4_assumes,
)
from proxyhelpers import proxy_twin_root  # noqa: F401


def test_real_sessions_order_as_r4_assumes(tmp_path: Path, proxy_twin_root: Any) -> None:  # noqa: F811
    assert_real_sessions_order_as_r4_assumes(tmp_path)


def test_cap_refusal_names_the_refused_tool(tmp_path: Path, proxy_twin_root: Any) -> None:  # noqa: F811
    assert_cap_refusal_names_the_refused_tool(tmp_path)


def test_early_stop_is_terminal(tmp_path: Path, proxy_twin_root: Any) -> None:  # noqa: F811
    assert_early_stop_is_terminal(tmp_path)
