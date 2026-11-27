import os
import hashlib
import json
from pathlib import Path
from bottle import BaseRequest, Bottle, HTTPError, HTTPResponse, ServerAdapter, request, response
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

# Bottle reads at most MEMFILE_MAX bytes (100 KB) of a JSON body and answers anything larger with
# 413. An export lists every included asset path, so about 1,000 assets went past it. Only JSON
# bodies get this larger cap: raising MEMFILE_MAX itself would keep every uploaded file up to that
# size in memory, and Bottle refuses an upload once those files add up past it, so a mesh sent with
# a few large textures would stop uploading.
_MAX_JSON_BYTES = 32 * 1024 * 1024
_JSON_TYPES = ("application/json", "application/json-rpc")


def _api_error(error):
    """Answer every /api failure in JSON, the only reply the page can read.

    Bottle's HTML error page reached the export dialog as "The server returned an unreadable job
    response", hiding a too-large request and an unexpected exception alike. The traceback of an
    unexpected exception still goes to the session log."""
    if not request.path.startswith("/api/"):
        return Bottle.default_error_handler(app, error)
    response.content_type = "application/json"
    if error.exception is not None:
        message = "Atelier hit an unexpected error: " + (str(error.exception) or type(error.exception).__name__)
    else:
        message = str(error.body or error.status_line)
    return json.dumps({"ok": False, "error": message})


app.default_error_handler = _api_error

# The API has no login: being on 127.0.0.1 is the only credential, so every request must provably
# come from this machine's own Atelier page. Any website the user visits can aim requests at
# localhost (a hidden form POST reached /api/reset_data and wiped the projects folder), and a
# DNS-rebinding page can even read the replies, so three checks run before any route:
#  - Host must name loopback. A rebinding page sends its own domain here; the port is irrelevant.
#  - Browser fetch metadata must not be cross-origin. Requests without these headers come from
#    non-browser clients (the startup probe, tests), which cannot be driven by a web page.
#  - State-changing requests must be JSON, a type no page can send cross-origin without a CORS
#    preflight, which this server never grants. Upload routes keep their multipart/binary bodies.
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "[::1]"})
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_SAME_ORIGIN_FETCHES = frozenset({"same-origin", "none"})
_NON_JSON_BODIES = {
    "/api/assets/add":              ("application/json", "multipart/form-data"),
    "/api/material_custom_texture": ("multipart/form-data",),
    "/api/replace_texture":         ("multipart/form-data",),
    "/api/mesh_replace":            ("multipart/form-data",),
    "/api/showcase_webp":           ("application/octet-stream",),
}


def _host_name(host):
    host = host.strip().lower()
    if host.startswith("["):
        return host[:host.find("]") + 1]
    return host.partition(":")[0]


def request_rejection(environ):
    """Why a request must not reach a route, as (status, message); None when it may."""
    host = environ.get("HTTP_HOST")
    if host is not None and _host_name(host) not in _LOCAL_HOSTS:
        return 403, "Atelier only answers requests addressed to this computer."
    path = environ.get("PATH_INFO", "")
    if not path.startswith("/api/"):
        return None
    site = environ.get("HTTP_SEC_FETCH_SITE")
    origin = environ.get("HTTP_ORIGIN")
    if (site is not None and site.lower() not in _SAME_ORIGIN_FETCHES or
            origin is not None and origin.lower() != f"http://{(host or '').lower()}"):
        return 403, "Atelier does not accept requests from other websites."
    if environ.get("REQUEST_METHOD", "GET").upper() not in _SAFE_METHODS:
        content_type = environ.get("CONTENT_TYPE", "").partition(";")[0].strip().lower()
        if content_type not in _NON_JSON_BODIES.get(path, ("application/json",)):
            return 415, "Send this request as application/json."
    return None


@app.hook("before_request")
def _reject_foreign_requests():
    rejection = request_rejection(request.environ)
    if rejection:
        status, message = rejection
        raise HTTPResponse(json.dumps({"ok": False, "error": message}), status=status,
                           headers={"Content-Type": "application/json"})


@app.hook("before_request")
def _read_large_json():
    """Parse a JSON body over Bottle's MEMFILE_MAX, up to _MAX_JSON_BYTES, into the cache that
    request.json reads. Smaller bodies take Bottle's own path."""
    content_type = request.environ.get("CONTENT_TYPE", "").partition(";")[0].strip().lower()
    if content_type not in _JSON_TYPES or request.content_length <= BaseRequest.MEMFILE_MAX:
        return
    if request.content_length > _MAX_JSON_BYTES:
        raise HTTPError(413, f"This request is too large for Atelier (over {_MAX_JSON_BYTES // 2**20} MB).")
    try:
        request.environ["bottle.request.json"] = json.loads(request.body.read())
    except ValueError:
        raise HTTPError(400, "Invalid JSON") from None


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
        with make_server(self.host, self.port, handler,
                         server_class=_ThreadingWSGIServer,
                         handler_class=WSGIRequestHandler) as srv:
            on_listening = self.options.get("on_listening")
            if on_listening is not None:
                on_listening()
            srv.serve_forever()
