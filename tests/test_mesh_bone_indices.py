"""Bone palettes larger than a byte survive rebuilds and streamed metadata readback."""
import atexit
import os
from pathlib import Path
import struct
import sys
import tempfile
import types
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
environment = tempfile.TemporaryDirectory(prefix='atelier-bone-indices-')
atexit.register(environment.cleanup)
os.environ['ATELIER_DATA_DIR'] = environment.name
from atelier.handlers import mesh, meshsurvey


def section(palette_size=274, mat=0):
    indices = np.zeros((3, 8), dtype=np.uint16)
    indices[:, :2] = [palette_size - 1, 2]
    weights = np.zeros((3, 8), dtype='f4')
    weights[:, :2] = [.75, .25]
    return dict(mat=mat, bonemap=list(range(palette_size)),
        positions=np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype='f4'),
        normal=np.tile([0, 0, 1], (3, 1)), tangent=np.tile([1, 0, 0], (3, 1)),
        tan_w=np.ones(3), uv=np.zeros((3, 2, 2)), color=None,
        global_idx=indices, weight=weights, triangles=np.array([[0, 1, 2]]))


def decoded_blob(sections, **options):
    blob, metadata, vertices, stride, count = mesh.rebuild_lod_buffers(
        sections, b'\0' * 8, b'\0' * 4, **options)
    model = mesh.Mesh.__new__(mesh.Mesh)
    model.uexp, model.ubulk = bytearray(blob), bytearray()
    lod = dict(num_verts=vertices, buf='uexp', pos_off=11 + count * stride + 16,
               layout={'blob_end':len(blob), 'sections':[]})
    model._locate_vertex_buffers(lod)
    return model, lod, metadata


class BoneIndices(unittest.TestCase):
    def test_palettes_crossing_the_byte_boundary_preserve_local_indices_and_weight_bytes(self):
        for size in (256, 257, 274, 65536):
            with self.subTest(palette=size):
                source = section(size)
                model, lod, metadata = decoded_blob([source])
                indices, weights = model.skin_weights(lod)
                np.testing.assert_array_equal(indices, source['global_idx'])
                self.assertEqual(lod['bone_index_16'], size > 256)
                self.assertFalse(lod['bone_weight_16'])
                self.assertFalse(lod['variable_bones'])
                self.assertEqual(lod['sw_cnt'], 3 * (24 if size > 256 else 16))
                self.assertEqual(metadata[0]['bonemap'], source['bonemap'])
                np.testing.assert_allclose(weights[:, :2], [[191/255, 64/255]] * 3)
                # Inspect the binary independently: all eight indices precede the
                # eight one-byte weights, even when the indices need two bytes.
                fmt = '<8H8B' if size > 256 else '<16B'
                row = struct.unpack_from(fmt, model.uexp, lod['sw_off'])
                self.assertEqual(row[:2], (size - 1, 2))
                self.assertEqual(row[8:], (191, 64, 0, 0, 0, 0, 0, 0))

    def test_wide_source_precision_is_retained_for_small_palettes_and_mixed_sections(self):
        for sections, preserve in (([section(20)], True), ([section(20), section(274, 1)], False)):
            with self.subTest(sections=len(sections)):
                model, lod, _ = decoded_blob(sections, bone_index_16=preserve)
                self.assertTrue(lod['bone_index_16'])
                indices, weights = model.skin_weights(lod)
                np.testing.assert_array_equal(indices, np.concatenate([s['global_idx'] for s in sections]))
                np.testing.assert_allclose(weights.sum(axis=1), 1)

    def test_streamed_metadata_agrees_with_the_rebuilt_blob_and_tail_offsets(self):
        for wide in (False, True):
            for has_layout in (False, True):
                with self.subTest(wide=wide, layout=has_layout):
                    model, lod, _ = decoded_blob([section(274 if wide else 20)])
                    blob = bytes(model.uexp)
                    payload = bytearray(b'x' * 192)
                    offset = 24
                    struct.pack_into('<I', payload, offset, 100)
                    metadata = types.SimpleNamespace(uexp=payload)
                    source = dict(num_tex_coords=2, col_off=None, sections=[{'after':offset}])
                    if has_layout:
                        source['layout'] = {'size_offset':offset}
                    mesh.Mesh._patch_mirror(metadata, source, 100, len(blob), 3, 3, 3, 3,
                                            bone_index_16=wide)
                    struct.pack_into('<I', payload, offset + 8 + 65, 0)  # profile names
                    header, end = meshsurvey._read_availability(payload, offset + 8, False, len(payload))
                    self.assertEqual(header['bone_index_16'], wide)
                    self.assertEqual((header['num_bones'], header['sw_num_verts']), (24, 3))
                    self.assertEqual((header['bone_weight_16'], header['num_lookup_verts']), (0, 0))
                    self.assertIn(lod['tail_off'], meshsurvey._tail_candidates(header))
                    self.assertEqual(bytes(payload[:offset]), b'x' * offset)
                    self.assertEqual(bytes(payload[offset + 4:offset + 8]), b'x' * 4)
                    self.assertEqual(bytes(payload[end:]), b'x' * (len(payload) - end))

    def test_preflight_accepts_the_reported_mesh_and_still_blocks_unsupported_weights(self):
        lod = dict(has_cloth=False, hi_prec_tangent=False, bone_index_16=True,
            bone_weight_16=False, variable_bones=True, skin_weight_profiles=0,
            unified_bonemap=False, max_bonemap=274, has_morphs=True,
            idx_stride=4, num_verts=78154, cooked_out=False, disabled_sections=0)
        report = meshsurvey._classify({'status':'ok', 'lods':[lod]})
        self.assertEqual(report['status'], 'ok')
        self.assertEqual(report['unsupported'], [])
        self.assertEqual(set(report['warnings']), {'morphs', 'variable_bones'})
        for field, value, blocker in (('bone_weight_16', True, 'bone_weight_16'),
                                       ('max_bonemap', 65537, 'bonemap_overflow')):
            with self.subTest(field=field):
                report = meshsurvey._classify({'status':'ok', 'lods':[{**lod, field:value}]})
                self.assertEqual(report['status'], 'unsupported')
                self.assertEqual(report['unsupported'], [blocker])


if __name__ == '__main__':
    unittest.main()
