"""HDR cubemap range, face ordering, layouts and cooked resource-table validation."""
import copy
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from atelier.handlers import hdr_texture as H


def pixels(size=8):
    value = np.ones((6, size, size, 4), dtype=np.float32)
    for face in range(6): value[face, ..., :3] = (face+1)*2
    return value


def radiance(image):
    image = np.asarray(image, dtype=np.float32)[..., :3]
    maximum = image.max(axis=-1)
    _mantissa, exponent = np.frexp(maximum)
    scale = np.ldexp(np.ones_like(maximum), 8-exponent)
    rgb = np.clip(image*scale[..., None], 0, 255).astype(np.uint8)
    rgbe = np.concatenate((rgb, (exponent+128).astype(np.uint8)[..., None]), axis=-1)
    rgbe[maximum == 0] = 0
    return f'#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n-Y {image.shape[0]} +X {image.shape[1]}\n'.encode()+rgbe.tobytes()


def template(root, cube):
    base = root/'T_Cube'; prefix = b'property-prefix\x01\x00\x00\x00'
    fmt = (cube.format+'\0').encode()
    platform = bytearray(bytes(16)+struct.pack('<iiIi', cube.size, cube.size, 0x80000006, len(fmt))+fmt+struct.pack('<ii', 0, len(cube.mips)))
    resources = []
    for level, faces in enumerate(cube.mips):
        data = b''.join(faces); size = max(1, cube.size >> level)
        platform += struct.pack('<i', level)
        resources.append({'SerialSize': len(data), 'RawSize': len(data), 'LegacyBulkDataFlags': 72,
                          'SerialOffset': len(prefix)+16+len(platform)})
        platform += data+struct.pack('<iii', size, size, 1)
    platform += bytes(4)
    raw = prefix+struct.pack('<IIq', 1, 0, len(platform)+8)+platform+bytes(8)
    base.with_suffix('.uasset').write_bytes(b'TextureCube\0'+bytes(116))
    base.with_suffix('.uexp').write_bytes(raw+b'\xc1\x83\x2a\x9e')
    doc = {'ObjectVersionUE5': 'DATA_RESOURCES', 'NameMap': ['None', cube.format],
           'Imports': [{'ObjectName': 'TextureCube'}], 'DataResources': resources,
           'Exports': [{'ClassIndex': -1, 'IsTexture2D': True, 'SerialSize': len(raw),
                        'SerialOffset': 128, 'PlatformData': {'PixelFormat': cube.format}}]}
    return str(base), doc


