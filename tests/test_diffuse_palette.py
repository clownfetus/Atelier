"""Diffuse palette for the export ink-well, using generated PNGs only."""
import atexit
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlencode
from wsgiref.util import setup_testing_defaults

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_data = tempfile.TemporaryDirectory(prefix="atelier-palette-tests-")
os.environ["ATELIER_DATA_DIR"] = _data.name
from atelier.diffuse_palette import average_colour, diffuse_candidates, skin_palette  # noqa: E402
from atelier.web import routes as R  # noqa: E402


def _cleanup():
    R._observer.stop()
    R._observer.join()
    _data.cleanup()


atexit.register(_cleanup)

FOLDER = [
    "Characters/1015/1015101/Texture/T_1015101_Equip_01_D.uasset",
    "Characters/1015/1015101/Texture/T_1015101_Equip_01_D.uexp",
    "Characters/1015/1015101/Texture/T_1015101_Body_D.uasset",
    "Characters/1015/1015101/Texture/T_1015101_Body_ORM.uasset",
    "Characters/1015/1015101/Texture/T_1015101_Eyes_01_D.uasset",
    "Characters/1015/1015101/Texture/T_1015101_Hair_Line_02_D.uasset",
    "Characters/1015/1015101/Texture/T_1015101_Head_BaseColor.uasset",
    "Characters/1015/1015101/Materials/MI_1015101_Body.uasset",
]


class DiffusePaletteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def png(self, name, pixels, size=(8, 8)):
        path = os.path.join(self.tmp.name, name + ".png")
        image = Image.new("RGBA", size)
        image.putdata([pixels[i % len(pixels)] for i in range(size[0] * size[1])])
        image.save(path)
        return path

    def test_candidates_keep_diffuse_maps_and_rank_large_parts_first(self):
        self.assertEqual(diffuse_candidates(FOLDER), [
            "Characters/1015/1015101/Texture/T_1015101_Body_D",
            "Characters/1015/1015101/Texture/T_1015101_Head_BaseColor",
            "Characters/1015/1015101/Texture/T_1015101_Equip_01_D",
        ])

    def test_average_skips_padding_and_transparency_and_weights_colour(self):
        path = self.png("mix", [(255, 0, 0, 255), (255, 255, 255, 255), (0, 0, 0, 255), (0, 255, 0, 0)])
        # Black padding and the transparent green are ignored. Red counts 1.25 to white's 0.25, in
        # linear light: G and B land on 1/6 linear, which is #71 in sRGB.
        self.assertEqual(average_colour(path), "#ff7171")
        self.assertEqual(average_colour(self.png("grey", [(128, 128, 128, 255)])), "#808080")
        self.assertIsNone(average_colour(self.png("empty", [(3, 3, 3, 255), (90, 90, 90, 0)])))

    def test_dark_average_is_lifted_along_its_hue(self):
        colour = average_colour(self.png("navy", [(20, 24, 60, 255)]))
        r, g, b = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
        self.assertGreater(b, 60)
        self.assertTrue(b > g > r)

    def test_palette_reads_only_cached_images_and_drops_near_duplicates(self):
        cache = {
            "Characters/1015/1015101/Texture/T_1015101_Body_D": self.png("body", [(200, 30, 40, 255)]),
            "Characters/1015/1015101/Texture/T_1015101_Equip_01_D": self.png("equip", [(205, 32, 41, 255)]),
            "Characters/1014/1014100/Textures/T_1014100_Body_D": self.png("other", [(20, 60, 210, 255)]),
        }
        folders = {"1015101": FOLDER, "1014100": ["Characters/1014/1014100/Textures/T_1014100_Body_D.uasset"]}
        asked = []

        def cached(game_rel):
            asked.append(game_rel)
            return cache.get(game_rel)

        result = skin_palette(["1015101", "1014100"], folders.__getitem__, cached)
        self.assertEqual(result["sources"], ["Characters/1015/1015101/Texture/T_1015101_Body_D",
                                             "Characters/1014/1014100/Textures/T_1014100_Body_D"])
        self.assertEqual(len(result["colors"]), 2)
        self.assertIn("Characters/1015/1015101/Texture/T_1015101_Head_BaseColor", asked)  # uncached: skipped
        self.assertEqual(skin_palette(["1015101"], folders.__getitem__, lambda _gr: None),
                         {"colors": [], "sources": []})

    def test_palette_stops_at_limit(self):
        folder = [f"Characters/1015/1015101/Texture/T_Part{i}_D.uasset" for i in range(6)]
        colours = [(250, 20, 20), (20, 250, 20), (20, 20, 250), (240, 240, 20), (20, 240, 240), (240, 20, 240)]
        paths = {f"Characters/1015/1015101/Texture/T_Part{i}_D": self.png(f"p{i}", [c + (255,)])
                 for i, c in enumerate(colours)}
        result = skin_palette(["1015101"], lambda _s: folder, paths.get, limit=4)
        self.assertEqual(len(result["colors"]), 4)


class DiffusePaletteRouteTests(unittest.TestCase):
    def get(self, skins):
        env = {}
        setup_testing_defaults(env)
        env.update(REQUEST_METHOD="GET", PATH_INFO="/api/diffuse_palette",
                   QUERY_STRING=urlencode({"skin": skins}, doseq=True), **{"wsgi.input": io.BytesIO(b"")})
        status = []
        body = b"".join(R.app(env, lambda s, h, exc_info=None: status.append(s)))
        return int(status[0].split()[0]), json.loads(body)

    def test_route_reads_thumbnails_then_viewport_cache_and_never_decodes(self):
        root = Path(tempfile.mkdtemp(dir=_data.name))
        body = "Characters/1015/1015101/Texture/T_1015101_Body_D"
        head = "Characters/1015/1015101/Texture/T_1015101_Head_D"
        index = [(gr + ".uasset", None, None) for gr in (body, head, "Characters/1015/1015101/Texture/T_1015101_Equip_D")]
        with patch.object(R, "THUMBS_DIR", str(root / "thumbs")), patch.object(R, "CACHE_3DVIEW", str(root / "3dview")), \
                patch("atelier.index.prefix_entries", lambda prefix: index if prefix == "Characters/1015/1015101/" else []), \
                patch.object(R, "_texture_png", side_effect=AssertionError("palette must not decode")):
            thumb = Path(R._thumb_path(body))
            thumb.parent.mkdir(parents=True)
            Image.new("RGBA", (8, 8), (220, 40, 60, 255)).save(thumb)
            decoded = Path(R.project_base(head, str(root / "3dview")) + ".png")
            decoded.parent.mkdir(parents=True)
            Image.new("RGBA", (8, 8), (40, 70, 220, 255)).save(decoded)
            status, result = self.get(["1015101", "../etc", "1015101"])
        self.assertEqual(status, 200)
        self.assertEqual(result["sources"], [body, head])
        self.assertEqual(len(result["colors"]), 2)
        self.assertEqual(self.get(["nope"])[1], {"colors": [], "sources": []})


if __name__ == "__main__":
    unittest.main()
