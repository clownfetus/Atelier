"""Unit tests for Look Presets and One-Click Hero Colour Theme (atelier/themes.py)."""
import tempfile
import unittest

from atelier import themes


class HeroThemesTests(unittest.TestCase):
    def test_builtin_and_custom_looks_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            initial = themes.list_looks(tmp)
            self.assertGreaterEqual(len(initial), 6)
            self.assertTrue(all(l["builtin"] for l in initial))

            after_save = themes.save_custom_look(tmp, {
                "name": "Spider Gwen",
                "primary": "#f5f7fa",
                "secondary": "#15161c",
                "accent": "#ec4899",
                "energy": "#38bdf8",
            })
            custom = [l for l in after_save if not l["builtin"]]
            self.assertEqual(len(custom), 1)
            self.assertEqual(custom[0]["name"], "Spider Gwen")

            after_del = themes.delete_custom_look(tmp, custom[0]["id"])
            self.assertEqual(len(after_del), len(initial))

    def test_colour_mapping_preserves_alpha_and_hdr_emissive_intensity(self):
        colors = [
            {"name": "Region 1 - ColorA", "rgba": [0.5, 0.5, 0.5, 0.75]},
            {"name": "Region 3 - ColorB", "rgba": [0.2, 0.2, 0.2, 1.0]},
            {"name": "Region 5 - Accent", "rgba": [0.8, 0.8, 0.8, 1.0]},
            {"name": "EmissiveColor", "rgba": [4.0, 1.0, 0.5, 1.0]},
            {"name": "UnrelatedUVOffset", "rgba": [1.0, 2.0, 0.0, 1.0]},
        ]
        theme = {"primary": "#ff0000", "secondary": "#0000ff", "accent": "#00ff00", "energy": "#ffffff"}
        edits = themes.compute_material_colour_edits(colors, theme)
        self.assertIn("Region 1 - ColorA", edits)
        self.assertAlmostEqual(edits["Region 1 - ColorA"][0], 1.0, places=4)
        self.assertAlmostEqual(edits["Region 1 - ColorA"][3], 0.75, places=4)
        self.assertAlmostEqual(edits["Region 3 - ColorB"][2], 1.0, places=4)
        self.assertAlmostEqual(edits["Region 5 - Accent"][1], 1.0, places=4)
        # EmissiveColor had HDR peak 4.0 -> preserved at 4.0!
        self.assertAlmostEqual(edits["EmissiveColor"][0], 4.0, places=4)
        self.assertNotIn("UnrelatedUVOffset", edits)

    def test_propose_theme_targets_unchecks_shared_common_materials_by_default(self):
        entries = [(p, "pak", "Marvel/Content/Marvel/") for p in [
            "Characters/1060/1060501/Materials/MI_1060501_Body.uasset",
            "Characters/1060/1060501/Weapons/Materials/MI_1060501_Weapon.uasset",
            "Characters/1060/1060CommonMaterial/MI_1060_Shared.uasset",
            "Characters/1060/1060001/VFX/NS_1060_Slash.uasset",
        ]]
        proposal = themes.propose_theme_targets(skin_id="1060501", index_entries=entries)
        by_name = {t["name"]: t for t in proposal["targets"]}
        self.assertTrue(by_name["MI_1060501_Body"]["checked"])
        self.assertFalse(by_name["MI_1060501_Body"]["shared"])
        self.assertTrue(by_name["MI_1060501_Weapon"]["checked"])
        self.assertEqual(by_name["MI_1060501_Weapon"]["group"], "Weapon materials")
        self.assertFalse(by_name["MI_1060_Shared"]["checked"])
        self.assertTrue(by_name["MI_1060_Shared"]["shared"])


if __name__ == "__main__":
    unittest.main()
