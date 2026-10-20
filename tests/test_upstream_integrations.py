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
from atelier.handlers import mesh, meshsurvey, meshmat, meshstudio
from atelier.unreal_refs import imported_package
from atelier.blender.psk_reader import normalized_weights
from atelier.handlers import texture
from PIL import Image as PillowImage


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


class TexturePublication(unittest.TestCase):
    def test_failed_or_truncated_worker_output_never_replaces_an_existing_image(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)/'edited.png'
            PillowImage.new('RGB', (4, 4), 'red').save(target)
            original = target.read_bytes()
            for success in (False, True):
                def worker(request):
                    Path(request['output_path']).write_bytes(b'partial PNG')
                    return {'success':success}
                with patch.object(texture, 'uat_pooled', side_effect=worker), \
                     patch.object(texture, 'uat', return_value=types.SimpleNamespace(returncode=1)):
                    self.assertFalse(texture._decode_png_file('input.uasset', str(target)))
                self.assertEqual(target.read_bytes(), original)
                self.assertEqual([p for p in Path(directory).iterdir() if p.is_file()], [target])
                self.assertFalse(list((Path(directory)/'.atelier').iterdir()))

    def test_older_tool_falls_back_and_publishes_a_valid_image(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)/'output.png'
            def legacy(arguments):
                PillowImage.new('RGB', (8, 8), 'blue').save(arguments[2], format='PNG')
                return types.SimpleNamespace(returncode=0)
            with patch.object(texture, 'uat_pooled', return_value=None), patch.object(texture, 'uat', side_effect=legacy):
                self.assertTrue(texture._decode_png_file('input.uasset', str(target)))
            with PillowImage.open(target) as image:
                self.assertEqual(image.size, (8, 8))
            self.assertEqual([p for p in Path(directory).iterdir() if p.is_file()], [target])
            self.assertFalse(list((Path(directory)/'.atelier').iterdir()))

    def test_texture_metadata_expires_when_a_companion_file_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)/'texture'; base.with_suffix('.uasset').write_bytes(b'header')
            companion = base.with_suffix('.uexp'); companion.write_bytes(b'export')
            response = {'success':True, 'data':{'is_texture':True, 'width':32, 'height':32, 'pixel_format':'PF_BC7', 'mip_count':3}}
            with patch.object(texture, 'uat_pooled', return_value=response) as worker:
                self.assertEqual(texture.texture_info(str(base))['fmt'], 'BC7')
                texture.texture_info(str(base)); self.assertEqual(worker.call_count, 1)
                companion.write_bytes(b'new export data')
                texture.texture_info(str(base)); self.assertEqual(worker.call_count, 2)


class CookedMaterialTags(unittest.TestCase):
    def test_tagged_material_layout_retains_fname_values_and_number_suffixes(self):
        material = struct.pack('<i4i', -1, 0, 0, 0, 0)+bytes(20)
        material += struct.pack('<i4i', 2, 1, 0, 2, 2)
        skeleton = struct.pack('<I', 8)+bytes(8*12)+struct.pack('<I', 8)+bytes(8*80)+struct.pack('<I', 8)+bytes(8*12)
        data = struct.pack('<I', 1)+material+skeleton
        for parser in (mesh._try_extras, meshsurvey._try_extras_any_bonecount):
            parsed = parser(data, 0, len(data))
            self.assertIsNotNone(parsed)
            materials = mesh.resolve_materials(parsed['materials'], ['MI_Body', 'MaterialTag.Body', 'MaterialTag.Number'])
            self.assertEqual(materials[0]['gameplay_tags'], ['MaterialTag.Body', 'MaterialTag.Number_1'])
        with self.assertRaisesRegex(ValueError, 'gameplay-tag'):
            mesh.resolve_materials([{'slot_name_idx':0, 'imported_slot_name_idx':0, 'tag_names':[(99, 0)]}], ['MI_Body'])

    def test_tags_follow_the_exact_slot_into_preview_and_blender_manifest(self):
        tags = ['MaterialTag.Weapon.Visible']
        model = types.SimpleNamespace(materials=[{'slot_name':'Body', 'gameplay_tags':tags}])
        with patch.object(meshmat, '_index_candidates', return_value=[]):
            slots = meshmat.resolve_mesh_materials('Meshes/SK_Body', model)
        self.assertEqual(slots[0]['gameplay_tags'], tags)
        with patch.object(meshstudio, 'cooked_slots', return_value=[{**slots[0], 'index':0}]):
            binding = meshstudio.preview_bindings('Meshes/SK_Body', [{'key':'body', 'name':'Body'}])[0]
        self.assertEqual(binding['gameplay_tags'], tags)
        slots[0].update(maps=[], parameters={})
        with patch.object(meshmat, 'resolve_mesh_materials', return_value=slots), \
             patch.object(meshmat, 'resolve_mesh_textures', side_effect=lambda value:value), \
             patch.object(meshmat, 'extract_textures_to_project', return_value={}):
            manifest = meshmat.build_manifest('Meshes/SK_Body', model)
        self.assertEqual(manifest['slots']['Body']['gameplay_tags'], tags)
        self.assertNotIn('hidden_sections', manifest['slots']['Body'])


class ImportReferences(unittest.TestCase):
    def test_nested_imports_keep_the_full_package_and_live_reference(self):
        package = {'ObjectName':'/Game/Marvel/Characters/Body/MI_Shared'}
        document = {'Imports':[{'ObjectName':'MI_Shared', 'OuterIndex':-2},
                               {'ObjectName':'Nested', 'OuterIndex':-3}, package]}
        record, relative = imported_package(document, -1)
        self.assertIs(record, package)
        self.assertEqual(relative, 'Characters/Body/MI_Shared')
        self.assertEqual(meshmat._mi_from_imports(document, -1), relative)

    def test_cycles_invalid_indices_and_escaping_packages_do_not_resolve(self):
        for imports in ([{'OuterIndex':-1}], [{'OuterIndex':True}], [{'OuterIndex':-99}],
                        [{'ObjectName':'/Game/Marvel/../../escape'}],
                        [{'ObjectName':'/Script/Engine.Material'}], ['broken']):
            self.assertIsNone(imported_package({'Imports':imports}, -1))
        self.assertIsNone(imported_package({'Imports':[{'ObjectName':'/Game/Marvel/MI_Body'}]}, True))


class ImportedInfluences(unittest.TestCase):
    def test_duplicate_vertex_bone_entries_accumulate_and_normalize_per_vertex(self):
        source = [(.2, 0, 1), (.3, 0, 1), (.5, 0, 2), (.2, 1, 1), (.2, 1, 2), (0, 2, 0)]
        result = {(point, bone):weight for weight, point, bone in normalized_weights(source)}
        self.assertEqual(result, {(0, 1):.5, (0, 2):.5, (1, 1):.5, (1, 2):.5})


if __name__ == '__main__':
    unittest.main()
