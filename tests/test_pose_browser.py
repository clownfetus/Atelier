"""Unit tests for categorized Pose & Animation Browser discovery and decoding."""
import unittest
from unittest.mock import patch

from atelier.handlers import animation as A


class PoseBrowserTests(unittest.TestCase):
    mesh = "Characters/1029/1029100/Meshes/10291/SK_Test"

    def test_animation_candidates_categorise_full_body_clips_and_filter_partials(self):
        entries = [(p, "pak", "Marvel/Content/Marvel/") for p in [
            "Characters/1029/1029001/Animations/10291/HeroDetails/Lobby_Stand_Idle.uasset",
            "Characters/1029/1029001/Animations/10291/HeroDetails/MVP_Intro_Pose.uasset",
            "Characters/1029/1029001/Animations/10291/Emote_Dance_01.uasset",
            "Characters/1029/1029001/Animations/10291/Combat_Melee_Attack_01.uasset",
            "Characters/1029/1029001/Animations/10291/Lobby_Half_Idle.uasset",
            "Characters/1029/1029001/Animations/10291/Idle_AO.uasset",
            "Characters/1029/1029001/Animations/10291/Face_Smile.uasset",
            "Characters/1029/1029001/Animations/10291/AM_Montage_Ult.uasset",
            "Characters/1029/1029001/Weapons/Animations/Weapon_Swing.uasset",
            "Characters/1035/1035001/Animations/10351/Emote_Wave.uasset",
        ]]
        with patch("atelier.index.ensure_index", return_value=entries):
            all_clips = A.animation_candidates(self.mesh)
            idles = A.idle_candidates(self.mesh)

        self.assertEqual([c["name"] for c in idles], ["Lobby_Stand_Idle"])
        self.assertEqual([c["name"] for c in all_clips], [
            "Lobby_Stand_Idle",
            "MVP_Intro_Pose",
            "Emote_Dance_01",
            "Combat_Melee_Attack_01",
        ])
        self.assertEqual([c["category"] for c in all_clips], ["idle", "lobby", "emote", "combat"])
        self.assertTrue(all_clips[0]["is_idle"])
        self.assertFalse(all_clips[2]["is_idle"])

    def test_decode_animation_rejects_unlisted_clips_before_native_call(self):
        with patch.object(A, "animation_candidates", return_value=[]), patch.object(A.hostos, "run_exe") as run:
            with self.assertRaises(ValueError):
                A.decode_animation(self.mesh, "Characters/1029/1029001/Animations/10291/Emote_Dance_01")
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
