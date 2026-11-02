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
        M.mark_opened(self.root, reset=True)
        self.assertEqual(M.load(self.root)["last_opened_at"], 0)
        self.assertEqual(M.get_deselected(self.root), {"Characters/Test"})

    def test_workspace_survives_save_and_preserves_selection(self):
        M.set_deselected(self.root, ["Characters/Test"])
        state = {"skin_id": "1029001", "model": "Characters/1029/1029001/Meshes/Body", "material_set": "1029002"}
        M.set_workspace(self.root, state)
        M.set_asset_opts(self.root, "Characters/Test", {"no_mips": True})
        self.assertEqual(M.workspace(self.root), state)
        self.assertEqual(M.get_deselected(self.root), {"Characters/Test"})

    def test_legacy_single_costume_is_inferred_but_ambiguous_projects_choose(self):
        asset = Path(self.root, "Characters/1029/1029001/Materials/Body.json")
        asset.parent.mkdir(parents=True); asset.write_text("{}")
        self.assertEqual(M.workspace(self.root), {"skin_id": "1029001"})
        other = Path(self.root, "Characters/1029/1029002/Textures/Body.png")
        other.parent.mkdir(parents=True); other.write_bytes(b"fixture")
        self.assertEqual(M.workspace(self.root), {})
        self.assertFalse(Path(self.root, ".atelier").exists())


class DockColourChanges(unittest.TestCase):
    """The Your mod dock shows what an edit changed, matched to the original by parameter name."""
    def changes(self, edited, original, **kwargs):
        from atelier.web import browse
        with patch.object(browse, "_edited_colors", return_value=edited), \
             patch("atelier.handlers.material.read_material_original", return_value={"colors": original}):
            return browse.edited_colour_changes("Characters/1029/1029001/Materials/MI_Body", **kwargs)

    def test_only_changed_colours_are_reported_as_the_editor_shows_them(self):
        original = [{"name": "Tint", "rgba": [1, 0, 0, 1]}, {"name": "Trim", "rgba": [0, 0, 1, 1]}]
        edited = [{"name": "Tint", "rgba": [1, 0, 0, 1]}, {"name": "Trim", "rgba": [0, 4, 0, 1]}]
        # HDR intensity is divided out, so a bright green reads as the green the picker shows.
        self.assertEqual(self.changes(edited, original), [{"name": "Trim", "before": "#0000ff", "after": "#00ff00"}])

    def test_a_colour_the_original_lacks_has_no_before(self):
        edited = [{"name": "Added", "rgba": [.5, .5, .5, 1]}]
        self.assertEqual(self.changes(edited, []), [{"name": "Added", "before": None, "after": "#808080"}])

    def test_no_project_copy_means_no_changes_and_no_original_read(self):
        from atelier.web import browse
        with patch.object(browse, "_edited_colors", return_value=None), \
             patch("atelier.handlers.material.read_material_original") as read:
            self.assertEqual(browse.edited_colour_changes("Characters/1029/1029001/Materials/MI_Body"), [])
        read.assert_not_called()

    def test_changes_are_capped(self):
        edited = [{"name": f"C{i}", "rgba": [i / 10, 0, 0, 1]} for i in range(1, 9)]
        self.assertEqual(len(self.changes(edited, [], limit=3)), 3)


if __name__ == "__main__":
    unittest.main()
