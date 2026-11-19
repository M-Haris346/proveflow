"""tools/count_dual_role.py: the ADR-007 counts (12/155 by v2, 10/155 by human labels, 7 in
both) are reproduced from the committed labeled sets by one command."""

from __future__ import annotations

import importlib.util
from pathlib import Path

TOOL = Path(__file__).resolve().parents[2] / "tools" / "count_dual_role.py"


def load() -> object:
    spec = importlib.util.spec_from_file_location("count_dual_role", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_adr_007_counts_are_reproduced() -> None:
    c = load().counts()  # type: ignore[attr-defined]
    assert c["labeled"] == 155
    assert len(c["v2"]) == 12
    assert len(c["human"]) == 10
    assert len(c["both"]) == 7
    assert "fetch" in c["both"]
    # F6: the overlap, stated with its meaning in ADR-007 (Jaccard 7/15).
    assert c["v2_only"] == [
        "browser_navigate",
        "get_blog_post",
        "get_blog_posts",
        "get_linkedin_post",
        "save_conversation",
    ]
    assert c["human_only"] == ["browser_network_requests", "fill", "image_pull"]
    assert len(c["union"]) == 15
