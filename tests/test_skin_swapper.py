"""Project Galacta Skin Swapper export (atelier/skin_swapper.py).

Galacta's template may not be redistributed outside Atelier, so it is never in this repository.
These checks use a JSON document shaped exactly like UAssetTool's reading of it (one tagged export,
class and default-object imports named Export_0/Export_1, a mesh package import plus its
SkeletalMesh import) and replace the native tool, so they cover Atelier's own decisions: the IDs,
the names, every rule the cooked config is held to, the off switch and what may reach the stage.
The real template and tools were exercised end to end separately (see the module docstring)."""
import atexit
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import quote
from wsgiref.util import setup_testing_defaults

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
_data = tempfile.TemporaryDirectory(prefix="atelier-skin-swapper-tests-")
os.environ["ATELIER_DATA_DIR"] = _data.name
from atelier import config as C, skin_swapper as S  # noqa: E402
from atelier.handlers import meshreplace as MR  # noqa: E402
from atelier.web import routes as R  # noqa: E402
import stage_tools as ST  # noqa: E402

atexit.register(lambda: (R._observer.stop(), R._observer.join(), _data.cleanup()))

MESH = "Characters/1024/1024503/Meshes/SK_1024_1024503"


def template_doc():
    """The shape of Galacta's GAL_ConfigTemplate as UAssetTool reads it (values from the real file)."""
    prop = lambda kind, name, value: {"$type": f"UAssetAPI.PropertyTypes.Objects.{kind}, UAssetAPI",
                                      "Name": name, "ArrayIndex": 0, "Value": value}
    old_pkg = "/Game/Marvel/ProjectGalacta/Meshes/1011/1011001/TestHulk/GAL_TestHulk1"
    old_mesh = "/Game/Marvel/ProjectGalacta/Meshes/1011/1011001/TestHulk/SK_HulkForm1"
    return {
        "NameMap": ["Author", "IntProperty", "MeshToSwap", "NativeClass", "None", "ObjectProperty",
                    "SkinName", "StrProperty", "TargetHeroID", "TargetSculptID", "TargetSkinID",
                    old_pkg, "GAL_TestHulk1", "/Script/CoreUObject", "Package", S.CLASS_PACKAGE,
                    "Object", "Export_0", "Export_1", old_mesh, "/Script/Engine", "SkeletalMesh",
                    "SK_HulkForm1"],
        "HasUnversionedProperties": False,
        "FolderName": old_pkg,
        "Exports": [{"ObjectName": "GAL_TestHulk1", "OuterIndex": 0, "ClassIndex": -1, "TemplateIndex": -2,
                     "Data": [prop("IntPropertyData", "TargetHeroID", 1011),
                              prop("IntPropertyData", "TargetSkinID", 1011001),
                              prop("IntPropertyData", "TargetSculptID", 1),
                              prop("StrPropertyData", "SkinName", "TestHulk"),
                              prop("StrPropertyData", "Author", "Saturn"),
                              prop("ObjectPropertyData", "MeshToSwap", -5),
                              prop("ObjectPropertyData", "NativeClass", -1)]}],
        "Imports": [
            {"ObjectName": "Export_0", "OuterIndex": -3, "ClassPackage": "/Script/CoreUObject", "ClassName": "Object"},
            {"ObjectName": "Export_1", "OuterIndex": -3, "ClassPackage": "/Script/CoreUObject", "ClassName": "Object"},
            {"ObjectName": S.CLASS_PACKAGE, "OuterIndex": 0, "ClassPackage": "/Script/CoreUObject", "ClassName": "Package"},
            {"ObjectName": old_mesh, "OuterIndex": 0, "ClassPackage": "/Script/CoreUObject", "ClassName": "Package"},
            {"ObjectName": "SK_HulkForm1", "OuterIndex": -4, "ClassPackage": "/Script/Engine", "ClassName": "SkeletalMesh"},
        ],
    }


