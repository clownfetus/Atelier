"""Trash keeps every edit sidecar and selection, without entering discovery or exports."""
import atexit
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from wsgiref.util import setup_testing_defaults
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
data = tempfile.TemporaryDirectory(prefix='atelier-trash-')
os.environ['ATELIER_DATA_DIR'] = data.name
from atelier import config as C, project_meta as PM, project_trash as T, asset_cache as AC
from atelier.web import routes as R, browse


def cleanup():
    R._observer.stop(); R._observer.join(); data.cleanup()


atexit.register(cleanup)


def call(path, body=None, method='POST'):
    env = {}; setup_testing_defaults(env)
    raw = json.dumps(body or {}).encode()
    env.update(REQUEST_METHOD=method, PATH_INFO=path, CONTENT_TYPE='application/json',
               CONTENT_LENGTH=str(len(raw)), **{'wsgi.input':io.BytesIO(raw), 'HTTP_X_ATELIER_PROJECT':'Trash'})
    return json.loads(b''.join(R.app(env, lambda *_args: None)))


class Trash(unittest.TestCase):
    def setUp(self):
        self.root = Path(C.PROJECTS_ROOT, 'Trash'); self.root.mkdir(parents=True, exist_ok=True)
        self.scope = C.project_context(str(self.root)); self.scope.__enter__()
        self.addCleanup(self.scope.__exit__, None, None, None)
        self.addCleanup(self.clear)
        self.tex = 'Characters/1029/1029001/Textures/T_Test'
        self.mat = 'Characters/1029/1029001/Materials/MI_Test'
        self.mesh = 'Characters/1029/1029001/Meshes/SK_Test'

    def clear(self):
        import shutil
        shutil.rmtree(self.root)
        AC.clear()

    def seed(self, gr, ext='.png', legacy=False):
        base = C.project_base_legacy(gr) if legacy else C.project_base(gr)
        path = Path(base + ext); path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((gr + ext).encode())
        cached = str(Path(C.WORK_IMPORT_ROOT, Path(gr).name))
        AC.record(gr, cached, 'fixture.pak', '../../../Marvel/Content/')
        PM.set_asset_opts(str(self.root), gr, {'blank':True, 'color_inten':{'Tint':4}})
        PM.set_deselected(str(self.root), PM.get_deselected(str(self.root)) | {gr})
        return path

    def test_http_multi_delete_and_undo_preserve_all_bytes_and_metadata(self):
        files = [self.seed(self.tex), self.seed(self.mat, '.json')]
        files += [self.seed(self.mesh, ext) for ext in T.EDIT_EXTS[2:]]
        original = {p:p.read_bytes() for p in files}
        opts = PM.get_asset_opts(str(self.root)); selected = PM.get_deselected(str(self.root))
        deleted = call('/api/delete_imported', {'game_rels':[self.tex,self.mat,self.mesh]})
        self.assertEqual(deleted['deleted'], 3)
        self.assertEqual(len(list((self.root/T.DIRECTORY).iterdir())), 1)
        self.assertEqual(browse.all_imported(), [])
        self.assertEqual(PM.get_asset_opts(str(self.root)), {})
        self.assertEqual(PM.get_deselected(str(self.root)), set())
        result = call('/api/restore_imported', {'entry':deleted['entry']})
        self.assertTrue(result['ok']); self.assertEqual(set(result['game_rels']), {self.tex,self.mat,self.mesh})
        for path, contents in original.items(): self.assertEqual(path.read_bytes(), contents)
        self.assertEqual(PM.get_asset_opts(str(self.root)), opts)
        self.assertEqual(PM.get_deselected(str(self.root)), selected)
        self.assertEqual(len(browse.all_imported()), 3)
        self.assertIsNotNone(AC.get(self.mesh))

    def test_legacy_layout_is_discoverable_after_cache_recreation(self):
        path = self.seed(self.tex, legacy=True); before = path.read_bytes()
        result = T.remove(str(self.root), [self.tex]); self.assertIsNone(AC.by_name('T_Test'))
        self.assertTrue(T.restore(str(self.root), result['entry'])['ok'])
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(browse.all_imported()[0]['game_rel'], self.tex)

    def test_restore_preserves_reimport_and_restores_nonconflicting_assets(self):
        texture = self.seed(self.tex); material = self.seed(self.mat, '.json')
        deleted = T.remove(str(self.root), [self.tex,self.mat])
        texture.write_bytes(b'new user edit')
        PM.set_asset_opts(str(self.root), self.tex, {'no_mips':True})
        result = T.restore(str(self.root), deleted['entry'])
        self.assertFalse(result['ok']); self.assertEqual(result['conflicts'], [self.tex])
        self.assertEqual(result['game_rels'], [self.mat]); self.assertTrue(material.exists())
        self.assertEqual(texture.read_bytes(), b'new user edit')
        self.assertEqual(PM.get_asset_opts(str(self.root), self.tex), {'no_mips':True})
        self.assertTrue((self.root/T.DIRECTORY/deleted['entry']).is_dir())

    def test_copy_failure_rolls_back_whole_delete(self):
        files = [self.seed(self.tex), self.seed(self.mat, '.json')]
        original = os.replace
        def replace(source, dest):
            if str(dest).endswith('MI_Test.json') and T.DIRECTORY in str(dest): raise OSError('disk full')
            return original(source,dest)
        with patch.object(T.os, 'replace', side_effect=replace), self.assertRaises(OSError):
            T.remove(str(self.root), [self.tex,self.mat])
        self.assertTrue(all(p.is_file() for p in files)); self.assertEqual(len(browse.all_imported()),2)
        self.assertTrue(PM.get_asset_opts(str(self.root), self.tex)['blank'])

    def test_purge_bounds_age_and_count(self):
        entries = []
        for index in range(23):
            self.seed(self.tex)
            with patch.object(T.time, 'time', return_value=1000000+index):
                entries.append(T.remove(str(self.root), [self.tex])['entry'])
        self.assertEqual(len(list((self.root/T.DIRECTORY).iterdir())),20)
        self.assertFalse((self.root/T.DIRECTORY/entries[0]).exists())
        T.purge(str(self.root), 1000000+T.MAX_AGE+24)
        self.assertEqual(list((self.root/T.DIRECTORY).iterdir()),[])

    def test_interrupted_rollback_preserves_earlier_and_newer_files(self):
        texture = self.seed(self.tex); self.seed(self.mat, '.json')
        before = texture.read_bytes(); original = os.replace
        def replace(source, dest):
            if str(dest).endswith('MI_Test.json') and T.DIRECTORY in str(dest):
                texture.write_bytes(b'new external edit')
                raise OSError('interrupted')
            return original(source,dest)
        with patch.object(T.os,'replace',side_effect=replace),self.assertRaisesRegex(RuntimeError,'earlier files remain'):
            T.remove(str(self.root),[self.tex,self.mat])
        T.purge(str(self.root))
        self.assertEqual(texture.read_bytes(),b'new external edit')
        saved=list((self.root/T.DIRECTORY).rglob('T_Test.png'))
        self.assertEqual(len(saved),1);self.assertEqual(saved[0].read_bytes(),before)

    def test_conflicting_rollback_keeps_newer_settings_and_is_never_replayed(self):
        texture = self.seed(self.tex); material = self.seed(self.mat, '.json'); before = texture.read_bytes()
        result = T.remove(str(self.root), [self.tex, self.mat]); folder = self.root/T.DIRECTORY/result['entry']
        manifest = json.loads((folder/'manifest.json').read_text()); manifest['state'] = 'moving'
        (folder/'manifest.json').write_text(json.dumps(manifest))
        # A crash left the delete half-done, and a newer edit was saved before the project reopened.
        texture.write_bytes(b'newer edit'); PM.set_asset_opts(str(self.root), self.tex, {'no_mips': True})
        for _ in range(2):  # Every project list, project switch and delete purges again.
            T.purge(str(self.root))
            self.assertEqual(texture.read_bytes(), b'newer edit')
            self.assertEqual(PM.get_asset_opts(str(self.root), self.tex), {'no_mips': True})
            self.assertNotIn(self.tex, PM.get_deselected(str(self.root)))
            self.assertTrue(material.is_file()); self.assertIn(self.mat, PM.get_deselected(str(self.root)))
        self.assertEqual(json.loads((folder/'manifest.json').read_text())['state'], 'kept')
        T.purge(str(self.root), T.time.time() + 2 * T.MAX_AGE)
        self.assertEqual([p.read_bytes() for p in folder.rglob('T_Test.png')], [before])

    def test_locked_file_is_reported_as_json_and_rolled_back(self):
        files = [self.seed(self.mat, '.json')] + [self.seed(self.mesh, ext) for ext in ('.blend', '.mesh.json')]
        original = os.replace
        def replace(source, dest):
            if str(source).endswith('SK_Test.blend') and T.DIRECTORY in str(dest):
                raise PermissionError(13, 'The process cannot access the file because it is being used by another process', str(source))
            return original(source, dest)
        with patch.object(T.os, 'replace', side_effect=replace):
            result = call('/api/delete_imported', {'game_rels':[self.mat, self.mesh]})
        self.assertFalse(result['ok'])
        self.assertIn('SK_Test.blend could not be moved to the project trash', result['error'])
        self.assertIn('Close any program using it', result['error'])
        self.assertTrue(all(p.is_file() for p in files))
        self.assertTrue(PM.get_asset_opts(str(self.root), self.mesh)['blank'])
        self.assertEqual(list((self.root/T.DIRECTORY).iterdir()), [])

    def test_interrupted_http_delete_reports_where_earlier_files_remain(self):
        texture = self.seed(self.tex); self.seed(self.mat, '.json'); original = os.replace
        def replace(source, dest):
            if str(dest).endswith('MI_Test.json') and T.DIRECTORY in str(dest):
                texture.write_bytes(b'new external edit')
                raise OSError('interrupted')
            return original(source, dest)
        with patch.object(T.os, 'replace', side_effect=replace):
            result = call('/api/delete_imported', {'game_rels':[self.tex, self.mat]})
        self.assertFalse(result['ok']); self.assertIn('earlier files remain', result['error'])

    def test_trash_is_absent_from_discovery_counts_and_project_archive(self):
        self.seed(self.tex); self.seed(self.mat,'.json')
        result = call('/api/delete_all_imported')
        self.assertEqual(result['deleted'],2)
        self.assertEqual(browse.all_imported(),[])
        self.assertIsNone(browse.game_rel_from_token(browse.token(self.tex)))
        project = next(p for p in R._list_projects() if p['name']=='Trash')
        self.assertEqual(project['asset_count'],0)
        archive = R._build_project_zip(['Trash'])
        with zipfile.ZipFile(archive) as z:
            self.assertFalse(any(T.DIRECTORY in p for p in z.namelist()))
        self.assertTrue(T.restore(str(self.root), result['entry'])['ok'])

    def test_invalid_entry_and_symlink_paths_cannot_escape_project(self):
        with self.assertRaises(ValueError): T.restore(str(self.root), '../elsewhere')
        with self.assertRaises(ValueError): T._inside(self.root, '../T_Test.png')
        with self.assertRaises(ValueError): C.project_base('.atelier-trash/entry/files/Fixture/T_Test')

    def test_interrupted_delete_recovers_on_open(self):
        path = self.seed(self.tex)
        result = T.remove(str(self.root),[self.tex]); folder = self.root/T.DIRECTORY/result['entry']
        manifest = json.loads((folder/'manifest.json').read_text()); manifest['state']='moving'
        (folder/'manifest.json').write_text(json.dumps(manifest))
        T.purge(str(self.root))
        self.assertTrue(path.exists()); self.assertTrue(PM.get_asset_opts(str(self.root),self.tex)['blank'])


if __name__ == '__main__': unittest.main()
