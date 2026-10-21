"""Eye colour layers and inherited opacity use generated images and isolated data."""
import atexit
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlencode
from wsgiref.util import setup_testing_defaults

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
temporary = tempfile.TemporaryDirectory(prefix='atelier-material-preview-')
os.environ['ATELIER_DATA_DIR'] = temporary.name
from atelier.handlers.material_preview import inherited_opacity, effect_surface, eye_layers, eye_image, eye_material
from atelier.web import routes as R


def cleanup():
    R.shutdown(5)
    temporary.cleanup()


atexit.register(cleanup)


class Surface(unittest.TestCase):
    def setUp(self):
        self.child = {'colors': [], 'scalars': [], 'surface': {
            'parent': 'MI_EyeHighlight', 'blend_mode': 'BLEND_Translucent', 'opacity': 1, 'two_sided': True}}
        self.parent = {'scalars': [{'name': 'Opacity', 'value': 0}], 'surface': {'opacity': 0}}

    def test_missing_child_opacity_inherits_zero_without_adding_editable_parameters(self):
        before = copy.deepcopy(self.child)
        result = inherited_opacity(self.child, lambda path: self.parent, lambda name: ['Common/MI_EyeHighlight'])
        self.assertEqual(result['surface']['opacity'], 0)
        self.assertTrue(result['surface']['two_sided'])
        self.assertEqual(result['surface']['opacity_source'], 'Common/MI_EyeHighlight')
        self.assertEqual(result['scalars'], [])
        self.assertEqual(self.child, before)

    def test_explicit_child_opacity_takes_precedence(self):
        self.child['scalars'] = [{'name': 'Opacity', 'value': .5}]
        self.child['surface']['opacity'] = .5
        read = Mock(side_effect=AssertionError('Parent must not override explicit opacity'))
        self.assertEqual(inherited_opacity(self.child, read, lambda _: [])['surface']['opacity'], .5)

    def test_exact_parent_reference_wins_over_duplicate_names(self):
        self.child['surface']['parent_path'] = 'Correct/MI_EyeHighlight'
        read = Mock(return_value=self.parent)
        result = inherited_opacity(self.child, read, lambda _: ['Correct/MI_EyeHighlight', 'Wrong/MI_EyeHighlight'])
        self.assertEqual(result['surface']['opacity'], 0)
        read.assert_called_once_with('Correct/MI_EyeHighlight')

    def test_ambiguous_parent_does_not_guess_a_material(self):
        read = Mock(side_effect=AssertionError('Ambiguous parent must not be loaded'))
        self.assertEqual(inherited_opacity(self.child, read, lambda _: ['A/MI_EyeHighlight', 'B/MI_EyeHighlight']), self.child)

    def test_parent_chain_is_bounded_and_cycles_fail(self):
        child = copy.deepcopy(self.child)
        with self.assertRaisesRegex(ValueError, 'recursive'):
            inherited_opacity(child, lambda _: child, lambda _: ['Common/MI_EyeHighlight'])


