"""Stage the bundled native tools into a PyInstaller dist, from an explicit allowlist.

Usage: python scripts/stage_tools.py --platform windows|linux [--src Tools] [--dist dist/Atelier]

This is the ONE place that decides what ships in <dist>/Tools. The dev Tools/ folder also holds
run data (Mappings, AES_KEY.txt, caches, Linux builds next to Windows ones), so it is never copied
wholesale and then pruned: that is how a release once went out with no UAssetTool at all
(TRIAGE #39) while game-derived files kept needing their own delete lines. Instead:

  * every manifest entry is copied by name; a REQUIRED entry that is missing fails the build;
  * nothing outside the manifest is copied, so run data cannot leak in by default;
  * the whole dist is then audited: only the exe, _internal/ and Tools/ may sit at its top level
    (running dist/Atelier/Atelier.exe to test it writes assets/, _cache/ and mr_config.json there),
    and no game-derived or user file may appear anywhere in it.

Atelier.iss lists the same Windows files explicitly; tests/test_packaging.py keeps the two in sync.
"""
import argparse
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]

# (path relative to Tools/, required). A directory entry is copied whole, minus _IGNORE.
# Oodle is the one easiest to lose: every pak read needs it, and each consumer loads its own copy
# (io_lib + retoc from shaders/, AtelierMesh from its own folder, UAssetTool on Linux from beside it).
MANIFEST = {
    "windows": [
        ("UAssetTool.exe", True),                    # tools.UAT: extract/inject/pack, everything
        ("UAssetGUI.exe", True),                     # world.UAG: level round-trip
        ("AtelierMesh", True),                       # tools.ATELIER_MESH: 3D viewport decoder
        ("AtelierMesh/AtelierMesh.exe", True),
        ("AtelierMesh/CUE4Parse-Natives.dll", True),
        ("AtelierMesh/oo2core_9_win64.dll", True),
        ("shaders/retoc-rivals-cli.exe", True),      # world.RETOC + plugin/text extracts
        ("shaders/oo2core_9_win64.dll", True),       # Oodle for retoc and io_lib
        ("shaders/dxc.exe", True),                   # shaders.DXC
        ("shaders/dxcompiler.dll", True),            # dxc_ir
        ("shaders/dxil.dll", True),                  # dxc_ir validator
        ("MarvelRivalsCharacterIDs.md", True),       # seed; the app rewrites it (installer: onlyifdoesntexist)
    ],
    # Native builds where they exist (hostos.native_tool prefers them over Wine); AtelierMesh runs
    # under Wine. UAssetGUI and DXC are omitted: hostos.unsupported() refuses those features here.
    "linux": [
        ("UAssetTool", True),
        ("liboo2corelinux64.so.9", True),            # UAssetTool decompresses nothing without it
        ("libooz.so", False),                        # io_lib fallback when no real Oodle is present
        ("AtelierMesh", True),
        ("AtelierMesh/AtelierMesh.exe", True),
        ("shaders/retoc-rivals-cli", True),
        ("shaders/liboo2corelinux64.so.9", True),
        ("MarvelRivalsCharacterIDs.md", True),
    ],
}
EXECUTABLES = {"linux": ["UAssetTool", "shaders/retoc-rivals-cli"], "windows": []}

_IGNORE = shutil.ignore_patterns("_cache", "__pycache__", "*.log", "*.tmp")

# Dev/run data that must never be in a dist, at any depth.
FORBIDDEN_NAMES = {"aes_key.txt", "mr_config.json", "extracted_assets.json",
                   "cli_index_cache.json", ".env", ".mcp.json"}
# Checked outside _internal only: third-party packages there may legitimately use these names.
FORBIDDEN_DIRS = {"mappings", "_cache", "_logs", "_webview", "assets", "projects", "imported", "exported"}
FORBIDDEN_EXTS = {".usmap", ".uasset", ".uexp", ".ubulk", ".uptnl", ".pak", ".ucas", ".utoc", ".blend"}


def stage(platform, src, dist):
    tools = dist / "Tools"
    if tools.exists():
        shutil.rmtree(tools)
    tools.mkdir(parents=True)
    missing = []
    for rel, required in MANIFEST[platform]:
        source, target = src / rel, tools / rel
        if target.exists():                          # a file inside a directory entry already copied
            continue
        if source.is_dir():
            shutil.copytree(source, target, ignore=_IGNORE)
        elif source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        elif required:
            missing.append(rel)
        else:
            print(f"  [optional] not found, skipped: Tools/{rel}")
    # Directory entries are copied whole, so re-check their required members after the fact.
    missing += [rel for rel, required in MANIFEST[platform]
                if required and rel not in missing and not (tools / rel).exists()]
    if missing:
        raise SystemExit("Required bundled tools are missing from " + str(src) + ":\n  "
                         + "\n  ".join(missing))
    for rel in EXECUTABLES[platform]:
        os.chmod(tools / rel, 0o755)


def audit(platform, dist):
    exe = "Atelier.exe" if platform == "windows" else "Atelier"
    allowed_top = {exe, "_internal", "Tools"}
    problems = [f"unexpected top-level entry: {p.name}" for p in dist.iterdir()
                if p.name not in allowed_top]
    problems += [f"missing: {name}" for name in allowed_top if not (dist / name).exists()]
    for path in dist.rglob("*"):
        rel = path.relative_to(dist)
        name = path.name.lower()
        if (path.is_file() and (name in FORBIDDEN_NAMES or path.suffix.lower() in FORBIDDEN_EXTS)) \
                or (path.is_dir() and name in FORBIDDEN_DIRS and rel.parts[0] != "_internal"):
            problems.append(f"dev/run data in dist: {rel.as_posix()}")
    if problems:
        raise SystemExit("Dist audit failed:\n  " + "\n  ".join(problems))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--platform", choices=sorted(MANIFEST), required=True)
    parser.add_argument("--src", type=Path, default=ROOT / "Tools")
    parser.add_argument("--dist", type=Path, default=ROOT / "dist" / "Atelier")
    args = parser.parse_args()
    if not args.dist.is_dir():
        raise SystemExit(f"No PyInstaller output at {args.dist}; run PyInstaller first.")
    stage(args.platform, args.src.resolve(), args.dist.resolve())
    audit(args.platform, args.dist.resolve())
    print(f"Staged {len(MANIFEST[args.platform])} tool entries for {args.platform} into {args.dist / 'Tools'}")


if __name__ == "__main__":
    sys.exit(main())
