#!/usr/bin/env bash
# Assembles dist/Atelier-<version>-x86_64.AppImage from an already built and staged dist/Atelier.
# Run through scripts/build.py, which builds the app with the pinned Python and stages the tools
# from toolchain/tools.lock.json first:   python scripts/build.py --platform linux
#
# Build on an older base (CI uses Ubuntu 24.04, glibc 2.39). Everything frozen into the AppImage
# needs the build machine's glibc or newer: the 1.0 build made on Arch required glibc 2.44 and
# would not start on Fedora.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
VERSION="${1:-$(cat version)}"
PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
[ -x dist/Atelier/Atelier ] || { echo "dist/Atelier is missing; run scripts/build.py --platform linux" >&2; exit 1; }

# appimagetool, pinned and hash-checked (the "continuous" channel moves under you).
APPIMAGETOOL_VERSION=1.9.1
APPIMAGETOOL_SHA256=ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0
TOOL="$ROOT/build/appimagetool-$APPIMAGETOOL_VERSION"
if [ ! -x "$TOOL" ]; then
    mkdir -p build
    curl -fsSL -o "$TOOL.part" "https://github.com/AppImage/appimagetool/releases/download/$APPIMAGETOOL_VERSION/appimagetool-x86_64.AppImage"
    echo "$APPIMAGETOOL_SHA256  $TOOL.part" | sha256sum -c - >/dev/null
    chmod +x "$TOOL.part" && mv "$TOOL.part" "$TOOL"
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

"$PYTHON" - <<'EOF'
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
