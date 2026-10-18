"""Native Linux core tools satisfy the same prerequisite gate as Windows tools."""
import atexit
from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
_bootstrap=tempfile.TemporaryDirectory(prefix='atelier-native-prereqs-')
os.environ['ATELIER_DATA_DIR']=_bootstrap.name
from atelier import config as C, hostos
atexit.register(_bootstrap.cleanup)

class NativePrerequisites(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='atelier-prereq-case-')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        self.tools=self.root/'Tools';self.tools.mkdir()
        key=self.tools/'AES_KEY.txt';key.write_text('11'*32)
        mapping=self.root/'fixture.usmap';mapping.write_bytes(b'fixture')
        (self.tools/'MarvelRivalsCharacterIDs.md').write_text('fixture')
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        for name,value in [('TOOLS',str(self.tools)),('AES_KEY_FILE',str(key)),('USMAP',str(mapping))]:
            self.stack.enter_context(patch.object(C,name,value))
        self.stack.enter_context(patch.object(C,'has_pak_files',return_value=True))
        self.stack.enter_context(patch.dict(os.environ,MR_TOOLS=str(self.tools)))
        self.stack.enter_context(patch.object(hostos,'_wine',return_value=None))

    def binary(self,name):
        path=self.tools/name;path.write_bytes(b'fixture tool');path.chmod(0o755)

    def test_linux_native_tool_without_windows_executable_or_wine(self):
        self.binary('UAssetTool')
        with patch.object(hostos,'IS_WINDOWS',False):
            C.check_prereqs()

    def test_missing_core_binary_is_still_an_error(self):
        with patch.object(hostos,'IS_WINDOWS',False):
            with self.assertRaisesRegex(RuntimeError,'UAssetTool'):
                C.check_prereqs()

    def test_windows_requires_windows_binary(self):
        self.binary('UAssetTool')
        with patch.object(hostos,'IS_WINDOWS',True):
            with self.assertRaisesRegex(RuntimeError,'UAssetTool'):
                C.check_prereqs()
            self.binary('UAssetTool.exe');C.check_prereqs()

    def test_linux_windows_binary_requires_wine(self):
        self.binary('UAssetTool.exe')
        with patch.object(hostos,'IS_WINDOWS',False):
            with self.assertRaisesRegex(RuntimeError,'Wine'):
                C.check_prereqs()
            with patch.object(hostos,'_wine',return_value='fixture-wine'):
                C.check_prereqs()

if __name__=='__main__':unittest.main()
