"""Read verified UE5 texture mip resources when the native platform parser fails.

The cooked format chain, resource table, mip dimensions and package trailer must
agree. Pixel bytes stay unchanged; only a decoded image is published. In
particular, inline mip offsets are relative to the export, not the package file,
and streamed mip records do not consume bytes from the following inline mip.
"""
import io
import os
from pathlib import Path
import struct
import tempfile


_BLOCK_BYTES = {'DXT1': 8, 'DXT5': 16, 'BC4': 8, 'BC5': 16, 'BC6H': 16, 'BC7': 16}
_PACKAGE_TAG = b'\xc1\x83\x2a\x9e'


def _integer(value, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('Invalid cooked texture mip metadata')
    return value


def _chain(document, base, raw, start, end, fmt, faces):
    cursor = start + 16
    if cursor + 32 > end or raw[cursor:cursor+16] != bytes(16):
        raise ValueError('Unsupported cooked texture platform header')
    cursor += 16
    width, height, packed, length = struct.unpack_from('<iiIi', raw, cursor)
    cursor += 16
    _integer(width, 1, 16384); _integer(height, 1, 16384)
    if packed != (0x80000006 if faces == 6 else 1) or faces == 6 and width != height:
        raise ValueError('Unsupported cooked texture dimensions or slices')
    encoded = ('PF_' + fmt + '\0').encode('ascii')
    if length != len(encoded) or cursor + length + 8 > end or raw[cursor:cursor+length] != encoded:
        raise ValueError('The cooked texture pixel format does not match its name map')
    cursor += length
    first, count = struct.unpack_from('<ii', raw, cursor)
    cursor += 8
    _integer(first, 0, 15); _integer(count, 1, 16)
    resources = document.get('DataResources') or []
    used, mips = set(), []
    for level in range(count):
        if cursor + 4 > end:
            raise ValueError('The cooked texture mip table is truncated')
        index = struct.unpack_from('<i', raw, cursor)[0]
        cursor += 4
        _integer(index, 0, len(resources)-1)
        if index in used:
            raise ValueError('The cooked texture reuses a mip resource')
        used.add(index)
        resource = resources[index]
        size = _integer(resource.get('SerialSize'), 1, 256 * 1024 * 1024)
        offset = _integer(resource.get('SerialOffset'), 0, 2**63-1)
        if resource.get('RawSize') != size:
            raise ValueError('Compressed cooked texture resources are unsupported')
        flags = resource.get('LegacyBulkDataFlags')
        if flags == 72:  # The verified inline SingleUse / ForceInlinePayload layout.
            if offset != cursor or cursor + size + 12 > end:
                raise ValueError('The inline cooked texture range is invalid')
            pixels = raw[cursor:cursor+size]
            cursor += size
        elif flags == 0x10501:  # The verified separate .ubulk resource layout.
            bulk = Path(str(base) + '.ubulk')
            pixels = None
            if bulk.is_file():
                if offset > bulk.stat().st_size - size:
                    raise ValueError('The streamed cooked texture range is invalid')
                with bulk.open('rb') as stream:
                    stream.seek(offset)
                    pixels = stream.read(size)
                if len(pixels) != size:
                    raise ValueError('The streamed cooked texture is truncated')
        else:
            raise ValueError('Unsupported cooked texture resource flags')
        if cursor + 12 > end:
            raise ValueError('The cooked texture mip dimensions are truncated')
        w, h, depth = struct.unpack_from('<iii', raw, cursor)
        cursor += 12
        expected_w, expected_h = max(1, width >> (first+level)), max(1, height >> (first+level))
        expected_size = ((expected_w+3)//4) * ((expected_h+3)//4) * _BLOCK_BYTES[fmt] * faces
        if (w, h) != (expected_w, expected_h) or depth != 1 or size != expected_size:
            raise ValueError('The cooked texture mip dimensions do not match its resource')
        mips.append({'width': w, 'height': h, 'data': pixels})
    if cursor + 4 != end or raw[cursor:end] != bytes(4):
        raise ValueError('Virtual or trailing cooked texture data is unsupported')
    return {'format': fmt, 'width': width, 'height': height, 'faces': faces, 'mips': mips}


def read_cooked(document, base):
    """Complete block-compressed mip records, or None for an unsupported package.

    Missing external mips keep data=None so a complete, smaller shipped mip can
    still be used. Inconsistent ranges or ambiguous format chains are refused.
    """
    from atelier.handlers.hdr_texture import texture_class
    kind = texture_class(document)
    if kind not in ('Texture2D', 'TextureCube') or document.get('ObjectVersionUE5') != 'DATA_RESOURCES':
        return None
    if not document.get('DataResources'):
        return None
    base = Path(base)
    payload = Path(str(base)+'.uexp').read_bytes()
    export = document['Exports'][0]
    if (payload[-4:] != _PACKAGE_TAG or export.get('SerialOffset') != Path(str(base)+'.uasset').stat().st_size
            or export.get('SerialSize') != len(payload)-4):
        raise ValueError('The cooked texture export range is invalid')
    raw = payload[:-4]
    names = document.get('NameMap') or []
    if 'None' not in names:
        return None
    trailer = struct.pack('<II', names.index('None'), 0)
    matches, errors = [], []
    for fmt in _BLOCK_BYTES:
        if 'PF_'+fmt not in names:
            continue
        marker = struct.pack('<II', names.index('PF_'+fmt), 0)
        offset = 0
        while True:
            start = raw.find(marker, offset, min(65536, len(raw)-16))
            if start < 0:
                break
            offset = start + 1
            skip = struct.unpack_from('<q', raw, start+8)[0]
            end = start + 8 + skip
            if skip < 8 or end+8 != len(raw) or raw[end:] != trailer:
                continue
            try:
                matches.append(_chain(document, base, raw, start, end, fmt, 6 if kind == 'TextureCube' else 1))
            except ValueError as error:
                errors.append(error)
    if len(matches) > 1:
        raise ValueError('The cooked texture format chain is ambiguous')
    if matches:
        return matches[0]
    if errors:
        raise errors[0]
    return None


def decode_png(base, destination):
    """Recover a regular 2D PNG after the native decoder fails, atomically."""
    from PIL import Image
    from atelier.handlers.hdr_texture import document
    from atelier.handlers.texture import _dds_header
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.texture-', dir=destination.parent) as temporary:
        scratch = Path(temporary)
        texture = read_cooked(document(base, scratch/'json'), base)
        if not texture or texture['faces'] != 1 or texture['format'] == 'BC6H':
            return False
        mip = next((mip for mip in texture['mips'] if mip['data'] is not None), None)
        if mip is None:
            return False
        dds = _dds_header(mip['width'], mip['height'], texture['format'], len(mip['data'])) + mip['data']
        output = scratch/'decoded.png'
        with Image.open(io.BytesIO(dds)) as image:
            image.convert('RGBA').save(output)
        os.replace(output, destination)
    return True
