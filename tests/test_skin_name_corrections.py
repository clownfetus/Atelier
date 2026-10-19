"""Tests for the verified, ID-based Marvel Rivals costume name corrections."""
import unittest
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


if __name__ == '__main__':
    unittest.main()
