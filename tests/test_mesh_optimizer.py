"""Exercise the real pinned simplifier, including all retained vertex channels."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from atelier.mesh_optimizer import simplify_section
from atelier import mesh_optimizer


def grid(side=24):
    points = np.array([(x, y, .05*np.sin(x)) for y in range(side) for x in range(side)], 'f4')
    triangles = np.array([(y*side+x, y*side+x+1, (y+1)*side+x) for y in range(side-1) for x in range(side-1)] +
                        [(y*side+x+1, (y+1)*side+x+1, (y+1)*side+x) for y in range(side-1) for x in range(side-1)], 'u4')
    count = len(points); weights = np.zeros((count, 8), 'f4'); weights[:, 0] = 1
    return dict(mat=0, positions=points, triangles=triangles,
        normal=np.tile([0, 0, 1], (count, 1)).astype('f4'), tangent=np.tile([1, 0, 0], (count, 1)).astype('f4'),
        tan_w=np.ones(count, 'f4'), uv=(points[:, None, :2]/side).astype('f4'),
        color=np.column_stack((points[:, :2]/side, np.zeros(count), np.ones(count))).astype('f4'),
        global_idx=np.zeros((count, 8), 'u2'), weight=weights, bonemap=[0, 1],
        morph_ids=np.arange(count), morph_lods=np.zeros(count, 'i4'), morph_rest=points.copy())


class MeshOptimizer(unittest.TestCase):
    def test_changed_module_is_rejected_before_compilation(self):
        mesh_optimizer._runtime.cache_clear()
        with patch.object(mesh_optimizer, '_WASM') as module:
            module.read_bytes.return_value = b'changed module'
            with self.assertRaisesRegex(RuntimeError, 'checksum'):
                mesh_optimizer._runtime()

    def test_real_reduction_keeps_every_channel_on_its_original_vertex(self):
        original = grid(); before = original['triangles'].copy()
        result, report = simplify_section(original, .3)
        self.assertLess(len(result['triangles']), len(original['triangles'])//2)
        self.assertGreaterEqual(len(result['triangles']), 4)
        self.assertLessEqual(report['error'], .010001)
        for key in ('positions', 'normal', 'tangent', 'tan_w', 'uv', 'color', 'global_idx', 'weight', 'morph_rest', 'morph_lods'):
            np.testing.assert_array_equal(result[key], original[key][result['morph_ids']])
        np.testing.assert_array_equal(original['triangles'], before)
        self.assertTrue(np.all(result['triangles'] < len(result['positions'])))

    def test_bone_support_boundaries_and_all_section_borders_remain(self):
        section = grid(); points = section['positions']; section['global_idx'][points[:, 0] >= 12, 0] = 1
        result, _ = simplify_section(section, .2)
        locked = np.flatnonzero((points[:, 0] == 11) | (points[:, 0] == 12) |
                                (points[:, 0] == 0) | (points[:, 0] == 23) |
                                (points[:, 1] == 0) | (points[:, 1] == 23))
        self.assertTrue(set(locked) <= set(result['morph_ids']))
        self.assertEqual(result['bonemap'], [0, 1])
        self.assertLess(len(result['triangles']), len(section['triangles']))

    def test_dense_character_sized_section_has_enough_fuel_and_preserves_vertices(self):
        original = grid(192)
        reduced, report = simplify_section(original, .25)
        self.assertLess(len(reduced['triangles']), len(original['triangles'])//2)
        self.assertLessEqual(report['error'], .010001)
        for field in mesh_optimizer._VERTEX_FIELDS:
            np.testing.assert_array_equal(reduced[field], original[field][reduced['morph_ids']])

    def test_work_limit_is_bounded_and_reports_a_readable_error_without_mutation(self):
        section = grid(192)
        before = section['triangles'].copy()
        with patch.object(mesh_optimizer, '_MAX_FUEL', 1_000_000_000):
            with self.assertRaisesRegex(ValueError, 'simplifier work limit'):
                simplify_section(section, .25)
        np.testing.assert_array_equal(section['triangles'], before)

    def test_invalid_inputs_are_rejected_and_small_sections_stay_nonempty(self):
        section = grid(2)
        result, _ = simplify_section(section, .1)
        self.assertIs(result, section)
        for ratio in (0, -1, float('nan'), 2):
            with self.assertRaises(ValueError):
                simplify_section(section, ratio)
        section['triangles'][0, 0] = 100
        with self.assertRaisesRegex(ValueError, 'geometry'):
            simplify_section(section, .5)


if __name__ == '__main__':
    unittest.main()
