#!/usr/bin/env bash
# Builds Atelier for Linux as a single-file AppImage: PyInstaller -> dist/Atelier (+ Tools/) ->
# dist/Atelier-<version>-x86_64.AppImage. Linux counterpart to BUILD.bat (same Atelier.spec, same
# "never ship game-derived data" guard).
#
# Usage: linux/build_appimage.sh [version]     (defaults to the contents of ./version)
#
# Prereqs (see LINUX.md "Setup"): venv built with --system-site-packages and PyInstaller installed,
# Tools/ populated, Tools/libooz.so built (linux/build_ooz.sh). appimagetool is downloaded on first use.
#
# An AppImage mounts read-only, but Atelier keeps its user data (mr_config.json, _cache, assets/,
# downloaded Mappings, AES_KEY.txt) next to the executable. So AppRun stages a writable copy of the
# small mutable parts under ~/.local/share/Atelier and symlinks the big read-only _internal/ back
# into the image. The staged Tools/ is refreshed when the version changes; user-authored files in
# it are never overwritten.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VERSION="${1:-$(cat version 2>/dev/null || true)}"
if [ -z "$VERSION" ]; then
    echo "No version given and ./version is empty. Usage: linux/build_appimage.sh 0.3.4" >&2
    exit 1
fi
if ! [[ "$VERSION" =~ ^[0-9]{1,2}\.[0-9]{1,2}\.[0-9]{1,2}$ ]]; then
    echo "Invalid version \"$VERSION\" - expected N.N.N with 1-2 digit numbers (e.g. 1.2.3)" >&2
    exit 1
fi

PYTHON="$ROOT/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
    echo "No venv at .venv -- see LINUX.md Setup step 2." >&2
    exit 1
fi
if ! "$PYTHON" -c "import gi" >/dev/null 2>&1; then
    echo "The venv can't import gi (PyGObject). It must be created with --system-site-packages:" >&2
    echo "  python -m venv --system-site-packages .venv" >&2
    exit 1
fi
if ! "$PYTHON" -c "import PyInstaller" >/dev/null 2>&1; then
    echo "PyInstaller not installed in the venv. Run: .venv/bin/pip install pyinstaller" >&2
    exit 1
fi
if [ ! -d Tools ]; then
    echo "Tools/ is missing -- see LINUX.md Setup step 4." >&2
    exit 1
fi
if [ ! -f Tools/libooz.so ] && [ -z "${ATELIER_OODLE:-}" ]; then
    echo "Tools/libooz.so is missing. Run linux/build_ooz.sh first (or set ATELIER_OODLE)." >&2
    exit 1
fi

echo "$VERSION" > version
rm -rf build dist
"$PYTHON" -m PyInstaller --noconfirm --clean Atelier.spec

cp -a Tools dist/Atelier/Tools

# Game-derived data -- never ship. Same two exclusions as BUILD.bat / Atelier.iss: the app
# fetches both itself on first run (Setup -> Download).
rm -rf dist/Atelier/Tools/Mappings
rm -f  dist/Atelier/Tools/AES_KEY.txt
if [ -e dist/Atelier/Tools/Mappings ] || [ -e dist/Atelier/Tools/AES_KEY.txt ]; then
    echo "FAILED to remove bundled Mappings/AES_KEY.txt" >&2
    exit 1
fi

# UAssetGUI.exe (world.py) and shaders/dxc.exe + dxcompiler.dll + dxil.dll (dxc_ir.py) back
# features hostos.unsupported() refuses unconditionally on Linux -- see the docstring at the top
# of atelier/hostos.py. They are never invoked here, Wine or not, so they're dead weight.
rm -f dist/Atelier/Tools/UAssetGUI.exe
rm -f dist/Atelier/Tools/shaders/dxc.exe
rm -f dist/Atelier/Tools/shaders/dxcompiler.dll
rm -f dist/Atelier/Tools/shaders/dxil.dll

# .exe siblings of a native Linux build are also dead weight: hostos.native_tool() prefers the
# extensionless native binary unconditionally, so the .exe is never invoked once it's present.
if [ -x dist/Atelier/Tools/UAssetTool ]; then
    rm -f dist/Atelier/Tools/UAssetTool.exe
fi
if [ -x dist/Atelier/Tools/shaders/retoc-rivals-cli ]; then
    rm -f dist/Atelier/Tools/shaders/retoc-rivals-cli.exe
fi

chmod +x dist/Atelier/Atelier dist/Atelier/Tools/UAssetTool dist/Atelier/Tools/shaders/retoc-rivals-cli 2>/dev/null || true

TOOL_DIR="$ROOT/linux/_appimagetool"
TOOL="$TOOL_DIR/appimagetool-x86_64.AppImage"
if [ ! -x "$TOOL" ]; then
    mkdir -p "$TOOL_DIR"
    curl -fL -o "$TOOL" https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
    chmod +x "$TOOL"
fi

APPDIR="$ROOT/build/AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr"
cp -al dist/Atelier "$APPDIR/usr/Atelier"      # hardlinks: no second 900 MB copy on disk

cat > "$APPDIR/AppRun" <<'EOF'
#!/usr/bin/env bash
HERE="$(dirname "$(readlink -f "$0")")"
SRC="$HERE/usr/Atelier"
DATA="${ATELIER_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/Atelier}"
VER="$(cat "$SRC/_internal/version" 2>/dev/null || echo 0)"

mkdir -p "$DATA"
# The bootloader must be a real file here so that its own directory (= Atelier's ROOT) is writable.
if [ "$(cat "$DATA/.staged" 2>/dev/null)" != "$VER" ]; then
    cp -f "$SRC/Atelier" "$DATA/Atelier"
    mkdir -p "$DATA/Tools"
    # Refresh bundled tools; leave user/runtime-authored files alone.
    tar -C "$SRC/Tools" --exclude=./Mappings --exclude=./AES_KEY.txt \
        --exclude=./MarvelRivalsCharacterIDs.md --exclude=./shaders/_cache -cf - . \
        | tar -C "$DATA/Tools" -xf -
    [ -e "$DATA/Tools/MarvelRivalsCharacterIDs.md" ] || cp "$SRC/Tools/MarvelRivalsCharacterIDs.md" "$DATA/Tools/" 2>/dev/null || true
    echo "$VER" > "$DATA/.staged"
fi
ln -sfn "$SRC/_internal" "$DATA/_internal"

unset APPDIR APPIMAGE_EXTRACT_AND_RUN
exec "$DATA/Atelier" "$@"
EOF
chmod +x "$APPDIR/AppRun"

cat > "$APPDIR/Atelier.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Atelier
Comment=Modding studio for Marvel Rivals
Exec=Atelier
Icon=Atelier
Categories=Utility;Development;
Terminal=false
EOF

"$ROOT/.venv/bin/python" - <<'EOF'
from PIL import Image
im = Image.open("icon.png").convert("RGBA")
s = max(im.size)
sq = Image.new("RGBA", (s, s), (0, 0, 0, 0))
sq.paste(im, ((s - im.width) // 2, (s - im.height) // 2))
sq.resize((256, 256), Image.LANCZOS).save("build/AppDir/Atelier.png")
EOF

OUT="dist/Atelier-${VERSION}-x86_64.AppImage"
ARCH=x86_64 "$TOOL" --appimage-extract-and-run --no-appstream "$APPDIR" "$OUT"
echo
echo "Built $OUT"
