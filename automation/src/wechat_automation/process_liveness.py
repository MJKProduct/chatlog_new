from __future__ import annotations

import ctypes
import errno
import os
import sys
from enum import Enum
from typing import Optional


class PidLiveness(str, Enum):
    ALIVE = "ALIVE"
    DEAD = "DEAD"
    UNKNOWN = "UNKNOWN"


if sys.platform == "win32":
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong]
    _kernel32.OpenProcess.restype = ctypes.c_void_p
    _kernel32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    _kernel32.GetExitCodeProcess.restype = ctypes.c_bool
    _kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    _kernel32.CloseHandle.restype = ctypes.c_bool
    _kernel32.GetProcessTimes.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_int64),
        ctypes.POINTER(ctypes.c_int64),
        ctypes.POINTER(ctypes.c_int64),
        ctypes.POINTER(ctypes.c_int64),
    ]
    _kernel32.GetProcessTimes.restype = ctypes.c_bool

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    ERROR_ACCESS_DENIED = 5
    ERROR_INVALID_PARAMETER = 87


def _win_last_error() -> int:
    return ctypes.get_last_error()


def get_process_instance_marker(pid: int) -> Optional[str]:
    """Windows creation time marker for PID instance disambiguation."""
    if sys.platform != "win32" or pid <= 0:
        return None
    handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        created = ctypes.c_int64()
        exit_time = ctypes.c_int64()
        kernel = ctypes.c_int64()
        user = ctypes.c_int64()
        ok = _kernel32.GetProcessTimes(
            handle,
            ctypes.byref(created),
            ctypes.byref(exit_time),
            ctypes.byref(kernel),
            ctypes.byref(user),
        )
        if not ok:
            return None
        return str(int(created.value))
    finally:
        _kernel32.CloseHandle(handle)


def check_pid_liveness(pid: int, expected_instance: Optional[str] = None) -> PidLiveness:
    if pid <= 0:
        return PidLiveness.UNKNOWN
    if sys.platform == "win32":
        handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            err = _win_last_error()
            if err in (ERROR_ACCESS_DENIED, 0):
                return PidLiveness.UNKNOWN
            if err == ERROR_INVALID_PARAMETER:
                return PidLiveness.DEAD
            return PidLiveness.UNKNOWN
        try:
            if expected_instance is not None:
                marker = get_process_instance_marker(pid)
                if marker is None or marker != expected_instance:
                    return PidLiveness.UNKNOWN
            exit_code = ctypes.c_ulong()
            ok = _kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            if not ok:
                return PidLiveness.UNKNOWN
            if int(exit_code.value) == STILL_ACTIVE:
                return PidLiveness.ALIVE
            return PidLiveness.DEAD
        finally:
            _kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return PidLiveness.DEAD
    except PermissionError:
        return PidLiveness.UNKNOWN
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return PidLiveness.DEAD
        return PidLiveness.UNKNOWN
    if expected_instance is not None:
        marker = get_process_instance_marker(pid)
        if marker is None or marker != expected_instance:
            return PidLiveness.UNKNOWN
    return PidLiveness.ALIVE


def is_pid_alive(pid: int) -> bool:
    return check_pid_liveness(pid) == PidLiveness.ALIVE
