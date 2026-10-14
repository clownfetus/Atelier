"""Failure-oriented regressions. Run through tests/run_checks.py (no game required)."""
import atexit
from contextlib import ExitStack
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch, Mock
from urllib.parse import quote
from wsgiref.util import setup_testing_defaults

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_app_data = tempfile.TemporaryDirectory(prefix="atelier-reliability-")
os.environ["ATELIER_DATA_DIR"] = _app_data.name
from atelier import config as C, operations as O, storage as S
from atelier.handlers import texture as T, world as W, material as M, container_merge as CM
from atelier.web import routes as R


def _cleanup():
    R._observer.stop()
    R._observer.join()
    _app_data.cleanup()


atexit.register(_cleanup)


def call(path, body=None, project=None):
    env = {}
    setup_testing_defaults(env)
    payload = json.dumps(body or {}).encode()
    env.update(REQUEST_METHOD="POST", PATH_INFO=path, CONTENT_TYPE="application/json",
               CONTENT_LENGTH=str(len(payload)), **{"wsgi.input": io.BytesIO(payload)})
    if project is not None:
        env["HTTP_X_ATELIER_PROJECT"] = quote(project, safe="")
    status = []
    result = R.app(env, lambda s, h, exc_info=None: status.append(s))
    try:
        data = b"".join(result).decode()
    finally:
        if hasattr(result, "close"):
            result.close()
    return int(status[0].split()[0]), json.loads(data)


def triple(base, value=b"new"):
    Path(base).parent.mkdir(parents=True, exist_ok=True)
    for ext in (".pak", ".ucas", ".utoc"):
        Path(str(base) + ext).write_bytes(value + ext.encode())
    return S.container_files(str(base))


