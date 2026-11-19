"""Mutation: break one rule of the dual-role exception or the guard step -> the NAMED
twin-side safety check fails.

* pure sink allowed onto the dual-role path (source requirement dropped on both sides)
  -> assert_pure_sink_never_reaches_twin_with_dual_role_on fails (tee log)
* dual-role forwarded without guard_passed
  -> assert_dual_role_never_reaches_guard_failing_twin fails (fake twin's own log)
* the guard reads the ORIGINAL path instead of the hashed copy (R4)
  -> assert_guard_runs_on_the_hashed_copy fails
"""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Collection, Mapping, Sequence
from pathlib import Path

import pytest

from proveflow.core.tools import ToolRole, ToolSpec
from proveflow.proxy import server, upstream
from proveflow.proxy.names import colliding_names
from proveflow.proxy.policy import TwinUpstreamError
from proxyhelpers import proxy_twin_root  # noqa: F401
from twinproxy import (
    assert_dual_role_never_reaches_guard_failing_twin,
    assert_guard_runs_on_the_hashed_copy,
    assert_pure_sink_never_reaches_twin_with_dual_role_on,
)


def _dirs(tmp_path: Path) -> tuple[Path, Path]:
    ok, mut = tmp_path / "ok", tmp_path / "mut"
    ok.mkdir()
    mut.mkdir()
    return ok, mut


def _sink_only_dual_roles(
    tools: Sequence[ToolSpec],
    proxy_roles: Mapping[str, Collection[str]],
    advertised: frozenset[str],
) -> frozenset[str]:
    """Mutant of policy.dual_role_names: 'sink on both sides' (source requirement dropped)."""
    session = {t.name for t in tools if ToolRole.SINK in {e.role for e in t.roles}}
    proxy = {n for n, r in proxy_roles.items() if ToolRole.SINK.value in r}
    return frozenset(session & proxy & advertised) - colliding_names(advertised)


def test_pure_sink_on_the_dual_role_path_fails_the_named_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ok, mut = _dirs(tmp_path)
    with monkeypatch.context() as m:
        assert_pure_sink_never_reaches_twin_with_dual_role_on(ok, m)
    monkeypatch.setattr(server, "dual_role_names", _sink_only_dual_roles)
    with pytest.raises(AssertionError, match="pure sink reached the twin"):
        assert_pure_sink_never_reaches_twin_with_dual_role_on(mut, monkeypatch)


def test_dual_role_without_guard_passed_fails_the_named_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ok, mut = _dirs(tmp_path)
    assert_dual_role_never_reaches_guard_failing_twin(ok)
    real = server.forwardable_dual_roles

    def ignore_guard(session_tools, advertised_tools, *, guard_passed):  # type: ignore[no-untyped-def]
        return real(session_tools, advertised_tools, guard_passed=True)

    monkeypatch.setattr(server, "forwardable_dual_roles", ignore_guard)
    with pytest.raises(AssertionError, match="dual-role tool reached a guard-failing twin"):
        assert_dual_role_never_reaches_guard_failing_twin(mut)


@pytest.mark.parametrize("original_passes", [True, False], ids=["generated", "fake"])
def test_guard_on_the_original_path_fails_the_named_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, original_passes: bool
) -> None:
    ok, mut = _dirs(tmp_path)
    with monkeypatch.context() as m:
        assert_guard_runs_on_the_hashed_copy(ok, m, original_passes=original_passes)

    def guard_original(source: Path, workdir: Path, twin_sha256: str) -> tuple[Path, bool]:
        copy = workdir / source.name
        shutil.copyfile(source, copy)
        if hashlib.sha256(copy.read_bytes()).hexdigest() != twin_sha256:
            raise TwinUpstreamError("sha256")
        return copy, upstream.guard_verdict(source.read_bytes())  # mutant: original path

    monkeypatch.setattr(upstream, "prepare_twin_copy", guard_original)
    with pytest.raises(AssertionError, match=r"did not follow the hashed copy|bytes that were"):
        assert_guard_runs_on_the_hashed_copy(mut, monkeypatch, original_passes=original_passes)
