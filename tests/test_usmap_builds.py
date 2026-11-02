"""Mapping age checks use filenames only, without reading game containers."""
import atexit
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
data = tempfile.TemporaryDirectory(prefix='atelier-mapping-builds-')
os.environ['ATELIER_DATA_DIR'] = data.name
from atelier import config as C
from atelier.web import routes as R
atexit.register(lambda: (R.shutdown(5), data.cleanup()))


class MappingBuilds(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='atelier-paks-')
        self.addCleanup(temporary.cleanup)
        self.paks = Path(temporary.name) / '[Game]'
        self.paks.mkdir()
        for name in ('PAKS', 'USMAP'):
            patcher = patch.object(C, name, str(self.paks) if name == 'PAKS' else '5.3.2-3962284+++Marvel.usmap')
            patcher.start(); self.addCleanup(patcher.stop)

    def container(self, name):
        (self.paks / name).touch()

    def test_container_names_parse_only_versioned_game_utocs(self):
        for name, expected in (
            ('Patch_-Windows_1.1.3984769_P.utoc', 3984769),
            ('pakchunkCharacter-Windows_1.2.4000000.utoc', 4000000),
            ('PATCH_-WINDOWS_1.1.3984769_P.UTOC', 3984769),
            ('C:\\Game\\Patch_-Windows_1.1.3984769_P.utoc', 3984769),
            ('pakchunkCharacter-Windows.utoc', -1),
            ('Patch_-Windows_20261029_P.utoc', -1),
            ('Patch_-Windows_1.1.bad_P.utoc', -1),
            ('Patch_-Windows_1.1.3984769_P.ucas', -1),
            ('!ProjectGalacta_9999999_P.utoc', -1),
            ('MyMod-Windows_1.1.9999999_P.utoc', -1),
        ):
            with self.subTest(name=name): self.assertEqual(C._pak_build(name), expected)

    def test_highest_build_is_numeric_and_ignores_mods_and_directories(self):
        for name in ('Patch_-Windows_1.1.999999_P.utoc', 'Patch_-Windows_1.1.1000000_P.utoc',
                     '!ProjectGalacta_9999999_P.utoc'):
            self.container(name)
        (self.paks / 'Patch_-Windows_1.1.99999999_P.utoc').mkdir()
        mods = self.paks / '~mods'; mods.mkdir()
        (mods / 'Patch_-Windows_1.1.9999999_P.utoc').touch()
        self.assertEqual(C._game_build(), 1000000)

    def test_mapping_build_parser(self):
        self.assertEqual(C._usmap_build('5.3.2-3984769+++Marvel.usmap'), 3984769)
        for name in ('', 'latest.usmap', '5.3.2-bad+++Marvel.usmap'):
            with self.subTest(name=name): self.assertEqual(C._usmap_build(name), -1)

    def test_stale_mapping_warns_without_blocking_other_work(self):
        self.container('Patch_-Windows_1.1.3984769_P.utoc')
        warnings = [(level, message) for level, message in C._prereq_issues(False) if 'mapping file is for' in message]
        self.assertEqual(len(warnings), 1)
        level, message = warnings[0]
        self.assertEqual(level, 'warning')
        self.assertIn('3962284', message); self.assertIn('3984769', message)
        self.assertIn("Colour edits can't be saved", message)
        self.assertIn('Restart Atelier', message)

    def test_missing_equal_newer_and_unparseable_builds_do_not_warn(self):
        self.assertIsNone(C._stale_usmap_builds())
        self.container('Patch_-Windows_1.1.3984769_P.utoc')
        for mapping in ('', 'latest.usmap', '5.3.2-3984769+++Marvel.usmap', '5.3.2-4000000+++Marvel.usmap'):
            with self.subTest(mapping=mapping), patch.object(C, 'USMAP', mapping):
                self.assertIsNone(C._stale_usmap_builds())
                self.assertFalse(any('mapping file is for' in msg for _, msg in C._prereq_issues(False)))
        with patch.object(C, 'PAKS', str(self.paks / 'missing')):
            self.assertEqual(C._game_build(), -1)

    def check_update(self, stale, running=False):
        with patch.object(C, 'get_usmap_checked_at', return_value=time.time()), \
             patch.object(C, '_stale_usmap_builds', return_value=(3962284, 3984769) if stale else None), \
             patch.object(R, '_usmap_check_running', running), patch.object(R.threading, 'Thread') as thread:
            result = json.loads(R.api_usmap_update_check())
            return result, thread.call_count

    def test_stale_mapping_bypasses_recent_check(self):
        result, threads = self.check_update(True)
        self.assertTrue(result['checking']); self.assertEqual(threads, 1)

    def test_current_mapping_keeps_recent_check(self):
        result, threads = self.check_update(False)
        self.assertFalse(result['updated']); self.assertEqual(threads, 0)

    def test_stale_mapping_does_not_start_duplicate_worker(self):
        result, threads = self.check_update(True, running=True)
        self.assertTrue(result['checking']); self.assertEqual(threads, 0)


if __name__ == '__main__':
    unittest.main()
