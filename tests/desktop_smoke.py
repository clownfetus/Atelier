"""Launch a hidden native WebView2 window against the real local backend, then close it.

Requires ATELIER_DATA_DIR. Updates and thumbnail prefetch are suppressed in this smoke only.
"""
import json
import os
from pathlib import Path
import sys
import threading
import time
from wsgiref.simple_server import make_server, WSGIRequestHandler

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    if not os.environ.get('ATELIER_DATA_DIR'):
        raise SystemExit('Set ATELIER_DATA_DIR to isolated development data.')
    print('Loading native desktop dependencies...', flush=True)
    from atelier import config as C
    from atelier.web import routes as R
    from atelier.web.app import _ThreadingWSGIServer
    import webview
    print('Starting native WebView2...', flush=True)

    class Quiet(WSGIRequestHandler):
        def log_message(self, *_args):
            pass

    def app(env, respond):
        stubs = {'/api/update_check': {'available': False},
                 '/api/download_usmap': {'ok': True, 'path': C.USMAP},
                 '/api/prefetch_thumbs': {'ok': True},
                 '/api/usmap_update_check': {'ok': True}}
        if env['PATH_INFO'] in stubs:
            data = json.dumps(stubs[env['PATH_INFO']]).encode()
            respond('200 OK', [('Content-Type', 'application/json'), ('Content-Length', str(len(data)))])
            return [data]
        return R.app(env, respond)

    server = make_server('127.0.0.1', 0, app, _ThreadingWSGIServer, Quiet)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    window = webview.create_window('Atelier development smoke',
        f'http://127.0.0.1:{server.server_port}', hidden=True, width=1400, height=900)
    result = {}

    def verify():
        try:
            deadline = time.monotonic() + 60
            data = {}
            while time.monotonic() < deadline:
                data = window.evaluate_js("""({
                  title: document.title,
                  cards: document.querySelectorAll('#grid-area .card').length,
                  viewport: typeof window.AtelierViewport === 'object',
                  project: window.atelierProject?.(),
                  items: typeof allItems === 'undefined' ? 0 : allItems.length,
                  status: document.querySelector('.overlay.active')?.id || '',
                  icons: document.querySelectorAll('svg.lucide').length,
                  renderer: navigator.userAgent
                })""")
                if data and data.get('items') and data.get('viewport') and data.get('project') and data.get('icons'):
                    result.update(data)
                    break
                time.sleep(0.2)
            if not result:
                result.update(error='Interface did not become ready within 60 seconds', last_state=data)
        except Exception as exc:
            result['error'] = str(exc)
        finally:
            print('Desktop result:', result, flush=True)
            window.destroy()

    try:
        webview.start(verify, gui='edgechromium', private_mode=False,
                      storage_path=str(Path(C.DATA_ROOT) / 'desktop-smoke-profile'))
    finally:
        server.shutdown()
        server.server_close()
        R._observer.stop()
        R._observer.join()
    report = Path(C.DATA_ROOT) / 'desktop-smoke.json'
    report.write_text(json.dumps(result, indent=2), encoding='utf-8')
    assert 'error' not in result, result
    print('PASS native WebView2: real asset browser, project, icons and viewport module loaded')
    print('Report:', report)


if __name__ == '__main__':
    main()
