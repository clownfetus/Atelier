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
    const original = materialTexture;
    const fresh = new THREE.Texture();
    let complete;
    materialTexture = () => new Promise(r => complete = r);
    matsByName = {Body: [{map: fresh, color: new THREE.Color()}]};
    const pending = applyMatTexture('Body', 'Test/Old');
    materialGeneration++;
    const stale = new THREE.Texture();
    complete(stale); await pending;
    const kept = matsByName.Body[0].map === fresh;
    materialTexture = original;
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
    parser.add_argument('--idle', type=Path, help='Optional real decoded standing-idle JSON for playback verification')
    parser.add_argument('--jobs-bulk-only', action='store_true', help='Run only tracked job and bulk editing workflows')
    parser.add_argument('--appearance-only', action='store_true', help='Run only interface appearance and dropdown workflows')
    parser.add_argument('--texture-reconstruction-only', action='store_true', help='Run only edited-texture motion workflows')
    parser.add_argument('--s-maps-only', action='store_true', help='Run only one-click D/S processing workflows')
    parser.add_argument('--viewport-only', action='store_true', help='Run model inspection, capture, loading and material safety checks')
    parser.add_argument('--viewport-loading-only', action='store_true', help='Run viewport cancellation, roster avatar and hero logo checks')
    parser.add_argument('--polish-only', action='store_true', help='Run continuity, presentation preferences and truthful feedback checks')
    parser.add_argument('--material-replacement-only', action='store_true', help='Run material replacement and existing editor safety checks')
    parser.add_argument('--viewer-followups-only',action='store_true',help='Check story banners, transparency, contextual bulk controls and replacement upload')
    parser.add_argument('--review-followups-only', action='store_true', help='Check project-scoped imports and format-preserving export retries')
    parser.add_argument('--trust-only', action='store_true', help='Check project trash, themed dialogs and guided setup')
    parser.add_argument('--find-only', action='store_true', help='Check global search, roster home and Continue')
    parser.add_argument('--library-only', action='store_true', help='Check search, home pins, filters and keyboard navigation')
    parser.add_argument('--inks-dial-only', action='store_true', help='Check measured inks, volume dial and moment arbitration')
    parser.add_argument('--surfaces-only',action='store_true',help='Check Krackle surfaces, byte drops and frame costs')
    parser.add_argument('--showcase-only',action='store_true',help='Check Showcase material restoration, cards and opt-in foley')
    args = parser.parse_args()
    report = args.report_dir.resolve()
    report.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='atelier-browser-') as data:
        os.environ['ATELIER_DATA_DIR'] = data
        from atelier.web import routes as R
        # Fixtures must also cover server-side metadata calls, including any
        # browser retry that reaches the real route during a page transition.
        R._get_latest_usmap_from_github = lambda: None
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
                '/api/catalogue/library': {'heroes': []},
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
                from startup_update_checks import run_startup_update_checks
                run_startup_update_checks(context, url, report, checks)

                if args.showcase_only:
                    from showcase_checks import run_showcase_checks
                    run_showcase_checks(page,context,url,report,checks)
                    assert not errors,errors
                    (report/'results.json').write_text(json.dumps({'checks':checks,'page_errors':errors},indent=2))
                    for check in checks:print('PASS '+check)
                    browser.close();return

                if args.surfaces_only:
                    from surfaces_checks import run_surfaces_checks
                    run_surfaces_checks(page,context,url,report,checks)
                    assert not errors,errors
                    (report/'results.json').write_text(json.dumps({'checks':checks,'page_errors':errors},indent=2))
                    for check in checks:print('PASS '+check)
                    browser.close();return

                if args.inks_dial_only:
                    from inks_dial_checks import run_inks_dial_checks
                    run_inks_dial_checks(page,context,url,report,checks)
                    assert not errors,errors
                    (report/'results.json').write_text(json.dumps({'checks':checks,'page_errors':errors},indent=2))
                    for check in checks:print('PASS '+check)
                    browser.close();return

                if args.review_followups_only:
                    from review_followup_checks import run_review_followup_checks
                    run_review_followup_checks(context, url, report, checks)
                    assert not errors, errors
                    (report / 'results.json').write_text(json.dumps({'checks': checks, 'page_errors': errors}, indent=2))
                    for check in checks: print('PASS ' + check)
                    browser.close()
                    return

                if args.material_replacement_only:
                    from material_replacement_checks import run_material_replacement_checks
                    from material_workflow_checks import run_material_workflow_checks
                    run_material_replacement_checks(page, context, url, report, checks)
                    run_material_workflow_checks(page, context, url, report, checks)
                    assert not errors, errors
                    (report / 'results.json').write_text(json.dumps({'checks': checks, 'page_errors': errors}, indent=2))
                    for check in checks:
                        print('PASS ' + check)
                    browser.close()
                    return

                if args.viewer_followups_only:
                    from viewer_followup_checks import run_viewer_followup_checks
                    run_viewer_followup_checks(page,context,url,report,checks)
                    assert not errors,errors
                    (report/'results.json').write_text(json.dumps({'checks':checks,'page_errors':errors},indent=2))
                    for check in checks:print('PASS '+check)
                    browser.close();return

                if args.trust_only:
                    from trust_checks import run_trust_checks
                    run_trust_checks(page, context, url, report, checks)
                    assert not errors, errors
                    (report / 'results.json').write_text(json.dumps({'checks':checks,'page_errors':errors},indent=2))
                    for check in checks: print('PASS '+check)
                    browser.close()
                    return

                if args.find_only:
                    from find_checks import run_find_checks
                    run_find_checks(page, context, url, report, checks)
                    assert not errors, errors
                    (report / 'results.json').write_text(json.dumps({'checks':checks,'page_errors':errors},indent=2))
                    for check in checks: print('PASS '+check)
                    browser.close()
                    return

                if args.library_only:
                    from find_checks import run_find_checks
                    from library_pins_checks import run_library_pins_checks
                    from library_workflow_checks import run_library_workflow_checks
                    for check in (run_find_checks,run_library_pins_checks,run_library_workflow_checks):check(page,context,url,report,checks)
                    assert not errors, errors
                    (report / 'results.json').write_text(json.dumps({'checks':checks,'page_errors':errors},indent=2))
                    for check in checks:print('PASS '+check)
                    browser.close()
                    return

                if args.polish_only:
                    from polish_checks import run_polish_checks
                    run_polish_checks(page, context, url, report, checks)
                    assert not errors, errors
                    (report / 'results.json').write_text(json.dumps({'checks':checks,'page_errors':errors},indent=2))
                    for check in checks: print('PASS '+check)
                    browser.close()
                    return

                if args.viewport_loading_only:
                    from viewport_loading_checks import run_viewport_loading_checks, run_hero_artwork_checks
                    run_viewport_loading_checks(page, context, url, report, checks)
                    run_hero_artwork_checks(page, context, url, report, checks)
                    assert not errors, errors
                    (report / 'results.json').write_text(json.dumps({'checks':checks,'page_errors':errors},indent=2))
                    for check in checks: print('PASS '+check)
                    browser.close()
                    return

                if args.viewport_only:
                    from viewport_loading_checks import run_viewport_loading_checks, run_hero_artwork_checks
                    from viewport_inspection_checks import run_viewport_inspection_checks
                    from viewport_motion_checks import run_viewport_motion_checks
                    from material_workflow_checks import run_material_workflow_checks
                    from material_save_motion_checks import run_material_save_motion_checks
                    run_viewport_inspection_checks(page, context, url, report, checks, args.mesh, args.idle)
                    run_viewport_loading_checks(page, context, url, report, checks)
                    run_hero_artwork_checks(page, context, url, report, checks)
                    run_viewport_motion_checks(page, context, url, report, checks)
                    run_material_workflow_checks(page, context, url, report, checks)
                    run_material_save_motion_checks(page, context, url, report, checks)
                    assert not errors, errors
                    (report / 'results.json').write_text(json.dumps({'checks':checks,'page_errors':errors},indent=2))
                    for check in checks:
                        print('PASS '+check)
                    browser.close()
                    return

                if args.s_maps_only:
                    from s_maps_browser_checks import run_s_maps_checks
                    run_s_maps_checks(page, context, url, report, checks)
                    assert not errors, errors
                    (report / 'results.json').write_text(json.dumps({'checks':checks,'page_errors':errors},indent=2))
                    for check in checks:
                        print('PASS '+check)
                    browser.close()
                    return

                if args.texture_reconstruction_only:
                    from texture_reconstruction_checks import run_texture_reconstruction_checks
                    run_texture_reconstruction_checks(page, context, url, report, checks)
                    assert not errors, errors
                    (report / 'results.json').write_text(json.dumps({'checks':checks,'page_errors':errors},indent=2))
                    for check in checks:
                        print('PASS '+check)
                    browser.close()
                    return

                if args.jobs_bulk_only:
                    from jobs_bulk_browser_checks import run_job_bulk_checks
                    run_job_bulk_checks(page, context, url, report, checks)
                    assert not errors, errors
                    (report / 'results.json').write_text(json.dumps({'checks':checks,'page_errors':errors},indent=2))
                    for check in checks:
                        print('PASS '+check)
                    browser.close()
                    return

                from design_checks import run_design_checks
                from showcase_checks import run_showcase_checks
                run_showcase_checks(page,context,url,report,checks)
                from surfaces_checks import run_surfaces_checks
                run_surfaces_checks(page,context,url,report,checks)
                from inks_dial_checks import run_inks_dial_checks
                run_inks_dial_checks(page,context,url,report,checks)
                from find_checks import run_find_checks
                run_find_checks(page, context, url, report, checks)
                from trust_checks import run_trust_checks
                run_trust_checks(page, context, url, report, checks)
                run_design_checks(page, context, url, report, checks)
                from appearance_checks import run_appearance_checks
                run_appearance_checks(page, context, url, report, checks)
                if args.appearance_only:
                    assert not errors, errors
                    (report / 'results.json').write_text(json.dumps({'checks':checks,'page_errors':errors},indent=2))
                    for check in checks:
                        print('PASS '+check)
                    browser.close()
                    return
                from polish_checks import run_polish_checks
                run_polish_checks(page, context, url, report, checks)
                from viewport_inspection_checks import run_viewport_inspection_checks
                run_viewport_inspection_checks(page, context, url, report, checks, args.mesh, args.idle)
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
                from jobs_bulk_browser_checks import run_job_bulk_checks
                run_job_bulk_checks(page, context, url, report, checks)
                from thumbnail_checks import run_thumbnail_checks
                run_thumbnail_checks(page, context, url, report, checks)
                from texture_reconstruction_checks import run_texture_reconstruction_checks
                run_texture_reconstruction_checks(page, context, url, report, checks)
                from s_maps_browser_checks import run_s_maps_checks
                run_s_maps_checks(page, context, url, report, checks)
                from category_icon_checks import run_category_icon_checks
                run_category_icon_checks(page, context, url, report, checks)
                from library_workflow_checks import run_library_workflow_checks
                run_library_workflow_checks(page, context, url, report, checks)
                from pin_label_checks import run_pin_label_checks
                run_pin_label_checks(page, context, url, report, checks)
                from material_workflow_checks import run_material_workflow_checks
                run_material_workflow_checks(page, context, url, report, checks)
                from material_replacement_checks import run_material_replacement_checks
                run_material_replacement_checks(page, context, url, report, checks)
                from export_review_checks import run_export_review_checks
                run_export_review_checks(page, context, url, report, checks)
                from skin_swapper_review_checks import run_skin_swapper_review_checks
                run_skin_swapper_review_checks(page, context, url, report, checks)
                from review_followup_checks import run_review_followup_checks
                run_review_followup_checks(context, url, report, checks)
                from empty_assets_motion_checks import run_empty_assets_motion_checks
                run_empty_assets_motion_checks(page, context, url, report, checks)
                from logo_motion_checks import run_logo_motion_checks
                run_logo_motion_checks(page, context, url, report, checks)
                from krackle_motion_checks import run_krackle_motion_checks
                run_krackle_motion_checks(page, context, url, report, checks)

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
