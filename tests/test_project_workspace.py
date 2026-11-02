"""Project navigation metadata stays separate from saved asset and export state."""
import atexit
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_data = tempfile.TemporaryDirectory(prefix="atelier-workspace-tests-")
os.environ["ATELIER_DATA_DIR"] = _data.name
atexit.register(_data.cleanup)
from atelier import project_meta as M


class ProjectWorkspace(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="atelier-project-case-")
        self.addCleanup(self.temp.cleanup)
        self.root = self.temp.name

    def test_legacy_project_has_no_invented_open_time(self):
        self.assertEqual(M.load(self.root)["last_opened_at"], 0)
        self.assertFalse(Path(self.root, ".atelier").exists())

    def test_open_time_survives_other_metadata_writes(self):
        with patch.object(M.time, "time", return_value=123.5):
            M.mark_opened(self.root)
        M.set_deselected(self.root, ["Characters/Test"])
        M.set_asset_opts(self.root, "Characters/Test", {"no_mips": True})
        data = M.load(self.root)
        self.assertEqual(data["last_opened_at"], 123.5)
        self.assertEqual(data["deselected"], ["Characters/Test"])
        self.assertTrue(data["asset_opts"]["Characters/Test"]["no_mips"])


if __name__ == "__main__":
    unittest.main()
