"""Tests for Project Trash browser routes, project palette, selection profiles, modular routes and bundler."""
import atexit
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from wsgiref.util import setup_testing_defaults

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
data = tempfile.TemporaryDirectory(prefix='atelier-improvements-')
os.environ['ATELIER_DATA_DIR'] = data.name

from atelier import config as C
from atelier.web import routes as R
from scripts import bundle_frontend


def cleanup():
    R._observer.stop()
    R._observer.join()
    data.cleanup()


atexit.register(cleanup)


def call(path, body=None, method='GET', project='Improvements'):
    env = {}
    setup_testing_defaults(env)
    raw = json.dumps(body).encode() if body is not None else b''
    env.update(
        REQUEST_METHOD=method,
        PATH_INFO=path,
        CONTENT_TYPE='application/json',
        CONTENT_LENGTH=str(len(raw)),
        **{'wsgi.input': io.BytesIO(raw), 'HTTP_X_ATELIER_PROJECT': project},
    )
    return json.loads(b''.join(R.app(env, lambda *_args: None)))


class AppImprovementsTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(C.PROJECTS_ROOT, 'Improvements')
        self.root.mkdir(parents=True, exist_ok=True)
        self.scope = C.project_context(str(self.root))
        self.scope.__enter__()
        self.addCleanup(self.scope.__exit__, None, None, None)
        self.addCleanup(lambda: shutil.rmtree(self.root, ignore_errors=True))

    def test_project_palette_roundtrip_and_sanitisation(self):
        self.assertEqual(call('/api/project/palette')['palette'], [])
        res = call('/api/project/palette', {'palette': ['#FF1122', 'invalid', '#ff1122', '#00aabb']}, method='POST')
        self.assertTrue(res['ok'])
        self.assertEqual(res['palette'], ['#ff1122', '#00aabb'])
        self.assertEqual(call('/api/project/palette')['palette'], ['#ff1122', '#00aabb'])

    def test_selection_profiles_roundtrip(self):
        self.assertEqual(call('/api/project/profiles')['profiles'], {})
        saved = call('/api/project/profiles', {
            'name': 'Body only',
            'deselected': ['Characters/1029/1029001/VFX/NS_Test'],
            'mod_name': 'MagikBody',
        }, method='POST')
        self.assertTrue(saved['ok'])
        self.assertIn('Body only', saved['profiles'])
        self.assertEqual(saved['profiles']['Body only']['mod_name'], 'MagikBody')
        bad = call('/api/project/profiles', {'name': '   ', 'deselected': []}, method='POST')
        self.assertFalse(bad['ok'])
        deleted = call('/api/project/profiles/delete', {'name': 'Body only'}, method='POST')
        self.assertTrue(deleted['ok'])
        self.assertEqual(deleted['profiles'], {})

    def test_modular_shader_and_world_routes_still_registered(self):
        disabled = call('/api/shaders/ir')
        self.assertFalse(disabled['ok'])
        self.assertIn('disabled', disabled['error'].lower())
        self.assertTrue(hasattr(R, 'api_shaders_status'))
        self.assertTrue(hasattr(R, 'api_world_params'))
        self.assertTrue(hasattr(R, 'api_text_params'))
        self.assertTrue(hasattr(R, 'api_trash_list'))

    def test_frontend_bundler_cuts_request_fanout(self):
        with tempfile.TemporaryDirectory(prefix='atelier-bundle-') as out:
            out_dir = Path(out) / 'gui'
            stats = bundle_frontend.bundle(ROOT / 'gui', out_dir)
            self.assertGreaterEqual(stats['css_count'], 25)
            self.assertGreaterEqual(stats['head_js_count'] + stats['body_js_count'], 45)
            bundled_html = (out_dir / 'index.html').read_text(encoding='utf-8')
            self.assertIn('/static/bundle.css', bundled_html)
            self.assertIn('/static/bundle-head.js', bundled_html)
            self.assertIn('/static/bundle-body.js', bundled_html)
            self.assertIn('type="importmap"', bundled_html)
            self.assertIn('src="/static/viewport.js"', bundled_html)
            self.assertEqual(len(bundle_frontend.CSS_RE.findall(bundled_html)), 1)
            self.assertEqual(len(bundle_frontend.JS_RE.findall(bundled_html)), 2)


