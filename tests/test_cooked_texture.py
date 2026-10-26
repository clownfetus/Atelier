"""Labelled UE5 resources: streamed top mip, inline tail and six-face LDR cubes."""
import atexit
import copy
import os
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
environment = tempfile.TemporaryDirectory(prefix='atelier-cooked-textures-')
atexit.register(environment.cleanup)
os.environ['ATELIER_DATA_DIR'] = environment.name
from atelier.handlers import cooked_texture as C, hdr_texture as H, meshimages, texture


class CookedTextures(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root/'T_Labelled'
        self.output = self.root/'decoded.png'

    def fixture(self, *, cube=False, streamed=False, fmt='DXT1', width=8, count=2):
        self.base.with_suffix('.uasset').write_bytes(b'Labelled package header'.ljust(128, b'!'))
        names = ['None', 'PF_'+fmt]
        prefix = b'Labelled texture properties'.ljust(32, b'P')
        raw = bytearray(prefix + struct.pack('<IIq', 1, 0, 0) + bytes(16))
        format_bytes = ('PF_'+fmt+'\0').encode()
        raw += struct.pack('<iiIi', width, width, 0x80000006 if cube else 1, len(format_bytes))
        raw += format_bytes + struct.pack('<ii', 0, count)
        resources, pixels, indices, dimensions = [], [], [], []
        for level in range(count):
            size = max(1, width >> level)
            # All-red BC1 blocks decode independently of the resource parser.
            block = struct.pack('<HHI', 0xf800, 0xf800, 0) if fmt == 'DXT1' else bytes([64+level])*16
            face = block * (((size+3)//4)**2)
            payload = face * (6 if cube else 1)
            if cube and fmt == 'DXT1':
                colours = (0xf800, 0x07e0, 0x001f, 0xffe0, 0x07ff)
                faces = [struct.pack('<HHI', colour, colour, 0) * (((size+3)//4)**2) for colour in colours]
                faces.append(struct.pack('<HHI', 0, 0xffff, 0xffffffff) * (((size+3)//4)**2))
                payload = b''.join(faces)
            pixels.append(payload)
            indices.append(len(raw))
            raw += struct.pack('<i', level)
            resource = {'SerialOffset': len(raw), 'SerialSize': len(payload), 'RawSize': len(payload),
                        'LegacyBulkDataFlags': 72}
            if streamed and level == 0:
                resource.update(SerialOffset=0, LegacyBulkDataFlags=0x10501)
                self.base.with_suffix('.ubulk').write_bytes(payload)
            else:
                raw += payload
            dimensions.append(len(raw))
            raw += struct.pack('<iii', size, size, 1)
            resources.append(resource)
        raw += bytes(4)
        struct.pack_into('<q', raw, len(prefix)+8, len(raw)-len(prefix)-8)
        raw += bytes(8) + b'\xc1\x83\x2a\x9e'
        self.base.with_suffix('.uexp').write_bytes(raw)
        document = {'ObjectVersionUE5': 'DATA_RESOURCES', 'NameMap': names,
                    'Imports': [{'ObjectName': 'TextureCube' if cube else 'Texture2D'}],
                    'Exports': [{'ClassIndex': -1, 'SerialOffset': 128, 'SerialSize': len(raw)-4}],
                    'DataResources': resources}
        return document, pixels, indices, dimensions

    def test_streamed_bc7_top_and_inline_tail_keep_their_own_offsets(self):
        document, pixels, _, _ = self.fixture(streamed=True, fmt='BC7')
        recovered = C.read_cooked(document, self.base)
        self.assertEqual((recovered['format'], recovered['faces']), ('BC7', 1))
        self.assertEqual([m['data'] for m in recovered['mips']], pixels)
        self.assertEqual([(m['width'], m['height']) for m in recovered['mips']], [(8, 8), (4, 4)])

    def test_missing_external_top_mip_keeps_the_complete_inline_mip(self):
        document, pixels, _, _ = self.fixture(streamed=True)
        self.base.with_suffix('.ubulk').unlink()
        recovered = C.read_cooked(document, self.base)
        self.assertIsNone(recovered['mips'][0]['data'])
        self.assertEqual(recovered['mips'][1]['data'], pixels[1])
        with patch.object(H, 'document', return_value=document):
            self.assertTrue(C.decode_png(self.base, self.output))
        with Image.open(self.output) as image:
            self.assertEqual(image.size, (4, 4))
            self.assertEqual(image.getpixel((0, 0)), (255, 0, 0, 255))

    def test_recovered_png_keeps_the_largest_shipped_mip_and_exact_bc1_colour(self):
        document, _, _, _ = self.fixture(streamed=True)
        with patch.object(H, 'document', return_value=document):
            self.assertTrue(C.decode_png(self.base, self.output))
        with Image.open(self.output) as image:
            self.assertEqual(image.size, (8, 8))
            self.assertEqual(image.getextrema(), ((255, 255), (0, 0), (0, 0), (255, 255)))

    def test_ldr_cube_mips_retain_six_faces_and_cannot_become_a_2d_png(self):
        document, pixels, _, _ = self.fixture(cube=True)
        recovered = C.read_cooked(document, self.base)
        self.assertEqual(recovered['faces'], 6)
        self.assertEqual([m['data'] for m in recovered['mips']], pixels)
        with patch.object(H, 'document', return_value=document):
            self.assertFalse(C.decode_png(self.base, self.output))
        self.assertFalse(self.output.exists())

    def test_invalid_resource_metadata_is_refused_without_replacing_an_existing_image(self):
        original, _, _, _ = self.fixture()
        self.output.write_bytes(b'previous artist image')
        mutations = [lambda d: d['Exports'][0].update(SerialSize=9999),
                     lambda d: d['DataResources'][0].update(SerialOffset=1),
                     lambda d: d['DataResources'][0].update(RawSize=1),
                     lambda d: d['DataResources'][0].update(LegacyBulkDataFlags=999),
                     lambda d: d['DataResources'][0].update(SerialSize=8, RawSize=8)]
        for mutate in mutations:
            document = copy.deepcopy(original)
            mutate(document)
            with self.subTest(document=document), patch.object(H, 'document', return_value=document):
                with self.assertRaises(ValueError):
                    C.decode_png(self.base, self.output)
            self.assertEqual(self.output.read_bytes(), b'previous artist image')

    def test_truncated_streamed_payload_is_refused(self):
        document, _, _, _ = self.fixture(streamed=True)
        self.base.with_suffix('.ubulk').write_bytes(b'too short')
        with self.assertRaisesRegex(ValueError, 'streamed.*range'):
            C.read_cooked(document, self.base)

    def test_mip_dimensions_and_resource_indices_are_checked(self):
        for mutation in ('dimensions', 'duplicate', 'out-of-range', 'virtual'):
            document, _, indices, dimensions = self.fixture()
            raw = bytearray(self.base.with_suffix('.uexp').read_bytes())
            if mutation == 'dimensions':
                struct.pack_into('<i', raw, dimensions[1], 256)
            elif mutation == 'duplicate':
                struct.pack_into('<i', raw, indices[1], 0)
            elif mutation == 'out-of-range':
                struct.pack_into('<i', raw, indices[0], 99)
            else:
                struct.pack_into('<i', raw, len(raw)-16, 1)
            self.base.with_suffix('.uexp').write_bytes(raw)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                C.read_cooked(document, self.base)

    def test_unsupported_package_keeps_the_existing_decoder_path(self):
        document, _, _, _ = self.fixture()
        document['ObjectVersionUE5'] = 'UNSUPPORTED'
        self.assertIsNone(C.read_cooked(document, self.base))

    def test_ldr_cube_does_not_enter_the_hdr_replacement_reader(self):
        document, _, _, _ = self.fixture(cube=True)
        document['Exports'][0]['PlatformData'] = {'PixelFormat': 'PF_DXT1'}
        with patch.object(H, 'candidate', return_value=True), patch.object(H, 'document', return_value=document), \
                patch.object(H, 'read_cooked', side_effect=AssertionError('not an HDR template')):
            self.assertFalse(H.extract_files(str(self.root/'unused'), self.base))

    def test_cube_converter_receives_every_face_and_a_float_output_format(self):
        document, pixels, _, _ = self.fixture(cube=True, fmt='BC6H')
        tools = self.root/'Tools'; tools.mkdir(); (tools/'texconv.exe').write_bytes(b'fixture')
        captured = []
        def read(args):
            import json
            target = Path(args[-1]); target.mkdir(exist_ok=True)
            (target/(self.base.name+'.json')).write_text(json.dumps(document))
            return SimpleNamespace(returncode=0)
        def convert(args, **kwargs):
            source = Path(args[-1]); dds = source.read_bytes()
            captured.append((struct.unpack_from('<II', dds, 12), dds[148:], args))
            source.with_suffix('.hdr').write_bytes(b'converted six-face image')
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        with patch.object(meshimages.config, 'TOOLS', str(tools)), patch.object(meshimages, 'uat', side_effect=read), \
                patch.object(meshimages.hostos, 'run_exe', side_effect=convert):
            result = meshimages.recover_inline_hdr(str(self.base), str(self.root/'cube'))
        self.assertEqual(captured[0][0], (48, 8))
        self.assertEqual(captured[0][1], pixels[0])
        self.assertIn('R32G32B32A32_FLOAT', captured[0][2])
        self.assertTrue(result['readonly'])
        self.assertEqual(result['layout'], 'cubemap_strip')

    def test_ldr_cube_input_keeps_all_face_colours_and_alpha_without_an_hdr_converter(self):
        document, _, _, _ = self.fixture(cube=True)
        def read(args):
            import json
            target = Path(args[-1]); target.mkdir(exist_ok=True)
            (target/(self.base.name+'.json')).write_text(json.dumps(document))
            return SimpleNamespace(returncode=0)
        with patch.object(meshimages, 'uat', side_effect=read), \
                patch.object(meshimages.hostos, 'run_exe', side_effect=AssertionError('LDR needs no HDR conversion')):
            result = meshimages.recover_inline_hdr(str(self.base), str(self.root/'cube'))
        self.assertTrue(result['readonly'])
        self.assertTrue(result['path'].endswith('.tga'))
        with Image.open(result['path']) as image:
            self.assertEqual(image.size, (8,48))
            self.assertEqual([image.getpixel((0,8*face)) for face in range(6)],
                [(255,0,0,255),(0,255,0,255),(0,0,255,255),(255,255,0,255),(0,255,255,255),(0,0,0,0)])

    def test_regular_png_decode_uses_recovery_only_after_a_native_failure(self):
        document, _, _, _ = self.fixture()
        with patch.object(texture, '_decode_png_file', return_value=False), patch.object(H, 'document', return_value=document):
            texture.decode_png(str(self.root/'fallback'), str(self.base))
        self.assertEqual(Image.open(self.root/'fallback.png').size, (8, 8))
        with patch.object(texture, '_decode_png_file', return_value=True), \
                patch.object(C, 'decode_png', side_effect=AssertionError('native succeeded')):
            texture.decode_png(str(self.root/'native'), str(self.base))


if __name__ == '__main__':
    unittest.main(verbosity=2)
