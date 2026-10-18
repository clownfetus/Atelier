"""Downloading a mapping must not invalidate the active session's imported tool paths."""
import atexit
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
data = tempfile.TemporaryDirectory(prefix="atelier-update-lifetime-")
os.environ["ATELIER_DATA_DIR"] = data.name
from atelier import config as C, tools as TL
from atelier.handlers import meshedit as ME
from atelier.web import routes as R
atexit.register(lambda: (R._observer.stop(), R._observer.join(), data.cleanup()))


class MappingLifetime(unittest.TestCase):
    def test_download_keeps_active_mapping_and_pins_new_mapping_for_restart(self):
        mappings = Path(C.TOOLS, "Mappings")
        mappings.mkdir(parents=True, exist_ok=True)
        old = mappings / "5.3.2-100+++depot_marvel+S10.5_release-Marvel.usmap"
        new = mappings / "5.3.2-200+++depot_marvel+S10.5_release-Marvel.usmap"
        old.write_bytes(b"active mapping")
        notices = []
        def download(url, target):
            Path(target).write_bytes(b"next launch mapping")
        with patch.object(C, "USMAP", str(old)), patch.object(TL, "USMAP", str(old)), \
             patch.object(ME, "USMAP", str(old)), patch.object(C, "get_usmap_checked_at", return_value=0), \
             patch.object(R, "_get_latest_usmap_from_github", return_value={"name": new.name, "download_url": "fixture"}), \
             patch.object(R, "_download_usmap_file", side_effect=download), patch.object(R, "_push_sse", side_effect=notices.append):
            R.api_usmap_update_check()
            deadline = time.monotonic() + 3
            while R._usmap_check_running and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertFalse(R._usmap_check_running)
            self.assertEqual(notices, [{"usmap_updated": True, "name": new.name}])
            self.assertEqual(C.USMAP, str(old))
            self.assertEqual(TL.USMAP, str(old))
            self.assertEqual(ME.USMAP, str(old))
            self.assertEqual(old.read_bytes(), b"active mapping")
            self.assertEqual(new.read_bytes(), b"next launch mapping")
            self.assertEqual(C._load_config()["usmap"], str(new).replace('\\', '/'))


if __name__ == "__main__":
    unittest.main()