class Eyes(unittest.TestCase):
    def test_iris_radius_preserves_coloured_centre_and_tinted_sclera(self):
        params = {'scalars': [{'name': 'IrisUVRadius', 'value': .15}],
                  'colors': [{'name': 'ScleraTint', 'rgba': [0, 1, 0, 1]}]}
        image = eye_image(Image.new('RGB', (16, 32), 'red'), Image.new('RGB', (32, 16), 'white'), params, 64)
        self.assertEqual(image.getpixel((32, 32)), (255, 0, 0))
        self.assertEqual(image.getpixel((0, 0)), (0, 255, 0))
        red = sum(image.getpixel((x, y)) == (255, 0, 0) for y in range(64) for x in range(64))
        self.assertGreater(red, 200)
        self.assertLess(red, 400)

    def test_disabled_iris_and_zero_brightness_stay_disabled(self):
        iris, sclera = Image.new('RGB', (8, 8), 'red'), Image.new('RGB', (8, 8), 'white')
        self.assertEqual(eye_image(iris, sclera, {'scalars': [{'name': 'IrisUVRadius', 'value': 0}]}, 32).getpixel((16, 16)), (255, 255, 255))
        self.assertEqual(eye_image(iris, sclera, {'scalars': [{'name': 'IrisBrightness', 'value': 0}]}, 32).getpixel((16, 16)), (0, 0, 0))
        with self.assertRaises(ValueError):
            eye_image(iris, sclera, {'scalars': [{'name': 'IrisUVRadius', 'value': float('nan')}]})

    def test_detection_requires_both_eye_layers_and_preserves_ordinary_albedo(self):
        textures = {'IrisBaseColor': 'Iris', 'ScleraBaseColor': 'Sclera'}
        self.assertTrue(eye_material({'textures': textures}))
        self.assertFalse(eye_material({'textures': {'IrisBaseColor': 'Iris'}}))
        self.assertFalse(eye_material({'textures': {**textures, 'BaseColor': 'Explicit'}}))

    def test_missing_eye_layers_use_exact_shared_defaults_without_changing_authored_inputs(self):
        params = {'surface': {'parent': 'M_Common_Eye_Opt'}, 'textures': {'IrisBaseColor': 'Custom/Iris'}}
        before = copy.deepcopy(params)
        result = eye_layers(params, lambda name: ['Characters/OtherSkin/Textures/' + name, 'Characters/Common/Textures/Eyes/' + name])
        self.assertEqual(result['textures'], {'IrisBaseColor': 'Custom/Iris', 'ScleraBaseColor': 'Characters/Common/Textures/Eyes/T_EyeSclera_D'})
        self.assertEqual(result['eye_defaults'], ['ScleraBaseColor'])
        self.assertTrue(eye_material(result))
        self.assertEqual(params, before)
        self.assertEqual(eye_layers(params, lambda name: ['Other/' + name]), params)
        shadow = {'surface': {'parent': 'M_Common_FakeEyeShadow'}}
        read = Mock(side_effect=AssertionError('Eye shadow is not an iris material'))
        self.assertEqual(eye_layers(shadow, read), shadow)


class Effects(unittest.TestCase):
    def test_animated_effects_are_omitted_without_hiding_project_sections(self):
        parent = {'surface': {'parent': 'M_BPStdMoAni', 'blend_mode': 'BLEND_Translucent'},
                  'textures': {'SequencesTex': 'VFX/Sequence'}}
        child = {'surface': {'parent': 'MI_Fire', 'blend_mode': 'BLEND_Translucent', 'opacity': 1}, 'colors': []}
        before = copy.deepcopy(child)
        result = effect_surface(child, lambda _: parent, lambda _: ['VFX/MI_Fire'])
        self.assertEqual(result['surface']['opacity'], 0)
        self.assertEqual(result['surface']['preview_omitted'], 'Animated game effect')
        self.assertNotIn('hidden', result)
        self.assertEqual(child, before)
        child['surface']['parent_path'] = 'VFX/Correct/MI_Fire'
        read = Mock(return_value=parent)
        result = effect_surface(child, read, lambda _: ['VFX/Correct/MI_Fire', 'VFX/Wrong/MI_Fire'])
        self.assertEqual(result['surface']['preview_omitted'], 'Animated game effect')
        read.assert_called_once_with('VFX/Correct/MI_Fire')

    def test_disabled_alpha_stays_off_but_ordinary_surfaces_stay_visible(self):
        effect = {'surface': {'parent': 'M_Energy', 'blend_mode': 'BLEND_Translucent', 'opacity': 1},
                  'scalars': [{'name': 'Alpha', 'value': 0}]}
        self.assertEqual(effect_surface(effect, None, None)['surface']['opacity'], 0)
        opaque = {**effect, 'surface': {**effect['surface'], 'blend_mode': 'BLEND_Masked'}}
        self.assertEqual(effect_surface(opaque, None, None), opaque)
        textured = {**effect, 'textures': {'BaseColor': 'Body'}}
        self.assertEqual(effect_surface(textured, None, None), textured)
        enabled = {**effect, 'scalars': [{'name': 'Alpha', 'value': 1}]}
        self.assertEqual(effect_surface(enabled, None, None), enabled)


