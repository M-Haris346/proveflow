"""Windows Job Object: an immediately spawned grandchild is inside the job; every failure
in the suspend -> assign -> resume sequence fails closed (docs/PROCESS_KILL.md)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import anyio
import psutil
import pytest

from fakehome import FAKE_SERVER

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object tests")


def _alive(pid: int) -> bool:
    try:
        return psutil.Process(pid).is_running()
    except psutil.NoSuchProcess:
        return False


def _wait_dead(pids: list[int], seconds: float = 10.0) -> list[int]:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        alive = [p for p in pids if _alive(p)]
        if not alive:
            return []
        time.sleep(0.1)
    return [p for p in pids if _alive(p)]


def _sleep_argv(tmp_path: Path) -> list[str]:
    return [sys.executable, str(FAKE_SERVER), "--mode", "sleep", "--log", str(tmp_path / "l"),
            "--pids", str(tmp_path / "pids")]  # fmt: skip


def test_immediate_grandchild_is_inside_job_and_dies(tmp_path: Path) -> None:
    from proveflow.introspect.procs import spawn

    async def run() -> tuple[list[int], list[bool]]:
        import os

        spawned = await spawn(_sleep_argv(tmp_path), dict(os.environ))
        pids_file = tmp_path / "pids"
        with anyio.fail_after(30):
            while not (pids_file.exists() and pids_file.read_text().strip()):
                await anyio.sleep(0.05)
        child, grandchild = (int(p) for p in pids_file.read_text().split())
        inside = [
            spawned.contains(spawned.pid),
            spawned.contains(child),
            spawned.contains(grandchild),
        ]
        await spawned.kill_tree()
        return [spawned.pid, child, grandchild], inside

    pids, inside = anyio.run(run)
    assert inside == [True, True, True]
    assert _wait_dead(pids) == []


@pytest.mark.parametrize("failing_step", ["assign", "zero_threads", "resume_not_one"])
def test_job_setup_failure_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failing_step: str
) -> None:
    from proveflow.introspect import procs, winjob

    seen: list[int] = []
    real_thread_ids = winjob.thread_ids

    if failing_step == "assign":

        def bad_assign(self: winjob.WinJob, pid: int) -> None:
            seen.append(pid)
            raise winjob.WinJobError(5, "AssignProcessToJobObject failed (simulated)")

        monkeypatch.setattr(winjob.WinJob, "assign", bad_assign)
    elif failing_step == "zero_threads":

        def no_threads(pid: int) -> list[int]:
            seen.append(pid)
            return []

        monkeypatch.setattr(winjob, "thread_ids", no_threads)
    else:

        def track(pid: int) -> list[int]:
            seen.append(pid)
            return real_thread_ids(pid)

        monkeypatch.setattr(winjob, "thread_ids", track)
        monkeypatch.setattr(winjob, "_ResumeThread", lambda handle: 2)

    import os

    async def run() -> None:
        await procs.spawn(_sleep_argv(tmp_path), dict(os.environ))

    with pytest.raises(procs.SpawnError, match="job-object setup failed"):
        anyio.run(run)
    assert seen, "the failing step was not reached"
    assert _wait_dead(seen) == []
    # The server never ran: its first act (writing pids) never happened.
    assert not (tmp_path / "pids").exists()


def test_resume_requires_exactly_one(monkeypatch: pytest.MonkeyPatch) -> None:
    from proveflow.introspect import winjob

    monkeypatch.setattr(winjob, "thread_ids", lambda pid: [123])
    monkeypatch.setattr(winjob, "_OpenThread", lambda *a: 1)
    monkeypatch.setattr(winjob, "_CloseHandle", lambda h: 1)
    for value, ok in ((1, True), (0, False), (2, False), (winjob.RESUME_FAILED, False)):
        monkeypatch.setattr(winjob, "_ResumeThread", lambda h, v=value: v)
        if ok:
            assert winjob.resume_suspended(99) == 1
        else:
            with pytest.raises(winjob.WinJobError):
                winjob.resume_suspended(99)
