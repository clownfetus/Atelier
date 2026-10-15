"""Real Chromium + Bottle smoke and failure checks; native/game APIs use explicit fixtures.

Run separately from run_checks.py: python tests/browser_smoke.py --report-dir <folder>
No production test hooks: viewport state access is appended only to the intercepted module.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from urllib.parse import urlparse
from wsgiref.simple_server import make_server, WSGIRequestHandler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

HOOK = """
window.__vp = {
  seed() {
    generation++; materialGeneration++; saving = false; viewportProject = 'Smoke A';
    matsByName = {}; edited = { Body: { Tint: [1,0,0,1] }, Hair: { Tint: [0,1,0,1] } };
    matData = Object.fromEntries(['Body','Hair'].map(n => [n, {
      game_rel: 'Characters/Smoke/MI_' + n, colors: [{name:'Tint', rgba:[1,1,1,1]}]
    }]));
    refreshFoot();
  },
  state: () => ({edited, saving, project: viewportProject}),
  edit: (name, rgba) => { (edited[name] ||= {}).Tint = rgba; },
  save: saveEdits, revert: revertEdits, canLeave,
  renderStats: () => ({geometries: renderer?.info.memory.geometries,
                       textures: renderer?.info.memory.textures, animating: !!raf}),
  async staleTexture() {
    const original = texLoader.loadAsync;
    const fresh = new THREE.Texture();
    let complete;
    texLoader.loadAsync = () => new Promise(r => complete = r);
    matsByName = {Body: [{map: fresh, color: new THREE.Color()}]};
    const pending = applyMatTexture('Body', 'Test/Old');
    materialGeneration++;
    const stale = new THREE.Texture();
    complete(stale); await pending;
    const kept = matsByName.Body[0].map === fresh;
    texLoader.loadAsync = original;
    matsByName = {};
    return kept;
  }
};
"""


class Quiet(WSGIRequestHandler):
    def log_message(self, *_args):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir', type=Path, required=True)
    parser.add_argument('--mesh', type=Path, help='Optional real decoded GLB for render/disposal smoke')
    args = parser.parse_args()
    report = args.report_dir.resolve()
    report.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='atelier-browser-') as data:
        os.environ['ATELIER_DATA_DIR'] = data
        from atelier.web import routes as R
        from atelier.web.app import _ThreadingWSGIServer
        from playwright.sync_api import sync_playwright
        for name in ('Smoke A', 'Smoke B'):
            Path(R.PROJECTS_ROOT, name).mkdir(parents=True)
        R.set_active_project('Smoke A')
        server = make_server('127.0.0.1', 0, R.app, _ThreadingWSGIServer, Quiet)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f'http://127.0.0.1:{server.server_port}'
        checks, errors = [], []
        fixture_items = [dict(type='folder', name=n, label=n, rel_path=n, count=3)
                         for n in ('Characters', 'UI', 'VFX', 'Maps')]

        def fixtures(route):
            path = urlparse(route.request.url).path
            payload = {
                '/api/update_check': {'available': False},
                '/api/setup_status': {'configured': True},
                '/api/download_usmap': {'ok': True, 'path': 'fixture.usmap'},
                '/api/prereqs': {'issues': []},
                '/api/browse': fixture_items,
                '/api/index_warnings': {'failed': []},
                '/api/stale_mips': {'ok': True, 'count': 0},
                '/api/usmap_update_check': {'ok': True},
                '/api/catalogue/status': {'updating': False, 'portraits': 803},
            }.get(path)
            if payload is not None:
                route.fulfill(json=payload)
            else:
                route.continue_()

        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                context = browser.new_context(viewport={'width': 1400, 'height': 900})
                context.route('**/api/**', fixtures)
                context.route('https://**', lambda route: route.fulfill(json={}))
                page = context.new_page()
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.add_init_script("""
                    // An unavailable remote key service must not block a configured launch.
                    const nativeFetch = window.fetch;
                    window.__remoteCalls = [];
                    window.fetch = (url, opts) => {
                      if (String(url).startsWith('https://')) {
                        window.__remoteCalls.push(String(url));
                        return new Promise(() => {});
                      }
                      return nativeFetch(url, opts);
                    };
                    window.__streams = [];
                    const Original = window.EventSource;
                    window.EventSource = class extends Original {
                      constructor(...args) { super(...args); window.__streams.push(this); }
                    };
                """)
                page.route('**/static/viewport.js', lambda route: route.fulfill(
                    body=(ROOT / 'gui/viewport.js').read_text(encoding='utf-8') + HOOK,
                    content_type='text/javascript'))
                page.goto(url)
                page.wait_for_function("window.__vp && window.atelierProject() === 'Smoke A'")
                page.wait_for_selector('#grid-area .folder-card, #grid-area .card')
                page.wait_for_function("!document.querySelector('.overlay.active')")
                assert page.evaluate('__remoteCalls.length') == 0
                for width, height in ((1400, 900), (1280, 800), (1920, 1080)):
                    page.set_viewport_size({'width': width, 'height': height})
                    page.screenshot(path=str(report / f'current-{width}x{height}.png'))
                checks.append('UI loads at three desktop sizes without uncaught JavaScript errors')
                checks.append('Configured startup does not wait for remote key/mapping downloads')

                from design_checks import run_design_checks
                run_design_checks(page, context, url, report, checks)
                from export_motion_checks import run_export_motion_checks
                run_export_motion_checks(page, context, url, report, checks)
                from viewport_motion_checks import run_viewport_motion_checks
                run_viewport_motion_checks(page, context, url, report, checks)
                from folder_motion_checks import run_folder_motion_checks
                run_folder_motion_checks(page, context, url, report, checks)
                from material_save_motion_checks import run_material_save_motion_checks
                run_material_save_motion_checks(page, context, url, report, checks)
                from library_pins_checks import run_library_pins_checks
                run_library_pins_checks(page, context, url, report, checks)
                from thumbnail_checks import run_thumbnail_checks
                run_thumbnail_checks(page, context, url, report, checks)
                from category_icon_checks import run_category_icon_checks
                run_category_icon_checks(page, context, url, report, checks)
                from library_workflow_checks import run_library_workflow_checks
                run_library_workflow_checks(page, context, url, report, checks)
                from pin_label_checks import run_pin_label_checks
                run_pin_label_checks(page, context, url, report, checks)
                from material_workflow_checks import run_material_workflow_checks
                run_material_workflow_checks(page, context, url, report, checks)
                from export_review_checks import run_export_review_checks
                run_export_review_checks(page, context, url, report, checks)
                from empty_assets_motion_checks import run_empty_assets_motion_checks
                run_empty_assets_motion_checks(page, context, url, report, checks)
                from logo_motion_checks import run_logo_motion_checks
                run_logo_motion_checks(page, context, url, report, checks)

                # Real backend CRUD, with encoded project header rather than a mock bridge.
                result = page.evaluate("""async () => {
                    const post = (url, data, project='Smoke A') => atelierFetch(url, {
                      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)
                    }, project).then(r=>r.json());
                    await post('/api/project/select', {name:'Smoke B'});
                    const saved = await post('/api/project/asset_selection', {deselected:['Test/Texture']});
                    const blocked = await post('/api/project/delete', {name:'../outside'});
                    return {saved, blocked};
                }""")
                assert result['saved']['ok'] and not result['blocked']['ok'], result
                assert R._project_meta.get_deselected(str(Path(R.PROJECTS_ROOT, 'Smoke A'))) == {'Test/Texture'}
                checks.append('Real HTTP project writes stay in their originating project; traversal rejected')

                calls = []
                def save_response(route):
                    body = route.request.post_data_json
                    calls.append((body, route.request.headers.get('x-atelier-project')))
                    route.fulfill(json={'ok': 'Body' in body['game_rel'], 'error': 'Simulated disk failure'})
                page.route('**/api/material_save', save_response)
                page.evaluate('__vp.seed()')
                page.evaluate('__vp.save()')
                state = page.evaluate('__vp.state()')
                assert list(state['edited']) == ['Hair'] and not state['saving'], state
                assert all(h == 'Smoke%20A' for _, h in calls), calls
                assert 'retained' in page.locator('#viewport-status').inner_text()
                checks.append('Partial save failure retains the failed draft and captures the project')
                page.unroute('**/api/material_save', save_response)
                page.route('**/api/material_save', lambda route: route.fulfill(json={'ok': True}))
                page.evaluate('__vp.save()')
                assert not page.evaluate('__vp.state().edited')
                checks.append('Retry saves the retained draft')

                page.evaluate("""() => {
                    __vp.seed();
                    window.__oldFetch = window.atelierFetch;
                    window.atelierFetch = () => new Promise(resolve => window.__finishSave = resolve);
                    window.__saving = __vp.save();
                    __vp.edit('Body', [0,0,1,1]);
                }""")
                assert page.evaluate('__vp.canLeave()') is False
                page.evaluate("__finishSave({json:async()=>({ok:true})})")
                page.wait_for_function("__vp.state().edited.Body.Tint[2] === 1")
                # The second material has its own pending response.
                page.evaluate("__finishSave({json:async()=>({ok:true})})")
                page.wait_for_function('!__vp.state().saving')
                assert page.evaluate('__vp.state().edited.Body.Tint') == [0, 0, 1, 1]
                page.evaluate('window.atelierFetch = window.__oldFetch')
                checks.append('Edits made during Save survive; leaving while saving is blocked')

                assert page.evaluate('__vp.staleTexture()')
                checks.append('An old texture response cannot overwrite a newer material set')
                page.evaluate("__streams[0].dispatchEvent(new Event('error'))")
                page.wait_for_timeout(2200)
                assert page.evaluate('__streams.length') == 1
                checks.append('SSE error does not create duplicate EventSource connections')
                if args.mesh:
                    mesh_bytes = args.mesh.read_bytes()
                    page.route('**/api/model_gltf?*', lambda route: route.fulfill(
                        body=mesh_bytes, content_type='model/gltf-binary'))
                    page.route('**/api/skin_materials', lambda route: route.fulfill(
                        json={'ok': True, 'materials': {}}))
                    page.route('**/api/browse_material_dirs?*', lambda route: route.fulfill(json={'dirs': []}))
                    page.evaluate('__vp.revert()')
                    stats = []
                    for index in range(3):
                        page.evaluate("AtelierViewport.openMesh('Characters/1029/1029100/Meshes/10291/SK_10291_1029100', 'Native mesh smoke')")
                        page.wait_for_function("document.getElementById('viewport-loading').style.display === 'none'")
                        page.wait_for_timeout(300)
                        if index == 0:
                            page.screenshot(path=str(report / 'native-mesh-preview.png'))
                        page.evaluate('AtelierViewport.close()')
                        stats.append(page.evaluate('__vp.renderStats()'))
                    assert all(not s['animating'] for s in stats), stats
                    assert stats[-1]['geometries'] <= stats[0]['geometries'], stats
                    assert stats[-1]['textures'] <= stats[0]['textures'], stats
                    checks.append('Real decoded GLB renders; three reopen/close cycles stop animation and release geometry')
                assert not errors, errors

                # Capture the original frontend against the same deterministic fixture data.
                base_page = context.new_page()
                base_page.set_viewport_size({'width': 1400, 'height': 900})
                def original(file, mime):
                    source = subprocess.run(['git', 'show', f'2a3f4e2:gui/{file}'], cwd=ROOT,
                        capture_output=True, check=True).stdout
                    return lambda route: route.fulfill(body=source, content_type=mime)
                base_page.route(url + '/', original('index.html', 'text/html'))
                base_page.route('**/static/app.js', original('app.js', 'text/javascript'))
                base_page.route('**/static/style.css', original('style.css', 'text/css'))
                base_page.goto(url)
                base_page.wait_for_selector('#grid-area .folder-card, #grid-area .card')
                base_page.screenshot(path=str(report / 'baseline-1400x900.png'))
                browser.close()
            (report / 'results.json').write_text(json.dumps({'checks': checks, 'page_errors': errors}, indent=2))
            for check in checks:
                print('PASS ' + check)
        finally:
            server.shutdown()
            server.server_close()
            R._observer.stop()
            R._observer.join()


if __name__ == '__main__':
    main()
