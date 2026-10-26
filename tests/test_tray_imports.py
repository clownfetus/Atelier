"""Completed imports carry authoritative tray entries without another project scan."""
import atexit
from contextlib import ExitStack
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from wsgiref.util import setup_testing_defaults

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
data = tempfile.TemporaryDirectory(prefix='atelier-tray-imports-')
os.environ['ATELIER_DATA_DIR'] = data.name
from atelier import config as C, project_meta as PM
from atelier.web import routes as R, browse as B


def cleanup():
    R._observer.stop()
    R._observer.join()
    data.cleanup()


atexit.register(cleanup)


class TrayImports(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.project = self.root / 'projects/A'
        self.project.mkdir(parents=True)
        self.source = self.root / 'source'
        self.source.with_suffix('.uasset').write_bytes(b'fixture')
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.multiple(C, PROJECTS_ROOT=str(self.project.parent), _active_project='A'))
        self.stack.enter_context(patch.object(R, 'PROJECTS_ROOT', str(self.project.parent)))
        self.stack.enter_context(patch.object(R, 'ensure_work_base', return_value=str(self.source)))
        self.stack.enter_context(patch.object(R, '_cache_import_base', return_value=str(self.source)))
        self.gr = 'Characters/1024/1024503/Textures/T_1024503_Equip_02_D'

    def call(self):
        env = {}
        setup_testing_defaults(env)
        payload = json.dumps({'game_rel': self.gr}).encode()
        env.update(REQUEST_METHOD='POST', PATH_INFO='/api/import_texture', CONTENT_TYPE='application/json',
                   CONTENT_LENGTH=str(len(payload)), HTTP_X_ATELIER_PROJECT='A', **{'wsgi.input': io.BytesIO(payload)})
        statuses = []
        result = R.app(env, lambda status, headers, exc_info=None: statuses.append(status))
        try:
            self.assertTrue(statuses[0].startswith('200'), statuses)
            return json.loads(b''.join(result))
        finally:
            if hasattr(result, 'close'):
                result.close()

    def write(self, gr, legacy=False):
        with C.project_context(str(self.project)):
            base = C.project_base_legacy(gr) if legacy else C.project_base(gr)
        path = Path(base + '.png')
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new('RGBA', (2, 2), (30, 70, 90, 255)).save(path)
        return path

    def test_response_contains_saved_selection_options_and_ready_texture(self):
        path = self.write(self.gr)
        before = path.read_bytes()
        PM.set_deselected(str(self.project), [self.gr])
        PM.set_asset_opts(str(self.project), self.gr, {'blank': True})
        with patch.object(R, 'decode_png', side_effect=AssertionError('Keep existing paint')):
            result = self.call()
        self.assertTrue(result['ok'])
        entry = result['imported']
        self.assertEqual(entry['game_rel'], self.gr)
        self.assertEqual(entry['token'], B.token(self.gr))
        self.assertEqual(entry['file_type'], 'texture')
        self.assertFalse(entry['selected'])
        self.assertEqual(entry['opts'], {'blank': True})
        self.assertEqual(entry['modified'], entry['mtime'])
        self.assertEqual(path.read_bytes(), before)

    def test_new_texture_is_listed_in_its_own_import_response(self):
        def decode(base, source):
            Image.new('RGBA', (2, 2), 'blue').save(base + '.png')
        with patch.object(R, 'decode_png', side_effect=decode):
            result = self.call()
        self.assertTrue(result['ok'])
        self.assertTrue(result['imported']['selected'])
        self.assertEqual(result['imported']['name'], self.gr.rsplit('/', 1)[-1])

    def test_failed_decode_does_not_claim_a_tray_entry(self):
        with patch.object(R, 'decode_png'):
            result = self.call()
        self.assertFalse(result['ok'])
        self.assertNotIn('imported', result)

    def test_targeted_lookup_avoids_tree_walk_and_excludes_other_assets(self):
        self.write(self.gr)
        self.write('Characters/1024/1024503/Textures/T_Other')
        self.write('UI/T_Unrelated')
        with C.project_context(str(self.project)), patch.object(B.os, 'walk', side_effect=AssertionError('No tree scan')):
            entries = B.all_imported(self.gr)
        self.assertEqual([entry['game_rel'] for entry in entries], [self.gr])

    def test_targeted_lookup_keeps_legacy_flat_projects(self):
        self.write(self.gr, legacy=True)
        with C.project_context(str(self.project)), patch('atelier.asset_cache.by_name', return_value=self.gr):
            entries = B.all_imported(self.gr)
        self.assertEqual([entry['game_rel'] for entry in entries], [self.gr])

    def test_targeted_lookup_rejects_invalid_paths(self):
        with self.assertRaises(ValueError):
            B.all_imported('../outside')


if __name__ == '__main__':
    unittest.main()
