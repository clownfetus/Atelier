"""Startup removes the vanilla_paks mirror that Atelier kept in its cache from 0.3.3 until 1.1.3.

The mirror held hard links to the game's top-level Paks files. Nothing has read it since 1.1.3,
and after a game patch its links keep the previous season's files on disk (about 80 GB). The
cleanup must only drop the mirror's own names: the game's files stay, and anything the mirror
never contained (a subfolder, a link or junction to somewhere else) is left alone."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from atelier import retired_cache


def _link_folder(target, link):
    """A directory symlink, or on Windows without that privilege a junction."""
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            raise unittest.SkipTest("cannot create a directory link here")
        import _winapi
        _winapi.CreateJunction(str(target), str(link))


class VanillaPaksMirror(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="atelier-retired-cache-")
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.paks = root / "Paks"
        self.paks.mkdir()
        self.cache = root / "_cache"
        self.mirror = self.cache / "vanilla_paks"
        self.mirror.mkdir(parents=True)

    def game_file(self, name, data):
        path = self.paks / name
        path.write_bytes(data)
        return path

    def test_removes_the_mirror_and_keeps_the_game_files(self):
        names = ["pakchunkCharacter-Windows.ucas", "pakchunkCharacter-Windows.utoc", "global.utoc"]
        for name in names:
            os.link(self.game_file(name, name.encode()), self.mirror / name)

        self.assertEqual(retired_cache.remove_vanilla_paks(self.cache), 3)

        self.assertFalse(self.mirror.exists())
        for name in names:
            self.assertEqual((self.paks / name).read_bytes(), name.encode())

    def test_removes_files_left_over_from_before_a_game_patch(self):
        # After a patch the game has replaced its file; the mirror's copy is the only name left.
        (self.mirror / "pakchunk0-Windows.ucas").write_bytes(b"last season")

        self.assertEqual(retired_cache.remove_vanilla_paks(self.cache), 1)
        self.assertFalse(self.mirror.exists())

    def test_removes_the_empty_folder_left_when_linking_failed(self):
        # Game and data folder on different drives: the old code made the folder, then gave up.
        self.assertEqual(retired_cache.remove_vanilla_paks(self.cache), 0)
        self.assertFalse(self.mirror.exists())

    def test_nothing_to_do_without_the_folder(self):
        self.mirror.rmdir()
        self.assertEqual(retired_cache.remove_vanilla_paks(self.cache), 0)
        self.assertEqual(retired_cache.remove_vanilla_paks(self.cache / "missing"), 0)

    def test_leaves_entries_the_mirror_never_held(self):
        (self.mirror / "global.utoc").write_bytes(b"mirror")
        (self.mirror / "~mods").mkdir()
        (self.mirror / "~mods" / "mine_P.utoc").write_bytes(b"someone's mod")

        self.assertEqual(retired_cache.remove_vanilla_paks(self.cache), 1)

        self.assertFalse((self.mirror / "global.utoc").exists())
        self.assertEqual((self.mirror / "~mods" / "mine_P.utoc").read_bytes(), b"someone's mod")

    def test_does_not_follow_a_link_inside_the_mirror(self):
        elsewhere = Path(self.temp.name) / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "keep.ucas").write_bytes(b"keep")
        _link_folder(elsewhere, self.mirror / "linked")

        self.assertEqual(retired_cache.remove_vanilla_paks(self.cache), 0)

        self.assertEqual((elsewhere / "keep.ucas").read_bytes(), b"keep")
        self.assertTrue(self.mirror.exists())

    def test_does_not_empty_a_mirror_folder_that_is_a_link(self):
        elsewhere = Path(self.temp.name) / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "keep.ucas").write_bytes(b"keep")
        self.mirror.rmdir()
        _link_folder(elsewhere, self.mirror)

        self.assertEqual(retired_cache.remove_vanilla_paks(self.cache), 0)

        self.assertEqual((elsewhere / "keep.ucas").read_bytes(), b"keep")


if __name__ == "__main__":
    unittest.main()
