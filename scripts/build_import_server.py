"""Build Atelier's persistent import server using its shipped CUE4Parse assemblies.

Requires .NET SDK 10. No game data, encryption keys or mappings are used at build
time. Existing native tool installations are never overwritten implicitly.
"""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile

from build_animation_decoder import extract_assemblies

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tools', type=Path, required=True)
    parser.add_argument('--output', type=Path, help='Fresh output folder; defaults to Tools/AtelierImport')
    parser.add_argument('--dotnet', default='dotnet')
    args = parser.parse_args()
    source = args.tools.resolve() / 'AtelierMesh'
    output = args.output.resolve() if args.output else args.tools.resolve() / 'AtelierImport'
    if output.exists():
        raise SystemExit(f'Output exists; choose a fresh folder: {output}')
    with tempfile.TemporaryDirectory(prefix='atelier-import-build-') as workspace:
        libraries = Path(workspace) / 'libraries'
        libraries.mkdir()
        extract_assemblies(source / 'AtelierMesh.exe', libraries)
        subprocess.run([args.dotnet, 'publish', str(ROOT / 'tools-src/AtelierImport/AtelierImport.csproj'),
            '-c', 'Release', '-r', 'win-x64', '--self-contained', 'true', '-p:PublishSingleFile=true',
            f'-p:MeshAssemblies={libraries}', '-o', str(output)], check=True)
    for name in ('CUE4Parse-Natives.dll', 'oo2core_9_win64.dll'):
        shutil.copy2(source / name, output / name)
    print(f'Built persistent import server: {output}')


if __name__ == '__main__':
    main()