def entry(sculpt=0, mod="RedeemedRedux"):
    layout = S.plan(mod, [{"game_rel": MESH, "sculpt": sculpt}], "The Redeemed Redux", "Tendo", check_edits=False)
    assert not layout["problems"], layout["problems"]
    return layout["entries"][0]


class TargetIds(unittest.TestCase):
    def test_ids_come_from_the_mesh_path(self):
        self.assertEqual(S.target_ids(MESH), ("1024", "1024503"))

    def test_a_skin_of_another_hero_or_a_non_character_path_has_no_ids(self):
        self.assertIsNone(S.target_ids("Characters/1024/1035503/Meshes/SK_X"))
        self.assertIsNone(S.target_ids("Weapons/1024/1024503/SK_X"))
        self.assertIsNone(S.target_ids(None))


class Plan(unittest.TestCase):
    def plan(self, meshes=None, mod="RedeemedRedux", skin="The Redeemed Redux", author="Tendo"):
        return S.plan(mod, meshes if meshes is not None else [{"game_rel": MESH, "sculpt": 0}], skin, author,
                      check_edits=False)

    def test_a_single_form_lays_out_the_galacta_folder(self):
        e = entry()
        self.assertEqual(e["folder"], "ProjectGalacta/Meshes/1024/1024503/RedeemedRedux")
        self.assertEqual(e["config_game_rel"], e["folder"] + "/GAL_RedeemedRedux")
        self.assertEqual(e["mesh_game_rel"], e["folder"] + "/SK_1024_1024503")
        self.assertEqual((e["hero_id"], e["skin_id"], e["sculpt"]), ("1024", "1024503", 0))

    def test_form_n_appends_s_n(self):
        self.assertEqual(entry(sculpt=1)["config_name"], "GAL_RedeemedRedux_S1")
        self.assertEqual(entry(sculpt=9)["config_name"], "GAL_RedeemedRedux_S9")

    def test_each_form_needs_its_own_mesh(self):
        result = self.plan([{"game_rel": MESH, "sculpt": 1}, {"game_rel": MESH + "_Form2", "sculpt": 1}])
        self.assertIn("Two meshes use form 1. Each form needs its own mesh.", result["problems"])

    def test_two_forms_get_two_configs(self):
        result = self.plan([{"game_rel": MESH, "sculpt": 0}, {"game_rel": MESH + "_Form2", "sculpt": 2}])
        self.assertEqual(result["problems"], [])
        self.assertEqual([e["config_name"] for e in result["entries"]], ["GAL_RedeemedRedux", "GAL_RedeemedRedux_S2"])

    def test_one_mod_targets_one_skin(self):
        result = self.plan([{"game_rel": MESH, "sculpt": 0},
                            {"game_rel": "Characters/1024/1024001/Meshes/SK_1024_1024001", "sculpt": 1}])
        self.assertIn("All meshes in one Skin Swapper mod must belong to the same skin.", result["problems"])

    def test_the_mod_name_must_be_a_package_safe_folder(self):
        for name in ("Redeemed Redux", "Redeemed-Redux", "", "x" * 49):
            with self.subTest(name=name):
                self.assertTrue(any("letters, digits and underscores" in p for p in self.plan(mod=name)["problems"]))

    def test_skin_name_and_author_are_required_single_lines(self):
        self.assertIn("Author is required.", self.plan(author="  ")["problems"])
        self.assertIn("Skin name must be one line of at most 64 characters.",
                      self.plan(skin="two\nlines")["problems"])

    def test_forms_are_whole_numbers_from_0_to_9(self):
        for sculpt in (10, -1, True, "1", 1.0):
            with self.subTest(sculpt=sculpt):
                problems = self.plan([{"game_rel": MESH, "sculpt": sculpt}])["problems"]
                self.assertIn("SK_1024_1024503: the form must be a number from 0 to 9.", problems)

    def test_a_mesh_outside_a_skin_folder_is_refused(self):
        problems = self.plan([{"game_rel": "Weapons/SK_Gun", "sculpt": 0}])["problems"]
        self.assertTrue(any("cannot be identified" in p for p in problems))

    def test_edit_problems_block_the_plan(self):
        with patch.object(S, "_edit_problem", return_value="SK_1024_1024503 has no edits."):
            result = S.plan("RedeemedRedux", [{"game_rel": MESH, "sculpt": 0}], "Skin", "Tendo")
        self.assertIn("SK_1024_1024503 has no edits.", result["problems"])


