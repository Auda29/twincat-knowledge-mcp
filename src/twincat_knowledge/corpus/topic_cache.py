"""Private loader caches with conservative recovery after process termination."""

from __future__ import annotations

import ctypes
import json
import os
import re
import stat
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

_NAME = re.compile(r"^\.topic-package-load-[a-z0-9_]{8}$")
_OWNER = ".owner.json"
_FILES = frozenset({_OWNER, "topics.jsonl", "topics.sqlite"})


def _plain(path: Path, kind: int) -> os.stat_result:
    metadata = path.lstat()
    if (
        stat.S_IFMT(metadata.st_mode) != kind
        or getattr(metadata, "st_file_attributes", 0) & 0x400
    ):
        raise OSError("redirected or special cache entry")
    return metadata


def _process_running(pid: int) -> bool:
    """Treat denied/unknown status and a reused live PID as still in use."""
    if pid == os.getpid():
        return True
    if sys.platform == "win32":
        # os.kill(pid, 0) is not a harmless process probe on Windows.
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        kernel.WaitForSingleObject.restype = ctypes.c_ulong
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle.restype = ctypes.c_int
        handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE only
        if not handle:
            return ctypes.get_last_error() != 87  # ERROR_INVALID_PARAMETER
        try:
            return int(kernel.WaitForSingleObject(handle, 0)) != 0
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _owner_pid(path: Path) -> int:
    metadata = _plain(path, stat.S_IFREG)
    if metadata.st_size > 128:
        raise ValueError("oversized cache owner")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    with os.fdopen(os.open(path, flags), "rb") as owner:
        if not os.path.samestat(metadata, os.fstat(owner.fileno())):
            raise OSError("cache owner changed")
        record = json.loads(owner.read(129))
    if (
        not isinstance(record, dict)
        or set(record) != {"version", "pid"}
        or type(record["version"]) is not int
        or record["version"] != 1
        or type(record["pid"]) is not int
        or not 0 < record["pid"] <= 0xFFFFFFFF
    ):
        raise ValueError("invalid cache owner")
    return int(record["pid"])


def prune_stale_topic_caches(cache: Path) -> int:
    """Remove only marked generations whose owning process has ended.

    Legacy/unmarked generations, live or inaccessible owners, redirected paths
    and unexpected contents are retained. No recursive deletion is used.
    """
    removed = 0
    try:
        _plain(cache, stat.S_IFDIR)
        generations = list(cache.iterdir())
    except OSError:
        return removed
    for directory in generations:
        if not _NAME.fullmatch(directory.name):
            continue
        try:
            _plain(directory, stat.S_IFDIR)
            if _process_running(_owner_pid(directory / _OWNER)):
                continue
            entries = list(directory.iterdir())
            if not {_OWNER} <= {entry.name for entry in entries} <= _FILES:
                continue
            for entry in entries:
                _plain(entry, stat.S_IFREG)
            # Retain ownership metadata until all data files have been removed,
            # so a sharing violation or interruption can be retried next start.
            for entry in sorted(entries, key=lambda item: item.name == _OWNER):
                entry.unlink()
            directory.rmdir()
            removed += 1
        except (OSError, ValueError):
            continue
    return removed


def create_topic_cache(cache: Path) -> TemporaryDirectory[str]:
    prune_stale_topic_caches(cache)
    directory = TemporaryDirectory(prefix=".topic-package-load-", dir=cache)
    try:
        with (Path(directory.name) / _OWNER).open("x", encoding="ascii") as owner:
            json.dump({"version": 1, "pid": os.getpid()}, owner)
    except BaseException:
        directory.cleanup()
        raise
    return directory
