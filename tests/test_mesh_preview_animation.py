"""Replacement previews must accept the native decoder's atelier-gltf-local clips.

The synthetic rig has rotated parents, numbered FNames and eight weight slots.
The reference math follows AnimationCommand.cs, independently of mesh.py's exporter.
No game assets, Blender installation or native decoder are required.
"""
import copy
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np
from scipy.spatial.transform import Rotation

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from atelier.handlers import mesh, meshreplace, meshedit
from test_blender_import import FakeMesh


def matrix(position, quaternion, scale=(1, 1, 1)):
    result = np.eye(4)
    result[:3, :3] = Rotation.from_quat(quaternion).as_matrix() @ np.diag(scale)
    result[:3, 3] = position
    return result


def worlds(locals_, parents):
    result = []
    for local, parent in zip(locals_, parents):
        result.append(local if parent < 0 else result[parent] @ local)
    return np.array(result)


class Rig(FakeMesh):
    def __init__(self):
        super().__init__(sections=1)
        self.bones = [
            dict(name='root', number=0, parent=-1, translation=(20, 30, 40),
                 rotation=Rotation.from_euler('xyz', (15, 25, 35), degrees=True).as_quat(), scale=(1, 1, 1)),
            dict(name='fin', number=1, parent=0, translation=(10, 40, 60),
                 rotation=Rotation.from_euler('xyz', (30, -40, 10), degrees=True).as_quat(), scale=(2, 3, 4)),
            dict(name='fin', number=4, parent=1, translation=(-10, 5, 30),
                 rotation=Rotation.from_euler('xyz', (-20, 15, 60), degrees=True).as_quat(), scale=(1, 1, 1)),
        ]
        self.lods[0]['max_bone_influences'] = 8

    def section_bonemap(self, sec):
        return [0, 1, 2]

    def skin_weights(self, lod):
        joints, weights = super().skin_weights(lod)
        joints[:, 4] = 2
        weights[:, 0], weights[:, 1], weights[:, 4] = .2, .3, .5
        return joints, weights