class EditedMeshesOnly(unittest.TestCase):
    """Rule 2: no game asset ships."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="atelier-skin-swapper-mesh-")
        self.base = os.path.join(self.temp.name, "SK_1024_1024503")
        self.patches = [patch.object(MR, "target_base", return_value=self.base),
                        patch.object(MR, "is_original", return_value=False)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def record(self, **fields):
        Path(self.base + ".blend").write_bytes(b"blend")
        Path(self.base + ".mesh.json").write_text(json.dumps({"version": 1, "game_rel": MESH, **fields}))

    def test_a_mesh_without_a_blend_has_no_edits(self):
        self.assertIn("has no edits", S._edit_problem(MESH))

    def test_an_unchanged_mesh_has_no_edits(self):
        self.record(state="original")
        with patch.object(MR, "is_original", return_value=True):
            self.assertIn("never the game's", S._edit_problem(MESH))

    def test_a_replacement_from_a_cooked_game_file_is_refused(self):
        self.record(state="replacement", source_format=".uasset", source_name="SK_1035_1035503.uasset")
        problem = S._edit_problem(MESH)
        self.assertIn("replaced with a cooked game mesh (SK_1035_1035503.uasset)", problem)

    def test_an_edited_or_imported_model_may_ship(self):
        self.record(state="replacement", source_format=".glb", source_name="mine.glb")
        self.assertIsNone(S._edit_problem(MESH))
        self.record(state="original", original_blend_sha256="changed")
        self.assertIsNone(S._edit_problem(MESH))


class ConfigPatch(unittest.TestCase):
    def test_the_template_becomes_this_meshs_config(self):
        e = entry(sculpt=1)
        doc = S.patch_config(template_doc(), e, "The Redeemed Redux", "Tendo")
        self.assertEqual(S.verify_config(doc, e, "The Redeemed Redux", "Tendo"), [])
        package = "/Game/Marvel/ProjectGalacta/Meshes/1024/1024503/RedeemedRedux/GAL_RedeemedRedux_S1"
        mesh = "/Game/Marvel/ProjectGalacta/Meshes/1024/1024503/RedeemedRedux/SK_1024_1024503"
        self.assertEqual(doc["FolderName"], package)
        self.assertEqual(doc["Exports"][0]["ObjectName"], "GAL_RedeemedRedux_S1")
        imports = [(i["ObjectName"], i["ClassPackage"], i["ClassName"]) for i in doc["Imports"]]
        self.assertEqual(imports, [
            ("GAL_ModSkinConfig_C", "/Script/Engine", "BlueprintGeneratedClass"),
            ("Default__GAL_ModSkinConfig_C", S.CLASS_PACKAGE, "GAL_ModSkinConfig_C"),
            (S.CLASS_PACKAGE, "/Script/CoreUObject", "Package"),
            (mesh, "/Script/CoreUObject", "Package"),
            ("SK_1024_1024503", "/Script/Engine", "SkeletalMesh")])
        values = {p["Name"]: p["Value"] for p in doc["Exports"][0]["Data"]}
        self.assertEqual(values, {"TargetHeroID": 1024, "TargetSkinID": 1024503, "TargetSculptID": 1,
                                  "SkinName": "The Redeemed Redux", "Author": "Tendo", "MeshToSwap": -5,
                                  "NativeClass": -1})

    def test_names_are_patched_in_place_so_every_index_stays_valid(self):
        before = template_doc()
        doc = S.patch_config(copy.deepcopy(before), entry(), "Skin", "Tendo")
        for i, name in enumerate(before["NameMap"][:11]):
            self.assertEqual(doc["NameMap"][i], name)            # property and type names keep their slots
        for gone in ("Export_0", "Export_1", "GAL_TestHulk1", "SK_HulkForm1"):
            self.assertNotIn(gone, doc["NameMap"])
        self.assertFalse(any("TestHulk" in n for n in doc["NameMap"]))
        self.assertIn("BlueprintGeneratedClass", doc["NameMap"])

    def test_a_template_missing_a_property_is_not_patched(self):
        doc = template_doc()
        doc["Exports"][0]["Data"] = [p for p in doc["Exports"][0]["Data"] if p["Name"] != "Author"]
        with self.assertRaisesRegex(ValueError, "no Author property"):
            S.patch_config(doc, entry(), "Skin", "Tendo")

    def test_a_template_with_two_exports_is_not_patched(self):
        doc = template_doc()
        doc["Exports"].append(copy.deepcopy(doc["Exports"][0]))
        with self.assertRaisesRegex(ValueError, "exactly one export"):
            S.patch_config(doc, entry(), "Skin", "Tendo")


class ConfigVerify(unittest.TestCase):
    def setUp(self):
        self.e = entry(sculpt=2)
        self.doc = S.patch_config(template_doc(), self.e, "Skin", "Tendo")

    def problems(self):
        return " | ".join(S.verify_config(self.doc, self.e, "Skin", "Tendo"))

    def test_unversioned_properties_fail(self):
        self.doc["HasUnversionedProperties"] = True
        self.assertIn("property tags, not unversioned", self.problems())

    def test_a_renamed_or_subclassed_class_fails(self):
        self.doc["Imports"][0]["ObjectName"] = "MyConfig_C"
        self.assertIn("class import", self.problems())
        self.doc = S.patch_config(template_doc(), self.e, "Skin", "Tendo")
        self.doc["Imports"][1]["ClassName"] = "MyConfig_C"
        self.assertIn("default object import", self.problems())

    def test_a_mesh_in_another_folder_fails(self):
        self.doc["Imports"][3]["ObjectName"] = "/Game/Marvel/Characters/1024/1024503/Meshes/SK_1024_1024503"
        self.assertIn("MeshToSwap package", self.problems())

    def test_ids_that_disagree_with_the_folder_fail(self):
        self.doc["Exports"][0]["Data"][1]["Value"] = 1024001
        self.assertIn("TargetSkinID", self.problems())

    def test_an_extra_property_or_package_reference_fails(self):
        self.doc["Exports"][0]["Data"].append({"$type": "UAssetAPI.PropertyTypes.Objects.IntPropertyData", "Name": "Price", "Value": 0})
        self.doc["Imports"].append({"ObjectName": "/Game/Marvel/Characters/1024/1024503/Meshes/SK_Paid",
                                    "OuterIndex": 0, "ClassPackage": "/Script/CoreUObject", "ClassName": "Package"})
        problems = self.problems()
        self.assertIn("unexpected properties: Price", problems)
        self.assertIn("references another package", problems)


class OffSwitch(unittest.TestCase):
    """Rule 5: Galacta can switch generation off for every install."""
    def setUp(self):
        Path(S._flag_path()).unlink(missing_ok=True)

    def response(self, payload):
        body = json.dumps(payload).encode()
        class Response(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False
        return Response(body)

    def test_a_never_published_switch_leaves_export_available(self):
        self.assertEqual(S.flag_state(), (True, ""))

    def test_galacta_can_switch_export_off_with_a_message(self):
        with patch.object(S.urllib.request, "urlopen",
                          return_value=self.response({"skin_swapper": {"enabled": False, "message": "Paused by request"}})):
            self.assertTrue(S.refresh_flag())
        self.assertEqual(S.flag_state(), (False, "Paused by request"))
        with patch.object(S, "template_files", return_value=(__file__, __file__)):
            state = S.status()
        self.assertFalse(state["available"])
        self.assertEqual(state["reasons"], ["Paused by request"])

    def test_an_unreachable_or_malformed_switch_keeps_the_last_known_value(self):
        with patch.object(S.urllib.request, "urlopen",
                          return_value=self.response({"skin_swapper": {"enabled": False}})):
            S.refresh_flag()
        with patch.object(S.urllib.request, "urlopen", side_effect=OSError("offline")):
            self.assertFalse(S.refresh_flag())
        with patch.object(S.urllib.request, "urlopen", return_value=self.response({"skin_swapper": {"enabled": "yes"}})):
            self.assertFalse(S.refresh_flag())
        self.assertEqual(S.flag_state()[0], False)

    def test_the_published_file_in_this_repository_parses(self):
        self.assertEqual(S.parse_flag(json.loads((ROOT / "integrations.json").read_text(encoding="utf-8"))),
                         {"enabled": True, "message": ""})


class StageAudit(unittest.TestCase):
    """Rules 3 and 4: only the planned Galacta packages, never skins.txt."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="atelier-skin-swapper-stage-")
        self.stage = self.temp.name
        self.e = entry()
        for key in ("mesh_game_rel", "config_game_rel"):
            path = S._stage_path(self.stage, self.e[key])
            os.makedirs(os.path.dirname(path), exist_ok=True)
            for ext in (".uasset", ".uexp"):
                Path(path + ext).write_bytes(b"x")

    def tearDown(self):
        self.temp.cleanup()

    def test_the_planned_packages_pass(self):
        S.audit_stage(self.stage, [self.e])

    def test_a_game_path_override_fails(self):
        path = Path(self.stage, "Marvel", "Content", "Marvel", "Characters", "1024", "1024503", "Meshes")
        path.mkdir(parents=True)
        (path / "SK_1024_1024503.uasset").write_bytes(b"x")
        with self.assertRaisesRegex(RuntimeError, "outside the planned Galacta packages"):
            S.audit_stage(self.stage, [self.e])

    def test_skins_txt_never_ships(self):
        Path(S._stage_path(self.stage, self.e["folder"]), "skins.txt").write_text("x")
        with self.assertRaisesRegex(RuntimeError, "skins.txt is the Companion App's file"):
            S.audit_stage(self.stage, [self.e])


