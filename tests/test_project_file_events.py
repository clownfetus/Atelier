"""Project settings/backups never masquerade as externally changed edited assets."""
import atexit
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_data = tempfile.TemporaryDirectory(prefix='atelier-file-events-')
os.environ['ATELIER_DATA_DIR'] = _data.name
from atelier.web import routes as R


def cleanup():
    R.shutdown(5)
    _data.cleanup()


atexit.register(cleanup)


class ProjectFileEvents(unittest.TestCase):
    def setUp(self):
        self.root = Path(_data.name, 'project')
        self.handler = R._PNGHandler()
        self.scope = patch.object(R, 'get_import_root', return_value=str(self.root))
        self.scope.start()
        self.addCleanup(self.scope.stop)
        self.events = patch.object(R, '_push_sse')
        self.push = self.events.start()
        self.addCleanup(self.events.stop)

    def event(self, relative):
        return SimpleNamespace(is_directory=False, src_path=str(self.root / relative))

    def test_metadata_and_backup_deletes_do_not_refresh_the_asset_list(self):
        for name in ('.atelier/project.json', '.atelier/backups/MI_Body.json', '.atelier-trash/deleted/MI_Body.json'):
            with self.subTest(name=name):
                self.handler.on_deleted(self.event(name))
                self.push.assert_not_called()

    def test_modified_backup_images_do_not_report_texture_edits(self):
        self.handler.on_modified(self.event('.atelier/backups/T_Body.png'))
        self.push.assert_not_called()

    def test_real_asset_deletion_still_refreshes_the_list(self):
        self.handler.on_deleted(self.event('Fixture/MI_Body.json'))
        self.push.assert_called_once_with({'asset_removed': True})

    def test_real_external_texture_edits_still_reach_the_ui(self):
        self.handler.on_modified(self.event('Fixture/T_Body.png'))
        self.push.assert_called_once_with({'file_changed': True,
                                          'token': R.token('Fixture/T_Body'), 'game_rel': 'Fixture/T_Body'})

    def test_project_location_can_itself_be_named_like_a_metadata_directory(self):
        self.root = Path(_data.name, '.atelier', 'project')
        with patch.object(R, 'get_import_root', return_value=str(self.root)):
            self.handler.on_modified(self.event('Fixture/T_Elsewhere.png'))
            self.handler.on_deleted(self.event('Fixture/MI_Elsewhere.json'))
        self.assertEqual(self.push.call_count, 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