class Reliability(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="atelier-case-")
        self.root = Path(self.temp.name)
        self.projects = self.root / "projects"
        for name in ("A", "B"):
            (self.projects / name).mkdir(parents=True)
        self.out = self.root / "exported"
        self.mods = self.root / "mods"
        self.cache = self.root / "cache"
        self.cache.mkdir()
        self.stack = ExitStack()
        self.stack.enter_context(patch.multiple(C, PROJECTS_ROOT=str(self.projects),
            IMPORT_ROOT=str(self.root / "imported"), _active_project="A",
            CONFIG_FILE=str(self.root / "config.json"), _CACHE=str(self.cache)))
        self.stack.enter_context(patch.multiple(R, PROJECTS_ROOT=str(self.projects),
            IMPORT_ROOT=C.IMPORT_ROOT, ASSETS_MODS=str(self.out), _CACHE=str(self.cache)))
        self.stack.enter_context(patch.object(T, "_CACHE", str(self.cache)))
        self.stack.enter_context(patch.object(R, "_push_sse", lambda event: None))
        R._job.update(running=False, done=False, results=[], error=None)

    def tearDown(self):
        self.stack.close()
        self.temp.cleanup()

    def test_project_routes_reject_escape_and_preserve_outside_data(self):
        outside = self.root / "outside"
        outside.mkdir()
        marker = outside / "keep.txt"
        marker.write_text("keep")
        for endpoint, body in (
            ("delete", {"name": "../outside"}),
            ("select", {"name": str(outside)}),
            ("rename", {"old_name": "../outside", "new_name": "Oops"}),
            ("duplicate", {"name": "../outside", "new_name": "Oops"}),
            ("create", {"name": ".."}),
        ):
            with self.subTest(endpoint=endpoint):
                code, data = call("/api/project/" + endpoint, body)
                self.assertEqual(code, 400)
                self.assertFalse(data["ok"])
                self.assertEqual(marker.read_text(), "keep")
        self.assertFalse((self.projects / "Oops").exists())

    def test_asset_paths_cannot_escape_through_post_or_query_helpers(self):
        for value in ("../outside", "/absolute", "C:/absolute", "UI/../outside", "UI/T:stream", "UI//T"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    C.project_base(value)
                code, data = call("/api/material_save", {"game_rel": value})
                self.assertEqual(code, 400)
        self.assertEqual(C.project_base("Plugins/X/UI/T_A"), str(self.projects / "A/Plugins/X/UI/T_A"))

    def test_existing_nested_and_legacy_layouts_are_preserved(self):
        legacy = self.projects / "A" / "T_A.png"
        legacy.write_bytes(b"legacy")
        self.assertEqual(R._import_base("UI/T_A"), str(legacy.with_suffix("")))
        nested = self.projects / "A" / "UI" / "T_A.png"
        nested.parent.mkdir()
        nested.write_bytes(b"nested")
        self.assertEqual(R._import_base("UI/T_A"), str(nested.with_suffix("")))

    def test_context_is_pinned_across_selection_change(self):
        root = C.get_import_root()
        with C.project_context(root):
            C.set_active_project("B")
            self.assertEqual(C.get_import_root(), root)
        self.assertEqual(C.get_import_root(), str(self.projects / "B"))

    def test_explicit_project_header_targets_originating_project(self):
        C.set_active_project("B")
        code, data = call("/api/project/asset_selection", {"deselected": ["UI/T_A"]}, project="A")
        self.assertEqual(code, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(R._project_meta.get_deselected(str(self.projects / "A")), {"UI/T_A"})
        self.assertEqual(R._project_meta.get_deselected(str(self.projects / "B")), set())

    def test_deleted_origin_never_falls_back_to_active_project(self):
        code, data = call("/api/project/asset_selection", {"deselected": ["UI/T_A"]}, project="Gone")
        self.assertEqual(code, 400)
        self.assertFalse(data["ok"])
        self.assertEqual(R._project_meta.get_deselected(str(self.projects / "A")), set())

    def test_active_operation_blocks_rename_delete_and_reset(self):
        release = O.reserve(str(self.projects / "A"))
        try:
            for path, body in (("/api/project/delete", {"name": "A"}),
                               ("/api/project/rename", {"old_name": "A", "new_name": "C"}),
                               ("/api/reset_data", {})):
                code, data = call(path, body)
                self.assertEqual(code, 409)
                self.assertFalse(data["ok"])
                self.assertTrue((self.projects / "A").is_dir())
        finally:
            release()
        self.assertTrue(call("/api/project/rename", {"old_name": "A", "new_name": "C"})[1]["ok"])

    def test_bulk_import_claims_before_start_and_keeps_original_project(self):
        scheduled, decoded = [], []
        class DeferredThread:
            def __init__(self, target, args, daemon):
                scheduled.append((target, args))
            def start(self):
                pass
        def decode(grs, output):
            decoded.append(output)
            for gr in grs:
                p = Path(C.project_base(gr, output) + ".png")
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b"decoded")
        items = [{"game_rel": "UI/T_A", "name": "T_A"}]
        with patch.object(R.threading, "Thread", DeferredThread):
            first = call("/api/import_all", {"items": items}, "A")[1]
            second = call("/api/import_all", {"items": items}, "A")[1]
        self.assertTrue(first["ok"])
        self.assertFalse(second["ok"])
        self.assertEqual(call("/api/project/delete", {"name": "A"})[0], 409)
        C.set_active_project("B")
        with patch.object(R, "extract_many", return_value={}), patch.object(R, "decode_flat", decode):
            scheduled[0][0](*scheduled[0][1])
        self.assertEqual(decoded, [str(self.projects / "A")])
        self.assertFalse(R._job["running"])
        self.assertIsNone(R._job["error"])
        self.assertEqual(len(R._job["results"]), 1)
        self.assertFalse((self.projects / "B/UI/T_A.png").exists())

    def test_failed_bulk_decode_reports_failure_and_releases_project(self):
        with patch.object(R, "extract_many", return_value={}), patch.object(R, "decode_flat", side_effect=OSError("decode failed")):
            R._run_import_job([{"game_rel": "UI/T_A", "name": "T_A"}])
        self.assertFalse(R._job["running"])
        self.assertIn("decode failed", R._job["error"])
        with O.change_projects(str(self.projects / "A")):
            pass

    def test_atomic_json_keeps_old_file_after_replace_failure(self):
        path = self.root / "edit.json"
        S.atomic_json(path, {"old": True})
        with patch.object(S.os, "replace", side_effect=PermissionError("locked")):
            with self.assertRaises(PermissionError):
                S.atomic_json(path, {"new": True})
        self.assertEqual(json.loads(path.read_text()), {"old": True})

    def test_config_setters_preserve_each_others_fields(self):
        jobs = [lambda: C.save_mods_folder("mods"), lambda: C.save_blender_path("blender"),
                lambda: C.save_export_password("test-only"), lambda: C.set_active_project("B")]
        workers = [threading.Thread(target=fn) for fn in jobs]
        for worker in workers: worker.start()
        for worker in workers: worker.join()
        cfg = C._load_config()
        self.assertEqual(cfg, {"mods_folder": "mods", "blender_path": "blender",
                               "export_password": "test-only", "active_project": "B"})

    def test_missing_output_does_not_remove_installed_mod(self):
        old = triple(self.mods / "Demo_9999999_P", b"old")
        with patch.object(R, "get_mods_folder", return_value=str(self.mods)):
            ok, error, _ = R._install_to_mods("Demo", str(self.out))
        self.assertFalse(ok)
        self.assertIn("Incomplete", error)
        self.assertTrue(all(Path(p).read_bytes().startswith(b"old") for p in old))

    def test_copy_failure_leaves_old_output_untouched(self):
        sources = triple(self.root / "new/Demo", b"new")
        old = triple(self.mods / "Demo", b"old")
        real_copy = S.shutil.copy2
        def fail(src, dst, *a, **kw):
            if str(src).endswith(".ucas") and str(src) in sources:
                raise OSError("disk full")
            return real_copy(src, dst, *a, **kw)
        with patch.object(S.shutil, "copy2", fail):
            with self.assertRaises(OSError): S.publish_files(sources, str(self.mods))
        self.assertTrue(all(Path(p).read_bytes().startswith(b"old") for p in old))

    def test_partial_publication_rolls_back_the_entire_file_set(self):
        sources = triple(self.root / "new/Demo", b"new")
        old = triple(self.mods / "Demo", b"old")
        real_replace, failed = S.os.replace, False
        def fail(src, dst):
            nonlocal failed
            if str(dst) == old[1] and not failed:
                failed = True
                raise PermissionError("locked second file")
            return real_replace(src, dst)
        with patch.object(S.os, "replace", fail):
            with self.assertRaises(PermissionError): S.publish_files(sources, str(self.mods))
        self.assertTrue(failed)
        self.assertTrue(all(Path(p).read_bytes().startswith(b"old") for p in old))

    def test_interrupted_publication_recovers_before_next_attempt(self):
        old = triple(self.mods / "Demo", b"old")
        transaction = self.mods / ".atelier-publish-interrupted"
        (transaction / "backup").mkdir(parents=True)
        (transaction / "new").mkdir()
        entries = []
        for p in old:
            name = Path(p).name
            (transaction / "backup" / name).write_bytes(Path(p).read_bytes())
            Path(p).write_bytes(b"partial")
            entries.append({"name": name, "had_old": True})
        S.atomic_json(transaction / "journal.json", {"state": "publishing", "entries": entries})
        other = triple(self.root / "new/Other")
        S.publish_files(other, str(self.mods))
        self.assertTrue(all(Path(p).read_bytes().startswith(b"old") for p in old))
        self.assertFalse(transaction.exists())

    def test_failed_rollback_retains_backups_and_recovers_when_lock_released(self):
        old = triple(self.mods / "Demo", b"old")
        sources = triple(self.root / "new/Demo", b"new")
        real_replace = S.os.replace
        def locked(src, dst):
            if str(dst) == old[1]:
                raise PermissionError("still locked")
            return real_replace(src, dst)
        with patch.object(S.os, "replace", locked):
            with self.assertRaises(S.PublicationRecoveryError):
                S.publish_files(sources, str(self.mods))
        journals = list(self.mods.glob('.atelier-publish-*/journal.json'))
        self.assertEqual(len(journals), 1)
        self.assertEqual(len(list((journals[0].parent / 'backup').iterdir())), 3)
        S.publish_files(triple(self.root / 'new/Other'), str(self.mods))
        self.assertTrue(all(Path(p).read_bytes().startswith(b'old') for p in old))

    def test_concurrent_archives_keep_independent_downloads(self):
        import concurrent.futures
        import zipfile
        (self.projects / 'A/marker').write_text('A')
        (self.projects / 'B/marker').write_text('B')
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(R._build_project_zip, ['A', 'B'])
            b = pool.submit(R._build_project_zip, ['B', 'A'])
            paths = [a.result(timeout=5), b.result(timeout=5)]
        self.assertNotEqual(paths[0], paths[1])
        for path in paths:
            with zipfile.ZipFile(path) as archive:
                self.assertEqual(archive.read('A/marker'), b'A')
                self.assertEqual(archive.read('B/marker'), b'B')

    def test_world_container_collision_fails_before_any_build(self):
        with patch.object(W, 'build_world_mod') as world:
            result = T.build_mod('Demo', [], [], str(self.out),
                                 world_items=['Maps/A/World', 'Maps/B/World'])
        self.assertFalse(result['ok'])
        world.assert_not_called()

    def test_successful_publish_preserves_unrelated_mods(self):
        sources = triple(self.root / "new/Demo")
        other = triple(self.mods / "Other", b"unrelated")
        result = S.publish_files(sources, str(self.mods))
        self.assertEqual(len(result), 3)
        self.assertTrue(all(Path(p).read_bytes().startswith(b"new") for p in result))
        self.assertTrue(all(Path(p).read_bytes().startswith(b"unrelated") for p in other))

    def test_failed_build_preserves_previous_export_and_other_staging(self):
        old = triple(self.out / "Demo_9999999_P", b"old")
        marker = self.cache / "build_stage/other/keep"
        marker.parent.mkdir(parents=True)
        marker.write_text("keep")
        with patch.object(T, "stage_inject", return_value="T_A"), patch.object(T, "uat", return_value=None):
            result = T.build_mod("Demo", ["UI/T_A"], [], str(self.out))
        self.assertFalse(result["ok"])
        self.assertTrue(all(Path(p).read_bytes().startswith(b"old") for p in old))
        self.assertEqual(marker.read_text(), "keep")

    def test_overlapping_build_is_rejected_without_touching_output(self):
        with T._build_lock:
            result = T.build_mod("Demo", ["UI/T_A"], [], str(self.out))
        self.assertFalse(result["ok"])
        self.assertIn("in progress", result["error"])
        self.assertFalse(self.out.exists())

    def test_cli_export_failure_preserves_previous_mod(self):
        old = triple(self.out / 'Demo_9999999_P', b'old')
        with patch.object(T, 'check_prereqs'), patch.object(T, 'expand_export_args', return_value=[('UI/T_A', 'T_A')]), \
             patch.object(T, 'stage_inject', side_effect=RuntimeError('decode failed')):
            with self.assertRaises(RuntimeError):
                T.cmd_export('Demo', ['T_A'], str(self.out), force=True)
        self.assertTrue(all(Path(p).read_bytes().startswith(b'old') for p in old))

    def test_cli_import_reports_count_without_undefined_name(self):
        import atelier.asset_cache as AC
        from contextlib import redirect_stdout
        output = io.StringIO()
        with patch.object(T, 'check_prereqs'), patch.object(T, 'skin_entries', return_value=[('T_A.uasset', 'pak')]), \
             patch.object(T, 'skin_rel', return_value='T_A.uasset'), \
             patch.object(T, 'game_rel_for_skin', return_value='UI/T_A'), \
             patch.object(T, 'uat', return_value=Mock(stdout='Extraction complete')), \
             patch.object(T, 'extract_info', return_value=(None, None, None)), \
             patch.object(AC, 'record_many'), patch.object(T, 'decode_flat'), \
             patch.multiple(T, IMPORT_ROOT=str(self.root / 'imported'), WORK_IMPORT_ROOT=str(self.cache)), \
             redirect_stdout(output):
            T.cmd_import('1000000')
        self.assertIn('Extracted 1 asset(s)', output.getvalue())

    def test_world_fallback_requires_explicit_opt_in(self):
        with patch.object(W, "build_world_mod", return_value={"ok": False, "error": "unsupported"}), \
             patch.object(W, "build_world_uag") as unsafe:
            result = T.build_mod("Demo", [], [], str(self.out), world_items=["Maps/World"])
        self.assertFalse(result["ok"])
        unsafe.assert_not_called()

    def test_world_only_export_installs_its_actual_artifact_names(self):
        def world(gr, edits, base):
            triple(base)
            return {"ok": True, "applied": ["light"]}
        with patch.object(W, "build_world_mod", world):
            result = T.build_mod("Demo", [], [], str(self.out), world_items=["Maps/World"])
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(result["artifacts"]), 3)
        with patch.object(R, "get_mods_folder", return_value=str(self.mods)):
            ok, error, _ = R._install_to_mods("Demo", str(self.out), result["artifacts"])
        self.assertTrue(ok, error)
        self.assertTrue((self.mods / "World_9999999_P.utoc").exists())

    def test_failed_merge_preserves_and_installs_both_containers(self):
        def world(gr, edits, base):
            triple(base, b"world")
            return {"ok": True, "applied": ["light"]}
        def pack(args):
            triple(args[1], b"texture")
        with patch.object(W, "build_world_mod", world), patch.object(T, "stage_inject", return_value="T_A"), \
             patch.object(T, "uat", pack), patch.object(CM, "merge_containers", side_effect=RuntimeError("merge failed")):
            result = T.build_mod("Demo", ["UI/T_A"], [], str(self.out), world_items=["Maps/World"])
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(result["artifacts"]), 6)
        with patch.object(R, "get_mods_folder", return_value=str(self.mods)):
            self.assertTrue(R._install_to_mods("Demo", str(self.out), result["artifacts"])[0])
        self.assertTrue((self.mods / "Demo_9999999_P.ucas").read_bytes().startswith(b"texture"))
        self.assertTrue((self.mods / "World_9999999_P.ucas").read_bytes().startswith(b"world"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