class BuildGate(unittest.TestCase):
    def setUp(self):
        Path(S._flag_path()).unlink(missing_ok=True)
        self.refresh = patch.object(S, "refresh_flag", return_value=False)
        self.refresh.start()

    def tearDown(self):
        self.refresh.stop()

    def test_without_the_template_nothing_is_built(self):
        with patch.object(S, "template_files", return_value=("missing.uasset", "missing.uexp")):
            result = S.build("RedeemedRedux", [{"game_rel": MESH, "sculpt": 0}], "Skin", "Tendo", _data.name)
        self.assertFalse(result["ok"])
        self.assertIn("template is not installed", result["error"])

    def test_plan_problems_stop_the_build_and_are_listed(self):
        with patch.object(S, "template_files", return_value=(__file__, __file__)), \
             patch.object(S, "_edit_problem", return_value=None):
            result = S.build("Redeemed Redux", [{"game_rel": MESH, "sculpt": 0}], "Skin", "Tendo", _data.name)
        self.assertFalse(result["ok"])
        self.assertTrue(any("letters, digits and underscores" in p for p in result["problems"]))


class Routes(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="atelier-skin-swapper-routes-")
        projects = Path(self.temp.name, "projects")
        (projects / "A").mkdir(parents=True)
        self.patches = [patch.multiple(C, PROJECTS_ROOT=str(projects), _active_project="A"),
                        patch.multiple(R, PROJECTS_ROOT=str(projects))]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def call(self, method, path, body=None):
        env = {}
        setup_testing_defaults(env)
        raw = json.dumps(body or {}).encode()
        env.update(REQUEST_METHOD=method, PATH_INFO=path, CONTENT_TYPE="application/json",
                   CONTENT_LENGTH=str(len(raw)), HTTP_X_ATELIER_PROJECT=quote("A", safe=""),
                   **{"wsgi.input": io.BytesIO(raw)})
        statuses = []
        result = R.app(env, lambda status, headers, exc_info=None: statuses.append(status))
        data = b"".join(result)
        if hasattr(result, "close"):
            result.close()
        return int(statuses[0].split()[0]), json.loads(data)

    def test_status_reports_why_export_is_unavailable(self):
        with patch.object(S, "refresh_flag_async"), \
             patch.object(S, "template_files", return_value=("missing.uasset", "missing.uexp")):
            status, body = self.call("GET", "/api/skin_swapper/status")
        self.assertEqual(status, 200)
        self.assertFalse(body["available"])
        self.assertIn("Tools/Galacta", body["reasons"][0])

    def test_plan_returns_read_only_ids_and_problems(self):
        with patch.object(S, "_edit_problem", return_value=None):
            status, body = self.call("POST", "/api/skin_swapper/plan", {
                "mod_name": "RedeemedRedux", "skin_name": "Skin", "author": "",
                "meshes": [{"game_rel": MESH, "sculpt": 0}], "hero_id": "9999"})
        self.assertEqual(status, 200)
        self.assertEqual((body["hero_id"], body["skin_id"]), ("1024", "1024503"))
        self.assertIn("Author is required.", body["problems"])

    def test_a_failed_build_returns_its_problems(self):
        with patch.object(S, "build", return_value={"ok": False, "error": "not built", "problems": ["p1"]}):
            status, body = self.call("POST", "/api/skin_swapper/build", {"mod_name": "RedeemedRedux", "meshes": []})
        self.assertEqual(status, 200)
        self.assertEqual((body["ok"], body["problems"]), (False, ["p1"]))


