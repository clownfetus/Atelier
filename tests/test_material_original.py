"""Pristine material comparisons use disposable fixtures, never installed game/project data."""
import atexit
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import quote, urlencode
from wsgiref.util import setup_testing_defaults

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_data = tempfile.TemporaryDirectory(prefix="atelier-original-tests-")
os.environ["ATELIER_DATA_DIR"] = _data.name
from atelier import config as C
from atelier.handlers import material as M, texture as T
from atelier.web import routes as R


def cleanup():
    R._observer.stop()
    R._observer.join()
    _data.cleanup()


atexit.register(cleanup)


def material(red):
    def entry(name, value):
        return {"Value": [
            {"Name": "ParameterInfo", "Value": [{"Name": "Name", "Value": name}]},
            {"Name": "ParameterValue", "Value": value}]}
    return {"Exports": [{"Data": [
        {"Name": "VectorParameterValues", "Value": [entry("Tint", [{"Value": {"R": red, "G": .2, "B": .3, "A": 1}}])]},
        {"Name": "ScalarParameterValues", "Value": [entry("Roughness", .4)]},
        {"Name": "TextureParameterValues", "Value": [entry("BaseColor", -1)]}
    ]}], "Imports": [{"OuterIndex": -2}, {"ObjectName": "/Game/Marvel/Characters/1015/T_Body"}]}


def call(query, project="A"):
    env = {}
    setup_testing_defaults(env)
    env.update(REQUEST_METHOD="GET", PATH_INFO="/api/material_original",
               QUERY_STRING=urlencode(query), **{"wsgi.input": io.BytesIO()})
    if project is not None:
        env["HTTP_X_ATELIER_PROJECT"] = quote(project, safe="")
    statuses = []
    result = R.app(env, lambda status, headers, exc_info=None: statuses.append(status))
    try:
        data = json.loads(b"".join(result))
    finally:
        if hasattr(result, "close"):
            result.close()
    return int(statuses[0].split()[0]), data


