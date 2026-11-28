"""Unit tests for Installed Mods Drawer & Clean-Test Sandbox (atelier/mod_sandbox.py)."""
from pathlib import Path
import tempfile
import unittest

from atelier import mod_sandbox


class ModSandboxTests(unittest.TestCase):
    def _touch_iostore(self, root: Path, stem: str, *, disabled: bool = False, partitioned: bool = False):
        suffix = ".disabled" if disabled else ""
        for ext in (".pak", ".utoc", ".ucas"):
            (root / f"{stem}{ext}{suffix}").write_bytes(b"moddata")
        if partitioned:
            (root / f"{stem}_s1.ucas{suffix}").write_bytes(b"part1")

    def test_scan_groups_iostore_partitions_and_marks_current_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            mods = Path(tmp) / "~mods"
            mods.mkdir()
            self._touch_iostore(mods, "MagikGold_P", partitioned=True)
            self._touch_iostore(mods, "OldSkin_P", disabled=True)
            (mods / "LegacyMod.pak").write_bytes(b"pak")

            res = mod_sandbox.scan_installed_mods(mods, current_mod_name="MagikGold")
            self.assertEqual(res["total_count"], 3)
            self.assertEqual(res["enabled_count"], 2)
            by_name = {m["name"]: m for m in res["mods"]}
            self.assertTrue(by_name["MagikGold_P"]["is_current"])
            self.assertEqual(len(by_name["MagikGold_P"]["files"]), 4)
            self.assertEqual(by_name["MagikGold_P"]["kind"], "IoStore")
            self.assertFalse(by_name["OldSkin_P"]["enabled"])
            self.assertEqual(by_name["LegacyMod"]["kind"], "PAK")

    def test_toggle_mod_renames_all_bundle_files_and_blocks_while_game_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            mods = Path(tmp) / "~mods"
            mods.mkdir()
            self._touch_iostore(mods, "HeroSkin_P", partitioned=True)

            with self.assertRaises(RuntimeError):
                mod_sandbox.toggle_mod(mods, "HeroSkin_P", False, game_running_check=lambda: True)
            self.assertTrue((mods / "HeroSkin_P.pak").is_file())

            mod_sandbox.toggle_mod(mods, "HeroSkin_P", False, game_running_check=lambda: False)
            for name in ("HeroSkin_P.pak.disabled", "HeroSkin_P.utoc.disabled", "HeroSkin_P.ucas.disabled", "HeroSkin_P_s1.ucas.disabled"):
                self.assertTrue((mods / name).is_file())

            mod_sandbox.toggle_mod(mods, "HeroSkin_P", True, game_running_check=lambda: False)
            for name in ("HeroSkin_P.pak", "HeroSkin_P.utoc", "HeroSkin_P.ucas", "HeroSkin_P_s1.ucas"):
                self.assertTrue((mods / name).is_file())

    def test_clean_test_pauses_only_other_mods_and_restores_exact_previous_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            mods = Path(tmp) / "~mods"
            mods.mkdir()
            state_file = Path(tmp) / "clean_test_state.json"
            self._touch_iostore(mods, "MyTest_P")
            self._touch_iostore(mods, "OtherA_P")
            self._touch_iostore(mods, "OtherB_P")
            self._touch_iostore(mods, "AlreadyOff_P", disabled=True)

            on = mod_sandbox.set_clean_test(mods, enable=True, keep_mod="MyTest", state_path=state_file)
            self.assertTrue(on["active"])
            self.assertEqual(on["paused"], 2)
            self.assertTrue((mods / "MyTest_P.pak").is_file())
            self.assertTrue((mods / "OtherA_P.pak.disabled").is_file())
            self.assertTrue((mods / "OtherB_P.pak.disabled").is_file())
            self.assertTrue((mods / "AlreadyOff_P.pak.disabled").is_file())

            off = mod_sandbox.set_clean_test(mods, enable=False, state_path=state_file)
            self.assertFalse(off["active"])
            self.assertEqual(off["restored"], 2)
            self.assertTrue((mods / "OtherA_P.pak").is_file())
            self.assertTrue((mods / "OtherB_P.pak").is_file())
            # Must NOT re-enable a mod that was already disabled before clean-test!
            self.assertTrue((mods / "AlreadyOff_P.pak.disabled").is_file())
            self.assertFalse(state_file.exists())

    def test_toggle_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            mods = Path(tmp) / "~mods"
            mods.mkdir()
            with self.assertRaises(ValueError):
                mod_sandbox.toggle_mod(mods, "../escape", False)


if __name__ == "__main__":
    unittest.main()
