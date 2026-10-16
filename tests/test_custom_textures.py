"""A user's own image as a brand-new texture for one material slot (handlers/custom_texture.py).

The native tool is replaced by a fake that speaks the same file contract (inject_texture writes
.uasset/.uexp/.ubulk at the output path, to_json/from_json round-trip JSON), so these checks cover
what Atelier itself decides: names, storage, the import rewiring and what lands in the stage."""
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
_data = tempfile.TemporaryDirectory(prefix="atelier-custom-texture-tests-")
os.environ["ATELIER_DATA_DIR"] = _data.name
from PIL import Image
from atelier import config as C, project_meta
from atelier.handlers import custom_texture as CT, material as M, texture as T
from atelier.web import browse as B, routes as R

atexit.register(lambda: (R._observer.stop(), R._observer.join(), _data.cleanup()))

MI = "Characters/1015/1015502/Materials/MI_Body"
BASE_TEX = "Characters/1015/1015502/Textures/T_Body_D"
NORMAL_TEX = "Characters/1015/1015502/Textures/T_Body_N"


def png(size=(8, 8), color=(255, 0, 0, 255)):
    out = io.BytesIO()
    Image.new("RGBA", size, color).save(out, "PNG")
    return out.getvalue()


def material_json(tint=.5):
    """A cooked MI as UAssetAPI JSON: two Texture2D slots and one cube slot."""
    def entry(name, value):
        return {"Value": [{"Name": "ParameterInfo", "Value": [{"Name": "Name", "Value": name}]},
                          {"Name": "ParameterValue", "Value": value, "IsZero": False}]}
    imp = lambda name, outer, cls, pkg="/Script/Engine": {
        "$type": "UAssetAPI.Import, UAssetAPI", "ObjectName": name, "OuterIndex": outer,
        "ClassPackage": pkg, "ClassName": cls, "PackageName": None, "bImportOptional": False}
    return {
        "NameMap": ["/Game/Marvel/" + BASE_TEX, "T_Body_D", "/Game/Marvel/" + NORMAL_TEX, "T_Body_N"],
        "Imports": [imp("/Game/Marvel/" + BASE_TEX, 0, "Package", "/Script/CoreUObject"),
                    imp("T_Body_D", -1, "Texture2D"),
                    imp("/Game/Marvel/" + NORMAL_TEX, 0, "Package", "/Script/CoreUObject"),
                    imp("T_Body_N", -3, "Texture2D"),
                    imp("/Game/Marvel/Env/Cube", 0, "Package", "/Script/CoreUObject"),
                    imp("Cube", -5, "TextureCube")],
        "Exports": [{"ObjectName": "MI_Body", "Data": [
            {"Name": "VectorParameterValues", "Value": [entry("Tint", [{"Value": {"R": tint, "G": 0, "B": 0, "A": 1}}])]},
            {"Name": "ScalarParameterValues", "Value": []},
            {"Name": "TextureParameterValues", "Value": [entry("BaseColor", -2), entry("Normal", -4),
                                                          entry("Reflection", -6)]}]}]}


def texture_json(name):
    return {"FolderName": "/Game/Marvel/Characters/1015/1015502/Textures/" + name,
            "NameMap": [name], "Imports": [],
            "Exports": [{"ObjectName": name, "OuterIndex": 0, "Data": [], "Extras": "AAAA"}]}


