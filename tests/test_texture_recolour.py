"""Texture recolour: blend maths, baked files, and the recipe kept in project.json."""
import atexit
import os
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_data = tempfile.TemporaryDirectory(prefix="atelier-recolour-tests-")
os.environ["ATELIER_DATA_DIR"] = _data.name
atexit.register(_data.cleanup)
from atelier import project_meta as M
from atelier.handlers import texture_recolour as R


def image(rgb, alpha=255, size=(4, 4)):
    return Image.new("RGBA", size, (*rgb, alpha))


def pixel(img):
    return img.getpixel((0, 0))


class Recipe(unittest.TestCase):
    def test_valid_recipe_is_normalised(self):
        self.assertEqual(R.recipe("#3f6fd8", "color", 1), {"colour": "#3F6FD8", "mode": "color", "strength": 1.0})

    def test_bad_values_are_refused(self):
        for args in [("blue", "color", 1), ("#3F6FD8", "dodge", 1), ("#3F6FD8", "color", 1.5), ("#3F6FD8", "color", True)]:
            with self.assertRaises(ValueError):
                R.recipe(*args)


class Curve(unittest.TestCase):
    LIGHTER = [[0, 0], [.5, .65], [1, 1]]

    def test_curve_is_kept_and_a_straight_one_is_left_out(self):
        self.assertEqual(R.recipe("#2050FF", "color", 1, self.LIGHTER)["curve"], self.LIGHTER)
        for straight in (None, [[0, 0], [1, 1]], [[0, 0], [.4, .4], [1, 1]]):
            self.assertNotIn("curve", R.recipe("#2050FF", "color", 1, straight))

    def test_bad_curves_are_refused(self):
        for curve in ([[0, 0]], [[0, 0], [.5, 1.2], [1, 1]], [[.1, 0], [1, 1]], [[0, 0], [.6, .5], [.4, .5], [1, 1]],
                      [[0, 0], [1, 1], [1, 1]], "lighter", [[0, 0], [True, 1], [1, 1]], [[i / 9, i / 9] for i in range(10)]):
            with self.assertRaises(ValueError, msg=curve):
                R.recipe("#2050FF", "color", 1, curve)

    def test_lookup_passes_through_its_points_without_overshooting(self):
        lut = R.curve_lut([[0, 0], [.25, .17], [.75, .83], [1, 1]])
        self.assertAlmostEqual(float(lut[0]), 0, places=5); self.assertAlmostEqual(float(lut[255]), 1, places=5)
        self.assertTrue(np.all(np.diff(lut) >= 0))
        np.testing.assert_allclose(R.curve_lut([[0, 0], [1, 1]]), np.linspace(0, 1, 256), atol=1e-6)
        lifted = R.curve_lut([[0, .08], [.5, .5], [1, .92]])
        self.assertAlmostEqual(float(lifted[0]), .08, places=5); self.assertAlmostEqual(float(lifted[255]), .92, places=5)

    def test_curve_works_on_its_own_and_keeps_alpha(self):
        spec = R.recipe("#2050FF", "color", 0, self.LIGHTER)
        r, g, b, a = pixel(R.bake(image((128, 128, 128), alpha=90), spec))
        self.assertEqual((r, g, b, a), (166, 166, 166, 90))