class Packaging(unittest.TestCase):
    def test_the_template_is_optional_but_never_half_staged(self):
        with tempfile.TemporaryDirectory() as tmp:
            tools = Path(tmp)
            for rel, required in ST.MANIFEST["windows"]:
                if required and "." in Path(rel).name:
                    (tools / rel).parent.mkdir(parents=True, exist_ok=True)
                    (tools / rel).write_bytes(b"x")
            (tools / "AtelierMesh").mkdir(exist_ok=True)
            ST.validate_tools(tools, "windows")                          # absent: fine
            (tools / "Galacta").mkdir()
            (tools / "Galacta" / "GAL_ConfigTemplate.uasset").write_bytes(b"x")
            with self.assertRaisesRegex(RuntimeError, "Incomplete Skin Swapper template"):
                ST.validate_tools(tools, "windows")
            (tools / "Galacta" / "GAL_ConfigTemplate.uexp").write_bytes(b"x")
            ST.validate_tools(tools, "windows")                          # whole pair: fine

    def test_the_dist_audit_accepts_only_the_template_pair(self):
        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp)
            (dist / "_internal").mkdir()
            (dist / "Atelier.exe").write_bytes(b"x")
            (dist / "Tools" / "Galacta").mkdir(parents=True)
            for ext in (".uasset", ".uexp"):
                (dist / "Tools" / "Galacta" / ("GAL_ConfigTemplate" + ext)).write_bytes(b"x")
            ST.audit("windows", dist)
            (dist / "Tools" / "Galacta" / "SK_Game.uasset").write_bytes(b"x")
            with self.assertRaises(SystemExit):
                ST.audit("windows", dist)

    def test_git_ignores_the_template_everywhere(self):
        self.assertIn("GAL_ConfigTemplate.*", (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines())


if __name__ == "__main__":
    unittest.main(verbosity=2)
