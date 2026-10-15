"""Small process-local guards for project lifetimes and conflicting writes.

Requests and background workers reserve their project before starting. Navigation
may change the active project; rename/delete/reset cannot invalidate reserved data.
"""
from contextlib import contextmanager
import os
import threading


class BusyError(RuntimeError):
    pass


_guard = threading.RLock()
_users = {}
_exclusive = set()
_writers = {}
_resetting = False


def _key(root):
    return os.path.normcase(os.path.realpath(root))


def reserve(root):
    """Reserve synchronously (including before Thread.start); return an idempotent release."""
    key = _key(root)
    with _guard:
        if _resetting or key in _exclusive:
            raise BusyError("Project is being changed; try again when the operation finishes.")
        _users[key] = _users.get(key, 0) + 1
    released = False

    def release():
        nonlocal released
        with _guard:
            if not released:
                released = True
                _users[key] -= 1
                if not _users[key]:
                    del _users[key]
    return release


@contextmanager
def project_use(root, write=False):
    release = reserve(root)
    with _guard:
        lock = _writers.setdefault(_key(root), threading.RLock())
    try:
        if write:
            lock.acquire()
        try:
            yield
        finally:
            if write:
                lock.release()
    finally:
        release()


@contextmanager
def change_projects(*roots):
    keys = {_key(root) for root in roots}
    with _guard:
        if _resetting or any(k in _exclusive or _users.get(k) for k in keys):
            raise BusyError("Project has an operation in progress; wait before renaming or deleting it.")
        _exclusive.update(keys)
    try:
        yield
    finally:
        with _guard:
            _exclusive.difference_update(keys)


@contextmanager
def change_all():
    global _resetting
    with _guard:
        if _resetting or _users or _exclusive:
            raise BusyError("An operation is in progress; wait before changing application data.")
        _resetting = True
    try:
        yield
    finally:
        with _guard:
            _resetting = False
