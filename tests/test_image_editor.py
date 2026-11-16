"""Settings → Image editor: textures open in the program the person chose, else the default app."""
import atexit
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import quote
from wsgiref.util import setup_testing_defaults

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_app_data = tempfile.TemporaryDirectory(prefix="atelier-image-editor-")
os.environ["ATELIER_DATA_DIR"] = _app_data.name
from atelier import config as C, hostos as H
from atelier.web import routes as R


def _cleanup():
    R._observer.stop()
    R._observer.join()
    _app_data.cleanup()


atexit.register(_cleanup)


def call(method, path, body=None, query=""):
    env = {}
    setup_testing_defaults(env)
    payload = json.dumps(body or {}).encode() if method == "POST" else b""
    env.update(REQUEST_METHOD=method, PATH_INFO=path, QUERY_STRING=query,
               CONTENT_TYPE="application/json", CONTENT_LENGTH=str(len(payload)),
               **{"wsgi.input": io.BytesIO(payload)})
    status = []
    result = R.app(env, lambda s, h, exc_info=None: status.append(s))
    try:
        data = b"".join(result).decode()
    finally:
        if hasattr(result, "close"):
            result.close()
    return int(status[0].split()[0]), json.loads(data)


class ImageEditor(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="atelier-editor-case-")
        self.root = Path(self.temp.name).resolve()
        self.editor = self.root / "Editor" / ("Paint Thing.exe" if H.IS_WINDOWS else "paint-thing")
        self.editor.parent.mkdir()
        self.editor.write_bytes(b"MZ")
        self.editor.chmod(0o755)
        self.image = self.root / "T_Body_D.png"
        self.image.write_bytes(b"png")
        self.config = patch.object(C, "CONFIG_FILE", str(self.root / "config.json"))
        self.config.start()

    def tearDown(self):
        self.config.stop()
        self.temp.cleanup()

    def test_editor_setting_round_trips_and_clears(self):
        self.assertEqual(C.get_image_editor(), "")
        C.save_image_editor(str(self.editor))
        self.assertEqual(C.get_image_editor(), str(self.editor).replace("\\", "/"))
        C.save_mods_folder("mods")
        self.assertEqual(C.get_image_editor(), str(self.editor).replace("\\", "/"))
        C.save_image_editor("")
        self.assertEqual(C.get_image_editor(), "")
        self.assertNotIn("image_editor", C._load_config())

    def test_only_existing_programs_count_as_editors(self):
        self.assertTrue(H.is_app_executable(str(self.editor)))
        self.assertFalse(H.is_app_executable(str(self.root / "missing.exe")))
        self.assertFalse(H.is_app_executable(""))
        self.assertFalse(H.is_app_executable(str(self.root)))
        if H.IS_WINDOWS:
            self.assertFalse(H.is_app_executable(str(self.image)))

    def test_display_name_falls_back_to_the_file_name_and_stays_short(self):
        # A fake .exe carries no version resource, so the file name is what the menu shows.
        self.assertEqual(H.app_display_name(str(self.editor)), "Paint Thing" if H.IS_WINDOWS else "paint-thing")
        self.assertEqual(H.app_display_name(""), "your image editor")
        self.assertEqual(H.app_display_name("C:/x/" + "A" * 80 + ".exe"), "A" * 40)
        self.assertEqual(H.app_display_name("C:/x/Odd\tname\x07.exe"), "Oddname")

    def test_open_with_starts_the_chosen_editor_with_the_image(self):
        with patch.object(H.subprocess, "Popen") as popen, patch.object(H, "open_path") as default:
            H.open_with(str(self.image), str(self.editor))
        default.assert_not_called()
        args = popen.call_args.args[0]
        self.assertEqual(args, [os.path.abspath(self.editor), os.path.abspath(self.image)])

    def test_open_with_uses_the_default_app_without_an_editor(self):
        with patch.object(H.subprocess, "Popen") as popen, patch.object(H, "open_path") as default:
            H.open_with(str(self.image))
        popen.assert_not_called()
        default.assert_called_once_with(os.path.abspath(self.image))

    def test_open_with_refuses_an_editor_that_has_gone(self):
        with patch.object(H.subprocess, "Popen") as popen:
            with self.assertRaises(FileNotFoundError):
                H.open_with(str(self.image), str(self.root / "gone.exe"))
        popen.assert_not_called()

    def test_open_route_reports_a_missing_editor(self):
        C.save_image_editor(str(self.root / "gone.exe"))
        with patch.object(H.subprocess, "Popen") as popen:
            status, data = call("GET", "/api/open_with", query="path=" + quote(str(self.image)))
        popen.assert_not_called()
        self.assertEqual((status, data), (200, {"ok": False, "error": "Check the image editor in Settings."}))

    def test_open_route_launches_the_configured_editor(self):
        C.save_image_editor(str(self.editor))
        with patch.object(H.subprocess, "Popen") as popen:
            status, data = call("GET", "/api/open_with", query="path=" + quote(str(self.image)))
        self.assertEqual((status, data), (200, {"ok": True}))
        self.assertEqual(popen.call_args.args[0], [os.path.abspath(self.editor), os.path.abspath(self.image)])

    def test_validation_names_each_state(self):
        def status(path):
            return call("GET", "/api/validate_image_editor", query="path=" + quote(path))[1]["status"]
        self.assertEqual(status(""), "empty")
        self.assertEqual(status(str(self.root / "gone.exe")), "missing")
        self.assertEqual(status(str(self.editor)), "ok")
        if H.IS_WINDOWS:
            self.assertEqual(status(str(self.image)), "invalid")

    def test_settings_refuse_a_file_that_is_not_a_program(self):
        status, data = call("POST", "/api/save_paks", {"path": str(self.root), "aes_key": "0x" + "A" * 64,
                                                       "image_editor": str(self.root / "gone.exe")})
        self.assertEqual(status, 200)
        self.assertFalse(data["ok"])
        self.assertIn("image editor must be an existing program", data["error"])
        self.assertEqual(C.get_image_editor(), "")

    def test_setup_status_names_the_editor(self):
        C.save_image_editor(str(self.editor))
        data = call("GET", "/api/setup_status")[1]
        self.assertEqual(data["image_editor"], str(self.editor).replace("\\", "/"))
        self.assertEqual(data["image_editor_name"], H.app_display_name(str(self.editor)))
        C.save_image_editor("")
        data = call("GET", "/api/setup_status")[1]
        self.assertEqual((data["image_editor"], data["image_editor_name"]), ("", ""))


if __name__ == "__main__":
    unittest.main()
