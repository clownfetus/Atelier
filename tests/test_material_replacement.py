"""Material replacement graph, export and failure safety in disposable projects."""
import atexit
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
_data = tempfile.TemporaryDirectory(prefix="atelier-material-replacement-")
os.environ["ATELIER_DATA_DIR"] = _data.name
from atelier import config as C, project_meta
from atelier.handlers import material as M, texture as T
from atelier.web import routes as R

atexit.register(lambda: (R._observer.stop(), R._observer.join(), _data.cleanup()))
TARGET = "Characters/1001/1001001/Materials/MI_Body"
SOURCE = "Characters/1002/1002001/Materials/MI_Galaxy"
PARENT = "Characters/1002/Materials/M_Galaxy"
TEX = "Characters/1002/Textures/T_Stars"


def document(gr, red=.2, parent=PARENT, parent_class="Material"):
    def parameter(name, value):
        return {"Value": [{"Name": "ParameterInfo", "Value": [{"Name": "Name", "Value": name}]},
                          {"Name": "ParameterValue", "Value": value, "IsZero": False}]}
    return {"FolderName": "/Game/Marvel/" + gr, "NameMap": [gr.rsplit("/", 1)[-1]],
            "Imports": [{"ObjectName": "MaterialInstanceConstant", "OuterIndex": 0},
                        {"ObjectName": "/Game/Marvel/" + parent, "OuterIndex": 0},
                        {"ObjectName": parent.rsplit("/", 1)[-1], "ClassName": parent_class, "OuterIndex": -2},
                        {"ObjectName": "/Game/Marvel/" + TEX, "OuterIndex": 0},
                        {"ObjectName": "T_Stars", "ClassName": "Texture2D", "OuterIndex": -4}],
            "SoftObjectPathList": ["/Game/Marvel/" + gr + "." + gr.rsplit("/", 1)[-1]],
            "Exports": [{"ObjectName": gr.rsplit("/", 1)[-1], "OuterIndex": 0, "ClassIndex": -1,
                         "Extras": "cooked shader data", "Data": [
                             {"Name": "Parent", "Value": -3},
                             {"Name": "StaticParametersRuntime", "Value": [{"switch": True}]},
                             {"Name": "VectorParameterValues", "Value": [parameter("Tint", [{"Value": {
                                 "R": red, "G": .3, "B": .4, "A": 1}}])]},
                             {"Name": "ScalarParameterValues", "Value": [parameter("Speed", .7)]},
                             {"Name": "TextureParameterValues", "Value": [parameter("BaseColor", -5)]}]}]}


class ReplacementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="atelier-replacement-case-")
        self.root = Path(self.temp.name).resolve()
        self.projects = self.root / "projects"
        for name in ("A", "B"):
            (self.projects / name).mkdir(parents=True)
        self.project = self.projects / "A"
        self.cache = self.root / "cache"
        self.cache.mkdir()
        self.stage = self.root / "stage"
        self.stage.mkdir()
        self.docs = {TARGET: document(TARGET, .1), SOURCE: document(SOURCE, .9)}
        self.stack = ExitStack()
        self.stack.enter_context(patch.multiple(C, PROJECTS_ROOT=str(self.projects), _active_project="A"))
        self.stack.enter_context(patch.object(R, "PROJECTS_ROOT", str(self.projects)))
        self.stack.enter_context(patch.multiple(M, CACHE_3DVIEW=str(self.cache), _CACHE=str(self.cache)))
        self.stack.enter_context(patch.object(T, "ensure_work_base", side_effect=self.work))
        self.tool = self.stack.enter_context(patch.object(M, "uat", side_effect=self.uat))
        self.stack.enter_context(patch.object(M, "pak_game_path", side_effect=lambda gr: "Marvel/Content/Marvel/" + gr))
        self.calls, self.compiled = [], None
        self.write_project(TARGET, document(TARGET, .5))
        self.write_project(SOURCE, document(SOURCE, .6))
        self.source_before = self.path(SOURCE).read_bytes()

    def tearDown(self):
        self.assertEqual(self.path(SOURCE).read_bytes(), self.source_before)
        self.stack.close()
        self.temp.cleanup()

    def path(self, gr, project=None):
        return (project or self.project) / (gr + ".json")

    def write_project(self, gr, d):
        path = self.path(gr)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(d), encoding="utf-8")

    def work(self, gr):
        path = self.root / "work" / gr
        path.parent.mkdir(parents=True, exist_ok=True)
        path.with_suffix(".uasset").write_bytes(b"fixture package")
        return str(path)

    def uat(self, args):
        self.calls.append(args)
        if args[0] == "to_json":
            source = Path(args[1])
            gr = source.relative_to(self.root / "work").as_posix()[:-7]
            Path(args[3], source.stem + ".json").write_text(json.dumps(self.docs[gr]), encoding="utf-8")
        elif args[0] == "from_json":
            self.compiled = json.loads(Path(args[1]).read_text(encoding="utf-8"))
            Path(args[2]).write_bytes(b"compiled material")
            Path(args[2][:-7] + ".uexp").write_bytes(b"shader resource")
        else:
            self.fail("Unexpected native command")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def call(self, path, body=None, query=None, project="A"):
        env = {}
        setup_testing_defaults(env)
        payload = json.dumps(body).encode() if body is not None else b""
        env.update(REQUEST_METHOD="POST" if body is not None else "GET", PATH_INFO=path,
                   QUERY_STRING=urlencode(query or {}), CONTENT_TYPE="application/json",
                   CONTENT_LENGTH=str(len(payload)), **{"wsgi.input": io.BytesIO(payload)})
        env["HTTP_X_ATELIER_PROJECT"] = quote(project, safe="")
        statuses = []
        response = R.app(env, lambda status, headers, exc_info=None: statuses.append(status))
        try:
            return int(statuses[0].split()[0]), json.loads(b"".join(response))
        finally:
            if hasattr(response, "close"):
                response.close()

    def test_replace_preserves_donor_graph_shader_and_target_identity(self):
        result = M.replace_material(TARGET, "/Game/Marvel/" + SOURCE + ".MI_Galaxy")
        d = json.loads(self.path(TARGET).read_text())
        self.assertEqual(d["Imports"], self.docs[SOURCE]["Imports"])
        self.assertEqual(d["Exports"][0]["Data"], self.docs[SOURCE]["Exports"][0]["Data"])
        self.assertEqual(d["Exports"][0]["Extras"], "cooked shader data")
        self.assertEqual(d["Exports"][0]["ObjectName"], "MI_Body")
        self.assertEqual(d["FolderName"], "/Game/Marvel/" + TARGET)
        self.assertEqual(d["SoftObjectPathList"], ["/Game/Marvel/" + TARGET + ".MI_Body"])
        self.assertEqual(result["colors"][0]["rgba"][0], .9)  # donor project .6 is deliberately ignored
        self.assertEqual(result["textures"], {"BaseColor": TEX})
        self.assertEqual(result["material_source"], SOURCE)

    def test_export_uses_current_donor_and_retains_saved_edits(self):
        M.replace_material(TARGET, SOURCE)
        M.save_material(TARGET, {"Tint": [.8, .1, .2, 1]}, {"Speed": 0})
        self.docs[SOURCE]["Exports"][0]["Extras"] = "updated cooked shader"
        M.stage_material(str(self.stage), TARGET, {}, {})
        self.assertEqual(self.compiled["Exports"][0]["Extras"], "updated cooked shader")
        self.assertEqual(self.compiled["Exports"][0]["ObjectName"], "MI_Body")
        self.assertEqual(self.compiled["Imports"], self.docs[SOURCE]["Imports"])
        self.assertNotIn(M._SOURCE_KEY, self.compiled)
        colors, scalars = M._mat_params(self.compiled)
        self.assertEqual(colors[0]["rgba"], [.8, .1, .2, 1])
        self.assertEqual(scalars[0]["value"], 0)
        self.assertEqual(sorted(p.name for p in self.stage.rglob("*") if p.is_file()), ["MI_Body.uasset", "MI_Body.uexp"])

    def test_repatch_ignores_project_replacement(self):
        M.replace_material(TARGET, SOURCE)
        M.stage_material(str(self.stage), TARGET, {}, {}, use_project=False)
        self.assertEqual(M._mat_params(self.compiled)[0][0]["rgba"][0], .1)

    def test_failed_decode_or_write_keeps_previous_target(self):
        before = self.path(TARGET).read_bytes()
        with patch.object(M, "uat", return_value=SimpleNamespace(returncode=1, stderr="decode failed", stdout="")):
            with self.assertRaisesRegex(RuntimeError, "decode failed"):
                M.replace_material(TARGET, SOURCE)
        self.assertEqual(self.path(TARGET).read_bytes(), before)
        from atelier import storage
        real_write = storage.atomic_json
        def fail_target(path, data, **kwargs):
            if Path(path) == self.path(TARGET):
                raise OSError("disk full")
            return real_write(path, data, **kwargs)
        with patch.object(storage, "atomic_json", side_effect=fail_target):
            with self.assertRaisesRegex(OSError, "disk full"):
                M.replace_material(TARGET, SOURCE)
        self.assertEqual(self.path(TARGET).read_bytes(), before)

    def test_metadata_failure_rolls_back_material_and_all_options(self):
        from atelier import storage
        project_meta.set_asset_opts(str(self.project), TARGET, {"dye_off": True, "color_inten": {"Tint": 2}})
        meta = self.project / ".atelier" / "project.json"
        before_doc, before_meta = self.path(TARGET).read_bytes(), meta.read_bytes()
        real_write = storage.atomic_json
        def fail_metadata(path, data, **kwargs):
            if Path(path) == meta:
                raise OSError("metadata write failed")
            return real_write(path, data, **kwargs)
        with patch.object(storage, "atomic_json", side_effect=fail_metadata):
            with self.assertRaisesRegex(OSError, "metadata write failed"):
                M.replace_material(TARGET, SOURCE)
        self.assertEqual(self.path(TARGET).read_bytes(), before_doc)
        self.assertEqual(meta.read_bytes(), before_meta)

    def test_reset_restores_original_and_failure_preserves_replacement(self):
        M.replace_material(TARGET, SOURCE)
        before = self.path(TARGET).read_bytes()
        with patch.object(M, "_original_document", side_effect=RuntimeError("offline")):
            with self.assertRaisesRegex(RuntimeError, "offline"):
                M.reset_material(TARGET)
        self.assertEqual(self.path(TARGET).read_bytes(), before)
        result = M.reset_material(TARGET)
        self.assertEqual(result["material_source"], "")
        self.assertEqual(result["colors"][0]["rgba"][0], .1)

    def test_invalid_source_and_non_material_class_never_change_target(self):
        before = self.path(TARGET).read_bytes()
        for source in (TARGET, "../MI_Outside", "C:/MI_Outside", "Characters/T_Texture", None):
            with self.subTest(source=source), self.assertRaises(ValueError):
                M.replace_material(TARGET, source)
        with patch("atelier.index.get_content_prefix", return_value="Engine/Content/"):
            with self.assertRaisesRegex(ValueError, "main game content"):
                M.replace_material(TARGET, SOURCE)
        self.docs[SOURCE]["Imports"][0]["ObjectName"] = "Texture2D"
        with self.assertRaisesRegex(ValueError, "MaterialInstanceConstant"):
            M.replace_material(TARGET, SOURCE)
        self.assertEqual(self.path(TARGET).read_bytes(), before)

    def test_recursive_parent_rejected_before_save_and_after_game_update(self):
        self.docs[SOURCE] = document(SOURCE, parent=TARGET, parent_class="MaterialInstanceConstant")
        before = self.path(TARGET).read_bytes()
        with self.assertRaisesRegex(ValueError, "inherits from the target"):
            M.replace_material(TARGET, SOURCE)
        self.assertEqual(self.path(TARGET).read_bytes(), before)
        # Simulate a donor that gained a dependency on the overridden material after saving.
        self.write_project(TARGET, {**document(TARGET), M._SOURCE_KEY: SOURCE})
        with self.assertRaisesRegex(ValueError, "inherits from the target"):
            M.stage_material(str(self.stage), TARGET, {}, {})
        self.assertFalse(list(self.stage.rglob("*.uasset")))

    def test_indirect_parent_cycle_rejected(self):
        intermediate = "Characters/1002/Materials/MI_Intermediate"
        self.docs[SOURCE] = document(SOURCE, parent=intermediate, parent_class="MaterialInstanceConstant")
        self.docs[intermediate] = document(intermediate, parent=TARGET, parent_class="MaterialInstanceConstant")
        with self.assertRaisesRegex(ValueError, "inherits from the target"):
            M.replace_material(TARGET, SOURCE)

    def test_api_binds_project_and_clears_incompatible_texture_options(self):
        opts = {"custom_textures": {"OldSlot": {}}, "dye_off": True, "color_inten": {"Tint": 3}, "lq_twin": True}
        project_meta.set_asset_opts(str(self.projects / "B"), TARGET, opts)
        before_a = self.path(TARGET).read_bytes()
        status, result = self.call("/api/material_replace", {"game_rel": TARGET, "source_game_rel": SOURCE}, project="B")
        self.assertEqual(status, 200)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["material_source"], SOURCE)
        self.assertEqual(self.path(TARGET).read_bytes(), before_a)
        self.assertEqual(project_meta.get_asset_opts(str(self.projects / "B"), TARGET), {"lq_twin": True})
        self.assertFalse(self.call("/api/material_replace", {"game_rel": TARGET, "source_game_rel": "../MI_Outside"})[1]["ok"])
        self.assertEqual(self.call("/api/material_replace", {"game_rel": TARGET, "source_game_rel": SOURCE}, project="Missing")[0], 400)

    def test_search_does_not_extract_or_import_and_reports_truncation(self):
        entries = [(f"Characters/1002/Materials/MI_Galaxy_{n:03}.uasset", "pak", "Marvel/Content/Marvel/") for n in range(85)]
        entries += [("Characters/1002/Textures/T_Galaxy.uasset", "pak", "Marvel/Content/Marvel/")]
        with patch("atelier.index.ensure_index", return_value=entries), \
                patch("atelier.handlers.skinnames.char_name", return_value="Fixture Hero"), \
                patch("atelier.handlers.skinnames.skin_name", return_value="Cosmic Outfit"):
            status, result = self.call("/api/material_sources", query={"q": "hero cosmic GALAXY"})
        self.assertEqual(status, 200)
        self.assertEqual(len(result["materials"]), 80)
        self.assertTrue(result["more"])
        self.assertIn("Fixture Hero", next(iter(result["labels"].values())))
        self.tool.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