class HDRTextures(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_dds_retains_every_hdr_face_and_authored_mip(self):
        cube = H.from_float_faces(pixels(), 4)
        actual = H.read_dds(H.write_dds(cube))
        self.assertEqual(actual, cube)
        self.assertEqual([float(np.frombuffer(face, '<f2')[0]) for face in actual.mips[0]], [2, 4, 6, 8, 10, 12])
        self.assertEqual([len(level[0]) for level in actual.mips], [512, 128, 32, 8])

    def test_mips_average_linear_hdr_values_above_one(self):
        image = pixels(2); image[:, 0, :, :3] = 0; image[:, 1, :, :3] = 8
        cube = H.from_float_faces(image, 2)
        self.assertEqual(float(np.frombuffer(cube.mips[1][0], '<f2')[0]), 4)

    def test_both_fmodel_six_face_strip_orientations_preserve_order(self):
        faces = pixels()
        for image in (faces.reshape(48, 8, 4), np.concatenate(list(faces), axis=1)):
            np.testing.assert_array_equal(H._image_faces(image), faces)

    def test_panorama_uses_all_six_directions_without_gamma_or_range_clamping(self):
        image = np.ones((20, 40, 4), np.float32)
        image[..., 0] = (np.arange(40)+.5)/40
        image[..., 1] = (np.arange(20)[:, None]+.5)/20
        image[..., 2] = 16
        faces = H._image_faces(image)
        for face, expected in ((0, .5), (4, .75), (5, .25)):
            self.assertAlmostEqual(float(faces[face, 5, 5, 0]), expected, delta=.05)
        self.assertLess(float(faces[2, 5, 5, 1]), .1)
        self.assertGreater(float(faces[3, 5, 5, 1]), .9)
        self.assertTrue((faces[..., 2] == 16).all())

    def test_wrong_layouts_are_rejected(self):
        for shape in ((32, 32, 4), (12, 16, 4), (16, 12, 4)):
            with self.subTest(shape=shape), self.assertRaisesRegex(ValueError, 'panorama'):
                H._image_faces(np.ones(shape, np.float32))

    def test_nonfinite_and_out_of_range_values_are_rejected(self):
        for value in (float('nan'), float('inf'), -float('inf'), 65536):
            image = pixels(); image[0, 0, 0, 0] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'finite'):
                H.from_float_faces(image)

    def test_dds_rejects_incomplete_faces_arrays_and_trailing_data(self):
        source = H.write_dds(H.from_float_faces(pixels(), 2))
        for data in (source[:-1], source+b'extra'):
            with self.subTest(length=len(data)), self.assertRaises(ValueError): H.read_dds(data)
        for offset, value in ((136, 0), (140, 2), (112, 0x200), (128, 98), (28, 100)):
            data = bytearray(source); struct.pack_into('<I', data, offset, value)
            with self.subTest(offset=offset), self.assertRaises(ValueError): H.read_dds(bytes(data))

    def test_dds_preparation_keeps_authored_hdr_data_exact(self):
        cube = H.from_float_faces(pixels(), 4); source = H.write_dds(cube)
        actual = H.prepare(source, 'Authored.DDS', cube.format, 1, self.root/'prepare')
        self.assertEqual(H.write_dds(actual), source)

    def test_unsigned_bc6h_rejects_negative_values_before_compression(self):
        image = pixels(); image[0, 0, 0, 0] = -2
        source = H.write_dds(H.from_float_faces(image))
        with patch.object(H, '_texconv') as codec, self.assertRaisesRegex(ValueError, 'negative'):
            H.prepare(source, 'signed.dds', 'PF_BC6H', 1, self.root/'prepare')
        codec.assert_not_called()

    def test_oversized_and_invalid_hdr_headers_do_not_start_native_tools(self):
        for data in (b'not hdr', b'#?RADIANCE\n\n-Y 999999 +X 999999\n'):
            with patch.object(H, '_texconv') as codec, self.assertRaises(ValueError):
                H.prepare(data, 'image.hdr', 'PF_FloatRGBA', 1, self.root/'prepare')
            codec.assert_not_called()

    def test_actual_export_class_wins_over_the_native_istexture2d_flag(self):
        cube = H.from_float_faces(pixels(), 3); base, doc = template(self.root, cube)
        self.assertTrue(doc['Exports'][0]['IsTexture2D'])
        self.assertEqual(H.texture_class(doc), 'TextureCube')
        self.assertEqual(H.read_cooked(doc, base)[0], cube)
        self.assertTrue(H.candidate(base))

    def test_cooked_mip_resources_and_format_extent_are_validated(self):
        cube = H.from_float_faces(pixels(), 3); base, doc = template(self.root, cube)
        for field, value in (('LegacyBulkDataFlags', 0), ('SerialOffset', 1), ('SerialSize', 17)):
            changed = copy.deepcopy(doc); changed['DataResources'][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): H.read_cooked(changed, base)
        path = Path(base+'.uexp'); path.write_bytes(path.read_bytes()[:-4]+bytes(8)+path.read_bytes()[-4:])
        with self.assertRaises(ValueError): H.read_cooked(doc, base)

    def test_project_metadata_detects_hdr_without_reading_full_pixel_payload(self):
        base = self.root/'T_Cube'; base.with_suffix('.dds').write_bytes(H.write_dds(H.from_float_faces(pixels(), 4)))
        info = H.project_info(str(base))
        self.assertEqual(info['texture_class'], 'TextureCube')
        self.assertEqual((info['faces'], info['mips']), (6, 4))
        self.assertTrue(info['hdr'])

    def test_hdr_http_replacement_returns_success_even_if_thumbnail_cache_is_locked(self):
        from atelier.web import routes as R
        base = self.root/'T_Cube'; base.with_suffix('.png').write_bytes(b'old preview')
        thumbs = self.root/'thumbs'; (thumbs/'Fixtures').mkdir(parents=True)
        (thumbs/'Fixtures/T_Cube.png').write_bytes(b'cached preview')
        payload = b'#?RADIANCE\nfixture'
        upload = SimpleNamespace(raw_filename='Sky.hdr', filename='Sky.hdr', file=io.BytesIO(payload))
        request = SimpleNamespace(forms={'game_rel':'Fixtures/T_Cube'}, files={'file':upload})
        with patch.object(R, 'request', request), patch.object(R, '_import_base', return_value=str(base)), \
             patch.object(R, 'THUMBS_DIR', str(thumbs)), \
             patch.object(H, 'replace_project', return_value={'hdr':True,'texture_class':'TextureCube'}) as replace, \
             patch.object(R.os, 'remove', side_effect=PermissionError('Thumbnail is in use')):
            result = json.loads(R.api_replace_texture())
        self.assertTrue(result['ok']); self.assertTrue(result['hdr'])
        self.assertTrue(R.response.content_type.startswith('application/json'))
        replace.assert_called_once_with('Fixtures/T_Cube', 'Sky.hdr', payload)

    def test_http_png_replacement_cannot_overwrite_an_hdr_cube_preview(self):
        from atelier.web import routes as R
        base = self.root/'T_Cube'; base.with_suffix('.png').write_bytes(b'saved HDR preview')
        upload = SimpleNamespace(raw_filename='Paint.png', filename='Paint.png', file=io.BytesIO(b'new pixels'))
        request = SimpleNamespace(forms={'game_rel':'Fixtures/T_Cube'}, files={'file':upload})
        with patch.object(R, 'request', request), patch.object(R, '_import_base', return_value=str(base)), \
             patch.object(H, 'project_info', return_value={'hdr':True}), patch.object(H, 'replace_project') as replace:
            result = json.loads(R.api_replace_texture())
        self.assertFalse(result['ok']); self.assertIn('tone-mapped preview', result['error'])
        replace.assert_not_called()
        self.assertEqual(base.with_suffix('.png').read_bytes(), b'saved HDR preview')


if __name__ == '__main__': unittest.main()
