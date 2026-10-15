"""Thumbnail delivery/jobs regressions using generated PNGs and fake native decoders only."""
import atexit
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import io
import json
import ntpath
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
from urllib.parse import quote, urlencode
from wsgiref.util import setup_testing_defaults

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_data = tempfile.TemporaryDirectory(prefix="atelier-thumbnail-tests-")
os.environ["ATELIER_DATA_DIR"] = _data.name
from atelier import config as C, operations as O
from atelier.web import routes as R


def _cleanup():
    R._observer.stop()
    R._observer.join()
    _data.cleanup()


atexit.register(_cleanup)


def call(path, body=None, project="A", query=None):
    env = {}
    setup_testing_defaults(env)
    payload = json.dumps(body).encode() if body is not None else b""
    env.update(REQUEST_METHOD="POST" if body is not None else "GET", PATH_INFO=path,
               QUERY_STRING=urlencode(query or {}), CONTENT_TYPE="application/json",
               CONTENT_LENGTH=str(len(payload)), **{"wsgi.input": io.BytesIO(payload)})
    if project is not None:
        env["HTTP_X_ATELIER_PROJECT"] = quote(project, safe="")
    response = []
    result = R.app(env, lambda status, headers, exc_info=None: response.append((status, dict(headers))))
    try:
        data = b"".join(result)
    finally:
        if hasattr(result, "close"): result.close()
    status, headers = response[0]
    if headers.get("Content-Type", "").startswith("application/json"):
        data = json.loads(data)
    return int(status.split()[0]), data, headers


def png(color="blue", size=(256, 128)):
    stream = io.BytesIO()
    Image.new("RGBA", size, color).save(stream, "PNG")
    return stream.getvalue()


