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
        ("AtelierAnimation/AtelierAnimation.exe", True),
        ("AtelierAnimation/CUE4Parse-Natives.dll", True),
        ("AtelierAnimation/oo2core_9_win64.dll", True),
        ("AtelierImport/AtelierImport.exe", True),
        ("AtelierImport/CUE4Parse-Natives.dll", True),
        ("AtelierImport/oo2core_9_win64.dll", True),
        ("shaders/retoc-rivals-cli.exe", True),      # world.RETOC + plugin/text extracts
        ("shaders/build-inputs.json", True),         # exact source-build provenance
        ("shaders/licenses/repak-MIT.txt", True),
        ("shaders/licenses/repak-APACHE.txt", True),
        ("shaders/licenses/retoc-MIT.txt", True),
        ("shaders/oo2core_9_win64.dll", True),       # Oodle for retoc and io_lib
        ("shaders/dxc.exe", True),                   # shaders.DXC
        ("shaders/dxcompiler.dll", True),            # dxc_ir
        ("shaders/dxil.dll", True),                  # dxc_ir validator
        ("MarvelRivalsCharacterIDs.md", True),       # seed; the app rewrites it (installer: onlyifdoesntexist)
        ("Galacta/GAL_ConfigTemplate.uasset", False),  # skin_swapper: Galacta's template, never in git
        ("Galacta/GAL_ConfigTemplate.uexp", False),
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
        ("AtelierAnimation/AtelierAnimation.exe", True),
        ("AtelierAnimation/CUE4Parse-Natives.dll", True),
        ("AtelierAnimation/oo2core_9_win64.dll", True),
        ("shaders/liboo2corelinux64.so.9", True),
        ("MarvelRivalsCharacterIDs.md", True),
        ("Galacta/GAL_ConfigTemplate.uasset", False),
        ("Galacta/GAL_ConfigTemplate.uexp", False),
    ],
}
# Project Galacta's Skin Swapper template (atelier/skin_swapper.py). Galacta allows it inside Atelier
# but not elsewhere, and this repository is public, so it is never committed: release builds stage it
# from a private Tools/Galacta/ or from CI secrets. It is optional, but the pair ships whole or not at
# all, and these two files are the only cooked packages the dist audit accepts.
GALACTA_TEMPLATE = ("Galacta/GAL_ConfigTemplate.uasset", "Galacta/GAL_ConfigTemplate.uexp")
EXECUTABLES = {"linux": ["UAssetTool", "shaders/retoc-rivals-cli"], "windows": []}
DIRECTORIES = {"AtelierMesh"}
# Retain the Windows helper API used by verification scripts and older callers.
# Both APIs use the same allowlist, including all required native dependencies.
REQUIRED = tuple(rel for rel, required in MANIFEST["windows"] if required and rel not in DIRECTORIES)
LINUX_ONLY = {"UAssetTool", "liboo2corelinux64.so.9", "libooz.so",
              "shaders/retoc-rivals-cli", "shaders/liboo2corelinux64.so.9"}

# Python packages the app never imports, kept out of _internal. PyInstaller follows OPTIONAL imports
# (scipy's array-API layer tries torch; scipy.stats tries matplotlib), and the Linux venv sees the
# system site-packages, so whatever happens to be installed system-wide got frozen in: one build
# grew _internal from 0.5 GB to 2.5 GB with torch, pandas, pyarrow, LLVM and MKL. Atelier.spec
# excludes these; audit() fails the build if one gets in anyway.
UNUSED_PACKAGES = [
    "torch", "torchvision", "torchaudio", "functorch", "torchgen", "safetensors", "onnxruntime",
    "tensorflow", "jax", "jaxlib", "cupy", "dask", "numba", "llvmlite", "sklearn",
    "pandas", "pyarrow", "matplotlib", "mpl_toolkits", "sympy", "networkx",
    "IPython", "jedi", "tkinter", "_tkinter", "botocore", "boto3", "s3fs", "mpi4py", "grpc",
]

_IGNORE = shutil.ignore_patterns("_cache", "__pycache__", "*.log", "*.tmp")

# Dev/run data that must never be in a dist, at any depth.
FORBIDDEN_NAMES = {"aes_key.txt", "mr_config.json", "extracted_assets.json",
                   "cli_index_cache.json", ".env", ".mcp.json"}
# Checked outside _internal only: third-party packages there may legitimately use these names.
FORBIDDEN_DIRS = {"mappings", "_cache", "_logs", "_webview", "assets", "projects", "imported", "exported"}
FORBIDDEN_EXTS = {".usmap", ".uasset", ".uexp", ".ubulk", ".uptnl", ".pak", ".ucas", ".utoc", ".blend"}