class EyeRoutes(unittest.TestCase):
    def call(self, original=False, body=None):
        env = {}
        setup_testing_defaults(env)
        env.update(REQUEST_METHOD='GET' if body is None else 'POST',
                   PATH_INFO='/api/eye_texture' if body is None else '/api/eye_preview',
                   QUERY_STRING=urlencode({'game_rel': 'Characters/Test/MI_Eye', 'original': '1' if original else '0'}))
        if body is not None:
            encoded = json.dumps(body).encode()
            env.update(CONTENT_TYPE='application/json', CONTENT_LENGTH=str(len(encoded)), **{'wsgi.input': io.BytesIO(encoded)})
        statuses = []
        response = R.app(env, lambda status, headers, exc_info=None: statuses.append(status))
        try:
            data = b''.join(response)
        finally:
            if hasattr(response, 'close'):
                response.close()
        return int(statuses[0].split()[0]), data

    def test_original_ignores_custom_images_and_drafts_and_versions_the_cache(self):
        root = Path(temporary.name)
        iris, sclera, custom = [root / name for name in ('iris.png', 'sclera.png', 'custom.png')]
        Image.new('RGB', (16, 16), 'red').save(iris)
        Image.new('RGB', (16, 16), 'blue').save(sclera)
        Image.new('RGB', (16, 16), 'green').save(custom)
        params = {'textures': {'IrisBaseColor': 'Iris', 'ScleraBaseColor': 'Sclera'},
                  'colors': [{'name': 'ScleraTint', 'rgba': [1, 1, 1, 1]}], 'scalars': []}
        before = copy.deepcopy(params)
        with patch.object(R, 'CACHE_3DVIEW', str(root / 'cache')), \
             patch.object(R, 'read_material', return_value=params), patch.object(R, 'read_material_original', return_value=params), \
             patch.object(R, '_texture_png', side_effect=lambda name, **_: str(iris if name == 'Iris' else sclera)), \
             patch.object(R._custom_tex, 'image_path', side_effect=lambda _gr, slot: str(custom) if slot == 'ScleraBaseColor' else None):
            status, data = self.call(original=True)
            self.assertEqual(status, 200)
            with Image.open(io.BytesIO(data)) as image:
                self.assertEqual(image.getpixel((0, 0)), (0, 0, 255))
            status, data = self.call(original=True, body={'game_rel': 'Characters/Test/MI_Eye', 'overrides': {'ScleraTint': [1, 0, 0, 1]}})
            self.assertEqual(status, 200)
            with Image.open(io.BytesIO(data)) as image:
                self.assertEqual(image.getpixel((0, 0)), (0, 0, 255))
            status, data = self.call(body={'game_rel': 'Characters/Test/MI_Eye', 'overrides': {'ScleraTint': [1, 0, 0, 1]}})
            self.assertEqual(status, 200)
            with Image.open(io.BytesIO(data)) as image:
                self.assertEqual(image.getpixel((0, 0)), (0, 0, 0))
            self.assertEqual(params, before)
            status, data = self.call(original=True)
            self.assertEqual(status, 200)
            with Image.open(io.BytesIO(data)) as image:
                self.assertEqual(image.getpixel((0, 0)), (0, 0, 255))
            status, _ = self.call(body={'game_rel': 'Characters/Test/MI_Eye', 'overrides': {'ScleraTint': [1, 2]}})
            self.assertEqual(status, 400)


if __name__ == '__main__':
    unittest.main()
