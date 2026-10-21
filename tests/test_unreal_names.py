"""Numeric asset identities have serializable FName bases and stable old indices."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from atelier.unreal_names import add_names


class UnrealNames(unittest.TestCase):
    def test_numbered_asset_and_package_get_bases_without_moving_existing_entries(self):
        names = ['OpaquePayloadName', 'None', 'Keep_17']
        doc = {'NameMap': names.copy()}
        package = '/Game/Marvel/ProjectGalacta/Meshes/1015/1015502/Feature/SK_1015_1015502'
        add_names(doc, 'SK_1015_1015502', package, 'SK_1015_1015502')
        self.assertEqual(doc['NameMap'][:len(names)], names)
        self.assertIn('SK_1015', doc['NameMap'])
        self.assertIn(package.rsplit('_', 1)[0], doc['NameMap'])
        self.assertEqual(doc['NameMap'].count('SK_1015_1015502'), 1)

    def test_zero_is_numbered_but_leading_zeros_and_out_of_range_suffixes_are_literal(self):
        doc = {}
        add_names(doc, 'Zero_0', 'Padded_07', 'Large_2147483648', 'Unicode_١', 'NoSuffix')
        self.assertEqual(doc['NameMap'], ['Zero_0', 'Zero', 'Padded_07', 'Large_2147483648', 'Unicode_١', 'NoSuffix'])


if __name__ == '__main__':
    unittest.main()