class PreviewAnimation(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.model = Rig()
        self.path = self.root / 'preview.glb'

    def export(self, **options):
        mesh.export_glb(self.model, 0, self.path, **options)
        return mesh.load_glb(self.path)

    def test_native_idle_tracks_deform_replacement_like_the_original(self):
        g, binary = self.export(for_preview=True)
        skin = g['skins'][0]
        nodes = [g['nodes'][j] for j in skin['joints']]
        self.assertEqual([n['name'] for n in nodes], ['root', 'fin_0', 'fin_3'])
        parents = [-1, 0, 1]
        # Native mesh conversion swaps Y/Z on local TRS and omits scale. Physical
        # animation uses the inverse quaternion, then carries its world delta
        # through the exported bind (AnimationCommand's v2 track contract).
        positions = [np.array(b['translation'])[[0, 2, 1]] / 100 for b in self.model.bones]
        quats = [np.array(b['rotation'])[[0, 2, 1, 3]] for b in self.model.bones]
        reference = worlds([matrix(p, q) for p, q in zip(positions, quats)], parents)
        physical_locals = [matrix(p, Rotation.from_quat(q).inv().as_quat()) for p, q in zip(positions, quats)]
        physical = worlds(physical_locals, parents)
        binds = mesh.gltf_accessor(g, binary, skin['inverseBindMatrices']).reshape(-1, 4, 4).transpose(0, 2, 1)
        np.testing.assert_allclose(reference @ binds, np.tile(np.eye(4), (3, 1, 1)), atol=1e-6)
        attrs = g['meshes'][0]['primitives'][0]['attributes']
        points = mesh.gltf_accessor(g, binary, attrs['POSITION'])
        np.testing.assert_allclose(points, self.model.pos[:, [0, 2, 1]] / 100, atol=1e-7)
        homogeneous = np.column_stack((points, np.ones(len(points))))
        joints = np.concatenate([mesh.gltf_accessor(g, binary, attrs['JOINTS_' + str(i)]) for i in (0, 1)], axis=1)
        weights = np.concatenate([mesh.gltf_accessor(g, binary, attrs['WEIGHTS_' + str(i)]) for i in (0, 1)], axis=1)
        for degrees in (0, 20, -45, 90):
            animated_locals = copy.deepcopy(physical_locals)
            animated_locals[1] = animated_locals[1] @ matrix((0, 0, 0), Rotation.from_euler('z', degrees, degrees=True).as_quat())
            deformation = worlds(animated_locals, parents) @ np.linalg.inv(physical)
            animated = deformation @ reference
            track_locals = [animated[0], np.linalg.inv(animated[0]) @ animated[1], np.linalg.inv(animated[1]) @ animated[2]]
            tracks = dict(zip(('root', 'fin_0', 'fin_3'), track_locals))
            # Apply by node name, just as viewport-animation.js does.
            posed = worlds([tracks.get(n['name'], matrix(n['translation'], n['rotation'], n['scale'])) for n in nodes], parents)
            actual = np.sum(np.einsum('nvij,nj->nvi', (posed @ binds)[joints], homogeneous) * weights[:, :, None], axis=1)
            expected = np.sum(np.einsum('nvij,nj->nvi', deformation[joints], homogeneous) * weights[:, :, None], axis=1)
            np.testing.assert_allclose(actual, expected, atol=1e-6)

    def test_preview_reflects_geometry_tangents_and_sparse_morphs_together(self):
        self.model.lods[0].update(had_morphs=True, tail_morph=b'xxxx')
        self.model.base = 'fixture'
        delta = np.array([[10, 20, 30, .1, .2, .3]], dtype='f4')
        with patch('atelier.handlers.morph.decode', return_value={'targets': [dict(indices=np.array([2]), deltas=delta)]}), \
             patch('atelier.handlers.morph.metadata', return_value={'names': ['Smile']}):
            g, binary = self.export(for_preview=True, with_morphs=True)
        primitive = g['meshes'][0]['primitives'][0]
        read = lambda index: mesh.gltf_accessor(g, binary, index)
        np.testing.assert_array_equal(read(primitive['indices']).ravel(), self.model.idx)
        at = primitive['attributes']
        np.testing.assert_allclose(read(at['NORMAL']), np.tile((0, 1, 0), (len(self.model.pos), 1)))
        np.testing.assert_allclose(read(at['TANGENT']), np.tile((1, 0, 0, -1), (len(self.model.pos), 1)))
        np.testing.assert_array_equal(read(at['_ATELIER_MORPH_REST']), self.model.pos)
        self.assertEqual(g['meshes'][0]['extras']['targetNames'], ['Smile'])
        for name, expected in [('POSITION', (.1, .3, .2)), ('NORMAL', (.1, .3, .2))]:
            sparse = g['accessors'][primitive['targets'][0][name]]['sparse']
            indices = g['bufferViews'][sparse['indices']['bufferView']]
            values = g['bufferViews'][sparse['values']['bufferView']]
            self.assertEqual(np.frombuffer(binary, '<u4', 1, indices['byteOffset'])[0], 2)
            np.testing.assert_allclose(np.frombuffer(binary, '<f4', 3, values['byteOffset']), expected)

    def test_repeated_slot_names_bind_like_the_native_preview(self):
        # Spider-Man's lobby mesh uses the slot FName MI_1036803_Equip_03 twice, the second
        # with FName number 2. The native slot table spells it MI_1036803_Equip_03_1; the
        # preview's old __slot_6 key matched nothing there, so that part rendered untextured.
        from atelier import import_server
        from atelier.handlers import meshstudio
        self.model.materials = [{'slot_name': 'MI_Equip_03', 'slot_name_number': 0},
                                {'slot_name': 'MI_Equip_03', 'slot_name_number': 2}]
        names = lambda g: [m['name'] for m in g['materials']]
        preview = names(self.export(for_preview=True)[0])
        self.assertEqual(preview, ['MI_Equip_03', 'MI_Equip_03_1'])
        # Blender keeps the keys existing .blend files already carry.
        self.assertEqual(names(self.export()[0]), ['MI_Equip_03', 'MI_Equip_03__slot_1'])
        material = 'Characters/1036/1036803/Materials/Lobby/MI_Equip_03'
        native = [{'index': 0, 'slot': 'MI_Equip_03', 'mi': material, 'via': 'imports'},
                  {'index': 1, 'slot': 'MI_Equip_03_1', 'mi': material, 'via': 'imports'}]
        requested = [{'key': f'body::{index}', 'name': name, 'material_index': index} for index, name in enumerate(preview)]
        with patch.object(import_server, 'mesh_slots', return_value=native):
            bindings = meshstudio.preview_bindings('Characters/1036/1036803/Meshes/SK_Body', requested)
        self.assertEqual([(b.get('slot_index'), b.get('game_rel'), b.get('mapping_error')) for b in bindings],
                         [(0, material, None), (1, material, None)])

    def test_editing_export_keeps_its_existing_coordinate_and_name_contract(self):
        self.model.lods[0]['col_off'] = None
        g, binary = self.export()
        at = g['meshes'][0]['primitives'][0]['attributes']
        points = mesh.gltf_accessor(g, binary, at['POSITION'])
        np.testing.assert_allclose(points, self.model.pos[:, [0, 2, 1]] * [1, 1, -1] / 100, atol=1e-7)
        self.assertEqual([g['nodes'][j]['name'] for j in g['skins'][0]['joints']], ['root', 'fin', 'fin'])
        self.assertEqual(g['nodes'][1]['scale'], [2, 3, 4])
        self.assertFalse(mesh.is_current_preview(self.path))
        sections = mesh.glb_to_sections(self.model, 0, self.path)
        np.testing.assert_allclose(sections[0]['positions'], self.model.pos, atol=1e-5)
        np.testing.assert_array_equal(sections[0]['triangles'].ravel(), self.model.idx)

    def test_existing_replacement_cache_is_migrated_once_even_when_newer_than_blend(self):
        base = str(self.root / 'model')
        blend = Path(base + '.blend'); blend.write_bytes(b'fixture')
        self.path = Path(base + '.mesh.glb')
        self.export()  # Old convention, with a newer timestamp than the source.
        os.utime(blend, (1, 1))
        self.model.rebuild_lod = Mock()
        with patch.object(meshreplace, 'target_base', return_value=base), \
             patch.object(meshedit, '_resolve_base', return_value='original'), \
             patch.object(meshedit, '_run_blender', return_value='GLB_OK') as blender, \
             patch.object(mesh, 'Mesh', return_value=self.model), \
             patch.object(mesh, 'glb_to_sections', return_value=[]):
            self.assertEqual(meshreplace.preview('model'), str(self.path))
            self.assertTrue(mesh.is_current_preview(self.path))
            self.assertEqual(meshreplace.preview('model'), str(self.path))
            blender.assert_called_once()

    def test_failed_cache_migration_keeps_previous_preview(self):
        base = str(self.root / 'model')
        Path(base + '.blend').write_bytes(b'fixture')
        self.path = Path(base + '.mesh.glb'); self.export()
        before = self.path.read_bytes()
        with patch.object(meshreplace, 'target_base', return_value=base), \
             patch.object(meshedit, '_run_blender', side_effect=ValueError('Cannot rebuild')):
            with self.assertRaisesRegex(ValueError, 'Cannot rebuild'):
                meshreplace.preview('model')
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(list(self.root.glob('.mesh-preview-*')))


if __name__ == '__main__':
    unittest.main()
