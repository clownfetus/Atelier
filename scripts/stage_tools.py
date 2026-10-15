"""Stage and validate native tools for the official Windows installer.

The contributor review ZIP intentionally keeps tools external; this helper is
only for BUILD.bat's bundled installer. Never stage keys, mappings or caches.
"""
import argparse
from pathlib import Path
import shutil


REQUIRED = (
    "UAssetTool.exe",
    "AtelierMesh/AtelierMesh.exe",
    "AtelierMesh/CUE4Parse-Natives.dll",
    "AtelierMesh/oo2core_9_win64.dll",
)
LINUX_ONLY = {
    "UAssetTool", "liboo2corelinux64.so.9", "libooz.so",
    "shaders/retoc-rivals-cli", "shaders/liboo2corelinux64.so.9",
}


def validate_tools(root):
    root = Path(root)
    missing = [name for name in REQUIRED
               if not (root / name).is_file() or (root / name).stat().st_size == 0]
    if missing:
        raise RuntimeError("Required Windows tools missing or empty: " + ", ".join(missing))


def stage_tools(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or source in destination.parents or destination in source.parents:
        raise ValueError("Source and destination Tools directories must be separate")
    validate_tools(source)  # Fail before touching an existing staging directory.
    if destination.exists():
        raise ValueError("Tools staging destination already exists; use a clean build directory")

    def excluded(directory, names):
        relative = Path(directory).relative_to(source)
        return [name for name in names
                if name.lower() in {"mappings", "aes_key.txt", "_cache", "__pycache__"}
                or (relative / name).as_posix() in LINUX_ONLY]

    try:
        shutil.copytree(source, destination, ignore=excluded)
        validate_tools(destination)
    except Exception:
        # A partial tree must never look like a usable build to a later retry.
        # destination is an explicitly supplied, newly created staging directory.
        if destination.is_dir():
            shutil.rmtree(destination)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        stage_tools(args.source, args.destination)
    except (OSError, RuntimeError, ValueError) as error:
        parser.exit(1, f"Tool staging failed: {error}\n")
    print("Required Windows tools staged and validated")


if __name__ == "__main__":
    main()
