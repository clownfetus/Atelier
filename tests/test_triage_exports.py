"""Regressions for #39 tool staging, #41 material rebasing and #45 cache recovery."""
import atexit
from contextlib import ExitStack
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_data = tempfile.TemporaryDirectory(prefix="atelier-triage-tests-")
os.environ["ATELIER_DATA_DIR"] = _data.name
atexit.register(_data.cleanup)
from atelier import config as C, asset_cache as AC
from atelier.handlers import material as M, texture as T
from scripts import stage_tools as ST


def material(tint=.1, scalar=.2):
    def entry(name, value):
        return {"OriginalStructHeader": "keep", "Value": [
            {"Name": "ParameterInfo", "Value": [{"Name": "Name", "Value": name}]},
            {"Name": "ParameterValue", "Value": value, "IsZero": scalar == 0}]}
    return {"Imports": [{"ObjectName": "current import"}], "Patch": "current",
            "Exports": [{"Data": [
                {"Name": "VectorParameterValues", "Value": [entry("Tint", [
                    {"Value": dict(R=tint, G=.2, B=.3, A=1)}])]},
                {"Name": "ScalarParameterValues", "Value": [entry("Power", scalar)]}]}]}


class ExportRegression(unittest.TestCase):
    gr = "Characters/1000/1000100/Materials/MI_Body"
    tex = "UI/Textures/T_Icon"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="triage-case-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.cache = self.root / "cache"
        self.cache.mkdir()
        self.stage = self.root / "stage"
        self.work = self.root / "work" / "MI_Body"
        self.work.parent.mkdir()
        self.work.with_suffix(".uasset").write_bytes(b"current vanilla")
        self.current = material(scalar=0)
        self.saved = material(.9, .7)
        self.saved.update(Patch="old", Imports=[{"ObjectName": "obsolete import"}])
        self.saved_path = Path(C.project_base(self.gr, str(self.project)) + ".json")
        self.write_saved(self.saved_path)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.multiple(C, IMPORT_ROOT=str(self.project), _active_project=""))
        self.stack.enter_context(patch.object(M, "_CACHE", str(self.cache)))
        self.stack.enter_context(patch.object(M, "pak_game_path", side_effect=lambda gr: "Marvel/Content/Marvel/" + gr))
        self.resolve = self.stack.enter_context(patch.object(T, "ensure_work_base", return_value=str(self.work)))
        self.convert = self.stack.enter_context(patch.object(M, "uat", side_effect=self.uat))
        self.serialized = None

    def write_saved(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.saved), encoding="utf-8")

    def uat(self, args):
        if args[0] == "to_json":
            self.assertEqual(Path(args[1]).read_bytes(), b"current vanilla")
            (Path(args[3]) / "MI_Body.json").write_text(json.dumps(self.current), encoding="utf-8")
        elif args[0] == "from_json":
            self.serialized = json.loads(Path(args[1]).read_text(encoding="utf-8"))
            Path(args[2]).write_bytes(b"rebuilt")
            Path(args[2]).with_suffix(".uexp").write_bytes(b"bulk companion")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def stage_material(self, colors=None, scalars=None, **kwargs):
        before = self.saved_path.read_bytes() if self.saved_path.exists() else None
        result = M.stage_material(str(self.stage), self.gr, colors or {}, scalars or {}, **kwargs)
        if before is not None:
            self.assertEqual(self.saved_path.read_bytes(), before)
        self.assertFalse(list(self.cache.iterdir()), "temporary conversion files leaked")
        return result

    def test_saved_parameters_rebase_onto_new_imports_and_schema(self):
        # An old viewport JSON is deliberately ignored too.
        cached = Path(C.project_base(self.gr, str(self.cache)) + ".json")
        cached.parent.mkdir(parents=True)
        cached.write_text("stale viewport JSON")
        self.stack.enter_context(patch.object(M, "CACHE_3DVIEW", str(self.cache)))
        before = self.saved_path.read_bytes()
        M.stage_material(str(self.stage), self.gr, {}, {})
        self.assertEqual(self.saved_path.read_bytes(), before)
        self.assertEqual(self.serialized["Imports"], self.current["Imports"])
        self.assertEqual(self.serialized["Patch"], "current")
        colors, scalars = M._mat_params(self.serialized)
        self.assertEqual(colors[0]["rgba"][0], .9)
        self.assertEqual(scalars[0]["value"], .7)
        scalar = self.serialized["Exports"][0]["Data"][1]["Value"][0]
        self.assertIsNone(scalar["OriginalStructHeader"])
        self.assertFalse(M._gn(scalar["Value"], "ParameterValue")["IsZero"])
        self.assertEqual(cached.read_text(), "stale viewport JSON")
        self.assertEqual(len(list(self.stage.rglob("*.uexp"))), 1)
        self.assertFalse(list(self.cache.glob(".material-export-*")))

    def test_legacy_project_values_and_explicit_overrides(self):
        legacy = Path(C.project_base_legacy(self.gr, str(self.project)) + ".json")
        self.write_saved(legacy)
        self.saved_path.unlink()
        before = legacy.read_bytes()
        self.stage_material(scalars={"Power": .5})
        colors, scalars = M._mat_params(self.serialized)
        self.assertEqual(colors[0]["rgba"][0], .9)
        self.assertEqual(scalars[0]["value"], .5)
        self.assertEqual(legacy.read_bytes(), before)

    def test_new_parameter_in_vanilla_keeps_its_default(self):
        self.current["Exports"][0]["Data"][1]["Value"].append(
            copy.deepcopy(self.current["Exports"][0]["Data"][1]["Value"][0]))
        entry = self.current["Exports"][0]["Data"][1]["Value"][-1]
        M._gn(entry["Value"], "ParameterInfo")["Value"][0]["Value"] = "AddedByPatch"
        self.stage_material()
        self.assertEqual(dict((s["name"], s["value"]) for s in M._mat_params(self.serialized)[1])["AddedByPatch"], 0)

    def test_removed_parameter_is_reported_instead_of_silently_lost(self):
        self.current["Exports"][0]["Data"][1]["Value"] = []
        with self.assertRaisesRegex(RuntimeError, "no longer has saved parameters: Power"):
            self.stage_material()
        self.assertFalse(list(self.stage.rglob("*.uasset")))

    def test_repatch_ignores_unrelated_project_parameters(self):
        self.stage_material(scalars={"Power": .6}, use_project=False)
        colors, scalars = M._mat_params(self.serialized)
        self.assertEqual(colors[0]["rgba"][0], .1)
        self.assertEqual(scalars[0]["value"], .6)

    def test_no_project_copy_exports_explicit_values_without_creating_one(self):
        self.saved_path.unlink()
        self.stage_material(scalars={"Power": .6})
        self.assertFalse(self.saved_path.exists())
        self.assertEqual(M._mat_params(self.serialized)[1][0]["value"], .6)

    def test_decode_error_never_serializes_old_project(self):
        self.convert.side_effect = None
        self.convert.return_value = SimpleNamespace(returncode=1, stdout="", stderr="schema decode failed")
        before = self.saved_path.read_bytes()
        with self.assertRaisesRegex(RuntimeError, "schema decode failed"):
            self.stage_material()
        self.assertEqual(self.saved_path.read_bytes(), before)
        self.assertEqual(self.convert.call_count, 1)
        self.assertFalse(list(self.stage.rglob("*.uasset")))

    def test_failed_serializer_cannot_leak_partial_asset_into_stage(self):
        def fail(args):
            result = self.uat(args)
            return SimpleNamespace(returncode=1, stdout="", stderr="serialize failed") if args[0] == "from_json" else result
        self.convert.side_effect = fail
        with self.assertRaisesRegex(RuntimeError, "serialize failed"):
            self.stage_material()
        self.assertFalse(list(self.stage.rglob("*.uasset")))

    def test_missing_current_material_does_not_fall_back_to_project(self):
        self.resolve.return_value = None
        with patch.object(T, "missing_reason", return_value="current material unavailable"):
            with self.assertRaisesRegex(RuntimeError, "current material unavailable"):
                self.stage_material()
        self.convert.assert_not_called()

    def texture_recovery(self, dds=False, fail=False, changed_container=False):
        # Exercise the real shared resolver through a missing recorded base.
        base = Path(C.project_base(self.tex, str(self.project)))
        base.parent.mkdir(parents=True)
        artwork = base.with_suffix(".dds" if dds else ".png")
        artwork.write_bytes(b"authored pixels, never replace")
        recovered = self.root / "recovered" / "T_Icon"
        recovered.parent.mkdir()
        if changed_container:
            recovered.with_suffix(".uasset").write_bytes(b"old same-name container bytes")
        calls = []
        def native(args):
            calls.append(args)
            if args[0] == "extract_iostore_legacy" and not fail:
                recovered.with_suffix(".uasset").write_bytes(b"fresh texture")
            if args[0] == "inject_texture":
                self.assertEqual(Path(args[1]).read_bytes(), b"fresh texture")
                self.assertEqual(Path(args[2]), artwork)
                Path(args[3]).write_bytes(b"injected texture")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        # Patch the resolver back to its implementation, retaining all its cache
        # recovery logic, while the native boundary remains a disposable fixture.
        with ExitStack() as stack:
            stack.enter_context(patch.object(T, "ensure_work_base", REAL_RESOLVER))
            stack.enter_context(patch.object(AC, "get", return_value={
                "cache_path": str(recovered if changed_container else self.root / "deleted"),
                "pak": "old.utoc", "source_stamp": "before patch"}))
            stack.enter_context(patch.object(AC, "source_stamp", return_value="after patch"))
            stack.enter_context(patch.object(AC, "remove"))
            record = stack.enter_context(patch.object(AC, "record"))
            stack.enter_context(patch.object(T, "extract_info", return_value=(str(recovered), "old.utoc", "Marvel/Content/Marvel/")))
            stack.enter_context(patch.object(T, "work_candidates", return_value=[str(recovered)] if changed_container else []))
            stack.enter_context(patch.object(T, "prefers_retoc", return_value=False))
            stack.enter_context(patch.object(T, "is_plugin_asset", return_value=False))
            stack.enter_context(patch.object(T, "find_extracted", return_value=None))
            stack.enter_context(patch.object(T, "_note_mip_attempt"))
            stack.enter_context(patch.object(T, "WORK_IMPORT_ROOT", str(self.root / "work")))
            stack.enter_context(patch.object(T, "pak_game_path", side_effect=lambda gr: "Marvel/Content/Marvel/" + gr))
            stack.enter_context(patch.object(T, "missing_reason", return_value="texture missing from current paks"))
            stack.enter_context(patch.object(T, "uat", side_effect=native))
            if fail:
                with self.assertRaisesRegex(RuntimeError, "texture missing from current paks"):
                    T.stage_inject(str(self.stage), self.tex)
                self.assertFalse(any(a[0] == "inject_texture" for a in calls))
            else:
                T.stage_inject(str(self.stage), self.tex, {"no_mips": True})
                self.assertEqual([a[0] for a in calls], ["extract_iostore_legacy", "inject_texture"])
                self.assertIn("--no-mips", calls[-1])
                record.assert_called_once()
        self.assertEqual(artwork.read_bytes(), b"authored pixels, never replace")

    def test_texture_recovers_deleted_base_and_preserves_png(self):
        self.texture_recovery()

    def test_texture_recovers_deleted_base_and_preserves_dds(self):
        self.texture_recovery(dds=True)

    def test_texture_recovery_failure_is_actionable_and_preserves_artwork(self):
        self.texture_recovery(fail=True)

    def test_same_container_name_with_changed_source_reextracts_old_base(self):
        self.texture_recovery(changed_container=True)

    def test_container_stamp_tracks_toc_and_bulk_updates(self):
        paks = self.root / "paks"
        paks.mkdir()
        toc, bulk = paks / "same.utoc", paks / "same.ucas"
        toc.write_bytes(b"toc")
        bulk.write_bytes(b"bulk")
        with patch.object(C, "PAKS", str(paks)):
            before = AC.source_stamp("same.utoc")
            bulk.write_bytes(b"changed bulk contents")
            after_bulk = AC.source_stamp("same.utoc")
            toc.write_bytes(b"changed directory index")
            after_toc = AC.source_stamp("same.utoc")
        self.assertNotEqual(before, after_bulk)
        self.assertNotEqual(after_bulk, after_toc)


