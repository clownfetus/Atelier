#!/usr/bin/env python3
import sys
import time
import threading
import urllib.request
import os
import datetime
if sys.platform.startswith("linux") and os.environ.get("WAYLAND_DISPLAY"):
    os.environ.setdefault("WEBKIT_DISABLE_DMABUF_RENDERER", "1")
import webview

from atelier import hostos
from atelier.window_theme import WindowTheme
from atelier.web.app import PORT, frontend_url

_ROOT = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
         else os.path.dirname(os.path.abspath(__file__)))
_DATA_ROOT = os.path.realpath(os.environ["ATELIER_DATA_DIR"]) if os.environ.get("ATELIER_DATA_DIR") else _ROOT
URL = frontend_url(os.path.join(getattr(sys, "_MEIPASS", _ROOT), "gui"))


def _show_launch_toast():
    try:
        # Bundled data: frozen it sits in _internal/, not beside the exe (see config.VERSION_FILE).
        with open(os.path.join(getattr(sys, "_MEIPASS", _ROOT), "version"), "r") as f:
            version = f.read().strip()
    except Exception:
        version = ""
    label = f"Atelier {version}" if version else "Atelier"
    hostos.notify(label, "Launching, please wait...")


def _setup_logging():
    logs_dir = os.path.join(_DATA_ROOT, "_logs")
    os.makedirs(logs_dir, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    lf = open(os.path.join(logs_dir, f"{ts}.txt"), "w", encoding="utf-8", buffering=1)

    orig_out, orig_err = sys.stdout, sys.stderr

    class _Tee:
        def __init__(self, orig):
            self._orig = orig
        def write(self, data):
            lf.write(data)
            if self._orig:
                try: self._orig.write(data)
                except Exception: pass
        def flush(self):
            lf.flush()
            if self._orig:
                try: self._orig.flush()
                except Exception: pass
        def fileno(self):
            return lf.fileno()

    sys.stdout = _Tee(orig_out)
    sys.stderr = _Tee(orig_err)


def _wait_for_server(timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(URL, timeout=1)
            return True
        except Exception:
            time.sleep(0.1)
    return False


def _run_server():
    import atelier.web.routes as _routes  # registers all Bottle routes
    from atelier.web.app import app, PORT as _PORT, _ThreadedServer
    try:
        app.run(host="127.0.0.1", port=_PORT, quiet=True, server=_ThreadedServer)
    finally:
        _routes._observer.stop()
        _routes._observer.join()


def main():
    webview.settings['ALLOW_DOWNLOADS'] = True  # Viewer captures use the native Save As dialog.
    _setup_logging()

    t = threading.Thread(target=_run_server, daemon=True)
    t.start()

    if not _wait_for_server():
        print("Server did not start in time.", file=sys.stderr)
        sys.exit(1)

    appearance = WindowTheme(_DATA_ROOT)
    window = webview.create_window("Atelier", URL, width=1400, height=900,
                                   background_color=appearance._background(), js_api=appearance)
    appearance._attach(window)
    close_started = threading.Event()
    close_ready = threading.Event()

    def drain():
        from atelier.web import routes
        while not routes.shutdown(5):
            pass
        close_ready.set()
        window.destroy()

    def closing():
        if close_ready.is_set():
            return True
        if not close_started.is_set():
            close_started.set()
            threading.Thread(target=drain, name="atelier-shutdown", daemon=True).start()
        return False

    window.events.closing += closing

    def _focus():
        time.sleep(0.3)
        hostos.focus_window("Atelier")

    # Debug (devtools) is off in production, but a "DEBUG" marker file next to the exe turns it on
    # for diagnostic builds — keeps the shipped app clean while letting debug builds inspect the console.
    _debug = bool(os.environ.get("ATELIER_DEBUG")) or os.path.exists(os.path.join(_ROOT, "DEBUG"))
    # private_mode=True (pywebview's default) hands WebKitGTK an ephemeral data store, which on
    # Linux means no localStorage at all — touching it throws and kills app.js before init().
    # A persistent store also keeps the Settings toggles across launches, which is what the UI
    # already assumes when it reads them back.
    webview.start(_focus, debug=_debug, private_mode=False,
                  storage_path=os.path.join(_DATA_ROOT, "_webview"))
    from atelier.web import routes
    while not routes.shutdown(5):
        pass


if __name__ == "__main__":
    main()
