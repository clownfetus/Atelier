"""Original comparisons, capture validation and idle discovery use disposable data."""
import atexit
from io import BytesIO
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from wsgiref.util import setup_testing_defaults
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_data = tempfile.TemporaryDirectory(prefix='atelier-viewer-tests-')
os.environ['ATELIER_DATA_DIR'] = _data.name
from atelier.web import routes as R
from atelier.handlers import animation as A, dye as D
from atelier.web.showcase import capture_frames, encode_turntable


def cleanup():
    R.shutdown(5)
    _data.cleanup()


atexit.register(cleanup)


def png(color, size=(20,20)):
    buffer = BytesIO()
    Image.new('RGB',size,color).save(buffer,'PNG')
    return buffer.getvalue()


class Showcase(unittest.TestCase):
    def test_turntable_preserves_transparent_backdrop_alpha(self):
        frames=[]
        for color in ((255,0,0,0),(0,255,0,128)):
            output=BytesIO(); Image.new('RGBA',(20,20),color).save(output,'PNG');frames.append(BytesIO(output.getvalue()))
        with Image.open(BytesIO(encode_turntable(frames))) as image:
            self.assertEqual(image.convert('RGBA').getpixel((0,0))[3],0)
            image.seek(1)
            self.assertEqual(image.convert('RGBA').getpixel((0,0))[3],128)

    def test_roundtrip_is_animated_and_keeps_frame_dimensions(self):
        frames = [png('red'),png('blue')]
        payload = b'ATC1'+struct.pack('<I',2)+b''.join(struct.pack('<I',len(f))+f for f in frames)
        encoded = encode_turntable(capture_frames(BytesIO(payload)))
        with Image.open(BytesIO(encoded)) as image:
            self.assertEqual(image.n_frames,2)
            self.assertEqual(image.size,(20,20))

    def test_rejects_truncated_oversized_and_mismatched_frames(self):
        for payload in (b'',b'ATC1'+struct.pack('<I',49),b'ATC1'+struct.pack('<II',2,100)+b'x'):
            with self.assertRaises(ValueError): capture_frames(BytesIO(payload))
        for frames in ([png('red')],[png('red'),png('blue',(30,20))],[png('red',(1025,1)),png('blue',(1025,1))]):
            with self.assertRaises(ValueError): encode_turntable([BytesIO(frame) for frame in frames])


class OriginalComparisons(unittest.TestCase):
    def test_original_texture_ignores_project_png_without_replacing_it(self):
        with tempfile.TemporaryDirectory() as workspace:
            root=Path(workspace); edited=root/'edited.png'; edited.write_bytes(png('red'))
            original=root/'cache'/'Body.png'; original.parent.mkdir(); original.write_bytes(png('blue'))
            before=edited.read_bytes()
            with patch.object(R,'_import_base',return_value=str(edited.with_suffix(''))), patch.object(R,'project_base',return_value=str(original.with_suffix(''))):
                self.assertEqual(R._texture_png('Characters/Test/Body'),str(edited))
                self.assertEqual(R._texture_png('Characters/Test/Body',original=True),str(original))
            self.assertEqual(edited.read_bytes(),before)

    def test_original_dye_uses_original_params_and_texture_inputs(self):
        info={'textures':{'DyeingTexture':'Mask','BaseColor':'Diffuse'},'colors':[{'name':'Region 1 - ColorA','rgba':[1,0,0,1]}]}
        with tempfile.TemporaryDirectory() as workspace, patch.object(D.M,'read_material_original',return_value=info), patch.object(D.M,'read_material',side_effect=AssertionError('Project material read')), patch.object(D,'_tex_image',return_value=Image.new('RGBA',(8,8),(255,255,255,36))) as images:
            target=Path(workspace)/'original.png'
            D.dye_preview('Characters/Test/MI_Body',original=True,size=8,out_path=str(target))
            self.assertTrue(target.is_file())
            self.assertTrue(all(call.kwargs.get('original') for call in images.call_args_list))