REAL_RESOLVER = T.ensure_work_base


class ToolStaging(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="triage-tools-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "Tools"
        self.destination = self.root / "dist" / "Tools"
        for name in ST.REQUIRED:
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"native fixture")

    def test_complete_bundle_excludes_keys_mappings_caches_and_linux_binaries(self):
        forbidden = ["Mappings/test.usmap", "AES_KEY.txt", "shaders/_cache/test.bin", *ST.LINUX_ONLY]
        for name in forbidden:
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"must not ship")
        ST.stage_tools(self.source, self.destination)
        for name in ST.REQUIRED:
            self.assertEqual((self.destination / name).read_bytes(), b"native fixture")
        for name in forbidden:
            self.assertFalse((self.destination / name).exists(), name)
            self.assertTrue((self.source / name).exists(), "source tools changed")

    def test_each_missing_required_file_fails_without_partial_staging(self):
        for name in ST.REQUIRED:
            with self.subTest(name=name):
                path = self.source / name
                path.unlink()
                with self.assertRaisesRegex(RuntimeError, "Required Windows tools"):
                    ST.stage_tools(self.source, self.destination)
                self.assertFalse(self.destination.exists())
                path.write_bytes(b"native fixture")

    def test_empty_required_binary_fails(self):
        (self.source / "UAssetTool.exe").write_bytes(b"")
        with self.assertRaisesRegex(RuntimeError, "UAssetTool.exe"):
            ST.stage_tools(self.source, self.destination)

    def test_copy_failure_cleans_only_new_staging_tree(self):
        original_copy = ST.shutil.copy2
        calls = []
        def partial(*args, **kwargs):
            original_copy(*args, **kwargs)
            calls.append(args)
            if len(calls) == 3:          # fail part-way, after some files have landed
                raise OSError("disk full")
        with patch.object(ST.shutil, "copy2", side_effect=partial):
            with self.assertRaisesRegex(OSError, "disk full"):
                ST.stage_tools(self.source, self.destination)
        self.assertFalse(self.destination.exists())
        ST.validate_tools(self.source)

    def test_existing_or_overlapping_destination_is_not_modified(self):
        for destination in (self.source, self.source / "nested", self.root):
            with self.subTest(destination=destination), self.assertRaises(ValueError):
                ST.stage_tools(self.source, destination)
        self.destination.mkdir(parents=True)
        keep = self.destination / "keep.txt"
        keep.write_text("existing build")
        with self.assertRaises(ValueError):
            ST.stage_tools(self.source, self.destination)
        self.assertEqual(keep.read_text(), "existing build")

    def test_cli_missing_tools_returns_failure_for_batch_gate(self):
        (self.source / "UAssetTool.exe").unlink()
        result = subprocess.run([sys.executable, str(ROOT / "scripts/stage_tools.py"),
                                 str(self.source), str(self.destination)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("UAssetTool.exe", result.stderr)
        batch = (ROOT / "BUILD.bat").read_text()
        self.assertIn(r'scripts\build.py" --platform windows %*', batch)
        self.assertIn("exit /b %ERRORLEVEL%", batch)

    def test_build_stops_before_the_installer_when_tool_staging_fails(self):
        """scripts/build.py runs every step with check=True: a failed stage_tools ends the build
        before Inno Setup, so no installer can ship without its tools (TRIAGE #39)."""
        sys.path.insert(0, str(ROOT / "scripts"))
        import build as B
        ran = []
        def fake_run(*cmd, **kw):
            ran.append(" ".join(map(str, cmd)))
            if "stage_tools.py" in ran[-1]:
                raise subprocess.CalledProcessError(1, cmd)
        with patch.object(B, "run", fake_run), patch.object(B, "PYTHON_VERSION", sys.version_info[:2]), \
             patch.object(B.sys, "prefix", "venv"), patch.object(B.sys, "base_prefix", "base"), \
             patch.object(B, "find_iscc", side_effect=AssertionError("installer must not be built")), \
             patch.object(B.shutil, "rmtree"), patch.object(B.Path, "write_text"), \
             patch.object(B.Path, "chmod"), patch.object(sys, "argv", ["build.py", "--platform", B.HOST]):
            with self.assertRaises(subprocess.CalledProcessError):
                B.main()
        self.assertTrue(any("toolchain.py install" in r for r in ran), ran)
        self.assertTrue(any("PyInstaller" in r for r in ran), ran)
        self.assertFalse(any("ISCC" in r or "build_appimage" in r for r in ran), ran)

if __name__ == "__main__":
    unittest.main()
