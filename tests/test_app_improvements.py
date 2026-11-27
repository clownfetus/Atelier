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


if __name__ == '__main__':
    unittest.main()
