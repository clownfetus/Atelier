"""Build the idle decoder against the exact libraries shipped in AtelierMesh.

Requires .NET SDK 10. No game data, keys or mappings are used during the build.
"""
import argparse
import io
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
SIGNATURE = bytes.fromhex('8b1202b96a612038727b930214d7a03213f5b9e6efae3318ee3b2dce24b36aae')


def extract_assemblies(executable, destination):
    payload = Path(executable).read_bytes()
    marker = payload.find(SIGNATURE)
    if marker < 8:
        raise ValueError('AtelierMesh is not a supported .NET single-file bundle')
    stream = io.BytesIO(payload)
    stream.seek(struct.unpack_from('<q', payload, marker - 8)[0])

    def number(fmt):
        return struct.unpack(fmt, stream.read(struct.calcsize(fmt)))[0]

    def string():
        length = shift = 0
        while True:
            byte = number('B')
            length |= (byte & 127) << shift
            shift += 7
            if byte < 128:
                break
            if shift > 35:
                raise ValueError('Invalid bundle string')
        return stream.read(length).decode('utf-8')

    major, _minor, count = number('<I'), number('<I'), number('<I')
    string()
    if major != 6 or count > 4096:
        raise ValueError('Unsupported bundle format')
    stream.read(40)
    destination = Path(destination).resolve()
    for _ in range(count):
        offset, size, compressed, _kind = number('<q'), number('<q'), number('<q'), number('B')
        name = string()
        if not name.endswith('.dll'):
            continue
        target = (destination / name).resolve()
        if not target.is_relative_to(destination) or offset < 0 or size < 0 or offset + (compressed or size) > len(payload):
            raise ValueError('Invalid bundle entry')
        data = payload[offset:offset + (compressed or size)]
        if compressed:
            data = zlib.decompress(data, -15)
        if len(data) != size:
            raise ValueError('Invalid bundle entry size')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tools', type=Path, required=True, help='Tools containing AtelierMesh')
    parser.add_argument('--dotnet', default='dotnet')
    args = parser.parse_args()
    source = args.tools.resolve() / 'AtelierMesh'
    output = args.tools.resolve() / 'AtelierAnimation'
    if output.exists():
        raise SystemExit(f'Output already exists; choose a fresh tools directory: {output}')
    with tempfile.TemporaryDirectory(prefix='atelier-animation-build-') as workspace:
        libraries = Path(workspace) / 'libraries'
        libraries.mkdir()
        extract_assemblies(source / 'AtelierMesh.exe', libraries)
        subprocess.run([args.dotnet, 'publish', str(ROOT / 'tools-src/AtelierAnimation/AtelierAnimation.csproj'),
            '-c', 'Release', '-r', 'win-x64', '--self-contained', 'true', '-p:PublishSingleFile=true',
            f'-p:MeshAssemblies={libraries}', '-o', str(output)], check=True)
    for name in ('CUE4Parse-Natives.dll', 'oo2core_9_win64.dll'):
        shutil.copy2(source / name, output / name)
    print(f'Built standing idle decoder: {output}')


if __name__ == '__main__':
    main()
