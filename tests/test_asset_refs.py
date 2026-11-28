"""Unit tests for Shared-Asset Reference inspection & Safe Fork (atelier/asset_refs.py)."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from atelier import asset_refs


class AssetRefsTests(unittest.TestCase):
    def test_common_material_bucket_flags_shared_across_hero_costumes(self):
        entries = [(p, "pak", "Marvel/Content/Marvel/") for p in [
            "Characters/1060/1060001/Meshes/SK_1060_001.uasset",
            "Characters/1060/1060501/Meshes/SK_1060_501.uasset",
            "Characters/1060/1060502/Meshes/SK_1060_502.uasset",
            "Characters/1060/1060CommonMaterial/MI_1060_SharedMetal.uasset",
        ]]
        with patch("atelier.index.ensure_index", return_value=entries):
            info = asset_refs.find_references("Characters/1060/1060CommonMaterial/MI_1060_SharedMetal")
        self.assertTrue(info["is_shared"])
        self.assertEqual(info["scope"], "hero_shared")
        self.assertEqual(len(info["affected_skins"]), 3)
        self.assertTrue(info["fork"]["forkable"])
        self.assertEqual(info["fork"]["folder"], "Atelier/Private/Hero_1060")

    def test_single_skin_material_stays_unflagged_when_not_shared(self):
        entries = [(p, "pak", "Marvel/Content/Marvel/") for p in [
            "Characters/1060/1060501/Materials/MI_1060501_Cloth.uasset",
            "Characters/1060/1060501/Meshes/SK_1060501.uasset",
        ]]
        with patch("atelier.index.ensure_index", return_value=entries):
            info = asset_refs.find_references("Characters/1060/1060501/Materials/MI_1060501_Cloth")
        self.assertFalse(info["is_shared"])
        self.assertEqual(info["scope"], "skin")

    def test_deep_scan_finds_verified_reverse_imports_in_cached_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            mat_doc = {
                "FolderName": "/Game/Marvel/Characters/1060/1060502/Materials/MI_Chroma",
                "Imports": [
                    {"ObjectName": "/Game/Marvel/Characters/1060/1060501/Textures/T_Shared_D", "ClassName": "Package", "OuterIndex": 0},
                    {"ObjectName": "T_Shared_D", "ClassName": "Texture2D", "OuterIndex": -1},
                ],
            }
            (cache / "MI_Chroma.json").write_text(json.dumps(mat_doc), encoding="utf-8")
            entries = [(p, "pak", "Marvel/Content/Marvel/") for p in [
                "Characters/1060/1060501/Textures/T_Shared_D.uasset",
                "Characters/1060/1060502/Materials/MI_Chroma.uasset",
            ]]
            with patch("atelier.index.ensure_index", return_value=entries):
                info = asset_refs.find_references(
                    "Characters/1060/1060501/Textures/T_Shared_D",
                    deep=True,
                    cache_dirs=[cache],
                )
            self.assertTrue(info["is_shared"])
            self.assertEqual(len(info["verified_referrers"]), 1)
            self.assertEqual(info["verified_referrers"][0]["game_rel"], "Characters/1060/1060502/Materials/MI_Chroma")

    def test_safe_fork_auto_increments_on_name_collision(self):
        calls = []

        def fake_add(ft, folder, name, source=""):
            calls.append((ft, folder, name, source))
            if len(calls) == 1:
                raise ValueError("An asset already exists in this project at this location.")
            return {"game_rel": f"{folder}/{name}", "file_type": ft}

        with patch("atelier.added_assets.add", side_effect=fake_add):
            res = asset_refs.safe_fork("Characters/1060/1060CommonMaterial/MI_1060_Metal", "material")
        self.assertTrue(res["ok"])
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[1][2].endswith("_2"))


if __name__ == "__main__":
    unittest.main()