def validate_tools(root, platform="windows"):
    root = Path(root)
    missing = []
    for rel, required in MANIFEST[platform]:
        path = root / rel
        valid = path.is_dir() if rel in DIRECTORIES else path.is_file() and path.stat().st_size > 0
        if required and not valid:
            missing.append(rel)
    if missing:
        label = "Windows" if platform == "windows" else "Linux"
        raise RuntimeError(f"Required {label} tools missing or empty: " + ", ".join(missing))
    present = [rel for rel in GALACTA_TEMPLATE if (root / rel).is_file() and (root / rel).stat().st_size > 0]
    if len(present) == 1:
        raise RuntimeError("Incomplete Skin Swapper template: Tools/" + present[0] + " has no matching "
                           + ("uexp" if present[0].endswith(".uasset") else "uasset"))


def stage_tools(source, destination, platform="windows"):
    """Copy only allowlisted tools into a new staging tree; preserve existing trees."""
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or source in destination.parents or destination in source.parents:
        raise ValueError("Source and destination Tools directories must be separate")
    validate_tools(source, platform)
    if destination.exists():
        raise ValueError("Tools staging destination already exists; use a clean build directory")
    created = False
    try:
        destination.mkdir(parents=True)
        created = True
        for rel, required in MANIFEST[platform]:
            src, target = source / rel, destination / rel
            if target.exists():  # A required file already copied inside its directory entry.
                continue
            if src.is_dir():
                shutil.copytree(src, target, ignore=_IGNORE)
            elif src.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, target)
            elif not required:
                print(f"  [optional] not found, skipped: Tools/{rel}")
                if rel == GALACTA_TEMPLATE[0]:
                    print("  [notice] No Skin Swapper template: this build cannot export Project Galacta mods.")
        validate_tools(destination, platform)
        for rel in EXECUTABLES[platform]:
            os.chmod(destination / rel, 0o755)
    except Exception:
        # This resolved, separate target was created by this call. Never delete
        # an existing build, source tools, or a path inferred from native input.
        if created:
            shutil.rmtree(destination)
        raise


def stage(platform, src, dist):
    stage_tools(src, Path(dist) / "Tools", platform)


def audit(platform, dist):
    exe = "Atelier.exe" if platform == "windows" else "Atelier"
    allowed_top = {exe, "_internal", "Tools"}
    problems = [f"unexpected top-level entry: {p.name}" for p in dist.iterdir()
                if p.name not in allowed_top]
    problems += [f"missing: {name}" for name in allowed_top if not (dist / name).exists()]
    template = {"Tools/" + rel for rel in GALACTA_TEMPLATE}
    for path in dist.rglob("*"):
        rel = path.relative_to(dist)
        name = path.name.lower()
        if rel.as_posix() in template:
            continue
        if (path.is_file() and (name in FORBIDDEN_NAMES or path.suffix.lower() in FORBIDDEN_EXTS)) \
                or (path.is_dir() and name in FORBIDDEN_DIRS and rel.parts[0] != "_internal"):
            problems.append(f"dev/run data in dist: {rel.as_posix()}")
    internal = dist / "_internal"
    problems += [f"unused package frozen into _internal: {name} -- see UNUSED_PACKAGES"
                 for name in UNUSED_PACKAGES if (internal / name).exists()]
    if problems:
        raise SystemExit("Dist audit failed:\n  " + "\n  ".join(problems))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", type=Path, nargs="?", help="Legacy Windows source Tools directory")
    parser.add_argument("destination", type=Path, nargs="?", help="Legacy Windows staging Tools directory")
    parser.add_argument("--platform", choices=sorted(MANIFEST))
    parser.add_argument("--src", type=Path)
    parser.add_argument("--dist", type=Path)
    args = parser.parse_args()
    try:
        if args.source is not None or args.destination is not None:
            if args.source is None or args.destination is None or args.platform or args.src or args.dist:
                parser.error("Use source destination, or --platform with optional --src/--dist")
            stage_tools(args.source, args.destination)
            print("Required Windows tools staged and validated")
        else:
            if not args.platform:
                parser.error("--platform is required")
            src, dist = args.src or ROOT / "Tools", args.dist or ROOT / "dist" / "Atelier"
            if not dist.is_dir():
                parser.error(f"No PyInstaller output at {dist}; run PyInstaller first.")
            stage(args.platform, src, dist)
            audit(args.platform, dist.resolve())
            print(f"Staged {len(MANIFEST[args.platform])} tool entries for {args.platform} into {dist / 'Tools'}")
    except (OSError, RuntimeError, ValueError) as error:
        parser.exit(1, f"Tool staging failed: {error}\n")


if __name__ == "__main__":
    sys.exit(main())
