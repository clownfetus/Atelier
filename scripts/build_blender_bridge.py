"""Package the version-pinned Blender add-on without duplicating material logic.

Usage: python scripts/build_blender_bridge.py [output.zip]
The zip contains our existing material_nodes.py (not an external dependency).
"""
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from atelier.blender_extension import archive_bytes


def package(output):
    output=Path(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_bytes(archive_bytes(ROOT))
    return output


if __name__=='__main__':
    file=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'dist'/'Atelier-Live-Bridge.zip'
    print(package(file))
