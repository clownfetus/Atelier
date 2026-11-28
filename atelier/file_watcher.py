"""Watch active project files for external editor saves (Photoshop, Krita, GIMP, Substance).

Atomic-save editors write a temporary file and rename it into place, firing ``on_moved``
rather than ``on_modified``. Streaming editors can also fire ``on_modified`` before the
PNG trailer is flushed. This module handles both safely with a short trailing debounce
and PNG completeness check so Model Studio and Texture Preview refresh live without
ever decoding a half-written image.
"""
import os
import threading
import time

from watchdog.events import FileSystemEventHandler

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PNG_IEND_TRAILER = b"IEND\xaeB`\x82"


def is_complete_png(path: str) -> bool:
    """Return True when ``path`` exists on disk and contains a complete PNG stream."""
    try:
        size = os.path.getsize(path)
        if size < 33:
            return False
        with open(path, "rb") as handle:
            head = handle.read(8)
            if head != _PNG_SIGNATURE:
                return False
            handle.seek(max(0, size - 64))
            tail = handle.read(64)
            return _PNG_IEND_TRAILER in tail
    except OSError:
        return False


def wait_for_complete_png(path: str, timeout: float = 2.0, poll: float = 0.04) -> bool:
    """Wait briefly for an external editor to finish flushing a PNG file."""
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        if is_complete_png(path):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(poll)


class ProjectFileHandler(FileSystemEventHandler):
    """Watch ``PROJECTS_ROOT`` and emit SSE updates for live external texture edits."""

    def __init__(
        self,
        *,
        get_import_root,
        project_game_rel,
        resolve_by_name,
        token_fn,
        push_sse,
        ignored_dirs,
        debounce_seconds: float = 0.25,
        complete_timeout: float = 2.0,
    ):
        super().__init__()
        self._get_import_root = get_import_root
        self._project_game_rel = project_game_rel
        self._resolve_by_name = resolve_by_name
        self._token = token_fn
        self._push_sse = push_sse
        self._ignored_dirs = frozenset(ignored_dirs)
        self._debounce = max(0.0, float(debounce_seconds))
        self._complete_timeout = max(0.0, float(complete_timeout))
        self._lock = threading.Lock()
        self._timers: dict[str, threading.Timer] = {}

    def _active_rel(self, path: str):
        import_root = self._get_import_root().replace("\\", "/").rstrip("/")
        evt_path = path.replace("\\", "/")
        prefix = import_root + "/"
        if not evt_path.lower().startswith(prefix.lower()):
            return None, None
        rel = evt_path[len(prefix):]
        first = rel.split("/", 1)[0]
        if not first or first in self._ignored_dirs:
            return None, None
        return import_root, rel

    def _schedule_png(self, path: str):
        if not path or not path.lower().endswith(".png"):
            return
        import_root, _ = self._active_rel(path)
        if not import_root:
            return
        key = os.path.normcase(os.path.abspath(path))
        with self._lock:
            existing = self._timers.pop(key, None)
            if existing is not None:
                existing.cancel()
            timer = threading.Timer(self._debounce, self._emit_png, args=(key, path))
            timer.daemon = True
            self._timers[key] = timer
            timer.start()

    def _emit_png(self, key: str, path: str):
        with self._lock:
            self._timers.pop(key, None)
        import_root, _ = self._active_rel(path)
        if not import_root:
            return
        if not wait_for_complete_png(path, timeout=self._complete_timeout):
            return
        try:
            ver = str(os.stat(path).st_mtime_ns)
        except OSError:
            return
        gr = self._project_game_rel(path, import_root)
        if "/" not in gr:
            gr = self._resolve_by_name(gr) or gr
        project_name = os.path.basename(import_root.rstrip("/"))
        self._push_sse({
            "file_changed": True,
            "token": self._token(gr),
            "game_rel": gr,
            "ver": ver,
            "project": project_name,
        })

    def _handle_removed(self, path: str):
        if not path:
            return
        lower = path.lower()
        if lower.endswith(".blend.mat.json") or not lower.endswith((".png", ".json", ".blend")):
            return
        import_root, _ = self._active_rel(path)
        if not import_root:
            return
        self._push_sse({"asset_removed": True})

    def cancel_pending(self):
        with self._lock:
            timers = list(self._timers.values())
            self._timers.clear()
        for timer in timers:
            timer.cancel()

    def on_modified(self, event):
        if not event.is_directory:
            self._schedule_png(event.src_path)

    def on_created(self, event):
        if not event.is_directory:
            self._schedule_png(event.src_path)

    def on_moved(self, event):
        if event.is_directory:
            return
        dest = getattr(event, "dest_path", "")
        src = getattr(event, "src_path", "")
        dest_root, _ = self._active_rel(dest) if dest else (None, None)
        src_root, _ = self._active_rel(src) if src else (None, None)
        if dest and dest_root and dest.lower().endswith(".png"):
            self._schedule_png(dest)
        if src and src_root and not dest_root:
            # Moving an edited asset out of the active project behaves like deletion.
            self._handle_removed(src)

    def on_deleted(self, event):
        if not event.is_directory:
            self._handle_removed(event.src_path)
