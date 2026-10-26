#!/usr/bin/env python3
import sys
import time
import threading
import urllib.request
import os
import datetime
from pathlib import Path
from atelier.updates import recover_interrupted

# Recovery runs before importing backend/native modules that may belong to an
# interrupted transaction. The standalone helper waits for this process to exit.
_early_root = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
_early_data = Path(os.environ.get('ATELIER_DATA_DIR', str(_early_root)))
if getattr(sys, 'frozen', False) and recover_interrupted(_early_root, _early_data):
    raise SystemExit(0)
if sys.platform.startswith("linux") and os.environ.get("WAYLAND_DISPLAY"):
    os.environ.setdefault("WEBKIT_DISABLE_DMABUF_RENDERER", "1")
if sys.platform.startswith("linux") and getattr(sys, "frozen", False):
    # The Linux build uses the system's GTK, GLib and WebKit as one set (packaging/Atelier.spec
    # leaves them out of the bundle): WebKit always comes from the system, and pairing it with a
    # bundled, older GTK stack is what kept the 1.0 AppImage from starting on newer distros
    # ("Could not locate webkit_get_major_version"). PyInstaller's GTK runtime hooks still point
    # these variables into the bundle, so drop those entries before GTK reads them.
    _bundle = getattr(sys, "_MEIPASS", "")
    for _var in ("GI_TYPELIB_PATH", "GIO_MODULE_DIR", "GSETTINGS_SCHEMA_DIR", "GDK_PIXBUF_MODULE_FILE",
                 "GDK_PIXBUF_MODULEDIR", "GTK_DATA_PREFIX", "GTK_EXE_PREFIX", "GTK_PATH", "XDG_DATA_DIRS"):
        _kept = [p for p in os.environ.get(_var, "").split(os.pathsep) if p and not p.startswith(_bundle)]
        if _kept:
            os.environ[_var] = os.pathsep.join(_kept)
        else:
            os.environ.pop(_var, None)

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
    from atelier.windows_runtime import launch_issue
    issue = launch_issue()
    if issue:
        print(issue, file=sys.stderr)
        if os.name == 'nt':
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, issue, 'Atelier requirements', 0x10)
        return 1
    import webview
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
    raise SystemExit(main())
