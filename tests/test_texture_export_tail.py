"""UE5 texture trailer regressions use labelled binary exports and isolated files."""
import base64
import copy
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_data = tempfile.TemporaryDirectory(prefix='atelier-texture-tail-')
os.environ['ATELIER_DATA_DIR'] = _data.name
from atelier.handlers import custom_texture as CT

MAGIC = b'\xc1\x83\x2a\x9e'


class TextureTail(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.asset = self.root / 'T_Visor.uasset'
        self.asset.write_bytes(b'Labelled package header'.ljust(96, b'!'))
        self.none = struct.pack('<II', 3, 0)
        self.typed = b''
        format_name = struct.pack('<II', 1, 0)
        header = b'Labelled properties'.ljust(40, b'P') + struct.pack('<II', 1, 1) + format_name + struct.pack('<q', 524420-56)
        self.prefix = header.ljust(524420, b'P')
        self.raw = self.prefix + self.none + self.none
        self.asset.with_suffix('.uexp').write_bytes(self.raw + MAGIC)
        self.asset.with_suffix('.ubulk').write_bytes(b'unchanged external mips')
        self.doc = {'ObjectVersionUE5': 'DATA_RESOURCES', 'NameMap': ['A', 'PF_DXT1', 'C', 'None'],
                    'Exports': [{'$type': 'UAssetAPI.ExportTypes.Texture.TextureExport, UAssetAPI',
                        'ObjectName': 'T_Visor', 'SerialOffset': 96, 'SerialSize': len(self.raw),
                        'PixelFormat': 'DXT1', 'bCooked': True, 'bSerializeMipData': True,
                        'NoneFName': 'None', 'ExtraBytes': base64.b64encode(self.typed).decode(),
                        'Extras': base64.b64encode(self.none).decode()}]}

    def test_exact_eight_byte_mismatch_is_removed_after_validating_the_name_and_payload(self):
        self.assertEqual(len(self.raw), 524436)
        self.assertEqual(CT._duplicate_none_bytes(self.doc, str(self.asset)), 8)
        CT._preserve_export_bytes(self.doc, str(self.asset), trim_tail=8)
        export = self.doc['Exports'][0]
        data = base64.b64decode(export['Data'])
        self.assertEqual(len(data), 524428)
        self.assertEqual(data, self.prefix + self.none + self.typed)
        self.assertEqual(export['$type'], 'UAssetAPI.ExportTypes.RawExport, UAssetAPI')
        self.assertEqual(export['Extras'], '')
        self.assertEqual(self.asset.with_suffix('.uexp').read_bytes(), self.raw + MAGIC)

    def test_healthy_opaque_texture_keeps_every_byte(self):
        self.raw = self.raw[:-8]
        self.asset.with_suffix('.uexp').write_bytes(self.raw + MAGIC)
        self.doc['Exports'][0].update(SerialSize=len(self.raw))
        self.assertEqual(CT._duplicate_none_bytes(self.doc, str(self.asset)), 0)
        CT._preserve_export_bytes(self.doc, str(self.asset))
        self.assertEqual(base64.b64decode(self.doc['Exports'][0]['Data']), self.raw)

    def test_unknown_trailer_and_mismatching_bytes_are_rejected(self):
        for extras in (b'unknown!', self.none):
            with self.subTest(extras=extras):
                self.doc['Exports'][0]['Extras'] = base64.b64encode(extras).decode()
                self.asset.with_suffix('.uexp').write_bytes(self.raw[:-8] + b'unknown!' + MAGIC)
                with self.assertRaisesRegex(RuntimeError, 'unrecognized'):
                    CT._duplicate_none_bytes(self.doc, str(self.asset))

    def test_other_package_versions_and_multiple_exports_are_not_trimmed(self):
        self.doc['ObjectVersionUE5'] = 'INITIAL_VERSION'
        self.assertEqual(CT._duplicate_none_bytes(self.doc, str(self.asset)), 0)
        self.doc['ObjectVersionUE5'] = 'DATA_RESOURCES'
        self.doc['Exports'].append(copy.deepcopy(self.doc['Exports'][0]))
        self.assertEqual(CT._duplicate_none_bytes(self.doc, str(self.asset)), 0)

    def test_secondary_format_and_legitimate_json_extras_share_one_valid_extent(self):
        self.doc['NameMap'] = ['None', 'PF_DXT1']
        self.doc['Exports'][0].update(SerialSize=104, Extras=base64.b64encode(bytes(8)).decode())
        header = b'Properties'.ljust(40, b'P') + struct.pack('<II', 1, 1) + struct.pack('<IIq', 1, 0, 32)
        raw = header.ljust(80, b'P') + struct.pack('<II', 1, 1) + struct.pack('<IIq', 1, 0, 0)
        self.asset.with_suffix('.uexp').write_bytes(raw + MAGIC)
        self.assertEqual(CT._duplicate_none_bytes(self.doc, str(self.asset)), 0)
        self.asset.with_suffix('.uexp').write_bytes(raw + bytes(8) + MAGIC)
        self.doc['Exports'][0]['SerialSize'] += 8
        self.assertEqual(CT._duplicate_none_bytes(self.doc, str(self.asset)), 8)

    def test_invalid_ranges_and_missing_package_tag_fail_before_publication(self):
        doc = copy.deepcopy(self.doc)
        doc['Exports'][0]['SerialOffset'] = 95
        with self.assertRaisesRegex(RuntimeError, 'texture'):
            CT._preserve_export_bytes(doc, str(self.asset), trim_tail=8)
        self.asset.with_suffix('.uexp').write_bytes(self.raw + b'bad!')
        with self.assertRaisesRegex(RuntimeError, 'texture'):
            CT._preserve_export_bytes(copy.deepcopy(self.doc), str(self.asset), trim_tail=8)

    def native(self, args, corrupt=False):
        if args[0] == 'to_json':
            doc = copy.deepcopy(self.doc)
            raw = Path(args[1]).with_suffix('.uexp').read_bytes()[:-4]
            doc['Exports'][0].update(SerialSize=len(raw), Extras=base64.b64encode(self.none).decode() if raw.endswith(self.none + self.typed + self.none) else '')
            Path(args[3], self.asset.stem + '.json').write_text(json.dumps(doc))
        else:
            self.assertEqual(args[0], 'from_json')
            doc = json.loads(Path(args[1]).read_text())
            output = Path(args[2]); output.write_bytes(self.asset.read_bytes())
            data = base64.b64decode(doc['Exports'][0]['Data'])
            output.with_suffix('.uexp').write_bytes(data + (b'bad!' if corrupt else MAGIC))
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    def test_staged_repair_is_idempotent_and_preserves_bulk_data(self):
        with patch.object(CT, 'uat', side_effect=self.native):
            self.assertTrue(CT.repair_export_tail(str(self.asset), self.root / 'repair'))
            self.assertFalse(CT.repair_export_tail(str(self.asset), self.root / 'recheck'))
        self.assertEqual(self.asset.with_suffix('.uexp').read_bytes(), self.raw[:-8] + MAGIC)
        self.assertEqual(self.asset.with_suffix('.ubulk').read_bytes(), b'unchanged external mips')

    def test_bad_native_rebuild_preserves_both_staged_package_files(self):
        before = [self.asset.read_bytes(), self.asset.with_suffix('.uexp').read_bytes()]
        with patch.object(CT, 'uat', side_effect=lambda args: self.native(args, corrupt=True)):
            with self.assertRaisesRegex(RuntimeError, 'safely repair'):
                CT.repair_export_tail(str(self.asset), self.root / 'repair')
        self.assertEqual([self.asset.read_bytes(), self.asset.with_suffix('.uexp').read_bytes()], before)


if __name__ == '__main__':
    try:
        unittest.main()
    finally:
        _data.cleanup()