class Thumbnails(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="atelier-thumbs-case-")
        self.root = Path(self.temp.name)
        self.projects = self.root / "projects"
        for project in ("A", "B"): (self.projects / project).mkdir(parents=True)
        self.cache = self.root / "cache"
        self.thumbs = self.cache / "thumbs"
        self.thumbs.mkdir(parents=True)
        self.events = []
        self.executor = ThreadPoolExecutor(max_workers=2)
        self.stack = ExitStack()
        self.stack.enter_context(patch.multiple(C, PROJECTS_ROOT=str(self.projects),
            IMPORT_ROOT=str(self.root / "imported"), _active_project="A"))
        self.stack.enter_context(patch.multiple(R, PROJECTS_ROOT=str(self.projects), IMPORT_ROOT=C.IMPORT_ROOT,
            _CACHE=str(self.cache), THUMBS_DIR=str(self.thumbs), _thumb_states={}, _thumb_files={},
            _thumb_executor=self.executor, _push_sse=self.events.append))
        self.pak = self.stack.enter_context(patch.object(R, "decode_thumb_from_pak", return_value=None))
        self.base = self.stack.enter_context(patch.object(R._asset_cache, "cache_base", return_value=""))
        self.extract = self.stack.enter_context(patch.object(R, "extract_many", return_value={}))
        self.decode = self.stack.enter_context(patch.object(R, "decode_thumb", return_value=False))

    def tearDown(self):
        self.executor.shutdown(wait=True)
        self.stack.close()
        self.temp.cleanup()

    def request(self, names, retry=False, project="A"):
        code, result, _ = call("/api/prefetch_thumbs", {"game_rels": names, "retry": retry}, project)
        self.assertEqual(code, 200, result)
        return result

    def status(self, names, project="A"):
        code, result, _ = call("/api/thumb_status", {"game_rels": names}, project)
        self.assertEqual(code, 200, result)
        return result

    def completed(self, names):
        end = time.monotonic() + 5
        while time.monotonic() < end:
            result = self.status(names)
            if not result["pending"]: return result
            time.sleep(0.01)
        self.fail("Thumbnail fixture jobs did not finish")

    def cached_uasset(self, gr):
        base = self.root / "native" / gr
        base.parent.mkdir(parents=True, exist_ok=True)
        base.with_suffix(".uasset").write_bytes(b"fixture")
        return str(base)

    def test_status_is_read_only_missing_after_restart_and_rejects_escape(self):
        result = self.status(["Textures/Missing"])
        self.assertEqual(result["missing"], ["Textures/Missing"])
        self.assertEqual(result["pending"], [])
        self.assertEqual(result["failed"], [])
        self.pak.assert_not_called()
        for path, body, query in (
            ("/api/thumb", None, {"game_rel": "../outside"}),
            ("/api/thumb_status", {"game_rels": ["../outside"]}, None),
            ("/api/prefetch_thumbs", {"game_rels": [{"game_rel": "Textures/A"}]}, None),
        ):
            self.assertEqual(call(path, body, query=query)[0], 400)
        code, _, headers = call("/api/thumb", query={"game_rel": "Textures/Missing"})
        self.assertEqual(code, 404)
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_cached_and_project_png_priority_and_query_project_context(self):
        gr = "Textures/Same"
        blue, red, green = png("blue"), png("red"), png("green")
        for name, value in (("A", red), ("B", green)):
            target = self.projects / name / (gr + ".png")
            target.parent.mkdir(parents=True)
            target.write_bytes(value)
        self.assertEqual(call("/api/thumb", project=None,
                              query={"game_rel": gr, "_project": "B"})[1], green)
        shared = Path(R._thumb_path(gr)); shared.parent.mkdir(parents=True); shared.write_bytes(blue)
        self.assertEqual(call("/api/thumb", query={"game_rel": gr})[1], blue)
        self.assertEqual(self.request([gr])["cached"], [gr])
        self.pak.assert_not_called()
        shared.write_bytes(b"broken old cache")
        self.assertEqual(call("/api/thumb", query={"game_rel": gr})[1], red)
        # A legacy flat project image still uses the established route fallback.
        (self.projects / "A" / "Legacy.png").write_bytes(red)
        self.assertEqual(call("/api/thumb", query={"game_rel": "Textures/Legacy"})[1], red)

    def test_overlapping_clients_deduplicate_without_cancelling_other_batches(self):
        started, unblock = threading.Event(), threading.Event()
        a, b, c = "Textures/A", "Textures/B", "Textures/C"
        def decode(gr):
            if gr == a:
                started.set()
                if not unblock.wait(5): raise RuntimeError("fixture gate timeout")
            return png()
        self.pak.side_effect = decode
        try:
            self.request([a, b, a])
            self.assertTrue(started.wait(2))
            second = self.request([a, c], project="B")
            self.assertIn(a, second["pending"])
            self.assertEqual(self.pak.call_args_list.count(((a,), {})), 1)
            with self.assertRaises(O.BusyError):
                with O.change_all(): pass
        finally:
            unblock.set()
        self.assertCountEqual(self.completed([a, b, c])["cached"], [a, b, c])
        self.assertEqual(self.pak.call_count, 3)
        self.assertCountEqual([event["game_rel"] for event in self.events if event.get("thumb_ready")], [a, b, c])
        self.assertEqual(self.status([a, b, c], project="B")["pending"], [])
        for name in (a, b, c):
            with Image.open(R._thumb_path(name)) as image: self.assertEqual(image.size, (128, 64))

    def test_pak_exception_and_invalid_png_fall_back_using_extractor_returned_paths(self):
        a, b, c = "Textures/A", "Textures/B", "Textures/C"
        def fast(gr):
            if gr == a: raise RuntimeError("bad TOC fixture")
            return b"not a PNG" if gr == b else png()
        self.pak.side_effect = fast
        stems = {gr: self.cached_uasset(gr) for gr in (a, b)}
        self.extract.return_value = stems
        def fallback(uasset, target):
            self.assertFalse(Path(target).exists())
            self.assertNotEqual(target, R._thumb_path(a))
            Path(target).write_bytes(png("red", (512, 256)))
            return True
        self.decode.side_effect = fallback
        self.request([a, b, c])
        self.assertCountEqual(self.completed([a, b, c])["cached"], [a, b, c])
        self.extract.assert_called_once_with([a, b])
        self.assertEqual(self.decode.call_count, 2)
        self.assertFalse(list(self.thumbs.glob(".decode-*")))
        self.assertFalse(list(self.thumbs.rglob(".thumb-*")))

    def test_decode_failures_are_terminal_and_retry_is_explicit_during_cooldown(self):
        gr = "Textures/Unsupported"
        self.base.return_value = self.cached_uasset(gr)
        self.request([gr])
        result = self.completed([gr])
        self.assertEqual(result["failed"], [gr])
        self.assertIn("could not be decoded", result["errors"][gr])
        self.assertTrue(any(event.get("thumb_failed") for event in self.events))
        calls = self.pak.call_count
        self.request([gr])
        self.assertEqual(self.pak.call_count, calls)
        self.pak.return_value = png()
        self.request([gr], retry=True)
        self.assertEqual(self.completed([gr])["cached"], [gr])
        self.assertEqual(self.pak.call_count, calls + 1)

    def test_missing_assets_and_batch_exception_never_remain_pending(self):
        self.request(["Textures/Absent"])
        self.assertEqual(self.completed(["Textures/Absent"])["failed"], ["Textures/Absent"])
        self.extract.side_effect = RuntimeError("extraction fixture failed")
        names = ["Textures/Bad1", "Textures/Bad2"]
        self.request(names)
        self.assertCountEqual(self.completed(names)["failed"], names)
        self.assertFalse(any(event.get("thumb_ready") for event in self.events))

    def test_atomic_publish_keeps_old_file_until_valid_replacement(self):
        gr = "Textures/Existing"
        target = Path(R._thumb_path(gr)); target.parent.mkdir(parents=True)
        old = png("red"); target.write_bytes(old)
        replace = os.replace
        def checked_replace(src, dst):
            self.assertEqual(target.read_bytes(), old)
            with Image.open(src) as image: image.verify()
            return replace(src, dst)
        with patch.object(R.os, "replace", side_effect=checked_replace):
            R._publish_thumb(gr, png("blue"))
        self.assertNotEqual(target.read_bytes(), old)
        with self.assertRaises(Exception): R._publish_thumb(gr, b"broken")
        with Image.open(target) as image: image.verify()
        self.assertFalse(list(target.parent.glob(".thumb-*")))

    def test_old_batch_cleanup_cannot_fail_a_new_retry(self):
        a, b = "Textures/Retry", "Textures/Slow"
        old_gate, retry_gate = threading.Event(), threading.Event()
        old_started, retry_started = threading.Event(), threading.Event()
        a_calls = 0
        def fast(gr):
            nonlocal a_calls
            if gr == a:
                a_calls += 1
                if a_calls == 1: return None
                retry_started.set()
                if not retry_gate.wait(5): raise RuntimeError("retry fixture timeout")
            else:
                old_started.set()
                if not old_gate.wait(5): raise RuntimeError("old fixture timeout")
            return png()
        self.pak.side_effect = fast
        self.base.side_effect = lambda gr: self.cached_uasset(gr) if gr == a else ""
        try:
            self.request([a, b])
            self.assertTrue(old_started.wait(2))
            self.assertEqual(self.status([a])["failed"], [a])
            self.request([a], retry=True)
            self.assertTrue(retry_started.wait(2))
            old_gate.set()
            self.completed([b])
            time.sleep(0.05)
            self.assertEqual(self.status([a])["pending"], [a])
        finally:
            old_gate.set(); retry_gate.set()
        self.assertCountEqual(self.completed([a, b])["cached"], [a, b])

    def test_ready_publication_between_status_reads_is_reported_cached(self):
        gr = "Textures/PublicationRace"
        source = R._thumb_source
        first = True

        def publishing_source(name):
            nonlocal first
            if first:
                first = False
                # The initial lookup observed absence; the worker finishes before
                # the snapshot reads the job state. Reproduce without sleep/timing.
                R._publish_thumb(name, png())
                R._finish_thumb(name)
                return None
            return source(name)

        with patch.object(R, "_thumb_source", side_effect=publishing_source):
            result = self.status([gr])
        self.assertEqual(result["cached"], [gr])
        self.assertEqual(result["missing"], [])

    def test_windows_realpath_prefix_differences_preserve_contained_paths(self):
        # Windows realpath may return an extended-length child during concurrent
        # parent creation, although the root has already resolved without it.
        # Simulate both spellings deterministically on every test platform.
        for root, child in (
            (r"D:\cache\thumbs", r"\\?\D:\cache\thumbs\Textures\A"),
            (r"\\?\D:\cache\thumbs", r"D:\cache\thumbs\Textures\A"),
            (r"\\server\share\thumbs", r"\\?\UNC\server\share\thumbs\Textures\A"),
            (r"\\?\UNC\server\share\thumbs", r"\\server\share\thumbs\Textures\A"),
        ):
            with self.subTest(root=root), patch.object(C.os, "path", ntpath):
                with patch.object(ntpath, "realpath", side_effect=[root, child]):
                    result = C.project_base("Textures/A", root)
                # Preserve the original resolved root for I/O, including its
                # extended-length spelling when required for long paths.
                self.assertEqual(result, ntpath.join(root, "Textures", "A"))
                project_child = ntpath.dirname(child)
                with patch.object(ntpath, "realpath", side_effect=[root, project_child]):
                    self.assertEqual(C.project_dir("Textures", root), ntpath.join(root, "Textures"))

    def test_windows_prefix_normalization_still_rejects_resolved_escapes(self):
        for root, outside in (
            (r"D:\cache\thumbs", r"\\?\E:\cache\thumbs\Textures\A"),
            (r"D:\cache\thumbs", r"\\?\D:\outside\Textures\A"),
            (r"\\server\share\thumbs", r"\\?\UNC\server\other\thumbs\Textures\A"),
            (r"D:\cache\thumbs", r"\\?\GLOBALROOT\Device\HarddiskVolume1\Textures\A"),
        ):
            with self.subTest(outside=outside), patch.object(C.os, "path", ntpath):
                with patch.object(ntpath, "realpath", side_effect=[root, outside]):
                    with self.assertRaises(ValueError):
                        C.project_base("Textures/A", root)
                with patch.object(ntpath, "realpath", side_effect=[root, ntpath.dirname(outside)]):
                    with self.assertRaises(ValueError):
                        C.project_dir("Textures", root)


if __name__ == "__main__":
    unittest.main()