class Blend(unittest.TestCase):
    def bake(self, rgb, colour, mode, strength=1, alpha=255):
        return pixel(R.bake(image(rgb, alpha), R.recipe(colour, mode, strength)))

    def test_zero_strength_leaves_the_texture_alone_and_alpha_is_kept(self):
        self.assertEqual(self.bake((200, 40, 90), "#00FF00", "color", 0, alpha=77), (200, 40, 90, 77))
        self.assertEqual(self.bake((200, 40, 90), "#00FF00", "multiply", 1, alpha=77)[3], 77)

    def test_neutral_colours_are_identities(self):
        texel = (200, 40, 90)
        self.assertEqual(self.bake(texel, "#FFFFFF", "multiply")[:3], texel)
        self.assertEqual(self.bake(texel, "#000000", "screen")[:3], texel)
        for mode in ("overlay", "soft_light"):
            # Overlay and soft light leave a texture alone under 50% grey (128 is a hair above it).
            for got, want in zip(self.bake(texel, "#808080", mode)[:3], texel):
                self.assertLessEqual(abs(got - want), 2, mode)

    def test_colour_mode_takes_the_hue_and_keeps_the_shading(self):
        dark, light = self.bake((60, 60, 60), "#2050FF", "color"), self.bake((200, 200, 200), "#2050FF", "color")
        for texel in (dark, light):
            self.assertGreater(texel[2], texel[0])          # blue now leads
        self.assertLess(sum(dark[:3]), sum(light[:3]))       # shading survives

    def test_hue_mode_cannot_colour_grey(self):
        r, g, b, _ = self.bake((128, 128, 128), "#2050FF", "hue")
        self.assertEqual(r, g); self.assertEqual(g, b)

    def test_red_and_white_becomes_blue_and_white_in_colour_mode(self):
        white = self.bake((255, 255, 255), "#2050FF", "color")
        red = self.bake((200, 30, 30), "#2050FF", "color")
        self.assertEqual(white[:3], (255, 255, 255))
        self.assertGreater(red[2], red[0])

    def test_hue_and_colour_keep_luminance(self):
        rgb = np.array([[[.8, .3, .1]]], dtype=np.float32)
        for mode in ("hue", "color"):
            out = R.blend(rgb, [.1, .4, .9], mode)
            self.assertAlmostEqual(float(R._lum(out)[0, 0, 0]), float(R._lum(rgb)[0, 0, 0]), places=4)


class Files(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="atelier-recolour-case-")
        self.addCleanup(self.temp.cleanup)
        self.source = os.path.join(self.temp.name, "T_Body_D.png")
        Image.new("RGBA", (2048, 1024), (180, 40, 40, 255)).save(self.source)
        self.spec = R.recipe("#2050FF", "color", 1)

    def test_preview_is_reduced_and_cached(self):
        cache = os.path.join(self.temp.name, "cache")
        first = R.preview(self.source, self.spec, cache)
        self.assertEqual(R.preview(self.source, self.spec, cache), first)
        with Image.open(first) as result:
            self.assertEqual(result.size, (1024, 512))
        other = R.preview(self.source, R.recipe("#2050FF", "color", .5), cache)
        self.assertNotEqual(other, first)

    def test_save_writes_full_size_from_the_original(self):
        target = os.path.join(self.temp.name, "project", "Characters", "T_Body_D.png")
        stamp = R.save(self.source, target, self.spec)
        self.assertEqual(stamp, R.stamp(target))
        with Image.open(target) as result:
            self.assertEqual(result.size, (2048, 1024))
            r, g, b, a = result.getpixel((0, 0))
        self.assertGreater(b, r)
        self.assertFalse(os.path.exists(target + ".recolour.tmp"))


class StoredRecipe(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="atelier-recolour-project-")
        self.addCleanup(self.temp.cleanup)
        self.root, self.gr = self.temp.name, "Characters/1029/1029001/Textures/T_Body_D"

    def test_recipe_round_trips_and_drops(self):
        saved = {**R.recipe("#2050FF", "color", 1), "stamp": [1, 2]}
        M.set_recolour(self.root, self.gr, saved)
        self.assertEqual(M.get_recolour(self.root, self.gr), saved)
        M.set_recolour(self.root, self.gr, None)
        self.assertIsNone(M.get_recolour(self.root, self.gr))

    def test_deleting_the_asset_forgets_the_recipe_and_undo_brings_it_back(self):
        saved = {**R.recipe("#2050FF", "color", 1), "stamp": [1, 2]}
        M.set_recolour(self.root, self.gr, saved)
        kept = {"opts": {}, "recolour": M.load(self.root)["recolours"].get(self.gr), "deselected": False}
        M.forget_asset(self.root, self.gr, selection=True)
        self.assertIsNone(M.get_recolour(self.root, self.gr))
        M.restore_asset(self.root, self.gr, kept)
        self.assertEqual(M.get_recolour(self.root, self.gr), saved)


if __name__ == "__main__":
    unittest.main()
