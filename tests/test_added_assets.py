"""Added asset paths, real project persistence, exports, failure rollback and trash recovery."""
import atexit
from contextlib import ExitStack
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_data = tempfile.TemporaryDirectory(prefix='atelier-added-assets-tests-')
os.environ['ATELIER_DATA_DIR'] = _data.name
atexit.register(_data.cleanup)

from atelier import added_assets as A, config as C, project_trash, storage
from atelier.handlers import custom_texture as CT, material as M, texture as T, meshreplace
from atelier.web import browse as B
from added_asset_fixtures import AssetTool, decode_png, image_bytes, package, mesh_probe


class AddedAssets(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.project = self.root / 'A'; self.project.mkdir()
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(C.project_context(str(self.project)))
        self.entries = []
        self.stack.enter_context(patch('atelier.index.ensure_index', side_effect=lambda: list(self.entries)))
        self.stack.enter_context(patch.object(A, 'ensure_index', side_effect=lambda: self.entries))
        self.stack.enter_context(patch.object(B, 'ensure_index', side_effect=lambda: self.entries))
        self.tool = AssetTool()
        for module in (A, CT, T, M): self.stack.enter_context(patch.object(module, 'uat', self.tool))
        self.stack.enter_context(patch.object(T, 'decode_to_png', side_effect=decode_png))
        self.stack.enter_context(patch('atelier.handlers.meshsurvey.probe', side_effect=mesh_probe))
        for module in (T, M): self.stack.enter_context(patch.object(module, 'pak_game_path', side_effect=lambda gr: 'Marvel/Content/Marvel/' + gr))
        self.stack.enter_context(patch.object(M, 'CACHE_3DVIEW', str(self.root / 'cache')))
        self.stack.enter_context(patch.object(M, '_CACHE', str(self.root / 'cache')))

    def source(self, kind, name=None):
        return package(self.root / 'input' / ((name or A.PREFIXES[kind] + 'Source') + '.uasset'), kind)

    def add(self, kind='texture', name='Custom', folder='MyAssets', source=None):
        source = source or self.source(kind)
        return A.add(kind, folder, name, files=[p for p in source.parent.glob(source.stem + '.*')])

    def test_types_are_listed_once_and_use_the_requested_package_identity(self):
        for kind in A.CLASSES:
            with self.subTest(kind=kind):
                result = self.add(kind)
                gr = result['game_rel']; base = A.source_base(gr)
                self.assertEqual(T.ensure_work_base(gr), base)
                doc = json.loads(Path(base + '.uasset').read_text())
                self.assertEqual(doc['Exports'][0]['ObjectName'], Path(gr).name)
                self.assertEqual(doc['FolderName'], A.GAME_ROOT + gr)
                self.assertEqual(doc['SoftObjectPathList'], [A.GAME_ROOT + gr + '.' + Path(gr).name])
                self.assertEqual(doc['Imports'][1]['ObjectName'], '/Game/Marvel/Shared/T_External')
                self.assertEqual(doc['NameMap'][:2], [A.PREFIXES[kind] + 'Source', '/Game/Marvel/Fixtures/' + A.PREFIXES[kind] + 'Source'])
        rows = B.all_imported()
        self.assertEqual(len(rows), 3)
        self.assertEqual({r['file_type'] for r in rows}, set(A.CLASSES))
        self.assertTrue(all(row['selected'] for row in rows))
        self.assertEqual(len(B.browse_dispatch('MyAssets')), 3)

    def test_path_validation_and_prefixes(self):
        self.assertEqual(A.asset_path('texture', '/Game/Marvel/Custom/Textures/', 'Paint'), 'Custom/Textures/T_Paint')
        self.assertEqual(A.asset_path('mesh', '', 'SM_Prop'), 'SM_Prop')
        for folder in ('../outside', 'A/../../outside', 'C:/Files', '/tmp', '.atelier', 'Plugins/Foo', 'Marvel_LQ/Foo', 'A//B'):
            with self.subTest(folder=folder), self.assertRaises(ValueError): A.asset_path('texture', folder, 'Good')
        for name in ('../escape', '', 'bad name', 'file.png', 'C:escape'):
            with self.subTest(name=name), self.assertRaises(ValueError): A.asset_path('material', 'Custom', name)
        with self.assertRaises(ValueError): A.asset_path('other', '', 'Good')
        self.assertFalse(list(self.project.iterdir()))

    def test_collisions_and_wrong_source_types_leave_existing_bytes_untouched(self):
        target = self.add()['game_rel']; before = Path(C.project_base(target) + '.png').read_bytes()
        with self.assertRaisesRegex(ValueError, 'already exists'): self.add()
        self.assertEqual(Path(C.project_base(target) + '.png').read_bytes(), before)
        self.entries.append(('MyAssets/T_Vanilla.uasset', 'fixture.utoc', 'Marvel/Content/Marvel/'))
        with self.assertRaisesRegex(ValueError, 'already exists in the game'): self.add(name='Vanilla')
        with self.assertRaisesRegex(ValueError, 'supported material'): self.add('material', source=self.source('texture'))
        self.assertEqual(len(B.all_imported()), 1)

    def test_root_additions_do_not_resolve_as_legacy_game_edits(self):
        from atelier import asset_cache
        result = self.add(folder='')
        with patch.object(asset_cache, 'by_name', return_value='Vanilla/Textures/T_Custom'):
            self.assertEqual(B.all_imported()[0]['game_rel'], 'T_Custom')
            self.assertEqual(B.game_rel_from_token(result['token']), 'T_Custom')

    def test_images_use_a_template_and_remain_editable_and_exportable(self):
        template = self.source('texture'); image = self.root / 'My paint.png'; image.write_bytes(image_bytes())
        ensure = T.ensure_work_base
        with patch.object(T, 'ensure_work_base', side_effect=lambda gr: str(template.with_suffix('')) if gr == 'Fixtures/T_Source' else ensure(gr)):
            result = A.add('texture', 'Custom/Textures', 'Paint', source='Fixtures/T_Source', files=[image])
        gr = result['game_rel']; changed = image_bytes((20, 180, 30, 255))
        Path(C.project_base(gr) + '.png').write_bytes(changed)
        stage = self.root / 'stage'
        T.stage_inject(str(stage), gr, {'no_mips': False})
        output = stage / ('Marvel/Content/Marvel/' + gr + '.uasset')
        self.assertEqual(output.with_suffix('.ubulk').read_bytes(), changed)
        self.assertEqual(json.loads(output.read_text())['Exports'][0]['ObjectName'], 'T_Paint')
        self.assertTrue(any(call[0] == 'inject_texture' and 'compiled' in call[1] for call in self.tool.calls))

    def test_material_and_mesh_stage_through_normal_exporters(self):
        material = self.add('material')['game_rel']; model = self.add('mesh')['game_rel']
        M.save_material(material, {'Tint': [.9, .8, .7, 1]}, {})
        stage = self.root / 'stage'; stage.mkdir()
        M.stage_material(str(stage), material, {}, {})
        doc = json.loads((stage / ('Marvel/Content/Marvel/' + material + '.uasset')).read_text())
        self.assertEqual(M._mat_params(doc)[0][0]['rgba'], [.9, .8, .7, 1])
        result = meshreplace.stage_original(model, str(stage))
        self.assertTrue(result['unchanged'])
        self.assertEqual(Path(result['uasset']).read_bytes(), Path(A.source_base(model) + '.uasset').read_bytes())
        M.reset_material(material)
        self.assertEqual(M.read_material(material)['colors'][0]['rgba'], [.2, .3, .4, 1.0])

    def test_added_mesh_preview_uses_its_local_package_without_blender(self):
        from atelier.handlers import mesh
        gr = self.add('mesh')['game_rel']
        with patch.object(mesh, 'Mesh') as parse, patch.object(mesh, 'export_glb', side_effect=lambda obj, lod, path: Path(path).write_bytes(b'glTF fixture')):
            path = meshreplace.preview(gr)
            parse.assert_called_once_with(A.source_base(gr))
            self.assertEqual(Path(path).read_bytes(), b'glTF fixture')
            self.assertEqual(meshreplace.preview(gr), path)
            parse.assert_called_once()

    def test_game_mesh_completes_streamed_source_before_copying(self):
        source = self.source('mesh')
        complete = self.root / 'complete' / source.name
        complete.parent.mkdir(); shutil.copy2(source, complete)
        complete.with_suffix('.uexp').write_bytes(b'opaque payload')
        complete.with_suffix('.ubulk').write_bytes(b'streamed high detail geometry')
        with patch.object(T, 'ensure_work_base', return_value=str(source.with_suffix(''))), \
             patch('atelier.handlers.meshstudio.complete_mesh_source', return_value=str(complete.with_suffix(''))) as resolve:
            result = A.add('mesh', 'Custom', 'Complete', source='Fixtures/SK_Source')
        resolve.assert_called_once_with('Fixtures/SK_Source')
        self.assertEqual(Path(A.source_base(result['game_rel']) + '.ubulk').read_bytes(), b'streamed high detail geometry')

    def test_incomplete_uploaded_mesh_and_lost_lods_publish_nothing(self):
        incomplete = {'status': 'ok', '_layout': [{'blob': 'missing'}]}
        with patch('atelier.handlers.meshsurvey.probe', return_value=incomplete), \
             self.assertRaisesRegex(ValueError, 'missing geometry'):
            self.add('mesh')
        self.assertFalse(list(self.project.rglob('*')))
        changed = mesh_probe(); changed['_layout'][0]['num_verts'] = 2
        with patch('atelier.handlers.meshsurvey.probe', side_effect=[mesh_probe(), changed]), \
             self.assertRaisesRegex(ValueError, 'every original LOD'):
            self.add('mesh')
        self.assertFalse(list(self.project.rglob('*')))

    def test_mesh_rename_may_move_serialized_section_offsets(self):
        original, renamed = mesh_probe(), mesh_probe()
        original['_layout'][0]['sections'][0].update(off=100, bm=120, after=180, bonemap_off=124)
        renamed['_layout'][0]['sections'][0].update(off=110, bm=130, after=190, bonemap_off=134)
        with patch('atelier.handlers.meshsurvey.probe', side_effect=[original, renamed]):
            self.assertTrue(self.add('mesh')['ok'])

    def test_folder_browser_includes_project_folders_and_filters_source_types(self):
        self.add('material', folder='Custom/Materials'); self.add('texture', folder='Custom/Textures')
        self.entries += [('Characters/Hero/Textures/T_Game.uasset', 'fixture.utoc', 'Marvel/Content/Marvel/'),
                         ('Characters/Hero/Materials/MI_Game.uasset', 'fixture.utoc', 'Marvel/Content/Marvel/')]
        self.assertEqual([row['name'] for row in A.browse()['items']], ['Characters', 'Custom'])
        self.assertEqual([row['name'] for row in A.browse('Custom')['items']], ['Materials', 'Textures'])
        self.assertEqual(A.browse('Custom/Materials', 'texture')['items'], [])
        self.assertEqual(A.browse('Custom/Materials', 'material')['items'][0]['name'], 'MI_Custom')
        self.assertEqual(A.browse('Characters/Hero/Textures', 'texture')['items'][0]['game_rel'], 'Characters/Hero/Textures/T_Game')

    def test_failures_and_invalid_images_publish_nothing(self):
        self.tool.fail = 'from_json'
        with self.assertRaisesRegex(ValueError, 'Could not build'): self.add()
        self.assertEqual(B.all_imported(), [])
        self.tool.fail = None
        original_write = storage._atomic_bytes
        def fail_marker(path, payload):
            if str(path).endswith('.asset.json'): raise OSError('fixture locked marker')
            return original_write(path, payload)
        with patch.object(storage, '_atomic_bytes', side_effect=fail_marker), self.assertRaises(OSError): self.add()
        self.assertEqual(B.all_imported(), [])
        self.assertFalse(list(self.project.rglob('*.uasset')))
        image = self.root / 'bad.png'; image.write_bytes(image_bytes(size=(15, 16)))
        template = self.source('texture')
        with patch.object(T, 'ensure_work_base', return_value=str(template.with_suffix(''))), self.assertRaisesRegex(ValueError, 'power of two'):
            A.add('texture', 'Custom', 'Bad', source='Fixtures/T_Source', files=[image])
        self.assertEqual(B.all_imported(), [])

    def test_trash_restore_and_project_copy_keep_the_added_source(self):
        gr = self.add()['game_rel']; original = Path(A.source_base(gr) + '.uasset').read_bytes()
        removed = project_trash.remove(str(self.project), [gr])
        self.assertEqual(B.all_imported(), []); self.assertIsNone(A.source_base(gr))
        self.assertTrue(project_trash.restore(str(self.project), removed['entry'])['ok'])
        self.assertEqual(Path(A.source_base(gr) + '.uasset').read_bytes(), original)
        clone = self.root / 'B'; shutil.copytree(self.project, clone)
        with C.project_context(str(clone)):
            self.assertTrue(Path(T.ensure_work_base(gr)).resolve().is_relative_to(clone.resolve()))
            self.assertEqual(Path(T.ensure_work_base(gr) + '.uasset').read_bytes(), original)
        removed = project_trash.remove(str(self.project), [gr]); self.add()
        self.assertFalse(project_trash.restore(str(self.project), removed['entry'])['ok'])


if __name__ == '__main__':
    unittest.main()
