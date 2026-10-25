"""Start a long-running child that outlives the client hook which spawned it.

The child receives no pipe of the caller: stdin is DEVNULL and stdout/stderr go to a log
file, so a client waiting for EOF on the hook's captured pipes returns as soon as the hook
exits. On Windows the child is detached and, when the hook sits in a Job Object that kills
its children, it first tries to break away from that job.
"""

import subprocess
import sys
from pathlib import Path
from typing import IO

_DETACHED_PROCESS: int = getattr(subprocess, "DETACHED_PROCESS", 0)
_CREATE_NEW_PROCESS_GROUP: int = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
_CREATE_BREAKAWAY_FROM_JOB: int = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)


def _open_log(log_path: Path) -> IO[bytes]:
    """Open the log for appending by the child as well as by this process.

    On POSIX, O_APPEND is shared through the inherited descriptor. On Windows an inherited
    handle keeps its own file pointer, so two children could overwrite each other. A handle
    with FILE_APPEND_DATA but no FILE_WRITE_DATA makes every write go to end of file.
    """
    if sys.platform != "win32":
        return log_path.open("ab")
    import ctypes
    import msvcrt
    from ctypes import wintypes

    file_append_data = 0x0004
    synchronize = 0x00100000
    share_all = 0x1 | 0x2 | 0x4  # read | write | delete
    open_always = 4
    file_attribute_normal = 0x80
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
    ]
    kernel.CreateFileW.restype = ctypes.c_void_p
    handle = kernel.CreateFileW(
        str(log_path),
        file_append_data | synchronize,
        share_all,
        None,
        open_always,
        file_attribute_normal,
        None,
    )
    if handle is None or handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    descriptor = msvcrt.open_osfhandle(handle, 0)
    # "wb" does not truncate an existing descriptor; no Python-side write ever happens.
    return open(descriptor, "wb", closefd=True)


def _start(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None,
    log: IO[bytes],
    creationflags: int = 0,
) -> subprocess.Popen[bytes]:
    if sys.platform == "win32":
        return subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            close_fds=True,
            creationflags=creationflags,
        )
    return subprocess.Popen(
        argv,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        close_fds=True,
        start_new_session=True,
    )


def spawn_detached(
    argv: list[str], *, cwd: Path, log_path: Path, env: dict[str, str] | None = None
) -> int:
    """Start ``argv`` without waiting for it and return the child's pid.

    Raises OSError when the executable cannot be started. The log file is opened in append
    mode in this process and closed once the child has been created.
    """
    if not argv:
        raise OSError("spawn_detached requires a non-empty argv")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with _open_log(log_path) as log:
        if sys.platform != "win32":
            return _start(argv, cwd=cwd, env=env, log=log).pid
        flags = _DETACHED_PROCESS | _CREATE_NEW_PROCESS_GROUP
        try:
            return _start(
                argv, cwd=cwd, env=env, log=log, creationflags=flags | _CREATE_BREAKAWAY_FROM_JOB
            ).pid
        except OSError:
            # The job may forbid breakaway (ERROR_ACCESS_DENIED); retry inside it. A missing
            # executable fails again here and propagates as OSError.
            return _start(argv, cwd=cwd, env=env, log=log, creationflags=flags).pid
