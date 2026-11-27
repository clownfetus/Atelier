"""Cooked material repair through the repatcher, using a simulated native tool."""
import copy
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_data = tempfile.TemporaryDirectory(prefix="atelier-material-rebuild-")
os.environ["ATELIER_DATA_DIR"] = _data.name
from atelier import config as C
from atelier.handlers import material as M, material_rebuild as MR, repatch as R, texture as T

GR = "Characters/1000/1000100/Materials/MI_Body"
NAME = "MI_Body"
CURRENT_BUILD = 4_000_000
OLD_BUILD = 3_999_990
OLDER_BUILD = 3_999_980
PRECISE = 0.12345679104328156
TINT = [0.12345679104328156, 0.0625000074505806, 0.9384534358978271, 0.8123456239700317]
PREFIX = "Marvel/Content/Marvel/"


def mapping_name(build):
    return f"5.3.2-{build}+++depot_marvel+S10.5_release-Marvel.usmap"


def parameter(name, value, association=None, index=None, *, masked=False, absent=False):
    info = [{"Name": "Name", "Value": name}]
    if association is not None:
        info.append({"Name": "Association", "Value": association})
    if index is not None:
        info.append({"Name": "Index", "Value": index, "IsZero": index == 0})
    fields = [{"Name": "ParameterInfo", "Value": info, "OriginalStructHeader": {"keep": True}},
              {"Name": "ExpressionGUID", "Value": "current-expression"}]
    if not absent:
        fields.append({"Name": "ParameterValue", "Value": value, "IsZero": masked})
    return {"Name": "0", "Value": fields, "OriginalStructHeader": {"keep": True}}


def colour(values):
    return [{"Name": "ParameterValue", "Value": dict(zip("RGBA", values))}]


def material(scalars=(), vectors=(), *, kind="MaterialInstanceConstant"):
    return {"Imports": [{"ObjectName": kind}], "Exports": [
        {"$type": "UAssetAPI.ExportTypes.NormalExport, UAssetAPI", "ObjectName": NAME,
         "OuterIndex": 0, "ClassIndex": -1, "Extras": "current cooked material payload", "Data": [
             {"Name": "ScalarParameterValues", "Value": list(scalars)},
             {"Name": "VectorParameterValues", "Value": list(vectors)}]}]}


def raw_material():
    doc = material()
    doc["Exports"][0].update({"$type": "UAssetAPI.ExportTypes.RawExport, UAssetAPI", "Data": "AAECAwQF"})
    return doc


def field(entry, name):
    return next((node for node in entry["Value"] if node["Name"] == name), {"Value": None})


