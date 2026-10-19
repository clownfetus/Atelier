"""Package the version-pinned Blender add-on without duplicating material logic.

Usage: python scripts/build_blender_bridge.py [output.zip]
The zip contains our existing material_nodes.py (not an external dependency).
"""
import sys
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/'atelier'/'blender'
PACKAGE=SRC/'atelier_live_bridge'
FILES=['blender_manifest.toml','__init__.py','tracking.py']


def package(output):
    output=Path(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    with ZipFile(output,'w',compression=ZIP_DEFLATED) as archive:
        for filename in FILES:
            archive.write(PACKAGE/filename,filename)
        archive.write(SRC/'material_nodes.py','material_nodes.py')
    return output


if __name__=='__main__':
    file=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'dist'/'Atelier-Live-Bridge.zip'
    print(package(file))
