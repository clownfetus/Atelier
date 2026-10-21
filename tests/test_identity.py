"""Shared identity labels across content mounts, with no asset/path mutations."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from atelier.catalogue import Catalogue
from atelier.identity import resolve_ids

IMAGE = 'https://rivalskins.com/wp-content/uploads/marvel-assets/items/costume/29/img_test.webp'
ENTRIES = {'1029': {'kind': 'hero', 'name': 'Magik', 'image': IMAGE},
           '1029304': {'kind': 'skin', 'name': 'Infernal Idol', 'hero': '1029', 'image': IMAGE},
           '1029305': {'kind': 'skin', 'name': 'Soulless Sword', 'hero': '1029', 'image': None},
           '1035': {'kind': 'hero', 'name': 'Thor', 'image': IMAGE},
           '1035300': {'kind': 'skin', 'name': 'Thunder', 'hero': '1035', 'image': IMAGE}}
UI = 'UI/Textures/HeroGallery/HeroDetail/Skin/BattleCustom'
CASES = [(path, '1029', '1029304') for path in (
    'Characters/1029/1029304', 'VFX/Materials/Characters/1029/1029304',
    UI+'/1029304', 'Marvel_LQ/'+UI+'/1029304/T_Icon',
    'Plugins/MarvelGAS/UI/1029304/T_Icon', 'UI/Portraits/1029/1029304/T_Icon',
    '/Game/Marvel/'+UI+'/1029304', r'UI\Textures\1029304', 'UI/T_1029304_Icon')]
CASES += [('UI/Icons/1029', '1029', None), ('UI/T_1029_Icon', '1029', None),
          ('UI/1029999', '1029', '1029999')]
INVALID = ['UI/Com', 'UI/2026', 'UI/10293040', 'UI/T_10293040_Icon',
           'UI/T_21029304_Icon', 'Characters/1029/1035300', 'UI/1029/1035300',
           'UI/1029304/1029305', 'UI/1029304/1035', '../1029', '/UI/1029',
           'UI/../1029', 'UI//1029', 'C:/1029', 'https://example.test/1029',
           'UI/1029?x=1', 'UI/1029\x00']


class Identities(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        seed = self.root/'seed.json'
        seed.write_text(json.dumps({'schema': 1, 'entries': ENTRIES}), encoding='utf-8')
        self.catalogue = Catalogue(self.root/'cache', seed)

    def test_known_ids_resolve_in_all_branches_and_filename_tokens(self):
        for path, cid, sid in CASES:
            with self.subTest(path=path):
                result = resolve_ids(path, ENTRIES)
                self.assertEqual((result['char_id'], result['skin_id']), (cid, sid))

    def test_ambiguous_unrelated_substring_and_unsafe_paths_stay_unlabelled(self):
        for path in INVALID:
            with self.subTest(path=path): self.assertIsNone(resolve_ids(path, ENTRIES))

    def test_inconsistent_catalogue_owner_is_not_used(self):
        entries = {**ENTRIES, '1029304': {**ENTRIES['1029304'], 'hero': '1035'}}
        self.assertIsNone(resolve_ids(UI+'/1029304', entries))

    def test_artwork_is_only_assigned_to_exact_id_folders(self):
        for prefix in ('Characters/1029', UI, 'Marvel_LQ/'+UI, 'Plugins/MarvelGAS/UI'):
            with self.subTest(prefix=prefix):
                self.assertEqual(self.catalogue.describe(prefix+'/1029304')['thumbnail'],
                                 '/api/catalogue/thumbnail/1029304')
                self.assertIsNone(self.catalogue.describe(prefix+'/1029304/Textures'))
        self.assertIsNone(self.catalogue.describe('UI/T_1029304_Icon'))

    def test_mixed_roster_folder_shows_owner_and_costume_without_renaming(self):
        original = {'type': 'folder', 'name': '1029304', 'rel_path': UI+'/1029304'}
        result = self.catalogue.decorate(original)
        self.assertEqual(result['name'], '1029304')
        self.assertEqual(result['rel_path'], original['rel_path'])
        self.assertEqual(result['display_name'], 'Infernal Idol')
        self.assertEqual(result['context_label'], 'Magik')
        self.assertEqual(result['label'], '1029304 — Magik — Infernal Idol')
        self.assertNotIn('label', original)

    def test_nested_character_skin_uses_existing_short_id_label(self):
        result = self.catalogue.decorate({'type': 'folder', 'name': '1029304',
                                         'rel_path': 'Characters/1029/1029304'})
        self.assertEqual(result['label'], '304 — Infernal Idol')
        self.assertEqual(result['context_label'], '')

    def test_unknown_costume_uses_labelled_hero_artwork(self):
        result = self.catalogue.decorate({'type': 'folder', 'name': '1029999', 'rel_path': UI+'/1029999'})
        self.assertEqual(result['display_name'], 'Skin 999')
        self.assertEqual(result['thumbnail'], '/api/catalogue/thumbnail/1029')
        self.assertTrue(result['hero_fallback'])

    def test_known_names_work_without_images(self):
        result = self.catalogue.decorate({'type': 'folder', 'name': '1029305', 'rel_path': UI+'/1029305'})
        self.assertEqual(result['display_name'], 'Soulless Sword')
        self.assertIsNone(result['thumbnail'])
        self.assertIn('1029305', self.catalogue.identity_entries())

    def test_asset_context_keeps_filename_and_payload_fields_exact(self):
        original = {'type': 'asset', 'name': 'T_1029304_Icon', 'game_rel': 'UI/T_1029304_Icon',
                    'token': 'unchanged', 'imported': True}
        result = self.catalogue.decorate(original)
        self.assertEqual({key: result[key] for key in original}, original)
        self.assertEqual(result['char_name'], 'Magik')
        self.assertEqual(result['skin_name'], 'Infernal Idol')
        self.assertNotIn('thumbnail', result)
        self.assertEqual(result['context_label'], 'Magik · Infernal Idol')

    def test_ids_embedded_in_folder_names_get_context_without_changing_paths(self):
        original = {'type': 'folder', 'name': '1029CommonMaterial', 'rel_path': 'UI/1029CommonMaterial'}
        result = self.catalogue.decorate(original)
        self.assertEqual(result['display_name'], 'Common Material')
        self.assertEqual(result['context_label'], 'Magik')
        self.assertEqual(result['name'], original['name'])
        self.assertEqual(result['rel_path'], original['rel_path'])
        self.assertEqual(result['thumbnail'], '/api/catalogue/thumbnail/1029')

    def test_browser_metadata_contains_only_local_artwork_routes(self):
        result = self.catalogue.identity_entries()
        self.assertEqual(result['1029304']['name'], 'Infernal Idol')
        self.assertEqual(result['1029304']['hero'], '1029')
        self.assertNotIn('https:', json.dumps(result))

    @unittest.skipUnless(shutil.which('node'), 'Node is required for browser resolver parity')
    def test_python_and_browser_agree_on_all_valid_and_invalid_paths(self):
        paths = [row[0] for row in CASES] + INVALID
        program = r'''
const fs=require('fs'),vm=require('vm');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const context={window:{dispatchEvent(){} ,addEventListener(){}},document:{addEventListener(){}},CustomEvent:class{}};
vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),context);
const art=context.window.AtelierCatalogueArt;art.setIdentities({identities:input.entries});
process.stdout.write(JSON.stringify(input.paths.map(path=>art.resolveIds(path))));
'''
        process = subprocess.run(['node', '-e', program, str(ROOT/'gui/catalogue-art.js')],
                                 input=json.dumps({'entries': ENTRIES, 'paths': paths}),
                                 capture_output=True, text=True, timeout=20)
        self.assertEqual(process.returncode, 0, process.stderr)
        for path, actual in zip(paths, json.loads(process.stdout)):
            with self.subTest(path=path): self.assertEqual(actual, resolve_ids(path, ENTRIES))

    def test_real_browse_and_template_picker_use_the_same_labels(self):
        from atelier import added_assets, config, index
        from atelier.web import browse
        path = UI+'/1029304/Textures/T_Icon.uasset'
        rows = [(path, 'fixture.utoc', 'Marvel/Content/Marvel/')]
        with config.project_context(str(self.root/'project')), patch.object(index, '_INDEX', rows), \
                patch.object(browse, 'catalogue', self.catalogue), \
                patch('atelier.catalogue.catalogue', self.catalogue):
            library = browse.browse_dispatch(UI)
            picker = added_assets.browse(UI)['items']
        self.assertEqual(library[0]['label'], picker[0]['label'])
        self.assertEqual(picker[0]['display_name'], 'Infernal Idol')
        self.assertEqual(picker[0]['thumbnail'], '/api/catalogue/thumbnail/1029304')


if __name__ == '__main__': unittest.main()