class FakeUAssetTool:
    """inject_texture/to_json/from_json with the file layout UAssetTool produces."""

    def __init__(self, test):
        self.test, self.calls, self.compiled = test, [], {}
        self.rename_breaks_mips = False      # the renamed package decodes to the 4x4 tail
        self.undecodable = False             # extract_texture produces nothing at all

    def __call__(self, args):
        self.calls.append(list(args))
        cmd = args[0]
        if cmd == "inject_texture":
            template, image, out = args[1], args[2], args[3]
            self.test.assertTrue(os.path.isfile(image), "inject must read the stored project image")
            stem = out[:-7]
            for ext in (".uasset", ".uexp", ".ubulk"):
                Path(stem + ext).write_bytes(f"{ext} from {os.path.basename(template)}".encode())
            Path(out + ".template").write_text(os.path.basename(template)[:-7])
        elif cmd == "to_json":
            src, out_dir = args[1], args[3]
            stem = os.path.basename(src)[:-7]
            if os.path.exists(src + ".template"):           # an injected texture: still the template's names
                data = texture_json(Path(src + ".template").read_text())
            else:
                data = material_json()
            Path(out_dir, stem + ".json").write_text(json.dumps(data))
        elif cmd == "from_json":
            jp, out = args[1], args[2]
            data = json.loads(Path(jp).read_text())
            self.compiled[os.path.basename(out)[:-7]] = data
            Path(out).write_bytes(b"uasset " + json.dumps(data).encode())
            Path(out[:-7] + ".uexp").write_bytes(b"uexp")
        elif cmd == "extract_texture":
            src, out = args[1], args[2]
            bulk = Path(src[:-7] + ".ubulk")
            if self.undecodable or not bulk.is_file():  # no mips beside it: nothing to decode
                return SimpleNamespace(returncode=1, stdout="", stderr="no mips")
            renamed = f"{os.sep}out{os.sep}" in src
            size = (4, 4) if renamed and self.rename_breaks_mips else (8, 8)
            Image.new("RGBA", size, tuple(bulk.read_bytes()[:3]) + (255,)).save(out)
        else:
            raise AssertionError("unexpected native command " + cmd)
        return SimpleNamespace(returncode=0, stdout="", stderr="")


class CustomTextureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="atelier-custom-texture-case-")
        root = Path(self.temp.name)
        self.projects = root / "projects"
        self.project = self.projects / "A"
        self.project.mkdir(parents=True)
        self.extracted = root / "extracted"
        self.extracted.mkdir()
        self.stage = root / "stage"
        self.stage.mkdir()
        self.cache = root / "cache"
        self.cache.mkdir()
        self.stack = ExitStack()
        self.stack.enter_context(patch.multiple(C, PROJECTS_ROOT=str(self.projects),
                                                IMPORT_ROOT=str(root / "imported"), _active_project="A"))
        self.stack.enter_context(patch.multiple(R, PROJECTS_ROOT=str(self.projects), IMPORT_ROOT=C.IMPORT_ROOT))
        self.stack.enter_context(patch.object(M, "_CACHE", str(self.cache)))
        self.uat = FakeUAssetTool(self)
        self.stack.enter_context(patch.object(M, "uat", self.uat))
        self.stack.enter_context(patch.object(CT, "uat", self.uat))
        self.stack.enter_context(patch.object(T, "ensure_work_base", side_effect=self.work_base))
        self.stack.enter_context(patch.object(M, "pak_game_path", side_effect=lambda gr: "Marvel/Content/Marvel/" + gr))
        mi = self.project / (MI + ".json")
        mi.parent.mkdir(parents=True)
        mi.write_text(json.dumps(material_json(.9)))

    def tearDown(self):
        self.stack.close()
        self.temp.cleanup()

    def work_base(self, game_rel):
        base = self.extracted / os.path.basename(game_rel)
        base.with_suffix(".uasset").write_bytes(b"vanilla " + game_rel.encode())
        return str(base)

    def assign(self, slot="BaseColor", data=None, filename="my paint v3.png", template=BASE_TEX):
        return CT.assign(MI, slot, filename, data or png(), template, str(self.project))

    def stored(self):
        folder = self.project / ".atelier" / "custom_textures"
        return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []

    # ── names, validation, storage ───────────────────────────────────────────────

    def test_names_are_ue_safe_and_keep_the_users_words(self):
        self.assertEqual(CT.texture_name("my paint v3.png"), "T_my_paint_v3")
        self.assertEqual(CT.texture_name("T_Hood_D.tga"), "T_Hood_D")
        self.assertEqual(CT.texture_name("C:\\art\\é.png"), "T_Custom")
        self.assertEqual(CT.texture_name("..//../x y--z.PNG"), "T_x_y_z")
        a = CT.package_game_rel(MI, "BaseColor", "T_x")
        self.assertTrue(a.startswith("Atelier/Custom/") and a.endswith("/T_x"))
        self.assertNotEqual(a, CT.package_game_rel(MI, "Normal", "T_x"), "two slots must never share a package")

    def test_images_must_have_power_of_two_sides(self):
        for size in ((1000, 1000), (2, 2), (16384, 16)):
            with self.subTest(size=size), self.assertRaisesRegex(ValueError, "power of two"):
                self.assign(data=png(size))
        with self.assertRaisesRegex(ValueError, "not an image"):
            self.assign(data=b"not an image")
        self.assertEqual(self.stored(), [])
        self.assertEqual(self.assign(data=png((512, 256)))["BaseColor"]["size"], [512, 256])

    def test_assignment_is_stored_out_of_the_edit_list_and_pruned_when_replaced(self):
        view = self.assign()
        rec = view["BaseColor"]
        self.assertEqual(rec["name"], "T_my_paint_v3")
        self.assertEqual(rec["source"], "my paint v3.png")
        self.assertEqual(rec["template"], BASE_TEX)
        self.assertEqual(rec["game_rel"], CT.package_game_rel(MI, "BaseColor", "T_my_paint_v3"))
        first = self.stored()
        self.assertEqual(len(first), 1)
        self.assertEqual(project_meta.get_asset_opts(str(self.project), MI)["custom_textures"]["BaseColor"]["file"], first[0])
        # The edit-list walker must not see the stored image as a texture edit.
        with patch.object(B, "get_import_root", return_value=str(self.project)):
            self.assertEqual([i["game_rel"] for i in B.all_imported()], [MI])
        # The same image in two slots is stored once; replacing one slot keeps the shared file.
        self.assign(slot="Normal", template=NORMAL_TEX)
        self.assertEqual(self.stored(), first)
        self.assign(data=png(color=(0, 255, 0, 255)))
        self.assertEqual(len(self.stored()), 2)
        CT.clear(MI, "Normal", str(self.project))
        self.assertEqual(len(self.stored()), 1, "an image no slot uses any more is pruned")
        self.assertEqual(CT.clear(MI, None, str(self.project)), {})
        self.assertEqual(self.stored(), [])
        self.assertNotIn(MI, project_meta.get_asset_opts(str(self.project)))

    def test_tampered_records_are_ignored(self):
        project_meta.set_asset_opts(str(self.project), MI, {"custom_textures": {
            "BaseColor": {"name": "T_ok", "file": "../../outside.png"},
            "Normal": {"name": "bad name", "file": "0123456789abcdef0123.png"}}})
        self.assertEqual(CT.assignments(MI, str(self.project)), {})
        self.assertIsNone(CT.image_path(MI, "BaseColor", str(self.project)))

    # ── export ───────────────────────────────────────────────────────────────────

    def test_export_builds_the_texture_and_points_the_slot_at_it(self):
        self.assign()
        with patch.object(CT, "get_import_root", return_value=str(self.project)):
            label = M.stage_material(str(self.stage), MI, {}, {})
        self.assertEqual(label, "MI_Body (+1 custom texture)")
        new_gr = CT.package_game_rel(MI, "BaseColor", "T_my_paint_v3")
        new_pkg = "/Game/Marvel/" + new_gr
        # The texture: injected into a copy of the slot's game texture, then renamed.
        inject = next(c for c in self.uat.calls if c[0] == "inject_texture")
        self.assertTrue(inject[1].endswith("T_Body_D.uasset"), "the slot's own texture is the template")
        tex = self.uat.compiled["T_my_paint_v3"]
        self.assertEqual(tex["Exports"][0]["ObjectName"], "T_my_paint_v3")
        self.assertEqual(tex["FolderName"], new_pkg)
        self.assertIn("T_my_paint_v3", tex["NameMap"])
        staged_tex = self.stage / "Marvel/Content/Marvel" / new_gr
        for ext in (".uasset", ".uexp", ".ubulk"):
            self.assertTrue(staged_tex.with_suffix(ext).is_file(), ext)
        self.assertEqual(staged_tex.with_suffix(".ubulk").read_bytes(), b".ubulk from T_Body_D.uasset",
                         "the bulk mips ship exactly as inject_texture wrote them")
        # The material: two cloned imports, and BaseColor now points at the new Texture2D.
        mat = self.uat.compiled["MI_Body"]
        imports = mat["Imports"]
        self.assertEqual(len(imports), 8)
        pkg, obj = imports[6], imports[7]
        self.assertEqual((pkg["ObjectName"], pkg["OuterIndex"], pkg["ClassName"]), (new_pkg, 0, "Package"))
        self.assertEqual((obj["ObjectName"], obj["OuterIndex"], obj["ClassName"]), ("T_my_paint_v3", -7, "Texture2D"))
        slots = M.texture_slots(mat)
        self.assertEqual(slots["BaseColor"]["value"]["Value"], -8)
        self.assertEqual(slots["BaseColor"]["game_rel"], new_gr)
        self.assertEqual(slots["Normal"]["game_rel"], NORMAL_TEX, "other slots are untouched")
        self.assertIn(new_pkg, mat["NameMap"])
        self.assertTrue((self.stage / "Marvel/Content/Marvel" / (MI + ".uasset")).is_file())
        # The vanilla template is never written to the stage.
        self.assertFalse((self.stage / "Marvel/Content/Marvel" / (BASE_TEX + ".uasset")).exists())

    def test_a_rename_that_changes_the_decoded_texture_is_not_shipped(self):
        self.assign()
        self.uat.rename_breaks_mips = True
        with patch.object(CT, "get_import_root", return_value=str(self.project)), \
             self.assertRaisesRegex(RuntimeError, r"changed it \(decoded 4×4 instead of 8×8\)"):
            M.stage_material(str(self.stage), MI, {}, {})
        self.assertEqual(list(self.stage.rglob("*.uasset")), [], "neither the texture nor the material ships")
        decodes = [c[1] for c in self.uat.calls if c[0] == "extract_texture"]
        self.assertEqual(len(decodes), 2)
        self.assertIn(f"{os.sep}inject{os.sep}", decodes[0])
        self.assertIn(f"{os.sep}out{os.sep}", decodes[1])

    def test_an_undecodable_encoding_ships_unverified_like_a_texture_edit(self):
        self.assign()
        self.uat.undecodable = True
        with patch.object(CT, "get_import_root", return_value=str(self.project)):
            self.assertEqual(M.stage_material(str(self.stage), MI, {}, {}), "MI_Body (+1 custom texture)")
        self.assertEqual(sum(c[0] == "extract_texture" for c in self.uat.calls), 1,
                         "without a baseline the renamed package is not decoded")

    def test_a_slot_the_game_material_no_longer_has_fails_without_staging_anything(self):
        project_meta.set_asset_opts(str(self.project), MI, {"custom_textures": {
            "Gone": {"name": "T_x", "file": "0123456789abcdef0123.png"}}})
        with patch.object(CT, "get_import_root", return_value=str(self.project)), \
             self.assertRaisesRegex(RuntimeError, "no longer has texture slots: Gone"):
            M.stage_material(str(self.stage), MI, {}, {})
        self.assertEqual(list(self.stage.rglob("*.uasset")), [])

    def test_missing_image_and_non_2d_slots_are_reported(self):
        project_meta.set_asset_opts(str(self.project), MI, {"custom_textures": {
            "BaseColor": {"name": "T_x", "file": "0123456789abcdef0123.png", "source": "x.png"}}})
        with patch.object(CT, "get_import_root", return_value=str(self.project)), \
             self.assertRaisesRegex(RuntimeError, "x.png is missing"):
            M.stage_material(str(self.stage), MI, {}, {})
        project_meta.set_asset_opts(str(self.project), MI, {"custom_textures": {
            "Reflection": {"name": "T_x", "file": "0123456789abcdef0123.png"}}})
        with patch.object(CT, "get_import_root", return_value=str(self.project)), \
             self.assertRaisesRegex(RuntimeError, "only Texture2D"):
            M.stage_material(str(self.stage), MI, {}, {})
        self.assertEqual(list(self.stage.rglob("*.uasset")), [])

    def test_repatch_staging_ships_no_project_images(self):
        self.assign()
        with patch.object(CT, "get_import_root", return_value=str(self.project)):
            self.assertEqual(M.stage_material(str(self.stage), MI, {}, {}, use_project=False), "MI_Body")
        self.assertFalse(any(c[0] == "inject_texture" for c in self.uat.calls))

    def test_rename_refuses_an_ambiguous_template(self):
        doc = texture_json("T_A")
        doc["Exports"].append(dict(doc["Exports"][0]))
        with self.assertRaisesRegex(RuntimeError, "2 top-level exports"):
            CT.rename_package(doc, "T_A", "T_B", "/Game/Marvel/Atelier/Custom/k/T_B")
        cooked = texture_json("T_A")
        cooked["FolderName"] = "None"
        CT.rename_package(cooked, "T_A", "T_B", "/Game/Marvel/Atelier/Custom/k/T_B")
        self.assertEqual(cooked["FolderName"], "None", "a cooked 'None' folder name stays as it is")

    # ── API ──────────────────────────────────────────────────────────────────────

    def call(self, method, path, query=None, body=None, files=None, form=None):
        env = {}
        setup_testing_defaults(env)
        payload, ctype = b"", ""
        if files is not None:
            boundary = "atelierboundary"
            parts = []
            for k, v in (form or {}).items():
                parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
            for k, (fname, data) in files.items():
                parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"; filename="{fname}"\r\n'
                             f'Content-Type: image/png\r\n\r\n'.encode() + data + b"\r\n")
            payload = b"".join(parts) + f"--{boundary}--\r\n".encode()
            ctype = "multipart/form-data; boundary=" + boundary
        elif body is not None:
            payload, ctype = json.dumps(body).encode(), "application/json"
        env.update(REQUEST_METHOD=method, PATH_INFO=path, QUERY_STRING=urlencode(query or {}),
                   CONTENT_TYPE=ctype, CONTENT_LENGTH=str(len(payload)),
                   HTTP_X_ATELIER_PROJECT=quote("A", safe=""), **{"wsgi.input": io.BytesIO(payload)})
        statuses, headers = [], []
        result = R.app(env, lambda status, h, exc_info=None: (statuses.append(status), headers.extend(h)))
        data = b"".join(result)
        if hasattr(result, "close"):
            result.close()
        return int(statuses[0].split()[0]), data, dict(headers)

    def test_api_assigns_previews_lists_resets_and_clears(self):
        status, data, _ = self.call("POST", "/api/material_custom_texture", files={"file": ("Hood Paint.png", png((16, 16)))},
                                    form={"game_rel": MI, "slot": "BaseColor"})
        res = json.loads(data)
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["custom_textures"]["BaseColor"]["name"], "T_Hood_Paint")
        status, data, headers = self.call("GET", "/api/material_custom_texture/preview",
                                          {"game_rel": MI, "slot": "BaseColor"})
        self.assertEqual((status, headers.get("Content-Type")), (200, "image/png"))
        self.assertEqual(Image.open(io.BytesIO(data)).size, (16, 16))
        params = json.loads(self.call("GET", "/api/material_params", {"game_rel": MI})[1])
        self.assertEqual(params["custom_textures"]["BaseColor"]["source"], "Hood Paint.png")
        self.assertEqual(params["texture_classes"], {"BaseColor": "Texture2D", "Normal": "Texture2D",
                                                     "Reflection": "TextureCube"})
        # Rejections name the reason and change nothing.
        for form, error in (({"game_rel": MI, "slot": "Nope"}, "no texture slot named"),
                            ({"game_rel": MI, "slot": "Reflection"}, "only Texture2D"),
                            ({"game_rel": BASE_TEX, "slot": "BaseColor"}, "only be assigned to a material")):
            with self.subTest(form=form):
                res = json.loads(self.call("POST", "/api/material_custom_texture",
                                           files={"file": ("x.png", png())}, form=form)[1])
                self.assertFalse(res["ok"])
                self.assertIn(error, res["error"])
        res = json.loads(self.call("POST", "/api/material_custom_texture", files={"file": ("x.png", png((100, 100)))},
                                   form={"game_rel": MI, "slot": "Normal"})[1])
        self.assertIn("power of two", res["error"])
        self.assertEqual(list(CT.assignments(MI, str(self.project))), ["BaseColor"])
        # Restoring game defaults restores the game's textures too.
        res = json.loads(self.call("POST", "/api/material_reset", body={"game_rel": MI})[1])
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["custom_textures"], {})
        self.assertEqual(self.stored(), [])
        self.call("POST", "/api/material_custom_texture", files={"file": ("x.png", png())},
                  form={"game_rel": MI, "slot": "Normal"})
        res = json.loads(self.call("POST", "/api/material_custom_texture/clear", body={"game_rel": MI, "slot": "Normal"})[1])
        self.assertEqual((res["ok"], res["custom_textures"]), (True, {}))
        self.assertEqual(self.call("GET", "/api/material_custom_texture/preview", {"game_rel": MI, "slot": "Normal"})[0], 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
