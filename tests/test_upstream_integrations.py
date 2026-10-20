"""Behavioral checks for the reviewed upstream integrations, without game files."""
import importlib.util
import atexit
import os
import struct
import tempfile
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_data = tempfile.TemporaryDirectory(prefix='atelier-upstream-')
atexit.register(_data.cleanup)
os.environ['ATELIER_DATA_DIR'] = _data.name
from atelier.handlers.mesh import Mesh


class BlenderImageCache(unittest.TestCase):
    def test_shared_textures_reuse_each_colour_space_without_mutating_the_other(self):
        copies, loads = [], []

        class Image:
            users = 1

            def __init__(self, space='sRGB'):
                self.colorspace_settings = types.SimpleNamespace(name=space)

            def copy(self):
                image = Image(self.colorspace_settings.name)
                copies.append(image)
                return image

        original = Image()
        def load(path, **options):
            loads.append(path)
            return original

        fake = types.SimpleNamespace(data=types.SimpleNamespace(images=types.SimpleNamespace(load=load)))
        spec = importlib.util.spec_from_file_location('atelier_material_nodes_test', ROOT/'atelier/blender/material_nodes.py')
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'bpy': fake}):
            spec.loader.exec_module(module)
            color = module.load_image(str(ROOT/'texture.png'), 'sRGB')
            data = module.load_image(str(ROOT/'texture.png'), 'Non-Color')
            self.assertIs(module.load_image(str(ROOT/'./texture.png'), 'Non-Color'), data)
            self.assertIs(module.load_image(str(ROOT/'texture.png'), 'sRGB'), color)
        self.assertIsNot(color, data)
        self.assertEqual(color.colorspace_settings.name, 'sRGB')
        self.assertEqual(data.colorspace_settings.name, 'Non-Color')
        self.assertEqual((len(loads), len(copies)), (2, 1))


class CookedSkinWeights(unittest.TestCase):
    def decode(self, blob, **options):
        lod = dict(num_verts=2, sw_off=0, sw_cnt=len(blob), sw_esz=1, max_bone_influences=4, **options)
        return Mesh.skin_weights(types.SimpleNamespace(_blob=lambda _: blob), lod)

    def test_fixed_indices_and_weights_have_independent_precision(self):
        for index16, weight16 in ((True, False), (False, True), (True, True)):
            indices = [300 if index16 else 30, 2, 0, 0]
            weights = [32768, 32767, 0, 0] if weight16 else [128, 127, 0, 0]
            record = struct.pack('<4'+('H' if index16 else 'B'), *indices)
            record += struct.pack('<4'+('H' if weight16 else 'B'), *weights)
            decoded, values = self.decode(record*2, bone_index_16=index16, bone_weight_16=weight16)
            np.testing.assert_array_equal(decoded[:, :4], [indices]*2)
            np.testing.assert_allclose(values.sum(axis=1), [1, 1])

    def test_variable_offsets_are_byte_offsets_and_keep_the_heaviest_eight(self):
        first = struct.pack('<4H', 300, 301, 65535, 0)
        second = struct.pack('<20H', *range(400, 410), *range(1, 11))
        data = first+second
        blob = data+struct.pack('<2I', 2, (len(first)<<8)|10)
        lod = dict(num_verts=2, sw_off=0, sw_cnt=len(data), sw_esz=1, max_bone_influences=12,
                   variable_bones=True, bone_index_16=True, bone_weight_16=True,
                   lookup_off=len(data), lookup_cnt=2, lookup_esz=4)
        indices, weights = Mesh.skin_weights(types.SimpleNamespace(_blob=lambda _: blob), lod)
        self.assertEqual(indices[0, 0], 300)
        np.testing.assert_array_equal(indices[1], range(409, 401, -1))
        np.testing.assert_allclose(weights.sum(axis=1), [1, 1])
        bad = bytearray(blob); struct.pack_into('<I', bad, len(data), (len(data)<<8)|2)
        with self.assertRaisesRegex(ValueError, 'exceeds'):
            Mesh.skin_weights(types.SimpleNamespace(_blob=lambda _: bad), lod)
        with self.assertRaisesRegex(ValueError, 'vertex count'):
            Mesh.skin_weights(types.SimpleNamespace(_blob=lambda _: blob), {**lod, 'lookup_cnt':1})


if __name__ == '__main__':
    unittest.main()
