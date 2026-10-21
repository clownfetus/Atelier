"""Extract managed dependencies from a validated .NET single-file bundle."""
import io
from pathlib import Path
import struct
import zlib

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
