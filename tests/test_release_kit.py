"""Unit tests for Batch Variant Builder & Release Kit Exporter (atelier/release_kit.py)."""
from pathlib import Path
import tempfile
import unittest
import zipfile

from atelier import release_kit


class ReleaseKitTests(unittest.TestCase):
    def test_plan_profile_variants_filters_deselected_and_dedupes_stems(self):
        items = [
            "Characters/1060/1060501/Textures/T_Body_D",
            "Characters/1060/1060501/Meshes/SK_Cape",
            "VFX/NS_Slash",
        ]
        profiles = {
            "Base": {"deselected": [], "mod_name": ""},
            "No Cape": {"deselected": ["Characters/1060/1060501/Meshes/SK_Cape"], "mod_name": "Kumiho_NoCape"},
            "Duplicate Stem": {"deselected": ["VFX/NS_Slash"], "mod_name": "Kumiho_NoCape"},
            "Empty": {"deselected": list(items), "mod_name": ""},
        }
        plan = release_kit.plan_profile_variants(profiles, items, "Kumiho")
        self.assertEqual([p["profile"] for p in plan], ["Base", "No Cape", "Duplicate Stem", "Empty"])
        self.assertEqual(plan[0]["mod_stem"], "Kumiho_Base")
        self.assertEqual(len(plan[0]["items"]), 3)
        self.assertEqual(plan[1]["mod_stem"], "Kumiho_NoCape")
        self.assertEqual(plan[1]["excluded_count"], 1)
        self.assertEqual(plan[2]["mod_stem"], "Kumiho_NoCape_2")
        self.assertEqual(plan[3]["items"], [])
        self.assertTrue(plan[3]["skipped_reason"])

    def test_write_release_kit_creates_zips_and_readme(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "mods"
            kit_dir = Path(tmp) / "kit"
            out_dir.mkdir()
            for stem in ("Mod_Base", "Mod_Alt"):
                for ext in (".pak", ".utoc", ".ucas"):
                    (out_dir / f"{stem}{ext}").write_bytes(f"data-{stem}-{ext}".encode())

            items = [
                "Characters/1060/1060501/Textures/T_Body_D",
                "Characters/1060/1060501/Materials/MI_Body",
                "Characters/1060/1060501/Meshes/SK_Body",
            ]
            variants = [
                {"profile": "Base", "mod_stem": "Mod_Base", "items": items, "ok": True, "artifacts": [], "skipped": []},
                {"profile": "Alt", "mod_stem": "Mod_Alt", "items": items[:2], "ok": True, "artifacts": [], "skipped": ["minor note"]},
            ]
            kit = release_kit.write_release_kit(
                kit_dir=str(kit_dir),
                project_name="CoastalRecolour",
                mod_name="Coastal_Gold",
                built_variants=variants,
                all_items=items,
                out_dir=str(out_dir),
                atelier_version="1.2.8",
            )
            self.assertEqual(len(kit["zips"]), 2)
            for zp in kit["zips"]:
                with zipfile.ZipFile(zp, "r") as zf:
                    names = sorted(zf.namelist())
                    self.assertEqual(len(names), 3)
            readme = Path(kit["readme_path"]).read_text(encoding="utf-8")
            self.assertIn("# Coastal_Gold", readme)
            self.assertIn("`Mod_Base.zip`", readme)
            self.assertIn("`Mod_Alt.zip`", readme)
            self.assertIn("1060501", readme)
            self.assertIn("1 warning(s)", readme)


if __name__ == "__main__":
    unittest.main()
