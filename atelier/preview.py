"""Cancellation shared by requests belonging to one viewport material load."""
from contextlib import contextmanager
from dataclasses import dataclass, field
import re
import threading
import time

from atelier import jobs


@dataclass
class _Load:
    cancelled: threading.Event = field(default_factory=threading.Event)
    active: int = 0
    touched: float = field(default_factory=time.monotonic)


_lock = threading.Lock()
_loads = {}


def _entry(project, identity):
    if not isinstance(identity, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', identity):
        raise ValueError('Invalid viewport load ID')
    now = time.monotonic()
    # Retain cancelled IDs so requests arriving after cancellation cannot restart old work.
    for key, value in list(_loads.items()):
        if not value.active and now - value.touched > 3600:
            del _loads[key]
    entry = _loads.setdefault((project, identity), _Load())
    entry.touched = now
    return entry


def cancel(project, identity):
    with _lock:
        _entry(project, identity).cancelled.set()


@contextmanager
def scope(project, identity):
    if not identity:
        yield
        return
    with _lock:
        entry = _entry(project, identity)
        entry.active += 1
    try:
        with jobs.cancellation_scope(entry.cancelled):
            yield
    finally:
        with _lock:
            entry.active -= 1
            entry.touched = time.monotonic()