class MaterialLoading(unittest.TestCase):
    def preview(self, prefetch_error=None, textures=False, concurrent=False):
        from atelier import config
        from atelier.handlers import meshstudio, texture
        project = Path(config.project_dir('Preview batch fixture'))
        project.mkdir(parents=True, exist_ok=True)
        bindings = [
            {'key': 'body::0', 'slot_name': 'Body', 'game_rel': 'Characters/Test/MI_Body'},
            {'key': 'body::1', 'slot_name': 'Hair', 'game_rel': 'Characters/Test/MI_Hair'},
            {'key': 'body::2', 'slot_name': 'Unmapped', 'game_rel': None},
        ]
        seen = []
        barrier = threading.Barrier(2) if concurrent else None
        def prefetch(paths):
            self.assertEqual(config.get_import_root(), str(project))
            seen.append(('prefetch', paths))
            if prefetch_error:
                raise prefetch_error
        def read(path, cache_only=False):
            self.assertTrue(cache_only)
            self.assertEqual(config.get_import_root(), str(project))
            seen.append(('read', path))
            if barrier:
                barrier.wait(timeout=5)
            maps = {}
            if textures:
                maps = {'BaseColor': 'Characters/Test/T_Diffuse', 'Normal': 'Characters/Test/T_UnusedNormal'}
                if path.endswith('MI_Body'):
                    maps['Opacity'] = 'Characters/Test/T_Opacity'
                else:
                    maps.update(DyeingTexture='Characters/Test/T_Mask', Emissive='Characters/Test/T_Emissive')
            return {'colors': [{'name': 'Tint', 'rgba': [1, 0, 0, 1]}], 'textures': maps, 'scalars': []}
        body = json.dumps({'skin_id': '1029100', 'meshes': [{'game_rel': 'Characters/Test/SK_Body'}]}).encode()
        env = {}
        setup_testing_defaults(env)
        env.update(PATH_INFO='/api/skin_materials', REQUEST_METHOD='POST',
                   CONTENT_TYPE='application/json', CONTENT_LENGTH=str(len(body)),
                   HTTP_X_ATELIER_PROJECT='Preview%20batch%20fixture', **{'wsgi.input': BytesIO(body)})
        statuses = []
        with patch.object(meshstudio, 'material_bindings', return_value=iter(bindings)), \
             patch.object(texture, 'prefetch_exact', side_effect=prefetch), \
             patch.object(R, 'read_material', side_effect=read):
            response = R.app(env, lambda status, headers, exc_info=None: statuses.append(status))
            try:
                result = json.loads(b''.join(response))
            finally:
                if hasattr(response, 'close'):
                    response.close()
        self.assertTrue(statuses[0].startswith('200'), statuses)
        self.assertTrue(result['ok'])
        self.assertEqual(list(result['materials']), ['body::0', 'body::1', 'body::2'])
        self.assertEqual(result['materials']['body::0']['colors'][0]['rgba'], [1, 0, 0, 1])
        self.assertEqual(result['materials']['body::2']['colors'], [])
        self.assertFalse(list(project.iterdir()), 'Preview must not add project edits')
        return seen

    def test_cold_preview_prefetches_before_reading_parameters_in_the_originating_project(self):
        seen = self.preview()
        self.assertEqual(seen[0], ('prefetch', ['Characters/Test/MI_Body', 'Characters/Test/MI_Hair', None]))
        self.assertCountEqual([row[1] for row in seen[1:]], ['Characters/Test/MI_Body', 'Characters/Test/MI_Hair'])

    def test_conversions_overlap_and_retain_the_request_project(self):
        self.preview(concurrent=True)

    def test_prefetches_only_viewport_texture_channels_and_shared_dye_inputs_once(self):
        seen = self.preview(textures=True)
        self.assertEqual(seen[-1], ('prefetch', ['Characters/Test/T_Diffuse', 'Characters/Test/T_Opacity',
                                               'Characters/Test/T_Emissive', 'Characters/Test/T_Mask']))

    def test_failed_batch_falls_back_to_individual_material_reads(self):
        seen = self.preview(OSError('Fixture native extractor unavailable'))
        self.assertEqual(len([row for row in seen if row[0] == 'read']), 2)


class IdleDiscovery(unittest.TestCase):
    mesh='Characters/1029/1029100/Meshes/10291/SK_Test'

    def test_candidates_prefer_matching_rig_and_exclude_halfbody_and_aimoffset(self):
        entries=[(p,'pak','Marvel/Content/Marvel/') for p in [
            'Characters/1029/1029001/Animations/10290/HeroDetails/Lobby_Stand_Idle.uasset',
            'Characters/1029/1029001/Animations/10291/HeroDetails/Lobby_Half_Idle.uasset',
            'Characters/1029/1029001/Animations/10291/HeroDetails/Lobby_Stand_Idle_AO.uasset',
            'Characters/1029/1029001/Animations/10291/HeroDetails/Lobby_Stand_Idle.uasset',
            'Characters/1035/1035001/Animations/10351/HeroDetails/Lobby_Stand_Idle.uasset']]
        with patch('atelier.index.ensure_index',return_value=entries):
            candidates=A.idle_candidates(self.mesh)
        self.assertEqual(len(candidates),2)
        self.assertIn('/Animations/10291/',candidates[0]['game_rel'])

    def test_decoder_rejects_unlisted_and_invalid_paths_before_running_native_tools(self):
        with patch.object(A,'idle_candidates',return_value=[]), patch.object(A.hostos,'run_exe') as run:
            with self.assertRaises(ValueError): A.decode_idle(self.mesh,'Characters/1035/Idle')
            with self.assertRaises(ValueError): A.decode_idle(self.mesh,'../outside')
            run.assert_not_called()

    def test_flat_mesh_folders_discover_body_idle_without_weapon_or_partial_clips(self):
        entries=[(p,'pak','Marvel/Content/Marvel/') for p in [
            'Characters/1057/1057001/Animations/HeroDetails/Lobby_Stand_Idle.uasset',
            'Characters/1057/1057001/Animations/HeroDetails/Lobby_Half_Idle.uasset',
            'Characters/1057/1057001/Weapons/Animations/Lobby_Stand_Idle.uasset']]
        with patch('atelier.index.ensure_index',return_value=entries):
            for name in ('SK_1057_1057001','SK_1057_1057001_Lobby'):
                candidates=A.idle_candidates('Characters/1057/1057001/Meshes/'+name)
                self.assertEqual(len(candidates),1)
                self.assertIn('/Animations/HeroDetails/',candidates[0]['game_rel'])


if __name__=='__main__': unittest.main()