class MaterialOriginal(unittest.TestCase):
    game_rel = "Characters/1015/1015502/Materials/MI_Body"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="atelier-original-case-")
        self.root = Path(self.temp.name)
        self.projects = self.root / "projects"
        for project in ("A", "B"):
            (self.projects / project).mkdir(parents=True)
        self.cache = self.root / "cache"
        self.cache.mkdir()
        self.stack = ExitStack()
        self.stack.enter_context(patch.multiple(C, PROJECTS_ROOT=str(self.projects),
            IMPORT_ROOT=str(self.root / "imported"), _active_project="A"))
        self.stack.enter_context(patch.multiple(R, PROJECTS_ROOT=str(self.projects), IMPORT_ROOT=C.IMPORT_ROOT))
        self.stack.enter_context(patch.object(M, "CACHE_3DVIEW", str(self.cache)))
        self.work = self.root / "extracted" / "MI_Body"
        self.work.parent.mkdir()
        self.work.with_suffix(".uasset").write_bytes(b"fixture asset")
        self.extract = self.stack.enter_context(patch.object(T, "ensure_work_base", return_value=str(self.work)))
        self.decode = self.stack.enter_context(patch.object(M, "uat", side_effect=self.decode_original))
        for project in ("A", "B"):
            self.write_json(self.projects / project / (self.game_rel + ".json"), material(.9))
            self.write_json(self.projects / project / "MI_Body.json", material(.8))
            (self.projects / project / "keep.png").write_bytes(b"unrelated texture")
        self.before = self.project_bytes()

    def tearDown(self):
        self.assertEqual(self.project_bytes(), self.before, "Original comparison changed project files")
        self.stack.close()
        self.temp.cleanup()

    def write_json(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")

    def project_bytes(self):
        return {str(path.relative_to(self.projects)): path.read_bytes()
                for path in self.projects.rglob("*") if path.is_file()}

    def decode_original(self, args):
        self.assertEqual(args[0], "to_json")
        self.assertEqual(args[1], str(self.work.with_suffix(".uasset")))
        self.assertTrue(Path(args[3]).is_relative_to(self.cache))
        self.write_json(Path(args[3]) / "MI_Body.json", material(.1))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def test_cached_original_bypasses_nested_and_legacy_project_edits(self):
        self.write_json(self.cache / (self.game_rel + ".json"), material(.1))
        self.assertEqual(M.read_material(self.game_rel)["colors"][0]["rgba"][0], .9)
        original = M.read_material_original(self.game_rel)
        self.assertEqual(original["colors"][0]["rgba"], [.1, .2, .3, 1])
        self.assertEqual(original["scalars"], [{"name": "Roughness", "value": .4}])
        self.assertEqual(original["textures"], {"BaseColor": "Characters/1015/T_Body"})
        self.extract.assert_not_called()
        self.decode.assert_not_called()

    def test_missing_cache_decodes_once_and_publishes_complete_json(self):
        result = M.read_material_original(self.game_rel)
        self.assertEqual(result["colors"][0]["rgba"][0], .1)
        cached = self.cache / (self.game_rel + ".json")
        self.assertEqual(json.loads(cached.read_text()), material(.1))
        self.assertEqual(M.read_material_original(self.game_rel), result)
        self.decode.assert_called_once()
        self.assertFalse(list(self.cache.glob(".material-original-*")))

    def test_concurrent_original_reads_share_one_conversion(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: M.read_material_original(self.game_rel), range(4)))
        self.assertEqual(results, [results[0]] * 4)
        self.extract.assert_called_once()
        self.decode.assert_called_once()

    def test_decode_failure_does_not_publish_partial_json_or_touch_projects(self):
        def fail(args):
            (Path(args[3]) / "MI_Body.json").write_text("{partial", encoding="utf-8")
            return SimpleNamespace(returncode=1, stdout="", stderr="fixture decode failure")
        self.decode.side_effect = fail
        with self.assertRaisesRegex(RuntimeError, "fixture decode failure"):
            M.read_material_original(self.game_rel)
        self.assertFalse((self.cache / (self.game_rel + ".json")).exists())
        self.assertFalse(list(self.cache.glob(".material-original-*")))
        self.decode.side_effect = self.decode_original
        self.assertEqual(M.read_material_original(self.game_rel)["colors"][0]["rgba"][0], .1)

    def test_invalid_cache_remains_untouched_when_repair_fails(self):
        cached = self.cache / (self.game_rel + ".json")
        cached.parent.mkdir(parents=True)
        cached.write_bytes(b"{existing incomplete cache")
        self.decode.return_value = SimpleNamespace(returncode=0, stdout="", stderr="")
        self.decode.side_effect = None
        with self.assertRaisesRegex(RuntimeError, "produced no JSON"):
            M.read_material_original(self.game_rel)
        self.assertEqual(cached.read_bytes(), b"{existing incomplete cache")
        self.assertFalse(list(self.cache.glob(".material-original-*")))

    def test_invalid_native_output_never_replaces_cache(self):
        def malformed(args):
            self.write_json(Path(args[3]) / "MI_Body.json", {"Exports": []})
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        self.decode.side_effect = malformed
        with self.assertRaises(IndexError):
            M.read_material_original(self.game_rel)
        self.assertFalse((self.cache / (self.game_rel + ".json")).exists())

    def test_api_returns_pristine_values_and_honors_project_and_path_guards(self):
        self.write_json(self.cache / (self.game_rel + ".json"), material(.1))
        status, data = call({"game_rel": self.game_rel}, "B")
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["game_rel"], self.game_rel)
        self.assertEqual(data["colors"][0]["rgba"][0], .1)
        for path in ("../outside", "Characters/../outside", "C:/outside", "/absolute"):
            with self.subTest(path=path):
                self.assertEqual(call({"game_rel": path})[0], 400)
                with self.assertRaises(ValueError):
                    M.read_material_original(path)
        self.assertEqual(call({"game_rel": self.game_rel}, "../outside")[0], 400)
        self.assertEqual(call({"game_rel": self.game_rel}, "Missing")[0], 400)
        self.assertFalse(call({})[1]["ok"])

    def test_api_decode_failure_returns_error_without_resetting_material(self):
        self.decode.side_effect = RuntimeError("fixture failure")
        status, data = call({"game_rel": self.game_rel})
        self.assertEqual(status, 200)
        self.assertFalse(data["ok"])
        self.assertIn("fixture failure", data["error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
