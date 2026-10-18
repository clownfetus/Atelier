"""Install a complete local Galacta template pair without leaving a mixed version on failure."""
import argparse
import hashlib
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from atelier import storage

FILES = ("GAL_ConfigTemplate.uasset", "GAL_ConfigTemplate.uexp")


def install_template(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    for name in FILES:
        path = source / name
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"Missing or empty {path}. The template is the .uasset and .uexp pair.")
    # Reuse the mod publisher's verified staging, rollback and interruption-recovery journal.
    storage.publish_files([source / name for name in FILES], destination)
    return {name: hashlib.sha256((destination / name).read_bytes()).hexdigest() for name in FILES}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    try:
        for name, digest in install_template(args.source, args.destination).items():
            print(f"  {name} sha256 {digest}")
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
