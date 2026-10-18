"""The card reports completed operations and requires actual hero/skin context."""
import shutil
import subprocess
from pathlib import Path
import unittest


class ModCardData(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'),'Node is needed for the pure frontend harness')
    def test_completed_counts_and_context(self):
        result=subprocess.run(['node',str(Path(__file__).with_name('mod_card_data_checks.js'))],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__=='__main__':unittest.main(verbosity=2)
