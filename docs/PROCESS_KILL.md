# Process-tree control and cache location [impl][tested]

> How proveflow makes sure a server it launched for `tools/list` — and everything that server
> spawns — dies on timeout or exit. Every API and constant below comes from the linked official
> page, accessed **2026-11-11**. Code: `src/proveflow/introspect/winjob.py`, `procs.py`.
> Tests: `tests/safety/test_winjob.py`, `tests/safety/test_introspection_safety.py`.

## 1. Windows: Job Object, child created suspended

Decision (Haris, 2026-11-11): documented APIs only, fail closed. Undocumented
`NtResumeProcess` is not used.

### Sequence

1. `CreateJobObjectW(NULL, NULL)`: an unnamed job, handle not inheritable.
2. `SetInformationJobObject(job, JobObjectExtendedLimitInformation = 9, JOBOBJECT_EXTENDED_LIMIT_INFORMATION)`
   with `LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (0x00002000)`. No `BREAKAWAY_OK` /
   `SILENT_BREAKAWAY_OK`, so descendants cannot leave the job.
3. Spawn with `CREATE_SUSPENDED (0x00000004) | CREATE_NO_WINDOW (0x08000000)`. "The primary
   thread of the new process is created in a suspended state, and does not run until the
   ResumeThread function is called."
4. `OpenProcess(PROCESS_SET_QUOTA 0x0100 | PROCESS_TERMINATE 0x0001)` +
   `AssignProcessToJobObject`. Both access rights are what the docs require.
5. CPython does not keep the primary thread: `subprocess.py:1538-1561` (3.12.10) calls
   `CloseHandle(ht)` and does not store `tid`. So the thread is found with
   `CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD 0x4, 0)` + `Thread32First/Thread32Next`,
   "compare its process identifier to the th32OwnerProcessID member" (`THREADENTRY32.dwSize` is
   set first, as the docs require). Enumeration must end with `ERROR_NO_MORE_FILES (18)`.
6. `OpenThread(THREAD_SUSPEND_RESUME 0x0002)` + `ResumeThread`. The return value is "the
   thread's previous suspend count", `(DWORD)-1` on failure.
7. Kill: `TerminateJobObject(job, 1)` ("It is not possible for any of the processes associated
   with the job to postpone or handle the termination") + `CloseHandle(job)` (with
   KILL_ON_JOB_CLOSE, "closing the last job object handle terminates all associated processes").

### Fail-closed rules

The server is killed and reported `failed`, and nothing outside the job ever runs, if:

- `AssignProcessToJobObject` fails (the child is still suspended, so it is terminated directly);
- zero threads owned by the child are found;
- any `ResumeThread` returns anything other than 1;
- the thread enumeration ends with any error other than `ERROR_NO_MORE_FILES`.

Each case is covered by `test_job_setup_failure_fails_closed[...]` and
`test_resume_requires_exactly_one`. These tests check that the process is dead and that the
server's first action never happened.

### Proof that grandchildren are inside the job

`test_immediate_grandchild_is_inside_job_and_dies`: the fake server's first statement spawns a
child, which immediately spawns a grandchild. `IsProcessInJob` (handle with
`PROCESS_QUERY_LIMITED_INFORMATION 0x1000`) returns TRUE for the server, the child and the
grandchild. After `kill_tree` all three are gone (checked with psutil, a dev-only dependency).

### Sources (Microsoft Learn)

| API / constant | URL |
|---|---|
| CreateJobObjectW | <https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-createjobobjectw> |
| SetInformationJobObject (class 9) | <https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-setinformationjobobject> |
| JOBOBJECT_BASIC_LIMIT_INFORMATION (KILL_ON_JOB_CLOSE, BREAKAWAY flags) | <https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_limit_information> |
| JOBOBJECT_EXTENDED_LIMIT_INFORMATION | <https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_extended_limit_information> |
| IO_COUNTERS | <https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-io_counters> |
| AssignProcessToJobObject | <https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-assignprocesstojobobject> |
| TerminateJobObject | <https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-terminatejobobject> |
| IsProcessInJob | <https://learn.microsoft.com/en-us/windows/win32/api/jobapi/nf-jobapi-isprocessinjob> |
| Process creation flags | <https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags> |
| Process access rights | <https://learn.microsoft.com/en-us/windows/win32/procthread/process-security-and-access-rights> |
| Thread access rights | <https://learn.microsoft.com/en-us/windows/win32/procthread/thread-security-and-access-rights> |
| CreateToolhelp32Snapshot | <https://learn.microsoft.com/en-us/windows/win32/api/tlhelp32/nf-tlhelp32-createtoolhelp32snapshot> |
| THREADENTRY32 | <https://learn.microsoft.com/en-us/windows/win32/api/tlhelp32/ns-tlhelp32-threadentry32> |
| Thread32Next (and First) | <https://learn.microsoft.com/en-us/windows/win32/api/tlhelp32/nf-tlhelp32-thread32next> |
| OpenThread | <https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-openthread> |
| ResumeThread | <https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-resumethread> |
| System error codes (ERROR_NO_MORE_FILES = 18) | <https://learn.microsoft.com/en-us/windows/win32/debug/system-error-codes--0-499-> |

