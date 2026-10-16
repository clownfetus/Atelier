"""Cancellation reaches native work and queued requests without affecting other previews."""
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from wsgiref.simple_server import make_server, WSGIRequestHandler

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
data = tempfile.TemporaryDirectory(prefix='atelier-cancel-tests-')
os.environ['ATELIER_DATA_DIR'] = data.name
from atelier import jobs, preview
from atelier.web import routes as R
from atelier.web.app import _ThreadingWSGIServer


class Quiet(WSGIRequestHandler):
    def log_message(self, *_): pass


class Cancellation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = make_server('127.0.0.1', 0, R.app, _ThreadingWSGIServer, Quiet)
        threading.Thread(target=cls.server.serve_forever,daemon=True).start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        R.shutdown(5)
        data.cleanup()

    def post(self, path, body, identity=None):
        headers={'Content-Type':'application/json','X-Atelier-Project':''}
        if identity: headers['X-Atelier-Preview']=identity
        try:
            with urlopen(Request(self.url+path,data=json.dumps(body).encode(),headers=headers),timeout=8) as reply:
                return reply.status,json.load(reply)
        except HTTPError as reply:
            return reply.code,json.load(reply)

    def test_cancel_interrupts_owned_native_process_and_stops_remaining_materials(self):
        entered = threading.Event()
        result, reads = [], []
        marker = Path(data.name) / 'native-process-started'
        def read(gr, **_):
            reads.append(gr)
            entered.set()
            jobs.run_process([sys.executable,'-c',
                'from pathlib import Path; import sys,time; Path(sys.argv[1]).write_text("started"); time.sleep(30)',str(marker)])
            return {'colors':[],'textures':{}}
        entries=[(f'Characters/1029/1029001/Materials/MI_{n}.uasset','pak') for n in range(3)]
        with patch.object(R,'skin_entries',return_value=entries), patch.object(R,'read_material',side_effect=read):
            worker=threading.Thread(target=lambda:result.append(self.post('/api/skin_materials',{'skin_id':'1029001'},'native-cancel')))
            worker.start()
            self.assertTrue(entered.wait(3))
            deadline = time.monotonic()+3
            while not marker.is_file() and time.monotonic()<deadline:
                time.sleep(.01)
            self.assertTrue(marker.is_file(), 'Native process must start before it is cancelled')
            start=time.monotonic()
            self.assertEqual(self.post('/api/viewport_cancel',{'id':'native-cancel'})[0],200)
            worker.join(3)
            self.assertFalse(worker.is_alive())
            self.assertLess(time.monotonic()-start,3)
            self.assertEqual(result[0],(409,{'ok':False,'cancelled':True}))
            self.assertEqual(len(reads),1)
            self.assertEqual(self.post('/api/skin_materials',{'skin_id':'1029001'},'native-cancel')[0],409)
            self.assertEqual(len(reads),1)
        with patch.object(R,'skin_entries',return_value=[]):
            self.assertEqual(self.post('/api/skin_materials',{'skin_id':'1029001'},'replacement-load')[0],200)

    def test_cancel_releases_waiter_without_acquiring_decode_slot_and_is_project_scoped(self):
        gate=threading.Semaphore(0)
        cancelled=threading.Event()
        def waiter():
            try:
                with preview.scope('A','slot-waiter'), jobs.cancellable_lock(gate):
                    self.fail('Cancelled request acquired the decode gate')
            except jobs.Cancelled:
                cancelled.set()
        worker=threading.Thread(target=waiter)
        worker.start()
        preview.cancel('A','slot-waiter')
        worker.join(2)
        self.assertTrue(cancelled.is_set())
        with preview.scope('B','slot-waiter'):
            jobs.checkpoint()

    def test_cancelled_conversion_does_not_publish_partial_material_json(self):
        from atelier.handlers import material as M, texture as TX
        root=Path(data.name)/'conversion'; root.mkdir()
        cache=root/'cache'; project=root/'project'
        source=root/'MI_Cancelled.uasset';source.write_bytes(b'fixture')
        def convert(args):
            (Path(args[3])/'MI_Cancelled.json').write_text('{"partial":')
            preview.cancel('A','conversion')
            jobs.checkpoint()
        with patch.object(M,'get_import_root',return_value=str(project)), \
             patch.object(M,'CACHE_3DVIEW',str(cache)), \
             patch.object(TX,'ensure_work_base',return_value=str(source.with_suffix(''))), \
             patch.object(M,'uat',side_effect=convert):
            with self.assertRaises(jobs.Cancelled), preview.scope('A','conversion'):
                M.mat_json('Characters/Test/MI_Cancelled',out_dir=str(cache))
        self.assertFalse(list(cache.rglob('*.json')))
        self.assertFalse(list(cache.rglob('.material-*')))


if __name__ == '__main__':
    unittest.main()
