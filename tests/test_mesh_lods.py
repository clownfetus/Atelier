"""Authored LOD atlases follow verified sculpts without losing their materials or rig."""
import atexit
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
environment = tempfile.TemporaryDirectory(prefix='atelier-mapped-lods-')
atexit.register(environment.cleanup)
os.environ['ATELIER_DATA_DIR'] = environment.name
from atelier.handlers import mesh, mesh_lods
from test_blender_import import FakeMesh


class MappedLods(unittest.TestCase):
    def fixture(self):
        model = FakeMesh()
        model.lods[0]['col_off'] = None
        model.lods[0]['layout']['source_index'] = 0
        model.materials.append({'slot_name':'BakedAtlas'})
        lower = {'num_verts':len(model.pos), 'col_off':None, 'idx_stride':4, 'idx_off':0,
                 'max_bone_influences':4, 'num_tex_coords':1, 'layout':{'source_index':1},
                 'sections':[{'mat':0, 'base_vertex':0, 'base_index':0,
                              'num_verts':len(model.pos), 'num_tris':len(model.idx)//3}]}
        model.lods.append(lower)
        rest = model.pos.copy()
        model.positions = lambda lod: rest if lod is model.lods[0] else rest + np.array([0,0,.2], 'f4')
        model.uvs = lambda lod: (rest[:, None, :2]/100 if lod is model.lods[0]
                                else rest[:, None, :2]/400+.5).astype('f4')
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'reference.glb'
            mesh.export_glb(model, 0, str(path))
            sections = mesh.glb_to_sections(model, 0, str(path))
        return model, sections

    def test_lod_info_is_read_from_the_mesh_export_and_preserves_identity_entries(self):
        prop = lambda value: {'Name':'LODMaterialMap', 'Value':[{'Value':x} for x in value]}
        document = {'Exports':[{'ObjectName':'A_Morph', 'Data':[]},
            {'ObjectName':'SK_Body', 'Data':[{'Name':'LODInfo',
                'Value':[{'Value':[prop([])]}, {'Value':[prop([2,-1])]}]}]}]}
        self.assertEqual(mesh_lods.material_maps(document, 'SK_Body'), [[], [2,-1]])
        invalid = copy.deepcopy(document)
        invalid['Exports'][1]['Data'][0]['Value'][1]['Value'][0]['Value'][0]['Value'] = True
        with self.assertRaisesRegex(ValueError, 'invalid LOD'):
            mesh_lods.material_maps(invalid, 'SK_Body')

    def test_translation_keeps_lower_uv_atlas_skinning_colours_and_raw_section_index(self):
        model, sections = self.fixture()
        shift = np.array([1.25,-.75,.5], 'f4')
        for section in sections:
            section['positions'] += shift
        field = mesh_lods.Sculpt(model, sections)
        result = field.sections(1, [2])[0]
        np.testing.assert_allclose(result['positions'], model.positions(model.lods[1])+shift, atol=1e-5)
        np.testing.assert_array_equal(result['uv'], model.uvs(model.lods[1]))
        np.testing.assert_array_equal(result['weight'], model.skin_weights(model.lods[1])[1])
        self.assertEqual(result['mat'], 0)  # The cooked map, not a rewritten header, selects material 2.
        self.assertEqual(len(result['positions']), len(model.pos))
        self.assertEqual(result['bonemap'], [0,1])
        self.assertEqual(result['morph_lods'][0], 1)

    def test_rotation_transfers_surface_offsets_and_normal_tangent_frames(self):
        model, sections = self.fixture()
        rotation = np.array([[0,0,1],[0,1,0],[-1,0,0]], 'f4')
        for section in sections:
            section['positions'] = section['positions'] @ rotation.T
        field = mesh_lods.Sculpt(model, sections)
        self.assertIsNone(field.translation)
        result = field.sections(1, [2])[0]
        np.testing.assert_allclose(result['positions'], model.positions(model.lods[1]) @ rotation.T, atol=1e-5)
        np.testing.assert_allclose(result['normal'], np.tile([1,0,0], (len(model.pos),1)), atol=1e-5)
        np.testing.assert_allclose(result['tangent'], np.tile([0,0,-1], (len(model.pos),1)), atol=1e-5)
        np.testing.assert_array_equal(result['uv'], model.uvs(model.lods[1]))

    def test_topology_changes_and_missing_tracking_are_refused_instead_of_losing_geometry(self):
        for mutation in ('faces', 'ids', 'lod', 'rest', 'winding'):
            model, sections = self.fixture()
            if mutation == 'faces': sections[0]['triangles'] = sections[0]['triangles'][:-3]
            elif mutation == 'ids': sections[0]['morph_ids'] = []
            elif mutation == 'lod': sections[0]['morph_lods'][0] = 99
            elif mutation == 'rest': sections[0]['morph_rest'][0] += 1
            else: sections[0]['triangles'] = sections[0]['triangles'].reshape(-1,3)[:,[0,2,1]].reshape(-1)
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, 'original topology'):
                mesh_lods.Sculpt(model, sections)

    def test_seam_copies_must_agree_on_the_deformation_of_a_tracked_vertex(self):
        model, sections = self.fixture()
        section = sections[0]
        for key in ('positions', 'morph_rest', 'morph_ids', 'morph_lods'):
            section[key] = np.concatenate((section[key], section[key][:1]))
        section['positions'][-1] += 1
        with self.assertRaisesRegex(ValueError, 'original topology'):
            mesh_lods.Sculpt(model, sections)

    def test_a_material_map_cannot_point_outside_the_cooked_material_array(self):
        model, sections = self.fixture()
        with self.assertRaisesRegex(ValueError, 'missing material'):
            mesh_lods.Sculpt(model, sections).sections(1, [99])

    def test_mapping_minus_one_and_missing_entries_keep_the_raw_material_index(self):
        self.assertEqual(mesh_lods.material_index({'mat':0}, [2]), 2)
        self.assertEqual(mesh_lods.material_index({'mat':0}, [-1]), 0)
        self.assertEqual(mesh_lods.material_index({'mat':3}, [2]), 3)

    def test_material_map_cache_is_tied_to_both_package_files(self):
        from atelier import tools
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)/'SK_Cache'
            base.with_suffix('.uasset').write_bytes(b'header')
            base.with_suffix('.uexp').write_bytes(b'first properties')
            calls = []
            def read(args):
                calls.append(args)
                document = {'Exports':[{'ObjectName':'SK_Cache', 'Data':[]}]}
                (Path(args[-1])/'SK_Cache.json').write_text(json.dumps(document))
                return SimpleNamespace(returncode=0)
            with patch.object(tools, 'uat', side_effect=read):
                self.assertEqual(mesh_lods.load_material_maps(str(base)), [])
                self.assertEqual(mesh_lods.load_material_maps(str(base)), [])
                self.assertEqual(len(calls), 1)
                base.with_suffix('.uexp').write_bytes(b'changed LOD material properties')
                self.assertEqual(mesh_lods.load_material_maps(str(base)), [])
                self.assertEqual(len(calls), 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
