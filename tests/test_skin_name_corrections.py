"""Tests for the verified, ID-based Marvel Rivals costume name corrections."""
import unittest
import sys
from pathlib import Path
import tempfile
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from atelier.skin_name_fixes import correct_skin_name


class SkinNameCorrectionTests(unittest.TestCase):
    def test_cyclops_upstream_typo(self):
        self.assertEqual(correct_skin_name('1063100', 'SHADOWED NEMESIS'), 'Shadowed Gaze')

    def test_unrelated_skin(self):
        self.assertEqual(correct_skin_name('1011001', 'Default'), 'Default')

    def test_catalogue_updates_names_and_preserves_the_offline_reference(self):
        from atelier.catalogue import catalogue
        from atelier.handlers import skinnames
        from atelier.web import browse
        from atelier.starsong import API

        original = '| 1063 | Old hero name | 1063100 | Old name |\n| | | 1063301 | Offline costume |\n'
        active = {'revision': '1.1.4066382:1', 'entries': {
            '1063': {'kind': 'hero', 'name': 'Cyclops', 'source': API},
            '1063100': {'kind': 'skin', 'name': 'Shadowed Gaze', 'source': API},
        }}
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'MarvelRivalsCharacterIDs.md'
            source.write_text(original, encoding='utf-8')
            with patch.object(catalogue, 'data', active), patch.object(skinnames, '_md_path', return_value=source):
                self.assertEqual(browse.char_name('1063'), 'Cyclops')
                self.assertEqual(browse.skin_name('1063100'), 'Shadowed Gaze')
                self.assertEqual(browse.skin_name('1063301'), 'Offline costume')
                self.assertEqual(skinnames.label_for('1063100'), 'Shadowed Gaze')
                self.assertEqual(source.read_text(encoding='utf-8'), original)


if __name__ == '__main__':
    unittest.main()
