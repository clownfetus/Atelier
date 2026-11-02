"""Library Home exposes useful content without removing folders from the underlying tree."""
import atexit
from contextlib import ExitStack
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
        self.assertEqual(self.folders('Helpers'), {'Helpers/Blueprints'})

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


if __name__ == '__main__':
    unittest.main(verbosity=2)
