"""Spawn a server process and kill its whole tree. No shell, pipes only.

Windows: Job Object with KILL_ON_JOB_CLOSE, child created suspended, assigned, then resumed
(``winjob``; docs/PROCESS_KILL.md). Any failure in that sequence kills the child and raises:
proveflow never runs a server outside the job.
POSIX: ``start_new_session=True`` makes the child a process-group leader;
``os.killpg(SIGKILL)`` reaches every descendant that stayed in the group.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import anyio
from anyio.abc import Process

# cmd.exe metacharacters: a .cmd/.bat launch passes args through cmd.exe, whose parsing
# differs from CreateProcess quoting (THREAT_MODEL T13). Such launches are refused.
_CMD_UNSAFE = frozenset('"&|<>^%!\r\n')


class SpawnError(RuntimeError):
    """The server could not be started safely. Message never contains arg values."""


_WIN_DEFAULT_PATHEXT = ".COM;.EXE;.BAT;.CMD"


def _norm(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def _is_under(path: str, roots: Sequence[str]) -> bool:
    return any(path == r or path.startswith(r.rstrip(os.sep) + os.sep) for r in roots)


def resolve_command(
    command: str, env: Mapping[str, str], untrusted_dirs: Sequence[Path] = ()
) -> str:
    """Resolve a bare command name on PATH without binary planting (THREAT_MODEL T14).

    CPython 3.12 ``shutil.which`` on Windows prepends the CURRENT DIRECTORY to the search
    path even when ``path=`` is given (shutil.py ``which``: ``path.insert(0, curdir)``
    when ``NeedCurrentDirectoryForExePathW`` is true; documented in the 3.12 shutil docs).
    So proveflow searches PATH itself and never returns a file from the current directory,
    a relative PATH entry, or an untrusted directory (the scanned project). A command that
    is itself an explicit path (has a directory part) is the config's own choice and is
    resolved as written.
    """
    if os.path.dirname(command):
        found = shutil.which(command)
        if found is None:
            raise SpawnError(f"explicit command path not found: {os.path.basename(command)!r}")
        return found
    # The CWD itself is skipped (not its subtree: running from ~ must still find e.g.
    # %APPDATA%\npm). Untrusted dirs (the scanned project) are skipped with their subtree.
    cwd = _norm(os.getcwd())
    banned = [_norm(str(d)) for d in untrusted_dirs]
    if sys.platform == "win32":
        exts = [e for e in (env.get("PATHEXT") or _WIN_DEFAULT_PATHEXT).split(os.pathsep) if e]
        has_ext = any(command.lower().endswith(e.lower()) for e in exts)
        names = ([command] if has_ext else []) + [command + e for e in exts]
    else:
        names = [command]
    for entry in (env.get("PATH") or "").split(os.pathsep):
        if not entry or not os.path.isabs(entry):
            continue  # relative entries resolve against the current directory
        normed = _norm(entry)
        if normed == cwd or _is_under(normed, banned):
            continue
        for name in names:
            candidate = os.path.join(entry, name)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
    raise SpawnError(f"command not found on PATH: {command!r}")


def check_cmd_args(resolved: str, args: Sequence[str]) -> None:
    if sys.platform != "win32":
        return
    if resolved.lower().endswith((".cmd", ".bat")) and any(
        ch in _CMD_UNSAFE for a in args for ch in a
    ):
        raise SpawnError(
            "refusing .cmd/.bat launch: an argument contains a cmd.exe metacharacter "
            '(one of " & | < > ^ % ! or a newline); quoting would differ from the client'
        )


@dataclass
class Spawned:
    process: Process
    job: Any = None  # winjob.WinJob on Windows
    killed: bool = field(default=False)

    @property
    def pid(self) -> int:
        return self.process.pid

    def contains(self, pid: int) -> bool:
        """Windows only: is ``pid`` inside this server's job?"""
        if self.job is None:
            raise RuntimeError("no job object (not Windows)")
        return bool(self.job.contains(pid))

    async def kill_tree(self) -> None:
        if self.killed:
            return
        self.killed = True
        if sys.platform == "win32":
            if self.job is not None:
                self.job.terminate()
                self.job.close()
        else:
            with suppress(ProcessLookupError, PermissionError):
                os.killpg(self.process.pid, signal.SIGKILL)
        with suppress(ProcessLookupError, OSError):
            self.process.kill()
        with anyio.move_on_after(5), suppress(Exception):
            await self.process.wait()
        # Close our pipe ends too (otherwise asyncio warns about unclosed transports).
        with anyio.move_on_after(5), suppress(Exception):
            await self.process.aclose()


async def spawn(
    argv: Sequence[str],
    env: Mapping[str, str],
    *,
    cwd: Path | None = None,
    untrusted_dirs: Sequence[Path] = (),
) -> Spawned:
    """Start ``argv`` in its own job / process group. ``cwd`` should be an empty temp dir
    (docs/PROCESS_KILL.md §4): never the scanned project, so nothing in it is picked up."""
    resolved = resolve_command(argv[0], env, untrusted_dirs)
    args = list(argv[1:])
    check_cmd_args(resolved, args)
    if sys.platform == "win32":
        from proveflow.introspect import winjob

        job = winjob.WinJob()
        try:
            process = await anyio.open_process(
                [resolved, *args],
                env=dict(env),
                cwd=cwd,
                creationflags=winjob.CREATE_SUSPENDED | winjob.CREATE_NO_WINDOW,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except BaseException:
            job.close()
            raise
        try:
            job.assign(process.pid)
            winjob.resume_suspended(process.pid)
        except BaseException as exc:
            # Fail closed: the suspended child never ran outside the job.
            job.terminate()
            job.close()
            with suppress(ProcessLookupError, OSError):
                process.kill()
            with anyio.move_on_after(5), suppress(Exception):
                await process.wait()
            raise SpawnError(f"job-object setup failed: {exc}") from None
        return Spawned(process=process, job=job)
    process = await anyio.open_process(
        [resolved, *args],
        env=dict(env),
        cwd=cwd,
        start_new_session=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return Spawned(process=process)
