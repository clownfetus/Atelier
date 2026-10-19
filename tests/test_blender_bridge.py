"""Bridge protocol tests. They require no native Blender or Marvel Rivals files."""
import json
from pathlib import Path
import tempfile
import unittest
from atelier import blender_bridge as B


class BlenderBridgeTests(unittest.TestCase):
    def test_inactive_receiver_fails_before_export(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            B._atomic_json(root/'receiver.json', {'protocol': B.PROTOCOL, 'time': 1})
            with self.assertRaisesRegex(RuntimeError, 'not running'):
                B.receiver_status(root, now=100)

    def test_live_receiver(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            B._atomic_json(root/'receiver.json', {'protocol': B.PROTOCOL, 'time': 100})
            self.assertEqual(B.receiver_status(root, now=103)['time'], 100)

    def test_atomically_submitted_request_gets_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); job=B.new_job_id()
            B.submit(root, job, [{'name': 'fixture'}])
            document=json.loads((root/'requests'/(job+'.json')).read_text())
            self.assertEqual(document['protocol'], B.PROTOCOL)
            B._atomic_json(root/'receipts'/(job+'.json'),{
                'protocol': B.PROTOCOL,'job':job,'ok':True,'meshes':1})
            self.assertEqual(B.await_receipt(root,job,timeout=1)['meshes'],1)
            self.assertFalse((root/'receipts'/(job+'.json')).exists())

    def test_failure_receipt_is_not_reported_as_success(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); job=B.new_job_id()
            B._atomic_json(root/'receipts'/(job+'.json'),{
                'protocol':B.PROTOCOL,'job':job,'ok':False,'error':'invalid mesh'})
            with self.assertRaisesRegex(RuntimeError,'invalid mesh'):
                B.await_receipt(root,job,timeout=1)

    def test_timed_out_request_removed(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); job=B.new_job_id()
            B.submit(root,job,[])
            with self.assertRaises(TimeoutError):
                B.await_receipt(root,job,timeout=0)
            self.assertFalse((root/'requests'/(job+'.json')).exists())


if __name__ == '__main__':
    unittest.main()
