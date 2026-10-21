"""Real child-pipe lifecycle tests with a labelled decoder fixture, no game data."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import json
import ntpath
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_data = tempfile.TemporaryDirectory(prefix='atelier-import-tests-')
os.environ['ATELIER_DATA_DIR'] = _data.name
from atelier import config, import_server as S, jobs, preview


FIXTURE = r'''
import json,os,pathlib,sys,time,struct
count=0
for line in sys.stdin:
 r=json.loads(line);action=r['action'];count+=1
 with open(os.environ['ATELIER_PIPE_EVENTS'],'a') as events:events.write(action+'\n')
 if action=='initialize':
  while os.environ.get('ATELIER_HOLD_INIT') and not pathlib.Path(os.environ['ATELIER_PIPE_RELEASE']).exists():time.sleep(.01)
  data=dict(protocol=1,pid=os.getpid(),initializations=1,files=42)
 elif action=='hold':
  while not pathlib.Path(os.environ['ATELIER_PIPE_RELEASE']).exists():time.sleep(.01)
  data={'released':True}
 elif action=='hang':
  time.sleep(60);data={}
 elif action=='malformed':
  print('not JSON',flush=True);continue
 elif action=='asset_error':
  print(json.dumps(dict(id=r['id'],ok=False,error='Fixture asset is unsupported')),flush=True);continue
 elif action=='material':
  data={'colors':[{'name':'Tint','rgba':[1,0,0,1]}],'scalars':[],'textures':{}}
 elif action=='texture':
  target=pathlib.Path(root_dir)/'blocks'/(r['asset']+'.bin');target.parent.mkdir(parents=True,exist_ok=True)
  blocks=bytes([18,19])+bytes(6)+struct.pack('<HHI',0x07e0,0,0)
  target.write_bytes(blocks[:-1] if r['asset'].endswith('_Truncated') else blocks)
  data=dict(path=str(target.parent/'wrong.bin' if r['asset'].endswith('_BadPath') else target),
            encoding='blocks',format='DXT5',width=4,height=4)
 elif action=='mesh':
  root=pathlib.Path(root_dir);target=root/'gltf'/(r['asset']+'.glb');target.parent.mkdir(parents=True,exist_ok=True)
  body=b'{"asset":{"version":"2.0"}}';body+=b' '*((-len(body))%4)
  target.write_bytes(struct.pack('<4sII',b'glTF',2,20+len(body))+struct.pack('<I4s',len(body),b'JSON')+body)
  meta=root/'meshes'/(r['asset']+'.json');meta.parent.mkdir(parents=True,exist_ok=True)
  meta.write_text(json.dumps(dict(version=1,asset=r['asset'],slots=[dict(index=0,slot='Body',mi='Characters/Test/MI_Body',via='imports')])) )
  data={'path':str(target)}
 else:data={'pid':os.getpid(),'initializations':1,'requests':count}
 if action=='initialize':root_dir=r['cache_root']
 print(json.dumps(dict(id='wrong' if action=='wrong_id' else r['id'],ok=True,data=data)),flush=True)
'''


class PersistentImports(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix='atelier-pipe-case-')
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.events = self.root/'events'
        self.release = self.root/'release'
        tools = self.root/'Tools'
        (tools/'AtelierImport').mkdir(parents=True)
        (tools/'AtelierImport/AtelierImport.exe').write_bytes(b'fixture')
        paks = self.root/'Paks';paks.mkdir()
        (paks/'pakchunkFixture.utoc').write_bytes(b'index')
        self.mapping = self.root/'mapping.usmap';self.mapping.write_bytes(b'mapping')
        self.children = []
        S._worker = None;S._closing = False
        self.stack = ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.multiple(config, TOOLS=str(tools), PAKS=str(paks),
                                               USMAP=str(self.mapping), _CACHE=str(self.root/'cache')))
        self.stack.enter_context(patch.object(config,'get_aes_key',return_value='ab'*32))
        self.stack.enter_context(patch.object(S.hostos,'IS_WINDOWS',True))
        self.stack.enter_context(patch.dict(os.environ,ATELIER_PIPE_EVENTS=str(self.events),ATELIER_PIPE_RELEASE=str(self.release)))
        self.stack.enter_context(patch.object(S.hostos,'popen_exe',side_effect=self.spawn))
        def asset(gr):
            config.validate_game_rel(gr)
            return 'Marvel/Content/Marvel/'+gr
        self.stack.enter_context(patch.object(S,'_asset',side_effect=asset))
        self.addCleanup(S.shutdown)

    def spawn(self, args, **kwargs):
        child = subprocess.Popen([sys._base_executable,'-u','-c',FIXTURE],**kwargs)
        self.children.append(child)
        return child

    def wait_for(self, action):
        until=time.monotonic()+3
        while time.monotonic()<until:
            if self.events.exists() and action in self.events.read_text().splitlines():return
            time.sleep(.01)
        self.fail('Fixture did not accept '+action)

    def test_reuses_one_reader_and_keeps_its_key_off_the_command_line(self):
        first=S.stats();second=S.stats()
        self.assertEqual(first['pid'],second['pid'])
        self.assertEqual(len(self.children),1)
        self.assertEqual(self.events.read_text().splitlines().count('initialize'),1)
        self.assertNotIn('ab'*32,' '.join(self.children[0].args))

    def test_asset_failure_keeps_the_healthy_stream_reusable(self):
        pid=S.stats()['pid']
        with self.assertRaises(S.AssetError):S._request('asset_error',{})
        self.assertEqual(S.stats()['pid'],pid)

    def test_bad_frames_and_timeout_drop_the_worker_before_next_request(self):
        for action in ('malformed','wrong_id','hang'):
            with self.subTest(action=action):
                pid=S.stats()['pid']
                with self.assertRaises(S.ImportError):S._request(action,{},timeout=.15)
                self.assertIsNotNone(self.children[-1].poll())
                self.assertNotEqual(S.stats()['pid'],pid)

    def test_parallel_clients_receive_their_own_responses(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            result=list(pool.map(lambda _:S.stats(),range(12)))
        self.assertEqual(len({row['pid'] for row in result}),1)
        self.assertEqual(len({row['requests'] for row in result}),12)

    def test_active_preview_cancellation_kills_only_the_owned_worker(self):
        result=[]
        def run():
            try:
                with preview.scope('A','cancel-import'):S._request('hang',{})
            except BaseException as error:result.append(error)
        thread=threading.Thread(target=run);thread.start();self.wait_for('hang')
        preview.cancel('A','cancel-import');thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertIsInstance(result[0],jobs.Cancelled)
        self.assertIsNotNone(self.children[-1].poll())
        self.assertEqual(S.stats()['initializations'],1)

    def test_cancelled_waiter_does_not_kill_another_projects_active_import(self):
        active=[];cancelled=[]
        thread=threading.Thread(target=lambda:active.append(S._request('hold',{})))
        thread.start();self.wait_for('hold');pid=S._worker.pid
        def wait():
            try:
                with preview.scope('B','queued-import'):S.stats()
            except jobs.Cancelled:cancelled.append(True)
        queued=threading.Thread(target=wait);queued.start()
        preview.cancel('B','queued-import');queued.join(2)
        self.assertEqual(cancelled,[True]);self.assertIsNone(self.children[-1].poll())
        self.release.write_text('resume');thread.join(3)
        self.assertEqual(active,[{'released':True}]);self.assertEqual(S.stats()['pid'],pid)

    def test_shutdown_interrupts_initialization_and_prevents_resurrection(self):
        result=[]
        def run():
            try:S.stats()
            except S.ImportError as error:result.append(error)
        with patch.dict(os.environ,ATELIER_HOLD_INIT='1'):
            thread=threading.Thread(target=run);thread.start();self.wait_for('initialize')
            S.shutdown();thread.join(3)
        self.assertFalse(thread.is_alive());self.assertTrue(result)
        self.assertIsNotNone(self.children[-1].poll())
        with self.assertRaises(S.ImportError):S.stats()
        self.assertEqual(len(self.children),1)

    def test_game_mapping_and_tool_changes_restart_reader_and_separate_cache(self):
        previous=S.stats()['pid'];root=S._source()[1]
        for path in (self.mapping,Path(config.PAKS)/'pakchunkFixture.utoc',S.tool_path()):
            path.write_bytes(path.read_bytes()+b'changed')
            current=S.stats()['pid'];self.assertNotEqual(current,previous);previous=current
            self.assertNotEqual(S._source()[1],root);root=S._source()[1]
        (Path(config.PAKS)/'~mods').mkdir()
        (Path(config.PAKS)/'~mods/mod.utoc').write_bytes(b'not a game container')
        (Path(config.PAKS)/'!ProjectGalacta_9999999_P.utoc').write_bytes(b'not a game container either')
        self.assertEqual(S.stats()['pid'],previous)

    def test_published_mesh_and_material_caches_do_not_repeat_native_requests(self):
        mesh=S.mesh('Characters/Test/SK_Body')
        data=S.material('Characters/Test/MI_Body')
        self.assertTrue(Path(mesh).is_file());self.assertEqual(data['colors'][0]['rgba'],[1,0,0,1])
        before=self.events.read_text()
        self.assertEqual(S.mesh('Characters/Test/SK_Body'),mesh)
        self.assertEqual(S.material('Characters/Test/MI_Body'),data)
        self.assertEqual(S.mesh_slots('Characters/Test/SK_Body')[0]['mi'],'Characters/Test/MI_Body')
        self.assertEqual(self.events.read_text(),before)
        project=self.root/'project';project.mkdir()
        with config.project_context(str(project)):S.material('Characters/Test/MI_Body')
        self.assertFalse(list(project.iterdir()))

    def test_parallel_requests_for_one_material_share_one_conversion(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda _:S.material('Characters/Test/MI_Shared'),range(8)))
        self.assertTrue(all(row==results[0] for row in results))
        self.assertEqual(self.events.read_text().splitlines().count('material'),1)

    @unittest.skipUnless(os.name == 'nt', 'Windows long import-cache path')
    def test_long_material_cache_paths_publish_and_read_without_another_request(self):
        asset = 'Characters/Test/' + '/'.join(['LongMaterialFolder' * 3] * 3) + '/MI_Weapon'
        target = S._target(S._source()[1], 'materials', S._asset(asset), '.json')
        self.assertGreater(len(str(target)), 260)
        try:
            first = S.material(asset)
            events = self.events.read_text()
            self.assertEqual(S.material(asset), first)
            self.assertEqual(self.events.read_text(), events)
            self.assertTrue(target.is_file())
        finally:
            target.unlink(missing_ok=True)
            cache = config._path_comparison_key(str(self.root / 'cache'))
            for parent in target.parents:
                if config._path_comparison_key(str(parent)) == cache:
                    break
                self.assertTrue(config._path_comparison_key(str(parent)).startswith(cache + os.sep))
                parent.rmdir()

    def test_original_texture_blocks_preserve_mask_alpha_and_reuse_the_png(self):
        from PIL import Image
        path=S.texture('Characters/Test/T_Mask')
        with Image.open(path) as image:
            self.assertEqual(image.size,(4,4))
            self.assertEqual(set(image.convert('RGBA').getdata()),{(0,255,0,18)})
        before=self.events.read_text()
        self.assertEqual(S.texture('Characters/Test/T_Mask'),path)
        self.assertEqual(self.events.read_text(),before)
        self.assertFalse(list(Path(path).parent.glob('.texture-*')))

    def test_incomplete_texture_blocks_do_not_publish_an_image(self):
        with self.assertRaises(S.ImportError):S.texture('Characters/Test/T_Truncated')
        self.assertFalse(list((self.root/'cache').rglob('*.png')))
        self.assertEqual(S.stats()['initializations'],1)

    def test_texture_output_cannot_substitute_a_different_cache_path(self):
        with self.assertRaises(S.ImportError):S.texture('Characters/Test/T_BadPath')
        self.assertFalse(list((self.root/'cache').rglob('*.png')))

    def test_saved_material_edits_win_while_original_comparison_uses_native_data(self):
        from atelier.handlers import material as M
        gr='Characters/Test/MI_Body'
        project=self.root/'project';project.mkdir()
        document={'Exports':[{'Data':[{'Name':'VectorParameterValues','Value':[{'Value':[
            {'Name':'ParameterInfo','Value':[{'Name':'Name','Value':'Tint'}]},
            {'Name':'ParameterValue','Value':[{'Value':{'R':0,'G':.3,'B':.7,'A':1}}]}
        ]}]}]}]}
        with config.project_context(str(project)),patch.object(M,'uat',side_effect=AssertionError('No conversion needed')):
            path=Path(config.project_base(gr)+'.json');path.parent.mkdir(parents=True);path.write_text(json.dumps(document))
            self.assertEqual(M.read_material(gr,cache_only=True)['colors'][0]['rgba'],[0,.3,.7,1])
            self.assertEqual(M.read_material_original(gr)['colors'][0]['rgba'],[1,0,0,1])
        self.assertEqual(list(project.rglob('*.json')),[path])

    def test_asset_and_output_traversal_is_rejected_before_native_work(self):
        for asset in ('../outside','/absolute','Characters/../outside','Characters/Bad:Name'):
            with self.subTest(asset=asset),self.assertRaises(ValueError):S.mesh(asset)
        self.assertFalse(self.children)
        with self.assertRaises(ValueError):S._target(self.root,'textures','../outside','.png')

    def test_crashed_child_is_replaced_without_reusing_its_response_queue(self):
        pid=S.stats()['pid'];self.children[-1].kill();self.children[-1].wait()
        self.assertNotEqual(S.stats()['pid'],pid)

    def test_windows_cache_paths_accept_equivalent_prefixes_and_preserve_io_spelling(self):
        for base, target in (
            (r'D:\cache\textures', r'\\?\D:\cache\textures\Characters\T_A.png'),
            (r'\\?\D:\cache\textures', r'D:\cache\textures\Characters\T_A.png'),
            (r'\\server\share\textures', r'\\?\UNC\server\share\textures\Characters\T_A.png'),
            (r'\\?\UNC\server\share\textures', r'\\server\share\textures\Characters\T_A.png'),
        ):
            with self.subTest(base=base), patch.object(config.os, 'path', ntpath):
                with patch.object(ntpath, 'realpath', side_effect=[base, target]):
                    self.assertEqual(str(S._target(self.root, 'textures', 'Characters/T_A', '.png')), target)
                ordinary = ntpath.join(config._path_comparison_key(base), 'Characters', 'T_A.png')
                with patch.object(ntpath, 'realpath', side_effect=[ordinary, target]):
                    self.assertTrue(S._same_path(ordinary, target))

    def test_windows_cache_prefix_normalization_keeps_escape_checks(self):
        base = r'D:\cache\textures'
        for outside in (r'\\?\E:\cache\textures\Characters\T_A.png',
                        r'\\?\D:\outside\Characters\T_A.png',
                        r'\\?\D:\cache\textures-other\Characters\T_A.png',
                        r'\\?\GLOBALROOT\Device\HarddiskVolume1\Characters\T_A.png',
                        r'\\?\UNC\server\other\textures\Characters\T_A.png'):
            with self.subTest(outside=outside), patch.object(config.os, 'path', ntpath):
                with patch.object(ntpath, 'realpath', side_effect=[base, outside]):
                    with self.assertRaisesRegex(ValueError, 'outside the cache'):
                        S._target(self.root, 'textures', 'Characters/T_A', '.png')
                with patch.object(ntpath, 'realpath', side_effect=[base, outside]):
                    self.assertFalse(S._same_path(base, outside))


if __name__=='__main__':
    try:unittest.main()
    finally:S.shutdown();_data.cleanup()
