"""Unit tests for Colourblind & Readability Lens matrices (gui/vision-lens.js)."""
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parent.parent


class VisionLensTests(unittest.TestCase):
    def test_matrices_are_valid_20_element_color_matrices(self):
        proc = subprocess.run(
            ["node", "-e", """
                const lens = require('./gui/vision-lens.js');
                const valid = {};
                for (const [k, v] of Object.entries(lens.MATRICES)) {
                  const nums = v.trim().split(/\\s+/).map(Number);
                  valid[k] = nums.length === 20 && nums.every(Number.isFinite);
                }
                console.log(JSON.stringify({
                  modes: lens.MODES.map(m => m.id),
                  valid,
                  normalCss: lens.filterCss('normal'),
                  deutCss: lens.filterCss('deuteranopia'),
                }));
            """],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
        data = json.loads(proc.stdout.strip())
        self.assertEqual(data["modes"], ["normal", "protanopia", "deuteranopia", "tritanopia", "grayscale"])
        self.assertTrue(all(data["valid"].values()))
        self.assertEqual(data["normalCss"], "none")
        self.assertEqual(data["deutCss"], "url(#atelier-lens-deuteranopia)")


if __name__ == "__main__":
    unittest.main()
