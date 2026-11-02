"""Preview preparation uses disposable images and never calls the game decoder."""
import atexit
import copy
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_data = tempfile.TemporaryDirectory(prefix="atelier-dye-tests-")
os.environ["ATELIER_DATA_DIR"] = _data.name
atexit.register(_data.cleanup)
from atelier.handlers import dye as D, custom_texture as CT


class DyePreparation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="atelier-dye-case-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(D, "_PREPARED", D.collections.OrderedDict()))
        self.stack.enter_context(patch.object(D, "_IMCACHE", {}))
        self.stack.enter_context(patch.object(D, "_PREPARING", {}))
        rng = np.random.default_rng(19)
        self.images = {"mask": Image.fromarray(rng.integers(0, 256, (13, 17, 4), dtype=np.uint8)),
                       "diff": Image.fromarray(rng.integers(0, 256, (15, 19, 3), dtype=np.uint8))}
        self.regions = {i: {"ColorA": [i / 4, .2, .7, 1], "ColorB": [.1, .8, .3, 1],
                            "ColorGChannel": [.3, .1, .9, 1], "ColorBChannel": [.2, .7, .1, 1]}
                        for i in range(1, 8)}
        self.stack.enter_context(patch.object(D, "dye_slots", return_value=("mask", "diff")))
        self.stack.enter_context(patch.object(D, "dye_regions", side_effect=lambda *a, **k: copy.deepcopy(self.regions)))
        self.stack.enter_context(patch.object(D, "edited_png", return_value=None))
        from atelier import import_server
        self.stack.enter_context(patch.object(import_server, "available", return_value=False))
        self.custom = self.stack.enter_context(patch.object(CT, "image_path", return_value=None))
        self.decode = self.stack.enter_context(patch.object(D, "_tex_image_uncached", side_effect=lambda gr, **kw: self.images[gr]))
        self.prepare = self.stack.enter_context(patch.object(D, "_prepare", wraps=D._prepare))

    def bake(self, name="material", **kwargs):
        path = D.dye_preview(name, size=32, out_path=str(self.root / (name + ".png")), **kwargs)
        with Image.open(path) as image:
            return np.asarray(image).copy()

    def test_two_bakes_decode_and_prepare_once_and_match_uncached_pixels(self):
        first, second = self.bake(), self.bake()
        self.assertEqual(self.decode.call_count, 2)
        self.prepare.assert_called_once()
        np.testing.assert_array_equal(first, second)
        expected = D.composite(self.images["mask"], self.images["diff"], self.regions, size=32)
        np.testing.assert_array_equal(first, np.asarray(expected))
        self.assertTrue(all(not a.flags.writeable for pair in D._PREPARED.values() for a in pair))

    def test_changed_colours_reuse_sources(self):
        first = self.bake()
        overrides = {1: {"ColorA": [.9, .1, .1, 1]}}
        second = self.bake(overrides=overrides)
        self.assertFalse(np.array_equal(first, second))
        self.prepare.assert_called_once()
        expected = copy.deepcopy(self.regions)
        expected[1].update(overrides[1])
        np.testing.assert_array_equal(second, np.asarray(D.composite(self.images["mask"], self.images["diff"], expected, 32)))

    def test_edited_png_stamp_includes_subsecond_changes(self):
        png = self.root / "edited.png"
        png.write_bytes(b"one")
        with patch.object(D, "edited_png", side_effect=lambda gr: str(png) if gr == "diff" else None):
            self.bake()
            stamp = png.stat().st_mtime_ns
            os.utime(png, ns=(stamp, stamp + 1_000_000))
            self.bake()
        self.assertEqual(self.prepare.call_count, 2)
        self.assertEqual(self.decode.call_count, 3)
        self.assertEqual(len(D._PREPARED), 1)

    def test_custom_texture_change_and_removal_invalidate_without_affecting_original(self):
        original = self.bake(original=True)
        png = self.root / "custom.png"
        Image.new("RGB", (8, 8), (40, 80, 120)).save(png)
        self.custom.side_effect = lambda gr, slot: str(png) if slot == D.DIFF_SLOT else None
        custom = self.bake()
        self.assertFalse(np.array_equal(original, custom))
        stamp = png.stat().st_mtime_ns
        Image.new("RGB", (8, 8), (160, 100, 200)).save(png)
        os.utime(png, ns=(stamp, stamp + 1_000_000))
        changed = self.bake()
        self.assertFalse(np.array_equal(custom, changed))
        np.testing.assert_array_equal(original, self.bake(original=True))
        self.custom.side_effect = None
        np.testing.assert_array_equal(original, self.bake())
        self.assertEqual(self.prepare.call_count, 4)

    def test_cache_evicts_old_materials(self):
        for i in range(7):
            self.bake(str(i))
        self.assertEqual(len(D._PREPARED), 4)
        self.assertEqual([k[0] for k in D._PREPARED], ["3", "4", "5", "6"])

    def test_concurrent_bakes_share_preparation(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: D._prepared_arrays("material", "mask", "diff", 32, False), range(4)))
        self.prepare.assert_called_once()
        self.assertEqual(self.decode.call_count, 2)
        self.assertTrue(all(pair is results[0] for pair in results))

    def test_fast_encoding_only_when_requested_and_same_pixels(self):
        save = Image.Image.save
        with patch.object(Image.Image, "save", autospec=True, side_effect=save) as writer:
            normal = self.bake()
            self.assertNotIn("compress_level", writer.call_args.kwargs)
            fast = self.bake(fast_png=True)
            self.assertEqual(writer.call_args.kwargs["compress_level"], 1)
        np.testing.assert_array_equal(normal, fast)
        np.testing.assert_array_equal(self.bake(dye_off=True), np.asarray(self.images["diff"].resize((32, 32), Image.BILINEAR)))


if __name__ == "__main__":
    unittest.main()
