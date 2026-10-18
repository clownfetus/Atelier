import os
import hashlib
from pathlib import Path
from bottle import Bottle, ServerAdapter
from wsgiref.simple_server import WSGIServer, WSGIRequestHandler, make_server
from socketserver import ThreadingMixIn

def _configured_port():
    """Allow an isolated development/packaged instance without changing normal installs."""
    try:
        port = int(os.environ.get("ATELIER_PORT", "8767"))
    except ValueError:
        raise ValueError("ATELIER_PORT must be an integer from 1 to 65535") from None
    if not 1 <= port <= 65535:
        raise ValueError("ATELIER_PORT must be an integer from 1 to 65535")
    return port


PORT = _configured_port()
app  = Bottle()


def frontend_url(gui_dir):
    """Bypass old HTML cached by an existing desktop browser profile."""
    revision = hashlib.sha256((Path(gui_dir) / "index.html").read_bytes()).hexdigest()[:16]
    return f"http://localhost:{PORT}/?ui={revision}"

class _ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True
    # Chromium requests many local assets at startup and on reload. The default
    # backlog of five causes long connection retries on Windows.
    request_queue_size = 128

class _ThreadedServer(ServerAdapter):
    def run(self, handler):
        srv = make_server(self.host, self.port, handler,
                          server_class=_ThreadingWSGIServer,
                          handler_class=WSGIRequestHandler)
        srv.serve_forever()