### Residual risks (stated)

- **Toolhelp caveat:** the CreateToolhelp32Snapshot page says "Ensure that the target process
  was not started in a suspended state" in the context of *heap/module* snapshots that read the
  loader table. proveflow takes a *thread* snapshot only, which does not read the loader table.
  The docs do not say this explicitly for thread snapshots, and the tests show it works on
  Windows 11 Pro 10.0.26200.
- **`.cmd` launches (`npx` → `npx.cmd`):** arguments pass through cmd.exe, whose parsing differs
  from CreateProcess quoting (THREAT_MODEL T13). proveflow refuses a `.cmd`/`.bat` launch if any
  argument contains `" & | < > ^ % !` or a newline. A server with such arguments is reported
  `failed` with that reason.
- **Nested jobs:** if proveflow itself runs inside a job (some terminals or IDEs do that), the
  child belongs to both jobs. Windows 8+ allows nested jobs (AssignProcessToJobObject page).

## 2. POSIX: process group

`start_new_session=True` makes the server a session and process-group leader, and
`os.killpg(pgid, SIGKILL)` kills every descendant still in that group. **Limit:** a descendant
that calls `setsid()` / `setpgid()` itself leaves the group and survives. Linux cgroups would
close that gap but are out of scope for Phase 1. The POSIX path has no Linux test run yet: CI
has never run (no remote).

## 3. Cache location (per-user, never the project directory)

| OS | Default | Source |
|---|---|---|
| Windows | `%LOCALAPPDATA%\proveflow\cache`. FOLDERID_LocalAppData default path is "%LOCALAPPDATA% (%USERPROFILE%\AppData\Local)". If `LOCALAPPDATA` is unset, caching is off | <https://learn.microsoft.com/en-us/windows/win32/shell/knownfolderid> |
| macOS | `~/Library/Caches/proveflow`. "Put data cache files in the `Library/Caches/` directory" | <https://developer.apple.com/library/archive/documentation/FileManagement/Conceptual/FileSystemProgrammingGuide/FileSystemOverview/FileSystemOverview.html> |
| Linux | `$XDG_CACHE_HOME/proveflow`. "If $XDG_CACHE_HOME is either not set or empty, a default equal to $HOME/.cache should be used". Relative paths are invalid and ignored | <https://specifications.freedesktop.org/basedir/latest/> (Version 0.8) |

`--cache-dir DIR` overrides the default, and `--no-cache-write` compares against the cache
without updating it. The cache stores **only tool names and sha256 hashes** of each description
and schema, never the descriptions themselves.

## 4. Executable resolution and working directory (binary planting)

**Resolution.** CPython 3.12 `shutil.which` on Windows prepends the **current directory** to
the search path even when `path=` is given: `Lib/shutil.py` `which()` does `path.insert(0,
curdir)` when `NeedCurrentDirectoryForExePathW(cmd)` is true, as the 3.12 docs describe
("the current directory is prepended ... To avoid consulting the current working directory
for executables: set the environment variable `NoDefaultCurrentDirectoryInExePath`").
<https://docs.python.org/3.12/library/shutil.html#shutil.which>. Run from a scanned
repository, a planted `npx.cmd` there would be launched instead of the real npx. The shell these
tests were developed in sets `NoDefaultCurrentDirectoryInExePath=1`, which hid the problem;
a normal user shell does not set it.

proveflow therefore searches PATH itself (`introspect/procs.py:resolve_command`). It **never**
returns:
- a file from the current directory (exact match only: running from `~` must still find
  `%APPDATA%\npm`);
- a file from a relative PATH entry (those resolve against the current directory);
- a file from the scanned project or any directory under it (e.g. `node_modules/.bin`).

A command that is itself a path (has a directory part) is the config's own choice and is
resolved as written. Test: `test_planted_binary_in_cwd_is_never_resolved`. It first shows the
stdlib resolving the planted file (with the env var removed), then shows proveflow refusing it.

**Working directory.** Every server runs in a fresh, empty, private temp directory, which is
removed afterwards. It is **never** the scanned project. The npx docs say a package name
without a specifier "will be matched with whatever version exists in the local project", so a
project cwd would let the repository pick the code.

What each client does (official docs, 2026-11-11). This is the stated gap:

| Client | cwd for stdio servers |
|---|---|
| VS Code | `cwd` field: "Defaults to the workspace folder when run in a workspace" (editor-managed format) |
| Claude Code | not stated; it sets `CLAUDE_PROJECT_DIR` in the server's env "so your server can resolve project-relative paths without depending on the working directory" |
| Cursor, Windsurf, Claude Desktop | not stated |

So a server that reads relative paths at *startup* can behave differently under proveflow than
under its client. `tools/list` rarely depends on that, but a failure here is reported, not
hidden.

