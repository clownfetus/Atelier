"""Built-in S-map processing: pairing, pixels, source preservation and publication."""
import atexit
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import quote
from wsgiref.util import setup_testing_defaults

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_data = tempfile.TemporaryDirectory(prefix='atelier-s-maps-tests-')
os.environ['ATELIER_DATA_DIR'] = _data.name
from atelier import config as C, jobs, s_maps as S, storage
from atelier.web import routes as R


def cleanup():
    jobs.shutdown(3)
    R._observer.stop(); R._observer.join()
    _data.cleanup()


atexit.register(cleanup)


class Cases(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='atelier-s-map-case-')
        self.root = self.temp.name
        self.context = C.project_context(self.root)
        self.context.__enter__()
        self.index = []
        self.mock_index = patch.object(S, 'ensure_index', lambda: [(gr + '.uasset',) for gr in self.index])
        self.mock_index.start()
        self.folder = 'Characters/1/Skin/Textures/'

    def tearDown(self):
        self.mock_index.stop(); self.context.__exit__(None, None, None); self.temp.cleanup()

    def image(self, name, color, size=(8, 6), root=None):
        gr = self.folder + name
        path = C.project_base(gr, root or self.root) + '.png'
        os.makedirs(os.path.dirname(path), exist_ok=True)
        Image.new('RGBA', size, color).save(path)
        return gr, path

    def test_color_mode_gamut_and_alpha(self):
        # Known saturated Color-mode result, rather than HSL replacement or RGB multiplication.
        result = S.color_blend(Image.new('RGBA', (2, 2), (255, 0, 0, 255)),
                               Image.new('RGBA', (5, 600), (128, 128, 128, 37)))
        self.assertEqual(result.size, (5, 600))
        self.assertEqual(result.getpixel((0, 0)), (255, 74, 74, 37))
        self.assertEqual(result.getpixel((4, 599)), (255, 74, 74, 37))
        base = Image.new('RGBA', (3, 2), (50, 70, 90, 11))
        invisible = S.color_blend(Image.new('RGBA', (1, 1), (255, 0, 0, 0)), base)
        self.assertEqual(invisible.tobytes(), base.tobytes())
        for level in (0, 255):
            blended = S.color_blend(Image.new('RGB', (1, 1), (0, 40, 255)), Image.new('RGB', (1, 1), (level,) * 3))
            self.assertEqual(blended.getpixel((0, 0))[:3], (level,) * 3)

    def test_luminance_and_achromatic_color(self):
        rng = np.random.default_rng(12)
        base = rng.integers(0, 256, (32, 32, 4), dtype=np.uint8)
        source = rng.integers(0, 256, (32, 32, 4), dtype=np.uint8); source[..., 3] = 255
        result = np.asarray(S.color_blend(Image.fromarray(source), Image.fromarray(base)))
        weights = np.array([.30, .59, .11])
        self.assertLessEqual(np.abs((result[..., :3].astype(float) - base[..., :3]) @ weights).max(), .51)
        np.testing.assert_array_equal(result[..., 3], base[..., 3])
        gray = np.asarray(S.color_blend(Image.new('RGB', (32, 32), '#888888'), Image.fromarray(base)))
        np.testing.assert_array_equal(gray[..., 0], gray[..., 1])
        np.testing.assert_array_equal(gray[..., 1], gray[..., 2])

    def test_pairing_stays_in_folder_and_exposes_shared_targets(self):
        edited = ['A/Body_01_D', 'A/Body_02_D', 'B/Body_D', 'B/Eyes_D', 'A/Hair_N']
        pairs, skipped = S.pair_maps(edited, ['A/Body_S', 'B/Body_S', 'C/Eyes_S'])
        self.assertEqual(pairs, [{'s':'A/Body_S', 'candidates':edited[:2]}, {'s':'B/Body_S', 'candidates':['B/Body_D']}])
        self.assertEqual([row['d'] for row in skipped], ['B/Eyes_D'])
        pairs, skipped = S.pair_maps(['Body_01_D'], ['Body_S'])
        self.assertEqual(pairs, [{'s':'Body_S', 'candidates':['Body_01_D']}])
        self.assertFalse(skipped)
        pairs, skipped = S.pair_maps(['A/body_D'], ['A/Body_S', 'A/body_s'])
        self.assertFalse(pairs); self.assertTrue(skipped)
        with self.assertRaises(ValueError):
            S.pair_maps(['../Body_D'], [])

    def test_existing_s_processed_with_backup_and_unchanged_sources(self):
        d, d_path = self.image('Body_D', '#e03020', (16, 12))
        s, s_path = self.image('Body_S', (90, 90, 90, 51))
        unrelated, other_path = self.image('Eyes_N', '#88aaff')
        before = {path: Path(path).read_bytes() for path in (d_path, s_path, other_path)}
        result = S.process(S.plan()['plan_id'])
        self.assertEqual([row['s'] for row in result['processed']], [s])
        self.assertEqual(Path(d_path).read_bytes(), before[d_path])
        self.assertEqual(Path(other_path).read_bytes(), before[other_path])
        self.assertNotEqual(Path(s_path).read_bytes(), before[s_path])
        with Image.open(s_path) as image:
            self.assertEqual(image.size, (8, 6)); self.assertEqual(image.getpixel((0, 0))[3], 51)
        backup = Path(self.root, result['backup'], s + '.png')
        self.assertEqual(backup.read_bytes(), before[s_path])
        self.assertTrue(Path(self.root, result['backup'], 'batch.json').is_file())

    def test_unimported_s_is_decoded_to_scratch_then_added(self):
        d, _ = self.image('Body_D', '#1040f0')
        s = self.folder + 'Body_S'; self.index = [s]
        original = Path(self.temp.name, 'native-source.png')
        Image.new('RGB', (3, 7), '#777777').save(original)
        with patch.object(S.T, 'ensure_work_base', return_value='game-source'), \
             patch.object(S.T, 'decode_png', side_effect=lambda base, cb: shutil.copy2(original, base + '.png')):
            result = S.process(S.plan()['plan_id'])
        self.assertEqual(result['processed'][0]['size'], [3, 7])
        self.assertTrue(Path(C.project_base(s) + '.png').is_file())

    def test_ambiguity_requires_explicit_mapping(self):
        a, _ = self.image('Body_01_D', '#ff0000')
        b, _ = self.image('Body_02_D', '#0000ff')
        s, _ = self.image('Body_S', '#777777')
        plan = S.plan()
        with self.assertRaisesRegex(ValueError, 'Choose which D'):
            S.process(plan['plan_id'])
        result = S.process(plan['plan_id'], {s:b})
        self.assertEqual(result['processed'][0]['d'], b)
        with self.assertRaises(ValueError):
            S.process(plan['plan_id'], {s:a})

    def test_conflicts_reject_before_publishing(self):
        d, d_path = self.image('Body_D', '#ff0000')
        s, s_path = self.image('Body_S', '#777777')
        for change in (d_path, s_path):
            plan = S.plan()
            Image.new('RGB', (8, 6), '#224466').save(change)
            expected = Path(s_path).read_bytes()
            with self.assertRaisesRegex(RuntimeError, 'changed'):
                S.process(plan['plan_id'])
            self.assertEqual(Path(s_path).read_bytes(), expected)
        plan = S.plan()
        with self.assertRaises(ValueError):
            S.process(plan['plan_id'], {s:'Other/Body_D'})
        with tempfile.TemporaryDirectory() as other, C.project_context(other):
            with self.assertRaisesRegex(ValueError, 'another project'):
                S.process(plan['plan_id'])

    def test_failure_rolls_back_the_whole_batch(self):
        targets = []
        for name in ('Body', 'Head'):
            self.image(name + '_D', '#cc2299')
            _, path = self.image(name + '_S', '#777777'); targets.append(path)
        before = [Path(path).read_bytes() for path in targets]
        original = storage._atomic_bytes
        failed = []
        def write(path, payload):
            if str(path) == targets[1] and not failed:
                failed.append(True); raise OSError('Fixture disk failure')
            return original(path, payload)
        with patch.object(storage, '_atomic_bytes', side_effect=write):
            with self.assertRaisesRegex(OSError, 'Fixture disk failure'):
                S.process(S.plan()['plan_id'])
        self.assertEqual([Path(path).read_bytes() for path in targets], before)
        self.assertFalse(list(Path(self.root, '.atelier/s-map-backups').rglob('*.png')))

    def test_http_operation_uses_request_project(self):
        for name in ('A', 'B'):
            Path(R.PROJECTS_ROOT, name).mkdir(parents=True, exist_ok=True)
        root = str(Path(R.PROJECTS_ROOT, 'A'))
        _, d_path = self.image('Body_D', '#dd2211', root=root)
        s, s_path = self.image('Body_S', '#777777', root=root)
        def call(path, body):
            env = {}; setup_testing_defaults(env); payload = json.dumps(body).encode()
            env.update(REQUEST_METHOD='POST', PATH_INFO=path, CONTENT_TYPE='application/json',
                       CONTENT_LENGTH=str(len(payload)), HTTP_X_ATELIER_PROJECT=quote('A'),
                       **{'wsgi.input':io.BytesIO(payload)})
            status = []; response = R.app(env, lambda code, headers, exc_info=None: status.append(code))
            try: return json.loads(b''.join(response))
            finally:
                if hasattr(response, 'close'): response.close()
        plan = call('/api/s_maps/plan', {})
        C.set_active_project('B')
        result = call('/api/s_maps/process', {'plan_id':plan['plan_id']})
        self.assertTrue(result['ok']); self.assertTrue(Path(s_path).is_file())
        self.assertFalse(Path(C.project_base(s, str(Path(R.PROJECTS_ROOT, 'B'))) + '.png').exists())


if __name__ == '__main__':
    unittest.main()
