"""Tests for the verified, ID-based Marvel Rivals costume name corrections."""
import unittest
import sys
from pathlib import Path
import io
import tempfile
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from atelier.skin_name_fixes import correct_skin_name, merge_reference


class SkinNameCorrectionTests(unittest.TestCase):
    def test_cyclops_upstream_typo(self):
        self.assertEqual(correct_skin_name('1063100', 'SHADOWED NEMESIS'), 'Shadowed Gaze')

    def test_unrelated_skin(self):
        self.assertEqual(correct_skin_name('1011001', 'Default'), 'Default')

    def test_merge_updates_old_names_and_preserves_missing_rows(self):
        old = {'1063': {'name': 'Cyclops', 'skins': {
            '1063100': 'Shadowed Nemesis', '1063301': 'Phoenix Cyclops'}}}
        fresh = {'1063': {'name': 'Cyclops', 'skins': {
            '1063100': 'SHADOWED NEMESIS', '1063101': 'Futuristic Focus'}}}
        merged, count = merge_reference(old, fresh)
        self.assertEqual(merged['1063']['skins']['1063100'], 'Shadowed Gaze')
        self.assertEqual(merged['1063']['skins']['1063301'], 'Phoenix Cyclops')
        self.assertEqual(merged['1063']['skins']['1063101'], 'Futuristic Focus')
        self.assertEqual(count, 2)
        self.assertEqual(old['1063']['skins']['1063100'], 'Shadowed Nemesis')

    def test_empty_response_rejected(self):
        with self.assertRaises(ValueError): merge_reference({}, {})

    def test_cross_character_skin_id_rejected(self):
        payload = {'1063': {'name': 'Cyclops', 'skins': {
            '1063100': 'SHADOWED NEMESIS', '1099100': 'wrong hero'}}}
        updated, _ = merge_reference({}, payload)
        self.assertNotIn('1099100', updated['1063']['skins'])

    def test_renamed_reference_and_offline_entries_survive_restart(self):
        from atelier.web import browse
        original={'1063':{'name':'Cyclops','skins':{'1063100':'Old name','1063301':'Offline costume'}}}
        incoming=b'| 1063 | Cyclops | 1063100 | SHADOWED NEMESIS |\n'
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve()
            with patch.object(browse,'TOOLS',str(root)),patch.object(browse,'_CHAR_DATA',original), \
                 patch.object(browse,'_update_callback',None), \
                 patch.object(browse.urllib.request,'urlopen',return_value=io.BytesIO(incoming)):
                browse._fetch_char_data()
                restarted=browse._parse_char_md()
                self.assertEqual(restarted['1063']['skins'],{'1063100':'Shadowed Gaze','1063301':'Offline costume'})
                self.assertEqual(original['1063']['skins']['1063100'],'Old name')


if __name__ == '__main__':
    unittest.main()
