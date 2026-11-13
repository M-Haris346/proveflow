"""Mutation: broken grouping must make the scan report refuse to build (not under-report)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import proveflow.scan as scan_module
from fakehome import full_setup
from proveflow.config import ProveflowConfig
from proveflow.core.flows import group_attributes
from proveflow.discover import run_discovery
from proveflow.flows.graph import group_flows


def _scan(tmp_path: Path) -> Any:
    s = full_setup(tmp_path)
    return scan_module.build_scan(run_discovery(s.host, s.project), s.host, s.project,
                                  ProveflowConfig())  # fmt: skip


def test_dropping_a_member_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def drop_one(flows):  # type: ignore[no-untyped-def]
        groups = group_flows(flows)
        big = next(i for i, g in enumerate(groups) if len(g.member_ids) > 1)
        groups[big] = groups[big].model_copy(update={"member_ids": groups[big].member_ids[:-1]})
        return groups

    _scan(tmp_path)  # sanity: the real grouping builds
    monkeypatch.setattr(scan_module, "group_flows", drop_one)
    with pytest.raises(ValidationError):
        _scan(tmp_path)


def test_flow_moved_into_a_wrong_group_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both groups' derived fields are recomputed from their new members, so ONLY the
    member-key check can fire; the exact message is matched."""
    seen: dict[str, str] = {}

    def move_one(flows):  # type: ignore[no-untyped-def]
        by_id = {f.id: f for f in flows}
        groups = group_flows(flows)
        src = next(i for i, g in enumerate(groups) if len(g.member_ids) > 1)
        dst = next(i for i in range(len(groups)) if i != src)
        moved = groups[src].member_ids[-1]
        for i, members in ((src, groups[src].member_ids[:-1]),
                           (dst, (*groups[dst].member_ids, moved))):  # fmt: skip
            attrs = group_attributes([by_id[m] for m in members])
            groups[i] = groups[i].model_copy(update={"member_ids": members, **attrs})
        seen.update(dst=groups[dst].id, moved=moved)
        return groups

    monkeypatch.setattr(scan_module, "group_flows", move_one)
    with pytest.raises(ValidationError) as exc:
        _scan(tmp_path)
    expected = f"group {seen['dst']}: member {seen['moved']} has a different key"
    assert re.search(re.escape(expected), str(exc.value)), str(exc.value)
