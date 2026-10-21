"""Per-key locks so simultaneous requests for the same asset do the expensive work once.

The viewport, Model Studio, the texture editor and the Blender export all ask for the same
textures and meshes, often at the same moment (a viewport open fires ~2N texture requests). Each
caller already checks its on-disk cache first; holding a lock per asset across "check, then
extract/decode" makes the second caller wait for the first and then find the cached result,
instead of launching a duplicate extraction into the same folder.

Locks are reference-counted and dropped when idle, so the table never grows with the index.
Waiting honours job cancellation (jobs.cancellable_lock)."""
import threading
from contextlib import contextmanager

_table_lock = threading.Lock()
_locks = {}   # key -> [Lock, users]


@contextmanager
def key_lock(*key):
    from atelier import jobs
    k = tuple(str(part).lower() for part in key)
    with _table_lock:
        entry = _locks.get(k)
        if entry is None:
            entry = _locks[k] = [threading.Lock(), 0]
        entry[1] += 1
    try:
        with jobs.cancellable_lock(entry[0]):
            yield
    finally:
        with _table_lock:
            entry[1] -= 1
            if entry[1] <= 0 and _locks.get(k) is entry:
                del _locks[k]