class MaterialRebuildTests(unittest.TestCase):
    def setUp(self):
        temp = self.enterContext(tempfile.TemporaryDirectory(prefix="atelier-material-rebuild-case-"))
        self.root = Path(temp)
        self.cache = self.root / "cache"
        self.project = self.root / "project"
        self.project.mkdir()
        self.maps = self.root / "Tools" / "Mappings"
        self.maps.mkdir(parents=True)
        self.current_mapping = self.cache_mapping(CURRENT_BUILD)
        self.source = self.root / "old.zip"
        with zipfile.ZipFile(self.source, "w") as archive:
            archive.writestr("old.utoc", b"old container")
        self.current_asset = self.root / "vanilla" / (NAME + ".uasset")
        self.current_asset.parent.mkdir()
        self.current_asset.write_bytes(b"current vanilla")
        self.output = self.root / "output"
        self.work = self.root / "work"
        self.current = material(scalars=[parameter("Speed", .3)])
        self.source_docs = {CURRENT_BUILD: material(scalars=[parameter("Speed", PRECISE)])}
        self.depot = {}
        self.offline = False
        self.drop_readback_edit = False
        self.fail_pack = False
        self.native_calls = []
        self.fetches = []
        self.enterContext(patch.multiple(C, TOOLS=str(self.maps.parent), IMPORT_ROOT=str(self.project),
                                         _active_project=""))
        self.enterContext(patch.multiple(R, USMAP=str(self.current_mapping), uat=self.native))
        self.enterContext(patch.multiple(M, USMAP=str(self.current_mapping), uat=self.native, _CACHE=str(self.cache)))
        self.enterContext(patch.object(M, "pak_game_path", side_effect=lambda gr: PREFIX + gr))
        self.enterContext(patch.object(MR, "pak_game_path", side_effect=lambda gr: PREFIX + gr))
        self.enterContext(patch.object(T, "ensure_work_base", return_value=str(self.current_asset.with_suffix(""))))
        self.enterContext(patch.object(R.hostos, "run_exe", side_effect=self.unpack))
        self.enterContext(patch("atelier.repair_mappings.urlopen", side_effect=self.fetch))

    def cache_mapping(self, build):
        path = self.maps / mapping_name(build)
        path.write_bytes(b"\xc4\x30\x00\x00fixture")
        return path

    def fetch(self, request, timeout):
        url = request.full_url
        self.fetches.append(url)
        if self.offline:
            raise OSError("offline")
        if url.endswith("/contents/usmap"):
            return io.BytesIO(json.dumps([
                {"type": "file", "name": mapping_name(build),
                 "download_url": f"https://raw.githubusercontent.com/SpaceDepot/rivals-depot/main/usmap/{mapping_name(build)}"}
                for build in self.depot
            ]).encode())
        for build, data in self.depot.items():
            if mapping_name(build) in url:
                return io.BytesIO(data)
        self.fail(f"Unexpected request: {url}")

    def unpack(self, args, **kwargs):
        dest = Path(args[-1]) / PREFIX / (GR + ".uasset")
        dest.parent.mkdir(parents=True)
        dest.write_bytes(b"old asset")
        return SimpleNamespace(returncode=0)

    def native(self, args):
        cmd = args[0]
        if cmd == "to_json":
            source, mapping, output = Path(args[1]), Path(args[2]), Path(args[3])
            build = C._usmap_build(mapping)
            value = source.read_bytes()
            if value == b"old asset":
                self.native_calls.append(("source", build))
                doc = self.source_docs.get(build, raw_material())
            elif value == b"current vanilla":
                self.native_calls.append(("vanilla", build))
                doc = self.current
            else:
                self.native_calls.append(("readback", build))
                doc = json.loads(value)
                if self.drop_readback_edit:
                    field(doc["Exports"][0]["Data"][0]["Value"][0], "ParameterValue")["Value"] = .3
            (output / (source.stem + ".json")).write_text(json.dumps(doc), encoding="utf-8")
        elif cmd == "from_json":
            self.native_calls.append(("compile", C._usmap_build(args[3])))
            Path(args[2]).write_bytes(Path(args[1]).read_bytes())
        elif cmd == "create_mod_iostore":
            self.native_calls.append(("pack", C._usmap_build(args[-1])))
            if self.fail_pack:
                return SimpleNamespace(returncode=1, stderr="pack failed", stdout="")
            for ext in (".pak", ".ucas", ".utoc"):
                Path(args[1] + ext).write_bytes(b"packed")
        else:
            self.fail(f"Unexpected native command: {cmd}")
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    def repatch(self, **kwargs):
        return R.repatch_mod(str(self.source), str(self.output), work_dir=str(self.work), **kwargs)

    def rebuilt(self, stage=None):
        return json.loads(((stage or self.work / "stage") / PREFIX / (GR + ".uasset")).read_bytes())

    def test_raw_material_retries_validated_older_mappings_and_keeps_output_current(self):
        self.source_docs[CURRENT_BUILD] = raw_material()
        self.source_docs[OLD_BUILD] = material(kind="Texture2D")
        self.source_docs[OLDER_BUILD] = material(scalars=[parameter("Speed", PRECISE)])
        self.cache_mapping(OLD_BUILD)
        self.depot = {OLDER_BUILD: b"\xc4\x30\x00\x00depot", OLD_BUILD: b"do not download",
                      CURRENT_BUILD: b"do not download", CURRENT_BUILD + 10: b"do not download"}

        result = self.repatch()

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["manifest"].get("recovered_materials", 0), 1)
        self.assertEqual(result["skipped"], [])
        self.assertEqual(self.native_calls, [("source", CURRENT_BUILD), ("source", OLD_BUILD),
                         ("source", OLDER_BUILD), ("vanilla", CURRENT_BUILD), ("compile", CURRENT_BUILD),
                         ("readback", CURRENT_BUILD), ("pack", CURRENT_BUILD)])
        self.assertEqual(len(self.fetches), 2)
        self.assertEqual((self.maps / mapping_name(OLDER_BUILD)).read_bytes(), b"\xc4\x30\x00\x00depot")
        entry = self.rebuilt()["Exports"][0]["Data"][0]["Value"][0]
        self.assertEqual(field(entry, "ParameterValue")["Value"], PRECISE)

    def test_cached_mapping_decodes_without_requesting_the_depot_listing(self):
        self.cache_mapping(OLDER_BUILD)
        self.depot = {OLD_BUILD: b"\xc4\x30\x00\x00depot"}
        self.source_docs = {
            CURRENT_BUILD: raw_material(),
            OLD_BUILD: material(scalars=[parameter("Speed", .7)]),
            OLDER_BUILD: material(scalars=[parameter("Speed", PRECISE)]),
        }

        result = self.repatch()

        self.assertTrue(result["ok"], result)
        self.assertEqual(self.fetches, [])
        self.assertEqual(self.native_calls[:2], [("source", CURRENT_BUILD), ("source", OLDER_BUILD)])

    def test_older_mapping_retries_are_bounded_and_newest_first(self):
        self.offline = True
        self.source_docs[CURRENT_BUILD] = raw_material()
        for distance in range(12, 0, -1):
            self.cache_mapping(CURRENT_BUILD - distance)

        result = self.repatch()

        self.assertFalse(result["ok"], result)
        self.assertEqual(self.native_calls, [("source", CURRENT_BUILD - distance) for distance in range(9)])
        self.assertEqual(self.fetches, [])
        self.assertRegex(result["skipped"][0], "older mapping")

    def test_depot_mappings_use_the_remaining_attempts_and_are_reused_within_the_job(self):
        for distance in range(11, 17):
            self.cache_mapping(CURRENT_BUILD - distance)
        self.depot = {CURRENT_BUILD - distance: b"\xc4\x30\x00\x00depot" for distance in range(6, 0, -1)}
        history = R.OlderMappings(str(self.current_mapping))

        first = list(history.paths())
        second = list(history.paths())

        self.assertEqual([C._usmap_build(path) for path in first],
                         [CURRENT_BUILD - distance for distance in (11, 12, 13, 14, 15, 16, 1, 2)])
        self.assertEqual(second, first)
        self.assertEqual(len(self.fetches), 3)

    def test_wrong_asset_class_does_not_trigger_mapping_fallback(self):
        self.cache_mapping(OLD_BUILD)
        self.source_docs = {CURRENT_BUILD: material(scalars=[parameter("Speed", PRECISE)], kind="Texture2D"),
                            OLD_BUILD: material(scalars=[parameter("Speed", PRECISE)])}

        result = self.repatch()

        self.assertFalse(result["ok"], result)
        self.assertRegex(result["skipped"][0], "MaterialInstanceConstant")
        self.assertEqual(self.native_calls, [("source", CURRENT_BUILD)])
        self.assertEqual(self.fetches, [])

    def test_distinct_layers_and_zero_masks_survive_precision_and_readback(self):
        masked_layer = parameter("Tint", [], "LayerParameter", 0, masked=True)
        masked_layer["Value"][0]["Value"][1].update(IsZero=True, Value=None)
        self.current = material(
            scalars=[parameter("Speed", .7, "LayerParameter", 0), parameter("Speed", "+0", masked=True),
                     parameter("Speed", None, "BlendParameter", 0, absent=True)],
            vectors=[masked_layer, parameter("Tint", colour([.5, .5, .5, .5]), "GlobalParameter", -1)])
        self.source_docs[CURRENT_BUILD] = material(
            scalars=[parameter("Speed", PRECISE), parameter("Speed", None, "LayerParameter", 0, absent=True),
                     parameter("Speed", .6783459186553955, "BlendParameter", 0)],
            vectors=[parameter("Tint", [], masked=True), parameter("Tint", colour(TINT), "LayerParameter", 0)])

        result = self.repatch()

        self.assertTrue(result["ok"], result)
        scalars, vectors = (node["Value"] for node in self.rebuilt()["Exports"][0]["Data"])
        self.assertEqual([field(entry, "ParameterValue")["Value"] for entry in scalars],
                         [0, PRECISE, .6783459186553955])
        self.assertEqual([list(field(entry, "ParameterValue")["Value"][0]["Value"][channel] for channel in "RGBA")
                          for entry in vectors], [TINT, [0, 0, 0, 0]])
        value = field(vectors[0], "ParameterValue")
        self.assertFalse(value["IsZero"])
        self.assertIsNone(vectors[0]["OriginalStructHeader"])
        self.assertEqual(field(vectors[0], "ParameterInfo")["OriginalStructHeader"], {"keep": True})
        self.assertEqual(field(vectors[0], "ExpressionGUID")["Value"], "current-expression")
        self.assertEqual(self.fetches, [])

    def test_missing_layer_is_reported_without_replacing_a_different_layer(self):
        self.source_docs[CURRENT_BUILD] = material(scalars=[parameter("Speed", .9, "LayerParameter", 1)])

        result = self.repatch()

        self.assertFalse(result["ok"], result)
        self.assertRegex(result["skipped"][0], r"(?i)missing.*Speed.*LayerParameter.*1")
        self.assertFalse(list((self.work / "stage").rglob("*.uasset")))

    def test_duplicate_parameter_identity_is_reported(self):
        self.current["Exports"][0]["Data"][0]["Value"].append(parameter("Speed", .8, "GlobalParameter", -1))

        result = self.repatch()

        self.assertFalse(result["ok"], result)
        self.assertRegex(result["skipped"][0], r"(?i)ambiguous.*Speed.*GlobalParameter.*-1")
        self.assertFalse(list((self.work / "stage").rglob("*.uasset")))

    def test_zero_masked_parameter_array_is_empty(self):
        for document in (self.current, self.source_docs[CURRENT_BUILD]):
            document["Exports"][0]["Data"][1].update(IsZero=True, Value=None)

        result = self.repatch(stage_as_project=True)

        self.assertTrue(result["ok"], result)
        project_stage = self.root / "project-stage"
        M.stage_material(str(project_stage), GR, {}, {})
        entry = self.rebuilt(project_stage)["Exports"][0]["Data"][0]["Value"][0]
        self.assertEqual(field(entry, "ParameterValue")["Value"], PRECISE)

    def test_readback_mismatch_leaves_no_asset_to_pack_or_stage(self):
        self.drop_readback_edit = True

        result = self.repatch(stage_as_project=True)

        self.assertFalse(result["ok"], result)
        self.assertRegex(result["skipped"][0], r"(?i)read.back.*Speed")
        self.assertFalse(list((self.work / "stage").rglob("*.uasset")))
        self.assertFalse(list(self.project.rglob("*.json")))
        self.assertNotIn(("pack", CURRENT_BUILD), self.native_calls)

    def test_staged_layer_edits_round_trip_through_the_existing_project_export(self):
        self.current = material(scalars=[parameter("Speed", .3), parameter("Speed", .4, "LayerParameter", 0)])
        saved = copy.deepcopy(self.current)
        saved["project-only"] = "keep"
        path = Path(C.project_base(GR) + ".json")
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(saved), encoding="utf-8")
        self.source_docs[CURRENT_BUILD] = material(
            scalars=[parameter("Speed", PRECISE), parameter("Speed", .9, "LayerParameter", 0)])

        result = self.repatch(stage_as_project=True)

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["manifest"]["staged_project"], 1)
        self.assertEqual(json.loads(path.read_bytes())["project-only"], "keep")
        project_stage = self.root / "project-stage"
        M.stage_material(str(project_stage), GR, {}, {})
        entries = self.rebuilt(project_stage)["Exports"][0]["Data"][0]["Value"]
        self.assertEqual([field(entry, "ParameterValue")["Value"] for entry in entries], [PRECISE, .9])

    def test_pack_failure_leaves_no_project_edits(self):
        self.fail_pack = True

        result = self.repatch(stage_as_project=True)

        self.assertFalse(result["ok"], result)
        self.assertFalse(list(self.project.rglob("*.json")))


if __name__ == "__main__":
    unittest.main()
