# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_submodules
from pathlib import Path
import sys

# This spec lives in packaging/; every path below is relative to the repository root.
ROOT = Path(SPECPATH).resolve().parent
# One list, shared with the dist audit in scripts/stage_tools.py.
sys.path.insert(0, str(ROOT / 'scripts'))
from stage_tools import UNUSED_PACKAGES
from update_catalogue_seed import validate_seed

validate_seed(ROOT / 'gui' / 'catalogue.json')
from build_blender_bridge import package as package_blender_bridge
bridge_zip = package_blender_bridge(ROOT / 'build' / 'Atelier-Live-Bridge.zip')
from build_update_helper import build as build_update_helper
update_helper = build_update_helper(ROOT / 'build' / 'updater')

datas = [
    (str(ROOT / 'gui'), 'gui'),
    (str(ROOT / 'version'), '.'),
    (str(ROOT / 'CHANGELOG.md'), '.'),
    (str(ROOT / 'update_keys.json'), '.'),
    (str(update_helper), 'updates'),
    (str(bridge_zip), 'extensions'),
    # Blender runs these as standalone --python scripts, so they must exist as real .py files on
    # disk — being importable from the PYZ is not enough. meshedit._SCRIPTS resolves them next to
    # the package, which is <_MEIPASS>/atelier/blender when frozen. Without this the whole .blend
    # round-trip dies with "Python file ... could not be opened" in packaged builds only.
]
# Do not collect developer __pycache__ files beside the standalone scripts.
datas += [(str(script), 'atelier/blender') for script in (ROOT / 'atelier/blender').glob('*.py')]
datas += [(str(script), 'atelier/blender/atelier_live_bridge')
          for script in (ROOT / 'atelier/blender/atelier_live_bridge').iterdir() if script.is_file()]
# upscale.py loads its weights from beside the package (<_MEIPASS>/atelier/models when frozen).
datas += [(str(item), 'atelier/models') for item in (ROOT / 'atelier/models').iterdir() if item.is_file()]
datas += [(str(item), 'atelier/vendor/meshoptimizer') for item in (ROOT / 'atelier/vendor/meshoptimizer').iterdir() if item.is_file()]
binaries = []
hiddenimports = [
    'io_lib',
    'atelier.config',
    'atelier.tools',
    'atelier.jobs',
    'atelier.bulk',
    'atelier.blender_bridge',
    'atelier.blender_extension',
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
if sys.platform.startswith('linux'):
    # PyGObject's Python overrides (GLib.idle_add and friends). PyInstaller only adds them when it
    # can query GObject introspection at build time, which fails on some build hosts; without
    # them pywebview's GLib.idle_add(set_opacity, 1.0) raises and the window stays transparent.
    hiddenimports += collect_submodules('gi.overrides')

tmp_ret = collect_all('wasmtime')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    [str(ROOT / 'window.py')],
    pathex=[str(ROOT)],
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
# Linux: use the system's GTK/GLib/GObject-introspection stack together with the system's
# WebKitGTK (which cannot be bundled). A bundled GTK stack paired with a newer system WebKit is
# what made the 1.0 AppImage fail on newer distros; window.py drops the runtime-hook variables
# that would still point GTK into the bundle.
if sys.platform.startswith('linux'):
    _SYSTEM_GUI_LIBS = ('libgtk-3', 'libgdk-3', 'libgdk_pixbuf', 'libglib-2.0', 'libgobject-2.0',
                        'libgio-2.0', 'libgmodule-2.0', 'libgthread-2.0', 'libgirepository', 'libcairo',
                        'libpango', 'libharfbuzz', 'libatk', 'libatspi', 'libepoxy', 'libfontconfig',
                        'libfreetype', 'libfribidi', 'libpixman', 'libthai', 'libdatrie', 'libgraphite2',
                        # Base libraries the system GTK/WebKit (C++) need at the system's version:
                        # a 24.04 libstdc++ in the bundle broke WebKit on 26.04. Wheels vendor their
                        # own copies under hashed names (libfoo-1a2b3c4d.so), which are unaffected.
                        'libstdc++', 'libgcc_s', 'libffi', 'libz.so', 'libpcre2', 'libmount',
                        'libblkid', 'libselinux', 'libuuid', 'libexpat')
    _SYSTEM_GUI_DATA = ('gi_typelibs', 'gio_modules', 'lib/gdk-pixbuf', 'share/glib-2.0', 'share/icons',
                        'share/themes', 'etc/gtk-3.0', 'lib/gtk-3.0')
    a.binaries = [b for b in a.binaries if not Path(b[0]).name.startswith(_SYSTEM_GUI_LIBS)]
    a.datas = [d for d in a.datas if not Path(d[0]).as_posix().startswith(_SYSTEM_GUI_DATA)]
pyz = PYZ(a.pure)

# Keep Windows file properties in sync with the UI and installer version.
windows_version = None
if sys.platform == 'win32':
    from PyInstaller.utils.win32.versioninfo import (
        VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable,
        StringStruct, VarFileInfo, VarStruct,
    )
    application_version = (ROOT / 'version').read_text(encoding='utf-8').strip()
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
    icon=str(ROOT / 'icon.ico'),
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
