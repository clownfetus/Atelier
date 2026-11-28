"""Unit tests for the lazy-loaded UI / HUD Frame Mockup module (gui/ui-mockup.js)."""
import json
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parent.parent


class UiMockupTests(unittest.TestCase):
    def _run_node(self, script: str):
        proc = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(proc.stdout.strip())

    def test_ui_path_detection_excludes_character_and_vfx_textures(self):
        result = self._run_node("""
            import { isUiTexturePath, defaultPresetForPath, HUD_PRESETS, aspectHint } from './gui/ui-mockup.js';
            const cases = {
              nameplate: isUiTexturePath('UI/Textures/Show/NameplateFrame/T_NP_01'),
              playerhead: isUiTexturePath('UI/Textures/Show/PlayerheadFrame/T_Head_1060'),
              lq_ui: isUiTexturePath('Marvel_LQ/UI/Textures/HeroGallery_V3/T_Hero_1029'),
              spray: isUiTexturePath('UI/Textures/Spray/T_Spray_Magik'),
              crosshair: isUiTexturePath('UI/Textures/HUD/Crosshair/T_Crosshair_Dot'),
              char_diffuse: isUiTexturePath('Characters/1060/1060501/Textures/T_1060501_D'),
              char_normal: isUiTexturePath('Characters/1029/1029001/Textures/T_1029001_N'),
              vfx_tex: isUiTexturePath('VFX/Textures/T_Spark_01'),
            };
            const presets = {
              nameplate: defaultPresetForPath('UI/Textures/Show/NameplateFrame/T_NP_01'),
              playerhead: defaultPresetForPath('UI/Textures/Show/PlayerheadFrame/T_Head_1060'),
              crosshair: defaultPresetForPath('UI/Textures/HUD/Crosshair/T_Crosshair_Dot'),
              kill: defaultPresetForPath('UI/Textures/Item/item_kill_1060'),
              spray: defaultPresetForPath('UI/Textures/Spray/T_Spray_01'),
              ability: defaultPresetForPath('Plugins/MarvelGAS/UI/AbilityIcon_Q'),
              tile: defaultPresetForPath('UI/Textures/HeroGallery_V3/T_Hero_1029'),
            };
            const mismatch = aspectHint(HUD_PRESETS.find(p => p.id === 'nameplate'), 512, 512);
            const matched = aspectHint(HUD_PRESETS.find(p => p.id === 'portrait'), 512, 512);
            console.log(JSON.stringify({
              cases,
              presets,
              preset_count: HUD_PRESETS.length,
              all_have_svg: HUD_PRESETS.every(p => p.svg.includes('<svg') && p.svg.includes('</svg>')),
              mismatch_warns: mismatch.includes('check crop/aspect'),
              matched_clean: !matched.includes('check crop/aspect'),
            }));
        """)
        self.assertTrue(result["cases"]["nameplate"])
        self.assertTrue(result["cases"]["playerhead"])
        self.assertTrue(result["cases"]["lq_ui"])
        self.assertTrue(result["cases"]["spray"])
        self.assertTrue(result["cases"]["crosshair"])
        self.assertFalse(result["cases"]["char_diffuse"])
        self.assertFalse(result["cases"]["char_normal"])
        self.assertFalse(result["cases"]["vfx_tex"])
        self.assertEqual(result["presets"], {
            "nameplate": "nameplate",
            "playerhead": "portrait",
            "crosshair": "crosshair",
            "kill": "killfeed",
            "spray": "spray",
            "ability": "ability",
            "tile": "hero-tile",
        })
        self.assertEqual(result["preset_count"], 7)
        self.assertTrue(result["all_have_svg"])
        self.assertTrue(result["mismatch_warns"])
        self.assertTrue(result["matched_clean"])


if __name__ == "__main__":
    unittest.main()
