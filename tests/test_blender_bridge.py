"""Bridge protocol tests. They require no native Blender or Marvel Rivals files."""
import json
from pathlib import Path
import tempfile
import unittest
import sys
import time
import importlib.util
import copy
import io
import zipfile
import hashlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from atelier import blender_bridge as B


class BlenderBridgeTests(unittest.TestCase):
    def setUp(self):
        self.session = 'a' * 32

    def heartbeat(self, root):
        B._atomic_json(root/'receiver.json', {'protocol': B.PROTOCOL, 'time': time.time(), 'receiver': self.session})

    def test_inactive_receiver_fails_before_export(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            B._atomic_json(root/'receiver.json', {'protocol': B.PROTOCOL, 'time': 1})
            with self.assertRaisesRegex(RuntimeError, 'not running'):
                B.receiver_status(root, now=100)

    def test_live_receiver(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            B._atomic_json(root/'receiver.json', {'protocol': B.PROTOCOL, 'time': 100, 'receiver': self.session})
            self.assertEqual(B.receiver_status(root, now=103)['time'], 100)

    def test_atomically_submitted_request_gets_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); job=B.new_job_id(); self.heartbeat(root)
            B.submit(root, job, [{'name': 'fixture'}])
            document=json.loads((root/'requests'/(job+'.json')).read_text())
            self.assertEqual(document['protocol'], B.PROTOCOL)
            B._atomic_json(root/'receipts'/(job+'.json'),{
                'protocol': B.PROTOCOL,'job':job,'receiver':self.session,'ok':True,'meshes':1})
            self.assertEqual(B.await_receipt(root,job,receiver=self.session,timeout=1)['meshes'],1)
            self.assertFalse((root/'receipts'/(job+'.json')).exists())

    def test_failure_receipt_is_not_reported_as_success(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); job=B.new_job_id(); self.heartbeat(root)
            B._atomic_json(root/'receipts'/(job+'.json'),{
                'protocol':B.PROTOCOL,'job':job,'receiver':self.session,'ok':False,'error':'invalid mesh'})
            with self.assertRaisesRegex(RuntimeError,'invalid mesh'):
                B.await_receipt(root,job,receiver=self.session,timeout=1)

    def test_receipt_from_another_receiver_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve(); job=B.new_job_id()
            B._atomic_json(root/'receipts'/(job+'.json'),{
                'protocol':B.PROTOCOL,'job':job,'receiver':'c'*32,'ok':True})
            with self.assertRaisesRegex(RuntimeError,'invalid receipt'):
                B.await_receipt(root,job,receiver=self.session,timeout=1)

    def test_timed_out_request_removed(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); job=B.new_job_id(); self.heartbeat(root)
            B.submit(root,job,[])
            with self.assertRaises(TimeoutError):
                B.await_receipt(root,job,receiver=self.session,timeout=0)
            self.assertFalse((root/'requests'/(job+'.json')).exists())


class ConfinedRequests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.job = 'b' * 32; self.session = 'a' * 32
        self.stage = self.root/'staging'/self.job; self.stage.mkdir(parents=True)
        for name in ('model.glb', 'materials.json'): (self.stage/name).write_bytes(b'fixture')
        self.request = {'protocol': B.PROTOCOL, 'job': self.job, 'receiver': self.session,
            'expires': time.time()+100, 'parts': [{'glb':str(self.stage/'model.glb'),
            'materials':str(self.stage/'materials.json'), 'transform':[[int(x==y) for x in range(4)] for y in range(4)]}]}
        source = Path(__file__).resolve().parents[1]/'atelier/blender/atelier_live_bridge/safety.py'
        spec = importlib.util.spec_from_file_location('bridge_safety', source)
        self.safety = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.safety)

    def test_accepts_only_current_confined_request(self):
        self.assertEqual(self.safety.validate_request(self.request,self.root,self.session),self.request['parts'])
        for field,value in [('receiver','c'*32),('job','../escape'),('expires',0),('expires',float('nan'))]:
            request=copy.deepcopy(self.request);request[field]=value
            with self.assertRaises(ValueError):self.safety.validate_request(request,self.root,self.session)

    def test_refuses_external_geometry_and_invalid_transform(self):
        outside=self.root/'outside.glb';outside.write_bytes(b'outside')
        request=copy.deepcopy(self.request);request['parts'][0]['glb']=str(outside)
        with self.assertRaisesRegex(ValueError,'outside'):self.safety.validate_request(request,self.root,self.session)
        request=copy.deepcopy(self.request);request['parts'][0]['transform'][0][0]=float('nan')
        with self.assertRaisesRegex(ValueError,'transform'):self.safety.validate_request(request,self.root,self.session)

    def test_extension_is_reproducible_and_has_verified_sources(self):
        from atelier.blender_extension import archive_bytes
        # run_checks copies product source but deliberately omits repository licenses.
        root=Path(__file__).resolve().parents[1]
        fixture=self.root/'package';fixture.mkdir()
        import shutil
        shutil.copytree(root/'atelier/blender',fixture/'atelier/blender')
        (fixture/'version').write_text('1.1.1');(fixture/'LICENSE').write_text('fixture license')
        first=archive_bytes(fixture);self.assertEqual(first,archive_bytes(fixture))
        with zipfile.ZipFile(io.BytesIO(first)) as archive:
            record=json.loads(archive.read('build-inputs.json'))
            self.assertIn('safety.py',record['files'])
            for name,digest in record['files'].items():self.assertEqual(digest,hashlib.sha256(archive.read(name)).hexdigest())

    def test_external_resources_inside_a_glb_are_rejected(self):
        # Loading a .glb is not sufficient confinement: its JSON can name an
        # external buffer or texture that Blender would otherwise follow.
        import struct
        source=Path(__file__).resolve().parents[1]/'atelier/blender/atelier_live_bridge/tracking.py'
        spec=importlib.util.spec_from_file_location('bridge_tracking',source)
        tracking=importlib.util.module_from_spec(spec);spec.loader.exec_module(tracking)
        for key in ('buffers','images'):
            encoded=json.dumps({key:[{'uri':'file:///private/fixture'}]}).encode()
            encoded+=b' '*(-len(encoded)%4)
            blob=struct.pack('<III',0x46546c67,2,28+len(encoded))+struct.pack('<II',len(encoded),0x4e4f534a)+encoded+struct.pack('<II',0,0x004e4942)
            path=self.stage/'external.glb';path.write_bytes(blob)
            with self.assertRaisesRegex(ValueError,'external resources'):tracking.read_glb(path)


if __name__ == '__main__':
    unittest.main()
