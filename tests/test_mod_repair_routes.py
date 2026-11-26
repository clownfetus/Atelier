"""Check the install-folder scan and explicit save through their HTTP entry points."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from wsgiref.util import setup_testing_defaults

from bottle import Bottle

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from atelier.web import mod_repair


class RepairRoutesTests(unittest.TestCase):
    def setUp(self):
        self.app = Bottle()
        mod_repair.register(self.app, lambda kind, label, work: work(None))

    def query(self, path, body=None, method='POST'):
        body = json.dumps(body or {}).encode("utf-8")
        request = {}
        setup_testing_defaults(request)
        request.update(REQUEST_METHOD=method, PATH_INFO=path, CONTENT_TYPE="application/json",
                       CONTENT_LENGTH=str(len(body)))
        request["wsgi.input"] = io.BytesIO(body)
        status = []
        answer = self.app(request, lambda code, _headers, _exc_info=None: status.append(code))
        try:
            self.assertTrue(status[0].startswith("200"), status)
            return json.loads(b"".join(answer))
        finally:
            if hasattr(answer, "close"):
                answer.close()

    def test_unconfigured_folder_has_no_startup_scan(self):
        with patch.object(mod_repair.config, "get_mods_folder", return_value=""):
            self.assertEqual(self.query("/api/mod_repair/installed", method="GET")["repairs"], [])

    def test_startup_returns_a_background_job_in_global_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            with (patch.object(mod_repair.config, "get_mods_folder", return_value=directory),
                  patch.object(mod_repair.jobs, "manager") as manager):
                queued = {"id": "repair-job", "state": "queued", "project": ""}
                manager.return_value.submit.return_value = queued
                reply = self.query("/api/mod_repair/installed", method="GET")
                self.assertEqual(reply["job_id"], "repair-job")
                self.assertEqual(manager.return_value.submit.call_args.args[3], "")

    def test_save_only_writes_in_the_chosen_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            with (patch.object(mod_repair.hostos, "pick_folder", return_value=directory),
                  patch.object(mod_repair.file_repair, "save_repaired", return_value={"ok": True}) as save):
                reply = self.query("/api/mod_repair/save", {
                    "token": "approved", "suggested_name": "example-repaired.zip", "background": True})
                self.assertTrue(reply["ok"])
                self.assertEqual(save.call_args.args, ("approved", Path(directory) / "example-repaired.zip"))

    def test_rejects_path_components_and_skips_cancelled_picker(self):
        with (patch.object(mod_repair.hostos, "pick_folder", return_value="") as picker,
              patch.object(mod_repair.file_repair, "save_repaired") as save):
            self.assertFalse(self.query("/api/mod_repair/save", {
                "token": "approved", "suggested_name": "../example-repaired.zip"})["ok"])
            picker.assert_not_called()
            self.assertTrue(self.query("/api/mod_repair/save", {
                "token": "approved", "suggested_name": "valid.zip"})["cancelled"])
            save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
