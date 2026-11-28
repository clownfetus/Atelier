"""Regression tests for live external-editor hot reload (atelier/file_watcher.py)."""
from io import BytesIO
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest

from PIL import Image

from atelier.file_watcher import ProjectFileHandler, is_complete_png, wait_for_complete_png


class _FakeEvent:
    def __init__(self, src_path="", dest_path="", is_directory=False):
        self.src_path = src_path
        self.dest_path = dest_path
        self.is_directory = is_directory


def _png_bytes(color=(255, 0, 128, 255)):
    buf = BytesIO()
    Image.new("RGBA", (8, 8), color).save(buf, format="PNG")
    return buf.getvalue()


class HotReloadWatcherTests(unittest.TestCase):
    def test_is_complete_png_distinguishes_truncated_and_valid_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            full = Path(tmp) / "valid.png"
            data = _png_bytes()
            full.write_bytes(data)
            self.assertTrue(is_complete_png(str(full)))

            partial = Path(tmp) / "partial.png"
            partial.write_bytes(data[:20])
            self.assertFalse(is_complete_png(str(partial)))

            no_iend = Path(tmp) / "no_iend.png"
            no_iend.write_bytes(data[:-12])
            self.assertFalse(is_complete_png(str(no_iend)))

            self.assertFalse(is_complete_png(str(Path(tmp) / "missing.png")))

    def test_wait_for_complete_png_waits_for_delayed_flush(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "delayed.png"
            data = _png_bytes()
            target.write_bytes(data[:16])

            def finish():
                time.sleep(0.08)
                target.write_bytes(data)

            thread = threading.Thread(target=finish)
            thread.start()
            try:
                self.assertTrue(wait_for_complete_png(str(target), timeout=1.0, poll=0.02))
            finally:
                thread.join()

    def test_handler_emits_on_modified_created_and_atomic_move(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "MyMod"
            tex_dir = project_dir / "Characters" / "1060" / "1060501" / "Textures"
            tex_dir.mkdir(parents=True)
            tex_file = tex_dir / "T_1060501_D.png"
            tex_file.write_bytes(_png_bytes((10, 20, 30, 255)))

            events = []
            ready = threading.Event()

            def push(payload):
                events.append(payload)
                ready.set()

            handler = ProjectFileHandler(
                get_import_root=lambda: str(project_dir),
                project_game_rel=lambda p, root: os.path.relpath(p, root).replace("\\", "/")[:-4],
                resolve_by_name=lambda name: None,
                token_fn=lambda gr: f"tok:{gr}",
                push_sse=push,
                ignored_dirs=(".atelier", ".trash"),
                debounce_seconds=0.05,
                complete_timeout=0.5,
            )
            try:
                # Simulate rapid back-to-back writes coalesced into one trailing event.
                handler.on_modified(_FakeEvent(src_path=str(tex_file)))
                handler.on_modified(_FakeEvent(src_path=str(tex_file)))
                self.assertTrue(ready.wait(1.0))
                self.assertEqual(len(events), 1)
                self.assertTrue(events[0]["file_changed"])
                self.assertEqual(events[0]["game_rel"], "Characters/1060/1060501/Textures/T_1060501_D")
                self.assertEqual(events[0]["project"], "MyMod")
                self.assertTrue(events[0]["ver"])

                # Simulate atomic temp-file -> rename save (Photoshop / Krita / Substance).
                ready.clear()
                temp_file = tex_dir / "T_1060501_D.png.tmp"
                temp_file.write_bytes(_png_bytes((200, 100, 50, 255)))
                os.replace(temp_file, tex_file)
                handler.on_moved(_FakeEvent(src_path=str(temp_file), dest_path=str(tex_file)))
                self.assertTrue(ready.wait(1.0))
                self.assertEqual(len(events), 2)
                self.assertEqual(events[1]["game_rel"], "Characters/1060/1060501/Textures/T_1060501_D")
            finally:
                handler.cancel_pending()

    def test_handler_ignores_other_projects_and_internal_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            active = Path(tmp) / "Active"
            other = Path(tmp) / "Other"
            (active / ".atelier").mkdir(parents=True)
            other.mkdir(parents=True)
            internal_png = active / ".atelier" / "thumb.png"
            other_png = other / "T_Other.png"
            internal_png.write_bytes(_png_bytes())
            other_png.write_bytes(_png_bytes())

            events = []
            handler = ProjectFileHandler(
                get_import_root=lambda: str(active),
                project_game_rel=lambda p, root: os.path.relpath(p, root).replace("\\", "/")[:-4],
                resolve_by_name=lambda name: None,
                token_fn=lambda gr: gr,
                push_sse=events.append,
                ignored_dirs=(".atelier", ".trash"),
                debounce_seconds=0.03,
                complete_timeout=0.2,
            )
            try:
                handler.on_modified(_FakeEvent(src_path=str(internal_png)))
                handler.on_modified(_FakeEvent(src_path=str(other_png)))
                time.sleep(0.12)
                self.assertEqual(events, [])
            finally:
                handler.cancel_pending()

    def test_handler_emits_asset_removed_when_moved_outside_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            active = Path(tmp) / "Active"
            outside = Path(tmp) / "Outside"
            active.mkdir()
            outside.mkdir()
            events = []
            handler = ProjectFileHandler(
                get_import_root=lambda: str(active),
                project_game_rel=lambda p, root: p,
                resolve_by_name=lambda name: None,
                token_fn=lambda gr: gr,
                push_sse=events.append,
                ignored_dirs=(".atelier", ".trash"),
            )
            handler.on_moved(_FakeEvent(
                src_path=str(active / "T_Test.png"),
                dest_path=str(outside / "T_Test.png"),
            ))
            self.assertEqual(events, [{"asset_removed": True}])


if __name__ == "__main__":
    unittest.main()
