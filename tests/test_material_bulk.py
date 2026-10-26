"""Reviewed material batches, metadata, parent graphs and export in disposable projects."""
import atexit
import copy
from contextlib import ExitStack
import io
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import urlencode
from wsgiref.util import setup_testing_defaults

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_data = tempfile.TemporaryDirectory(prefix="atelier-material-bulk-")
os.environ["ATELIER_DATA_DIR"] = _data.name
from atelier import bulk as B, config as C, jobs, project_meta, storage
from atelier.handlers import material as M, texture as T
from atelier.web import routes as R
from material_bulk_fixtures import material, BASE, NEW_PARENT, INSTANCE_PARENT, SOURCE


def cleanup():
    jobs.shutdown(5)
    R._observer.stop()
    R._observer.join()
    _data.cleanup()


atexit.register(cleanup)
A, OTHER = "Fixture/Materials/MI_One", "Fixture/Materials/MI_Two"


class MaterialBulkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="atelier-material-bulk-case-")
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / "projects" / "A"
        self.project.mkdir(parents=True)
        (self.root / "cache").mkdir()
        self.docs = {gr: material(gr, kind="Material" if gr in (BASE, NEW_PARENT) else "MaterialInstanceConstant")
                     for gr in (A, OTHER, SOURCE, BASE, NEW_PARENT, INSTANCE_PARENT)}
        self.stack = ExitStack()
        self.stack.enter_context(patch.object(C, "PROJECTS_ROOT", str(self.root / "projects")))
        self.stack.enter_context(patch.object(R, "PROJECTS_ROOT", str(self.root / "projects")))
        self.stack.enter_context(C.project_context(str(self.project)))
        self.original = self.stack.enter_context(patch.object(M, "_original_document", side_effect=lambda gr: copy.deepcopy(self.docs[gr])))
        self.stack.enter_context(patch.multiple(M, _CACHE=str(self.root / "cache")))
        B._plans.clear()
        self.compiled = None

    def tearDown(self):
        self.stack.close()
        B._plans.clear()
        self.temp.cleanup()

    def path(self, gr):
        return Path(C.project_base(gr) + ".json")

    def write(self, gr, document=None):
        path = self.path(gr)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document or self.docs[gr]), encoding="utf-8")
        return path

    def read(self, gr):
        return json.loads(self.path(gr).read_text(encoding="utf-8"))

    def review(self, assets, operation="set_opacity", **spec):
        return B.preview(assets, {"operation": operation, **spec})

    def test_hundreds_of_unimported_materials_review_without_project_writes(self):
        assets = [f"VFX/Materials/MI_Effect_{i:03}" for i in range(205)]
        self.docs.update({gr: material(gr) for gr in assets})
        result = self.review(assets, value=0)
        self.assertEqual(list(self.project.iterdir()), [])
        self.assertEqual(result["changed_assets"], 205)
        B.apply(result["preview_id"])
        self.assertEqual(len(list(self.project.rglob("MI_*.json"))), 205)
        for gr in (assets[0], assets[-1]):
            self.assertEqual(M._mat_params(self.read(gr))[1][-1]["value"], 0)

    def test_opacity_preserves_parameters_precision_source_and_options(self):
        document = {**material(A, opacity=.000000123), M._SOURCE_KEY: SOURCE}
        self.write(A, document)
        opts = {"custom_textures": {"BaseColor": {"file": "keep.png"}}, "dye_off": True,
                "color_inten": {"Tint": 3}, "lq_twin": True}
        project_meta.set_asset_opts(str(self.project), A, opts)
        result = self.review([A], value=0)
        self.assertEqual(result["assets"][0]["sample"]["before"], .000000123)
        B.apply(result["preview_id"])
        expected = copy.deepcopy(document)
        M._apply_mat_edits(expected, {}, {"Opacity": 0})
        self.assertEqual(self.read(A), expected)
        self.assertEqual(project_meta.get_asset_opts(str(self.project), A), opts)

    def test_missing_scalar_is_reported_and_never_imported(self):
        self.docs[OTHER] = material(OTHER, opacity=None)
        self.write(A)
        result = self.review([A, OTHER], value=0)
        self.assertEqual(result["changed_assets"], 1)
        self.assertIn("No existing scalar override", result["assets"][1]["note"])
        B.apply(result["preview_id"])
        self.assertFalse(self.path(OTHER).exists())

    def test_named_scalar_is_exact_case_insensitive_and_zero_can_become_nonzero(self):
        document = material(A, opacity=0)
        self.write(A, document)
        result = self.review([A], "set_scalar", parameter=" oPaCiTy ", value=2.75)
        B.apply(result["preview_id"])
        entries = M._gn(M._ex_props(self.read(A)["Exports"][0]), "ScalarParameterValues")["Value"]
        value = M._gn(entries[-1]["Value"], "ParameterValue")
        self.assertEqual(value["Value"], 2.75)
        self.assertFalse(value["IsZero"])
        self.assertIsNone(entries[-1]["OriginalStructHeader"])
        result = self.review([A], "set_scalar", parameter="Opac", value=0)
        self.assertEqual(result["changed_assets"], 0)

    def test_material_rgb_and_multiplication_keep_alpha_and_raw_precision(self):
        self.write(A)
        project_meta.set_asset_opts(str(self.project), A, {"color_inten": {"Tint": 2}, "dye_off": True})
        result = self.review([A], "multiply", scope="rgb", factor=2)
        B.apply(result["preview_id"])
        color = M._mat_color(M._gn(M._ex_props(self.read(A)["Exports"][0]), "VectorParameterValues")["Value"][0])
        self.assertEqual(color, {"R": .5, "G": .246913578, "B": 5., "A": .375})
        self.assertEqual(project_meta.get_asset_opts(str(self.project), A), {"dye_off": True})
        result = self.review([A], "recolor", color=[0, .1, .2])
        B.apply(result["preview_id"])
        self.assertEqual(M._mat_params(self.read(A))[0][0]["rgba"], [0, .1, .2, .375])

    def test_native_signed_zero_strings_are_read_without_changing_unselected_values(self):
        document = material(A, opacity=0)
        props = M._ex_props(document["Exports"][0])
        color = M._mat_color(M._gn(props, "VectorParameterValues")["Value"][0])
        color.update(R="+0", A="-0")
        scalar_entries = M._gn(props, "ScalarParameterValues")["Value"]
        M._gn(scalar_entries[0]["Value"], "ParameterValue")["Value"] = "-0"
        M._gn(scalar_entries[1]["Value"], "ParameterValue")["Value"] = "+0"
        self.write(A, document)
        result = self.review([A], value=.5)
        B.apply(result["preview_id"])
        expected = copy.deepcopy(document)
        M._apply_mat_edits(expected, {}, {"Opacity": .5})
        self.assertEqual(self.read(A), expected)
        result = self.review([A], "multiply", scope="rgb", factor=2)
        B.apply(result["preview_id"])
        saved = self.read(A)
        self.assertEqual(M._mat_params(saved)[0][0]["rgba"], [0, .24691, 5, -0.])
        color = M._mat_color(M._gn(M._ex_props(saved["Exports"][0]), "VectorParameterValues")["Value"][0])
        self.assertEqual(math.copysign(1, color["A"]), -1)

    def test_reparent_isolated_imports_keep_shared_texture_refs_and_saved_values(self):
        document = material(A)
        document["Imports"][4]["OuterIndex"] = -2  # Package shared with the old parent.
        self.write(A, document)
        result = self.review([A], "reparent", source="/Game/Marvel/" + NEW_PARENT + ".M_Alternate")
        self.assertEqual(self.read(A), document)
        B.apply(result["preview_id"])
        saved = self.read(A)
        self.assertEqual(saved["Imports"][:5], document["Imports"])
        self.assertEqual(M._mat_textures(saved), M._mat_textures(document))
        self.assertEqual(M._mat_params(saved), M._mat_params(document))
        self.assertEqual(M._mat_surface(saved)["parent_path"], NEW_PARENT)
        self.assertEqual(saved[M._PARENT_KEY], NEW_PARENT)
        self.assertEqual(M.read_material(A)["material_parent"], NEW_PARENT)
        self.assertIn("M_Alternate", saved["NameMap"])
        self.assertEqual(self.review([A], "reparent", source=NEW_PARENT)["changed_assets"], 0)

    def test_self_indirect_and_batch_parent_cycles_reject_before_any_write(self):
        for gr in (A, OTHER):
            self.write(gr)
        before = [self.path(gr).read_bytes() for gr in (A, OTHER)]
        for source in (A, OTHER):
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, "recursive"):
                self.review([A, OTHER], "reparent", source=source)
        self.docs[INSTANCE_PARENT] = material(INSTANCE_PARENT, parent=A, parent_class="MaterialInstanceConstant")
        with self.assertRaisesRegex(ValueError, "recursive"):
            self.review([A], "reparent", source=INSTANCE_PARENT)
        self.assertEqual([self.path(gr).read_bytes() for gr in (A, OTHER)], before)

    def test_parent_change_after_review_invalidates_entire_batch(self):
        for gr in (A, OTHER, INSTANCE_PARENT):
            self.write(gr)
        result = self.review([A, OTHER], "reparent", source=INSTANCE_PARENT)
        before = [self.path(gr).read_bytes() for gr in (A, OTHER)]
        self.write(INSTANCE_PARENT, material(INSTANCE_PARENT, opacity=.1))
        with self.assertRaisesRegex(RuntimeError, "changed after preview"):
            B.apply(result["preview_id"])
        self.assertEqual([self.path(gr).read_bytes() for gr in (A, OTHER)], before)

    def test_replacement_uses_vanilla_source_and_clears_only_affected_options(self):
        opts = {"custom_textures": {"BaseColor": {}}, "dye_off": True, "color_inten": {"Tint": 3}, "lq_twin": True}
        for gr in (A, OTHER, SOURCE):
            self.write(gr, material(gr, opacity=.1))
            project_meta.set_asset_opts(str(self.project), gr, opts)
        source_before = self.path(SOURCE).read_bytes()
        result = self.review([A, OTHER, SOURCE], "replace_material", source=SOURCE)
        self.assertEqual(result["changed_assets"], 2)
        self.assertIn("Source material", result["assets"][-1]["note"])
        B.apply(result["preview_id"])
        for gr in (A, OTHER):
            saved = self.read(gr)
            self.assertEqual(saved["Exports"][0]["ObjectName"], gr.rsplit("/", 1)[-1])
            self.assertEqual(saved[M._SOURCE_KEY], SOURCE)
            self.assertEqual(saved["Imports"], self.docs[SOURCE]["Imports"])
            self.assertEqual(M._mat_params(saved)[1][-1]["value"], .75)
            self.assertEqual(project_meta.get_asset_opts(str(self.project), gr), {"lq_twin": True})
        self.assertEqual(self.path(SOURCE).read_bytes(), source_before)
        self.assertEqual(project_meta.get_asset_opts(str(self.project), SOURCE), opts)

    def test_new_options_and_new_canonical_copy_cannot_bypass_a_review(self):
        legacy = Path(C.project_base_legacy(A) + ".json")
        legacy.write_text(json.dumps(material(A)), encoding="utf-8")
        result = self.review([A], value=0)
        self.write(A)
        with self.assertRaisesRegex(RuntimeError, "changed after preview"):
            B.apply(result["preview_id"])
        result = self.review([A], "replace_material", source=SOURCE)
        before = self.path(A).read_bytes()
        project_meta.set_asset_opts(str(self.project), A, {"dye_off": True})
        with self.assertRaisesRegex(RuntimeError, "changed after preview"):
            B.apply(result["preview_id"])
        self.assertEqual(self.path(A).read_bytes(), before)

    def test_failed_metadata_publication_restores_all_materials_and_options(self):
        for gr in (A, OTHER):
            self.write(gr)
            project_meta.set_asset_opts(str(self.project), gr, {"dye_off": True})
        meta = self.project / ".atelier" / "project.json"
        paths = [self.path(A), self.path(OTHER), meta]
        before = [p.read_bytes() for p in paths]
        result = self.review([A, OTHER], "replace_material", source=SOURCE)
        real = storage.atomic_json
        def fail(path, data, **kwargs):
            if Path(path) == meta:
                raise OSError("injected metadata failure")
            return real(path, data, **kwargs)
        with patch.object(storage, "atomic_json", side_effect=fail), self.assertRaises(OSError):
            B.apply(result["preview_id"])
        self.assertEqual([p.read_bytes() for p in paths], before)

    def export(self, *, use_project=True):
        def work(gr):
            path = self.root / "work" / gr
            path.parent.mkdir(parents=True, exist_ok=True)
            path.with_suffix(".uasset").write_bytes(b"fixture package")
            return str(path)
        def uat(args):
            if args[0] == "to_json":
                gr = Path(args[1]).relative_to(self.root / "work").as_posix()[:-7]
                Path(args[3], Path(gr).name + ".json").write_text(json.dumps(self.docs[gr]), encoding="utf-8")
            elif args[0] == "from_json":
                self.compiled = json.loads(Path(args[1]).read_text(encoding="utf-8"))
                Path(args[2]).write_bytes(b"fixture compiled material")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        with patch.object(T, "ensure_work_base", side_effect=work), patch.object(M, "uat", side_effect=uat), \
                patch.object(M, "pak_game_path", side_effect=lambda gr: "Marvel/Content/Marvel/" + gr):
            M.stage_material(str(self.root / "stage"), A, {}, {}, use_project=use_project)

    def test_export_reconstructs_donor_then_parent_and_scalar_edits_without_markers(self):
        for operation, spec in (("replace_material", {"source": SOURCE}), ("reparent", {"source": NEW_PARENT}), ("set_opacity", {"value": 0})):
            result = self.review([A], operation, **spec)
            B.apply(result["preview_id"])
        self.docs[SOURCE]["Exports"][0]["Extras"] = "current donor shader"
        self.export()
        self.assertEqual(self.compiled["Exports"][0]["Extras"], "current donor shader")
        self.assertEqual(M._mat_surface(self.compiled)["parent_path"], NEW_PARENT)
        self.assertEqual(M._mat_params(self.compiled)[1][-1]["value"], 0)
        self.assertEqual(M._mat_params(self.compiled, precision=None)[1][0]["value"], 1.234567891)
        self.assertEqual(M._mat_params(self.compiled, precision=None)[0][0]["rgba"][1], .123456789)
        self.assertNotIn(M._SOURCE_KEY, self.compiled)
        self.assertNotIn(M._PARENT_KEY, self.compiled)
        self.export(use_project=False)
        self.assertEqual(M._mat_surface(self.compiled)["parent_path"], BASE)
        self.assertEqual(M._mat_params(self.compiled)[1][-1]["value"], .75)

    def test_game_update_parent_cycle_is_rejected_at_export(self):
        result = self.review([A], "reparent", source=INSTANCE_PARENT)
        B.apply(result["preview_id"])
        self.docs[INSTANCE_PARENT] = material(INSTANCE_PARENT, parent=A, parent_class="MaterialInstanceConstant")
        with self.assertRaisesRegex(ValueError, "recursive"):
            self.export()
        self.assertIsNone(self.compiled)

    def test_invalid_inputs_and_case_or_separator_duplicates_never_write(self):
        cases = [([A, A.lower()], {"value": 0}), ([A, A.replace("/", "\\")], {"value": 0}),
                 ([A], {"value": float("nan")}), ([A], {"value": True}), ([A], {"value": -1}),
                 ([A], {"value": 2}), ([A, "Fixture/C_Curve"], {"value": 0}),
                 ([A], {"operation": "set_scalar", "parameter": "", "value": 0}),
                 ([A], {"operation": "reparent", "source": "../M_Outside"}),
                 ([A], {"operation": "reparent", "source": "Fixture/T_Texture"}),
                 ([None], {"value": 0}), ([A] * (B.MAX_ASSETS + 1), {"value": 0})]
        for items, spec in cases:
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                self.review(items, **spec)
        self.assertEqual(list(self.project.iterdir()), [])

    def test_parent_search_includes_base_materials_only_when_requested(self):
        from atelier import index
        entries = [(gr + ".uasset", "fixture", "Marvel/Content/Marvel/") for gr in (BASE, NEW_PARENT, SOURCE)]
        def search(parents):
            env = {}; setup_testing_defaults(env)
            env.update(PATH_INFO="/api/material_sources", QUERY_STRING=urlencode({"q": "Fixture", "parents": parents}),
                       HTTP_X_ATELIER_PROJECT="A", **{"wsgi.input": io.BytesIO(b"")})
            response = R.app(env, lambda *_args: None)
            try:
                return json.loads(b"".join(response))
            finally:
                if hasattr(response, "close"):
                    response.close()
        with patch.object(index, "ensure_index", return_value=entries):
            self.assertEqual(search("false")["materials"], [SOURCE])
            self.assertEqual(set(search("true")["materials"]), {BASE, NEW_PARENT, SOURCE})
        self.original.assert_not_called()
        self.assertEqual(list(self.project.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
