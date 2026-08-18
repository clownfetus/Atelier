# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [
    ('gui', 'gui'),
    ('version', '.'),
    # Blender runs these as standalone --python scripts, so they must exist as real .py files on
    # disk — being importable from the PYZ is not enough. meshedit._SCRIPTS resolves them next to
    # the package, which is <_MEIPASS>/atelier/blender when frozen. Without this the whole .blend
    # round-trip dies with "Python file ... could not be opened" in packaged builds only.
    ('atelier/blender', 'atelier/blender'),
]
binaries = []
hiddenimports = [
    'io_lib',
    'atelier.config',
    'atelier.tools',
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
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

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
