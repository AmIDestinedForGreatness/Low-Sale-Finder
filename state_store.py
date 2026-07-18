"""Small crash-safe, cross-process primitives for mutable local state.

JSON read-modify-write must hold the same lock for the entire mutation. Atomic
replacement prevents readers from observing a partially written document; the
lock prevents two valid snapshots from overwriting one another.
"""
from contextlib import contextmanager
import json
import os
import tempfile
import threading
import time


class StateLockTimeout(TimeoutError):
    pass


_THREAD_LOCKS = {}
_THREAD_LOCKS_GUARD = threading.Lock()


def _thread_lock(path):
    key = os.path.abspath(path)
    with _THREAD_LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(key, threading.Lock())


@contextmanager
def _process_lock(path, timeout=10.0):
    """Advisory one-byte lock that works on Windows and POSIX."""
    lock_path = os.path.abspath(path) + ".lock"
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    handle = open(lock_path, "a+b")
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
    deadline = time.monotonic() + timeout
    acquired = False
    try:
        while not acquired:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise StateLockTimeout(
                        f"timed out locking state file {path}") from exc
                time.sleep(0.01)
        yield
    finally:
        if acquired:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        handle.close()


@contextmanager
def locked(path, timeout=10.0):
    """Serialize threads and processes that mutate one state file."""
    with _thread_lock(path):
        with _process_lock(path, timeout=timeout):
            yield


def _load_json_unlocked(path, default_factory, recover_invalid):
    if not os.path.exists(path):
        return default_factory()
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        if recover_invalid:
            return default_factory()
        raise


def _atomic_write(path, write):
    absolute = os.path.abspath(path)
    directory = os.path.dirname(absolute)
    os.makedirs(directory, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{os.path.basename(absolute)}.", suffix=".tmp",
        dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            write(handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, absolute)
        temporary = None
        if os.name != "nt":
            directory_fd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if temporary and os.path.exists(temporary):
            try:
                os.remove(temporary)
            except OSError:
                pass


def _write_json_unlocked(path, value, indent):
    _atomic_write(path, lambda handle: json.dump(
        value, handle, ensure_ascii=False, indent=indent))


def read_json(path, default_factory=dict, recover_invalid=False):
    with locked(path):
        return _load_json_unlocked(path, default_factory, recover_invalid)


def write_json(path, value, indent=2, after_write=None):
    with locked(path):
        _write_json_unlocked(path, value, indent)
        if after_write:
            after_write(value)
    return value


def update_json(path, updater, default_factory=dict, indent=2,
                recover_invalid=False, after_write=None):
    """Lock, load, mutate, and atomically replace one JSON document."""
    with locked(path):
        value = _load_json_unlocked(path, default_factory, recover_invalid)
        updated = updater(value)
        if updated is not None:
            value = updated
        _write_json_unlocked(path, value, indent)
        if after_write:
            after_write(value)
    return value


def atomic_write_text(path, text):
    with locked(path):
        _atomic_write(path, lambda handle: handle.write(text))
