"""Unit tests for Showcase 2.0 duo positioning and WebM codec negotiation."""
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parent.parent


class ShowcaseCompareTests(unittest.TestCase):
    def test_duo_offsets_and_webm_mime_selection(self):
        script = """
            import { computeDuoOffsets, pickWebmMimeType } from './gui/viewport-showcase-compare.js';
            const layout = computeDuoOffsets(1.2, 0.3);
            const fallbackLayout = computeDuoOffsets(NaN);
            const vp9 = pickWebmMimeType({ isTypeSupported: m => m === 'video/webm;codecs=vp9' });
            const vp8 = pickWebmMimeType({ isTypeSupported: m => m === 'video/webm;codecs=vp8' });
            const none = pickWebmMimeType(null);
            console.log(JSON.stringify({ layout, fallbackLayout, vp9, vp8, none }));
        """
        proc = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
        data = json.loads(proc.stdout.strip())
        self.assertLess(data["layout"]["originalX"], 0)
        self.assertGreater(data["layout"]["editedX"], 0)
        self.assertAlmostEqual(data["layout"]["originalX"], -data["layout"]["editedX"], places=5)
        self.assertGreater(data["fallbackLayout"]["editedX"], 0)
        self.assertEqual(data["vp9"], "video/webm;codecs=vp9")
        self.assertEqual(data["vp8"], "video/webm;codecs=vp8")
        self.assertEqual(data["none"], "")


if __name__ == "__main__":
    unittest.main()
