"""The Library shows a folder only when it leads to something to list or holds project work."""
import atexit
from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_data = tempfile.TemporaryDirectory(prefix='atelier-home-')
os.environ['ATELIER_DATA_DIR'] = _data.name
atexit.register(_data.cleanup)
from atelier import config as C, search as S
from atelier.catalogue import catalogue
from atelier.web import browse as B


class LibraryHome(unittest.TestCase):
    def setUp(self):
        self.entries = [
            ('Characters/1029/1029001/Materials/MI_Body.uasset', 'fixture.utoc', 'Marvel/Content/Marvel/'),
            ('Helpers/Blueprints/BP_Hidden.uasset', 'fixture.utoc', 'Marvel/Content/Marvel/'),
            ('Audio/SC_Unlisted.uasset', 'fixture.utoc', 'Marvel/Content/Marvel/'),
            ('Textures/Icons/PlainName.uasset', 'fixture.utoc', 'Marvel/Content/Marvel/'),
        ]
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(B, 'ensure_index', side_effect=lambda: self.entries))
        stack.enter_context(patch('atelier.index.ensure_index', side_effect=lambda: self.entries))
        self.maps = stack.enter_context(patch('atelier.handlers.world.list_maps', return_value=[]))
        self.added = stack.enter_context(patch('atelier.added_assets.library_items', return_value=[]))

    def folders(self, path=''):
        return {item['rel_path'] for item in B.browse_dispatch(path) if item['type'] == 'folder'}

    def test_home_hides_folders_without_browsable_assets_and_empty_curated_sections(self):
        self.assertEqual(self.folders(), {'Characters', 'Textures'})
        self.assertEqual(B.browse_dispatch('Helpers'), [])

    def test_curated_sections_appear_only_when_their_content_exists(self):
        self.entries = self.entries + [
            ('UI/Textures/Show/NameplateFrame/T_Plate.uasset', 'fixture.utoc', 'Marvel/Content/Marvel/'),
            ('Data/StringTable/Fixture_ST.uasset', 'fixture.utoc', 'Marvel/Content/Marvel/'),
        ]
        self.maps.return_value = ['FixtureMap']
        self.assertTrue({'Nameplates', 'Maps', 'Text'}.issubset(self.folders()))
        plates = B.browse_dispatch('Nameplates')
        self.assertEqual(len(plates), 3)
        self.assertEqual(sum('not in your paks' in item['label'] for item in plates), 2)

    def test_project_added_folders_survive_even_when_the_game_has_no_assets_in_them(self):
        self.added.return_value = [{'type': 'folder', 'name': 'My assets', 'label': 'My assets', 'rel_path': 'My assets'}]
        self.assertIn('My assets', self.folders())

    def test_a_rebuilt_index_updates_home_content(self):
        self.assertNotIn('Helpers', self.folders())
        self.entries = self.entries + [('Helpers/T_Preview.uasset', 'fixture.utoc', 'Marvel/Content/Marvel/')]
        self.assertIn('Helpers', self.folders())
        self.entries = self.entries[:1]
        self.assertEqual(self.folders(), {'Characters'})

    def test_map_availability_reads_the_map_directory_without_loading_assets(self):
        from atelier.handlers import world
        self.maps.side_effect = lambda: sorted(world._enum())
        with patch.object(world, '_MAPS', None), \
             patch.object(world, 'dir_glob', return_value=['fixture.utoc']), \
             patch.object(world.io_lib, 'parse_toc', return_value=object()), \
             patch.object(world.io_lib, 'parse_dir_index', return_value=[
                 ('../../../Marvel/Content/Marvel/Maps/FixtureMap/Lighting.umap', None)]):
            self.assertIn('Maps', self.folders())
            self.assertEqual(self.folders('Maps'), {'Maps/FixtureMap'})


