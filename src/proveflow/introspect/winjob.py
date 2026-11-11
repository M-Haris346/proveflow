"""Windows process-tree control with a Job Object, documented Win32 APIs only.

Every API, constant and struct below is cited in docs/PROCESS_KILL.md (Microsoft Learn,
accessed 2026-11-11). Sequence used by ``procs.spawn`` (fail closed at every step):

1. ``CreateJobObjectW`` + ``SetInformationJobObject(JobObjectExtendedLimitInformation)``
   with ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`` (no breakaway flags).
2. Spawn the child with ``CREATE_SUSPENDED`` (its primary thread does not run).
3. ``AssignProcessToJobObject`` (handle opened with PROCESS_SET_QUOTA | PROCESS_TERMINATE).
4. Find the child's threads with ``CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD)`` +
   ``Thread32First/Next``, comparing ``th32OwnerProcessID`` (CPython's subprocess closes
   the primary thread handle and does not keep the thread id: subprocess.py:1538-1561).
5. ``OpenThread(THREAD_SUSPEND_RESUME)`` + ``ResumeThread``; every return value must be 1.

No undocumented API (e.g. NtResumeProcess) is used.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

assert sys.platform == "win32"  # noqa: S101 - platform guard (also narrows mypy)

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)

# Process Creation Flags
CREATE_SUSPENDED = 0x00000004
CREATE_NO_WINDOW = 0x08000000
# JOBOBJECT_BASIC_LIMIT_INFORMATION.LimitFlags
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
# JOBOBJECTINFOCLASS (SetInformationJobObject)
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
# Process / thread access rights
PROCESS_TERMINATE = 0x0001
PROCESS_SET_QUOTA = 0x0100
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
THREAD_SUSPEND_RESUME = 0x0002
# Toolhelp
TH32CS_SNAPTHREAD = 0x00000004
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
# System error codes
ERROR_NO_MORE_FILES = 18
RESUME_FAILED = 0xFFFFFFFF  # (DWORD) -1


class WinJobError(OSError):
    """A Job Object step failed; the caller must kill and report the server as failed."""


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),  # LARGE_INTEGER
        ("PerJobUserTimeLimit", ctypes.c_int64),  # LARGE_INTEGER
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),  # ULONG_PTR
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class THREADENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ThreadID", wintypes.DWORD),
        ("th32OwnerProcessID", wintypes.DWORD),
        ("tpBasePri", wintypes.LONG),
        ("tpDeltaPri", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
    ]


def _proto(name: str, restype: object, *argtypes: object) -> ctypes._NamedFuncPointer:
    fn = getattr(_k32, name)
    fn.restype = restype
    fn.argtypes = list(argtypes)
    return fn  # type: ignore[no-any-return]


_CreateJobObjectW = _proto("CreateJobObjectW", wintypes.HANDLE, wintypes.LPVOID, wintypes.LPCWSTR)
_SetInformationJobObject = _proto(
    "SetInformationJobObject",
    wintypes.BOOL,
    wintypes.HANDLE,
    ctypes.c_int,
    wintypes.LPVOID,
    wintypes.DWORD,
)
_AssignProcessToJobObject = _proto(
    "AssignProcessToJobObject", wintypes.BOOL, wintypes.HANDLE, wintypes.HANDLE
)
_TerminateJobObject = _proto("TerminateJobObject", wintypes.BOOL, wintypes.HANDLE, wintypes.UINT)
_IsProcessInJob = _proto(
    "IsProcessInJob", wintypes.BOOL, wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)
)
_OpenProcess = _proto("OpenProcess", wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
_OpenThread = _proto("OpenThread", wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
_ResumeThread = _proto("ResumeThread", wintypes.DWORD, wintypes.HANDLE)
_CreateToolhelp32Snapshot = _proto(
    "CreateToolhelp32Snapshot", wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD
)
_Thread32First = _proto(
    "Thread32First", wintypes.BOOL, wintypes.HANDLE, ctypes.POINTER(THREADENTRY32)
)
_Thread32Next = _proto(
    "Thread32Next", wintypes.BOOL, wintypes.HANDLE, ctypes.POINTER(THREADENTRY32)
)
_CloseHandle = _proto("CloseHandle", wintypes.BOOL, wintypes.HANDLE)


def _fail(step: str) -> WinJobError:
    err = ctypes.get_last_error()
    return WinJobError(err, f"{step} failed (Win32 error {err})")


class WinJob:
    """A Job Object whose processes all die when it is terminated or its handle closes."""

    def __init__(self) -> None:
        handle = _CreateJobObjectW(None, None)
        if not handle:
            raise _fail("CreateJobObjectW")
        self._handle: int | None = handle
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = _SetInformationJobObject(
            handle,
            JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not ok:
            error = _fail("SetInformationJobObject")
            self.close()
            raise error

    def assign(self, pid: int) -> None:
        proc = _OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, pid)
        if not proc:
            raise _fail("OpenProcess")
        try:
            if not _AssignProcessToJobObject(self._handle, proc):
                raise _fail("AssignProcessToJobObject")
        finally:
            _CloseHandle(proc)

    def contains(self, pid: int) -> bool:
        """True if ``pid`` is in this job (IsProcessInJob). Used by tests and checks."""
        proc = _OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not proc:
            raise _fail("OpenProcess")
        try:
            result = wintypes.BOOL(False)
            if not _IsProcessInJob(proc, self._handle, ctypes.byref(result)):
                raise _fail("IsProcessInJob")
            return bool(result.value)
        finally:
            _CloseHandle(proc)

    def terminate(self) -> None:
        if self._handle is not None:
            _TerminateJobObject(self._handle, 1)

    def close(self) -> None:
        """Close the last handle; KILL_ON_JOB_CLOSE terminates any remaining members."""
        if self._handle is not None:
            _CloseHandle(self._handle)
            self._handle = None


def thread_ids(pid: int) -> list[int]:
    """Thread ids owned by ``pid`` (Toolhelp thread snapshot, all threads of the system)."""
    snap = _CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    if not snap or snap == INVALID_HANDLE_VALUE:
        raise _fail("CreateToolhelp32Snapshot")
    try:
        entry = THREADENTRY32()
        entry.dwSize = ctypes.sizeof(THREADENTRY32)
        out: list[int] = []
        ok = _Thread32First(snap, ctypes.byref(entry))
        while ok:
            if entry.th32OwnerProcessID == pid:
                out.append(int(entry.th32ThreadID))
            ok = _Thread32Next(snap, ctypes.byref(entry))
        err = ctypes.get_last_error()
        if err != ERROR_NO_MORE_FILES:
            raise WinJobError(err, f"Thread32First/Next ended with Win32 error {err}")
        return out
    finally:
        _CloseHandle(snap)


def resume_suspended(pid: int) -> int:
    """Resume every thread of a CREATE_SUSPENDED process. Fail closed: zero threads, or any
    ResumeThread result other than 1 (previous suspend count), raises WinJobError."""
    tids = thread_ids(pid)
    if not tids:
        raise WinJobError(0, "no threads found for suspended process")
    for tid in tids:
        handle = _OpenThread(THREAD_SUSPEND_RESUME, False, tid)
        if not handle:
            raise _fail("OpenThread")
        try:
            previous = _ResumeThread(handle)
        finally:
            _CloseHandle(handle)
        if previous == RESUME_FAILED:
            raise _fail("ResumeThread")
        if previous != 1:
            raise WinJobError(0, f"ResumeThread returned {previous}, expected 1")
    return len(tids)
