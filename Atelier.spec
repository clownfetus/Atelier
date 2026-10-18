# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
from pathlib import Path
import sys

# One list, shared with the dist audit in scripts/stage_tools.py.
sys.path.insert(0, str(Path(SPECPATH) / 'scripts'))
from stage_tools import UNUSED_PACKAGES
from update_catalogue_seed import validate_seed

validate_seed(Path(SPECPATH) / 'gui' / 'catalogue.json')

datas = [
    ('gui', 'gui'),
    ('version', '.'),
    ('CHANGELOG.md', '.'),
    # Blender runs these as standalone --python scripts, so they must exist as real .py files on
    # disk — being importable from the PYZ is not enough. meshedit._SCRIPTS resolves them next to
    # the package, which is <_MEIPASS>/atelier/blender when frozen. Without this the whole .blend
    # round-trip dies with "Python file ... could not be opened" in packaged builds only.
]
# Do not collect developer __pycache__ files beside the standalone scripts.
datas += [(str(script), 'atelier/blender') for script in Path('atelier/blender').glob('*.py')]
# upscale.py loads its weights from beside the package (<_MEIPASS>/atelier/models when frozen).
datas += [(str(item), 'atelier/models') for item in Path('atelier/models').iterdir() if item.is_file()]
binaries = []
hiddenimports = [
    'io_lib',
    'atelier.config',
    'atelier.tools',
    'atelier.jobs',
    'atelier.bulk',
    'atelier.properties',
    'atelier.index',
    'atelier.paths',
    'atelier.handlers.texture',
    'atelier.handlers.material',
    'atelier.handlers.dye',       # imported function-level in routes.py -> PyInstaller won't find it
    'atelier.handlers.skinnames', # ditto (skin-name labels for the chroma picker)
    'atelier.handlers.vfx',
    'atelier.handlers.curve',
    'atelier.handlers.world',
    'atelier.handlers.container_merge',  # imported function-level in texture.build_mod -> add explicitly
    'atelier.handlers.text',
    'atelier.handlers.repatch',
    'atelier.handlers.modlock',
    'atelier.handlers.pak_thumb',
    'atelier.handlers.shaders',
    'atelier.handlers.dxc_ir',
    'atelier.web.app',
    'atelier.web.browse',
    'atelier.web.routes',
    'atelier.web.showcase',
    'atelier.handlers.animation',
    'atelier.handlers.meshreplace', 'atelier.handlers.projectedit', 'atelier.handlers.texturerefresh',
    'atelier.handlers.morph',
]
tmp_ret = collect_all('watchdog')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('bottle')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('webview')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['window.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=UNUSED_PACKAGES,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# Keep Windows file properties in sync with the UI and installer version.
windows_version = None
if sys.platform == 'win32':
    from PyInstaller.utils.win32.versioninfo import (
        VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable,
        StringStruct, VarFileInfo, VarStruct,
    )
    application_version = Path('version').read_text(encoding='utf-8').strip()
    numbers = tuple(int(part) for part in application_version.split('.'))
    if len(numbers) != 3 or any(not 0 <= number <= 99 for number in numbers):
        raise ValueError('Application version must be N.N.N with 1-2 digit numbers')
    windows_version = VSVersionInfo(
        ffi=FixedFileInfo(filevers=(*numbers, 0), prodvers=(*numbers, 0),
                          mask=0x3f, flags=0, OS=0x40004, fileType=1,
                          subtype=0, date=(0, 0)),
        kids=[StringFileInfo([StringTable('040904B0', [
            StringStruct('CompanyName', 'Atelier'),
            StringStruct('FileDescription', 'Atelier Modding Studio'),
            StringStruct('FileVersion', application_version),
            StringStruct('InternalName', 'Atelier'),
            StringStruct('OriginalFilename', 'Atelier.exe'),
            StringStruct('ProductName', 'Atelier'),
            StringStruct('ProductVersion', application_version),
        ])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])],
    )

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Atelier',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico',
    version=windows_version,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Atelier',
)
