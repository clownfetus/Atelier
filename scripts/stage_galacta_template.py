"""Install a complete local Galacta template pair without leaving a mixed version on failure."""
import argparse
import hashlib
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from atelier import storage

FILES = ("GAL_ConfigTemplate.uasset", "GAL_ConfigTemplate.uexp")


def find_bundled_template(destination, candidates=()):
    """Reuse an installed pair, or take a complete pair bundled with native tools."""
    for candidate in (destination, *candidates):
        root = Path(candidate).resolve()
        if all((root / name).is_file() and (root / name).stat().st_size for name in FILES):
            return root
    raise ValueError("No bundled Skin Swapper template was found. Use -ToolsFrom with a current "
                     "Atelier installation, or -Template to supply a publisher template.")


def install_template(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    for name in FILES:
        path = source / name
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"Missing or empty {path}. The template is the .uasset and .uexp pair.")
    # Reuse the mod publisher's verified staging, rollback and interruption-recovery journal.
    if source != destination:
        storage.publish_files([source / name for name in FILES], destination)
    return {name: hashlib.sha256((destination / name).read_bytes()).hexdigest() for name in FILES}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--bundled-from", type=Path, action="append", default=[])
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    try:
        source = args.source or find_bundled_template(args.destination, args.bundled_from)
        for name, digest in install_template(source, args.destination).items():
            print(f"  {name} sha256 {digest}")
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