class ProjectWorkflowsBrowserTest(unittest.TestCase):
    def setUp(self):
        from playwright.sync_api import sync_playwright
        playwright = sync_playwright().start()
        self.addCleanup(playwright.stop)
        browser = playwright.chromium.launch()
        self.addCleanup(browser.close)
        self.page = browser.new_page()
        self.page.set_content('''
            <style>.overlay { display: none; } .overlay.active { display: block; }</style>
            <input id="mod-name-input">
            <div id="tray-filter-bar" hidden>
              <input id="tray-search">
              <div class="tray-type-pills"></div>
              <div class="tray-filter-summary"></div>
            </div>
        ''')
        self.page.evaluate('''() => {
            window.requests = [];
            window.atelierFetch = (path, options, project) => new Promise(resolve => {
                requests.push({path, options, project, reply: data => resolve({json: async () => data})});
            });
            window.atelierProject = () => window.testProject;
            window.AtelierAssetEditors = {projectAssets: () => []};
            window.switchProject = project => {
                window.testProject = project;
                window.dispatchEvent(new CustomEvent('atelier:project-assets', {detail: {project}}));
            };
        }''')

    def load_script(self, name):
        self.page.add_script_tag(path=str(ROOT / 'gui' / name))

    def test_selection_profiles_ignore_previous_project_rows_and_responses(self):
        from playwright.sync_api import expect
        self.load_script('tray-filters.js')
        page = self.page
        page.evaluate("() => { switchProject('One'); AtelierTrayFilters.openProfiles(); }")
        page.evaluate("requests[0].reply({ok: true, profiles: {'First profile': {deselected: []}}})")
        expect(page.get_by_text('First profile')).to_be_visible()
        page.evaluate('''() => {
            AtelierTrayFilters.closeProfiles();
            switchProject('Two');
            AtelierTrayFilters.openProfiles();
        }''')
        self.assertEqual(page.get_by_role('button', name='Apply').count(), 0)
        page.evaluate("() => { switchProject('Three'); AtelierTrayFilters.openProfiles(); }")
        page.evaluate("requests[2].reply({ok: true, profiles: {'Current profile': {deselected: []}}})")
        expect(page.get_by_text('Current profile')).to_be_visible()
        page.evaluate("requests[1].reply({ok: true, profiles: {'Late profile': {deselected: []}}})")
        self.assertEqual(page.get_by_text('Late profile').count(), 0)
        expect(page.get_by_text('Current profile')).to_be_visible()

    def test_trash_empty_confirmation_cannot_outlive_its_project(self):
        from playwright.sync_api import expect
        self.load_script('dialog.js')
        self.load_script('trash-dialog.js')
        page = self.page
        page.evaluate("() => { switchProject('One'); AtelierTrash.open(); }")
        page.evaluate('''requests[0].reply({ok: true, entries: [{
            entry: 'fixture', state: 'ready', count: 1, assets: [{name: 'T_Test', game_rel: 'A/T_Test'}]
        }]})''')
        page.locator('#trash-empty-btn').click()
        expect(page.locator('#atelier-confirm-ok')).to_be_visible()
        page.evaluate("switchProject('Two')")
        page.locator('#atelier-confirm-ok').click()
        self.assertEqual(page.evaluate("requests.filter(r => r.path === '/api/trash/discard').length"), 0)

    def test_tray_recovers_when_the_filtered_type_disappears(self):
        from playwright.sync_api import expect
        self.load_script('tray-filters.js')
        page = self.page
        page.evaluate('''() => {
            window.texture = {name: 'Texture', file_type: 'texture'};
            window.material = {name: 'Material', file_type: 'material'};
            window.items = [texture, material];
            window.renderSidebar = () => {
                window.shown = AtelierTrayFilters.filter(items);
                AtelierTrayFilters.updateControls(items, shown);
            };
            renderSidebar();
        }''')
        page.get_by_role('button', name='Textures').click()
        self.assertEqual(page.evaluate('shown.map(i => i.name)'), ['Texture'])
        page.evaluate("() => { items = [material]; renderSidebar(); }")
        self.assertEqual(page.evaluate('shown.map(i => i.name)'), ['Material'])
        page.evaluate("() => { items = [texture, material]; renderSidebar(); }")
        expect(page.get_by_role('button', name='Textures')).to_be_visible()


if __name__ == '__main__':
    unittest.main()
