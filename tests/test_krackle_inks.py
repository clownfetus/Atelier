"""Pure ink math runs in the same JS module the interface consumes."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]


class Inks(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'),'Node is required for the JS colour harness')
    def test_skin_outcome_separation_and_contrast(self):
        result=subprocess.run(['node',str(ROOT/'tests/krackle_inks_checks.js')],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('16 skin/surface pairs',result.stdout)


if __name__=='__main__':unittest.main()