SKIN = 'Characters/1029/1029001'
LISTED = (
    SKIN + '/Materials/MI_Body',
    SKIN + '/Mixed/Inner/Deep/T_Deep',
    'Characters/1030/1030001/Textures/PlainName',   # listed by the folder it sits in, not its name
    'UI/Mixed/T_Here',
    'UI/Textures/PlainName',
    'ui/casing/T_Lower',
    'Marvel_LQ/UI/T_Low',
)
UNLISTED = (
    SKIN + '/Cues/1029/GC_Hit',
    SKIN + '/Animations/A_Idle',
    SKIN + '/Mixed/BP_Helper',
    SKIN + '/Odd/Textures',                         # named like the folder rule, but it is a file
    'Characters/1029/1029CommonMaterial/M_Parent',
    'Characters/1031/1031001/Cues/GC_Only',
    'UI/Blueprints/Deep/Deeper/BP_Widget',
    'UI/Mixed/Only/BP_Widget',
    'Audio/SC_Unlisted',
    'Marvel_LQ/Audio/SC_Low',
)


def entry(path):
    return (path + '.uasset', 'fixture.utoc', 'Marvel/Content/Marvel/')


class EmptyFolders(unittest.TestCase):
    def setUp(self):
        self.entries = [entry(path) for path in LISTED + UNLISTED]
        temporary = tempfile.TemporaryDirectory(prefix='atelier-home-project-')
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(C.project_context(str(self.project)))
        stack.enter_context(patch.object(B, 'ensure_index', side_effect=lambda: self.entries))
        stack.enter_context(patch('atelier.index.ensure_index', side_effect=lambda: self.entries))
        stack.enter_context(patch('atelier.handlers.world.list_maps', return_value=[]))

    def names(self, path=''):
        return {item['name'] for item in B.browse_dispatch(path) if item['type'] == 'folder'}

    def keep(self, game_rel, ext='.png'):
        path = self.project / (game_rel + ext)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{}' if ext == '.json' else '')

    def add(self, game_rel):
        path = self.project / (game_rel + '.asset.json')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'version': 1, 'id': '0' * 32, 'file_type': 'texture'}))

    def test_a_folder_needs_a_listed_asset_beneath_it_at_any_depth(self):
        self.assertEqual(self.names(), {'Characters', 'UI', 'Marvel_LQ'})
        self.assertEqual(self.names('Characters'), {'1029', '1030'})
        self.assertEqual(self.names('Characters/1029'), {'1029001'})
        self.assertEqual(self.names('UI'), {'Mixed', 'Textures', 'casing'})
        self.assertEqual([item['name'] for item in B.browse_dispatch('UI/Mixed')], ['T_Here'])

    def test_skin_levels_follow_the_same_rule(self):
        self.assertEqual(self.names(SKIN), {'Materials', 'Mixed'})
        self.assertEqual([item['name'] for item in B.browse_dispatch(SKIN + '/Mixed')], ['Inner'])
        self.assertEqual(self.names('Characters/1030/1030001'), {'Textures'})

    def test_every_visible_folder_leads_to_an_asset_and_every_listed_asset_is_reachable(self):
        assets, pending, visited = set(), [''], []
        while pending:
            path = pending.pop()
            items = B.browse_dispatch(path)
            if path:
                self.assertTrue(items, path + ' opened empty')
                visited.append(path)
            pending += [item['rel_path'] for item in items if item['type'] == 'folder']
            assets |= {item['game_rel'].casefold() for item in items if item['type'] == 'asset'}
        self.assertEqual(assets, {path.casefold() for path in LISTED})
        self.assertEqual({path.casefold() for path in visited},
                         {parent.casefold() for path in LISTED
                          for parent in (path.rsplit('/', depth)[0] for depth in range(1, path.count('/') + 1))})

    def test_a_link_to_a_hidden_folder_opens_empty_rather_than_failing(self):
        # Pins and history keep paths the Library no longer offers; each must still answer.
        for path in ('Audio', 'UI/Blueprints', 'UI/Blueprints/Deep/Deeper', 'UI/Mixed/Only',
                     'Characters/1029/1029CommonMaterial', 'Characters/1031', 'Characters/1031/1031001',
                     SKIN + '/Cues', SKIN + '/Cues/1029', SKIN + '/Odd', 'Marvel_LQ/Audio'):
            with self.subTest(path=path):
                self.assertEqual(B.browse_dispatch(path), [])

    def test_paths_match_whatever_their_case(self):
        self.assertEqual(self.names('ui'), {'Mixed', 'Textures', 'casing'})
        self.assertEqual(self.names('CHARACTERS/1029/1029001'), {'Materials', 'Mixed'})
        self.assertEqual([item['name'] for item in B.browse_dispatch('UI/CASING')], ['T_Lower'])

    def test_low_quality_twins_keep_their_labelled_root_when_they_have_content(self):
        root = {item['name']: item['label'] for item in B.browse_dispatch('')}
        self.assertIn('low-quality twin', root['Marvel_LQ'])
        self.assertEqual(self.names('Marvel_LQ'), {'UI'})
        self.entries = [item for item in self.entries if not item[0].startswith('Marvel_LQ/UI/')]
        self.assertNotIn('Marvel_LQ', self.names())

    def test_an_imported_copy_keeps_its_folders_visible_at_every_level(self):
        self.keep('UI/Blueprints/Deep/Deeper/BP_Widget', '.json')
        self.assertIn('Blueprints', self.names('UI'))
        self.assertEqual(self.names('UI/Blueprints'), {'Deep'})
        self.assertEqual(self.names('UI/Blueprints/Deep'), {'Deeper'})
        self.keep(SKIN + '/Cues/1029/T_Retired')
        self.assertIn('Cues', self.names(SKIN))
        self.assertEqual(self.names(SKIN + '/Cues'), {'1029'})
        self.keep('Audio/T_Retired')
        self.assertIn('Audio', self.names())

    def test_a_kept_folder_keeps_its_friendly_label(self):
        self.keep('Characters/1031/1031001/Cues/T_Retired')
        heroes = {item['name']: item['label'] for item in B.browse_dispatch('Characters')}
        self.assertTrue(heroes['1031'].startswith('1031 — '), heroes['1031'])

    def test_a_directory_the_project_has_emptied_does_not_count(self):
        (self.project / 'UI/Blueprints/Deep/Deeper').mkdir(parents=True)
        self.assertEqual(self.names('UI'), {'Mixed', 'Textures', 'casing'})

    def test_an_added_asset_keeps_its_folders_and_is_listed(self):
        self.add('UI/Blueprints/T_New')
        self.assertIn('Blueprints', self.names('UI'))
        self.assertIn('T_New', {item['name'] for item in B.browse_dispatch('UI/Blueprints')})
        self.add('MyAssets/Sub/T_Own')
        self.assertIn('MyAssets', self.names())
        self.assertEqual(self.names('MyAssets'), {'Sub'})

    def test_the_tree_is_walked_once_per_index(self):
        B.browse_dispatch('')
        first = B._home_content()[0]
        with patch.object(B, '_classify_file', side_effect=AssertionError('walked the index again')):
            self.assertEqual(self.names(), {'Characters', 'UI', 'Marvel_LQ'})
            self.assertEqual(self.names('Characters/1029'), {'1029001'})
        self.assertIs(B._home_content()[0], first)
        self.entries = self.entries + [entry('Audio/T_New')]
        self.assertIn('Audio', self.names())
        self.assertIsNot(B._home_content()[0], first)

    def test_search_still_finds_the_same_folders_and_assets(self):
        with patch.object(catalogue, 'data', {'entries': {}}):
            # Same definition as the Library, so a folder result can never be a hidden folder.
            folders = S._table_for(self.entries, {'entries': {}})[2]
            self.assertEqual({path.lower() for path in folders}, B._home_content()[0])
            self.assertEqual([row['path'] for row in S.search('Inner')['folders']],
                             [SKIN + '/Mixed/Inner', SKIN + '/Mixed/Inner/Deep'])
            self.assertEqual(S.search('Blueprints')['totals']['folders'], 0)
            self.assertEqual([row['game_rel'] for row in S.search('T_Deep')['assets']],
                             [SKIN + '/Mixed/Inner/Deep/T_Deep'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
