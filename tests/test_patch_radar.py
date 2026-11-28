"""Unit tests for Game Patch Radar baseline recording and diffing (atelier/patch_radar.py)."""
from pathlib import Path
import tempfile
import unittest

from atelier import patch_radar


class PatchRadarTests(unittest.TestCase):
    def test_scan_without_baseline_stays_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = patch_radar.scan_project(tmp, ["Characters/1060/1060501/Textures/T_Body_D"], paks_dir=tmp, lookup={})
            self.assertFalse(res["has_baseline"])
            self.assertFalse(res["needs_attention"])
            self.assertEqual(res["changed"], [])

    def test_detects_patch_container_override_in_place_update_and_removal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proj = root / "Proj"
            paks = root / "Paks"
            proj.mkdir()
            paks.mkdir()

            (paks / "pakchunk0-Windows.utoc").write_bytes(b"v1-base")
            (paks / "pakchunk1-Windows.utoc").write_bytes(b"v1-mat")
            (paks / "pakchunk2-Windows.utoc").write_bytes(b"v1-mesh")

            items = [
                "Characters/1060/1060501/Textures/T_Unchanged_D",
                "Characters/1060/1060501/Materials/MI_Patched",
                "Characters/1060/1060501/Meshes/SK_UpdatedInPlace",
                "Characters/1060/1060501/Textures/T_Removed_D",
            ]
            lookup_v1 = {
                "characters/1060/1060501/textures/t_unchanged_d.uasset": ("Characters/1060/1060501/Textures/T_Unchanged_D.uasset", "pakchunk0-Windows.utoc", "Marvel/Content/Marvel/"),
                "characters/1060/1060501/materials/mi_patched.uasset": ("Characters/1060/1060501/Materials/MI_Patched.uasset", "pakchunk1-Windows.utoc", "Marvel/Content/Marvel/"),
                "characters/1060/1060501/meshes/sk_updatedinplace.uasset": ("Characters/1060/1060501/Meshes/SK_UpdatedInPlace.uasset", "pakchunk2-Windows.utoc", "Marvel/Content/Marvel/"),
                "characters/1060/1060501/textures/t_removed_d.uasset": ("Characters/1060/1060501/Textures/T_Removed_D.uasset", "pakchunk0-Windows.utoc", "Marvel/Content/Marvel/"),
            }
            patch_radar.record_baseline(proj, items, paks_dir=paks, lookup=lookup_v1)

            # Before patch: everything matches baseline.
            clean = patch_radar.scan_project(proj, items, paks_dir=paks, lookup=lookup_v1)
            self.assertTrue(clean["has_baseline"])
            self.assertFalse(clean["needs_attention"])
            self.assertEqual(clean["unchanged_count"], 4)

            # Simulate a game patch:
            # - MI_Patched now comes from a new _P container
            # - pakchunk2-Windows.utoc changed size on disk
            # - T_Removed_D disappeared from the index
            (paks / "pakchunk1-Windows_P.utoc").write_bytes(b"v2-patch-mat")
            (paks / "pakchunk2-Windows.utoc").write_bytes(b"v2-updated-mesh-larger-bytes")
            lookup_v2 = {
                "characters/1060/1060501/textures/t_unchanged_d.uasset": ("Characters/1060/1060501/Textures/T_Unchanged_D.uasset", "pakchunk0-Windows.utoc", "Marvel/Content/Marvel/"),
                "characters/1060/1060501/materials/mi_patched.uasset": ("Characters/1060/1060501/Materials/MI_Patched.uasset", "pakchunk1-Windows_P.utoc", "Marvel/Content/Marvel/"),
                "characters/1060/1060501/meshes/sk_updatedinplace.uasset": ("Characters/1060/1060501/Meshes/SK_UpdatedInPlace.uasset", "pakchunk2-Windows.utoc", "Marvel/Content/Marvel/"),
            }

            after = patch_radar.scan_project(proj, items, paks_dir=paks, lookup=lookup_v2)
            self.assertTrue(after["needs_attention"])
            self.assertEqual(after["unchanged_count"], 1)
            self.assertEqual({c["name"] for c in after["changed"]}, {"MI_Patched", "SK_UpdatedInPlace"})
            self.assertEqual([r["name"] for r in after["removed"]], ["T_Removed_D"])
            self.assertTrue(all(c["risk"] == "high" for c in after["changed"]))


if __name__ == "__main__":
    unittest.main()
