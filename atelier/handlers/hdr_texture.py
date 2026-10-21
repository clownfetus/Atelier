"""HDR cubemap images and cooked TextureCube payloads; PNGs are previews only.

Uses the pinned texconv for Radiance RGBE and BC6H conversion. Cooked UE5
payloads use six faces per mip and the package's data-resource table. No typed
texture JSON writer participates in pixel serialization.
"""
import base64
import copy
from dataclasses import dataclass
import io
import hashlib
import json
import math
import os
from pathlib import Path
import re
import struct
import tempfile

import numpy as np
from PIL import Image, ImageDraw

from atelier import config, hostos
from atelier.tools import uat

MAX_FACE = 2048
MAX_PIXELS = 32 * 1024 * 1024
MAX_BYTES = 512 * 1024 * 1024
FORMATS = {10: 'PF_FloatRGBA', 2: 'PF_A32B32G32R32F', 95: 'PF_BC6H', 96: 'PF_BC6H_Signed'}
DXGI = {value: key for key, value in FORMATS.items()}
TEXCONV = {'PF_FloatRGBA': 'R16G16B16A16_FLOAT', 'PF_A32B32G32R32F': 'R32G32B32A32_FLOAT',
           'PF_BC6H': 'BC6H_UF16', 'PF_BC6H_Signed': 'BC6H_SF16'}


@dataclass
class Cube:
    size: int
    format: str
    mips: list  # mip-major, each entry contains +X, -X, +Y, -Y, +Z, -Z


def face_bytes(size, fmt):
    if fmt in ('PF_BC6H', 'PF_BC6H_Signed'):
        return max(1, (size + 3) // 4) ** 2 * 16
    if fmt in ('PF_FloatRGBA', 'PF_A32B32G32R32F'):
        return size * size * (8 if fmt == 'PF_FloatRGBA' else 16)
    raise ValueError('Use a BC6H or floating-point RGBA HDR cubemap.')


def read_dds(data, *, cube=True):
    if len(data) > MAX_BYTES or len(data) < 128 or data[:4] != b'DDS ':
        raise ValueError('Choose a valid HDR DDS file up to 512 MB.')
    if struct.unpack_from('<I', data, 4)[0] != 124 or struct.unpack_from('<I', data, 76)[0] != 32:
        raise ValueError('The DDS header is invalid.')
    height, width = struct.unpack_from('<II', data, 12)
    count = struct.unpack_from('<I', data, 28)[0] or 1
    caps2 = struct.unpack_from('<I', data, 112)[0]
    offset = 128
    if data[84:88] == b'DX10':
        if len(data) < 148:
            raise ValueError('The DDS extended header is truncated.')
        dxgi, dimension, misc, arrays, _alpha = struct.unpack_from('<5I', data, 128)
        if dimension != 3 or arrays != 1 or bool(misc & 4) != cube:
            raise ValueError('Choose one six-face TextureCube DDS, not a 2D texture or cubemap array.')
        fmt, offset = FORMATS.get(dxgi), 148
    else:
        fmt = 'PF_FloatRGBA' if struct.unpack_from('<I', data, 84)[0] == 113 else None
        if bool(caps2 & 0x200) != cube:
            raise ValueError('Choose a six-face HDR cubemap DDS.')
    if not fmt:
        raise ValueError('The DDS must contain BC6H or floating-point HDR pixels.')
    if width < 1 or height < 1 or width * height > MAX_PIXELS or (
            cube and (width != height or width > MAX_FACE or caps2 & 0xfe00 != 0xfe00)):
        raise ValueError('A cubemap needs six square faces, each up to 2048 pixels.')
    if count > 1 + int(math.log2(max(width, height))):
        raise ValueError('The DDS mip count is invalid.')
    faces = 6 if cube else 1
    result = [[] for _ in range(count)]
    for _face in range(faces):
        for level in range(count):
            w, h = max(1, width >> level), max(1, height >> level)
            length = face_bytes(w, fmt) if cube else w * h * (8 if fmt == 'PF_FloatRGBA' else 16)
            if offset + length > len(data):
                raise ValueError('The DDS is missing a face or mip payload.')
            result[level].append(data[offset:offset + length]); offset += length
    if offset != len(data):
        raise ValueError('The DDS has unexpected data after its faces and mips.')
    if not cube:
        if fmt not in ('PF_FloatRGBA', 'PF_A32B32G32R32F'):
            raise ValueError('The converted HDR pixels are not floating point.')
        pixels = np.frombuffer(result[0][0], dtype='<f2' if fmt == 'PF_FloatRGBA' else '<f4')
        return pixels.reshape(height, width, 4)
    return Cube(width, fmt, result)


def write_dds(cube):
    if not 1 <= cube.size <= MAX_FACE or not cube.mips or len(cube.mips) > 1 + int(math.log2(cube.size)):
        raise ValueError('The cubemap dimensions or mip count are invalid.')
    header = bytearray(148); header[:4] = b'DDS '
    compressed = cube.format in ('PF_BC6H', 'PF_BC6H_Signed')
    struct.pack_into('<7I', header, 4, 124, 0x1007 | 0x20000 | (0x80000 if compressed else 8),
                     cube.size, cube.size, face_bytes(cube.size, cube.format) if compressed else cube.size * (8 if cube.format == 'PF_FloatRGBA' else 16),
                     0, len(cube.mips))
    struct.pack_into('<II', header, 76, 32, 4); header[84:88] = b'DX10'
    struct.pack_into('<II', header, 108, 0x1008 | (0x400000 if len(cube.mips) > 1 else 0), 0xfe00)
    struct.pack_into('<5I', header, 128, DXGI[cube.format], 3, 4, 1, 0)
    for level, faces in enumerate(cube.mips):
        if len(faces) != 6 or any(len(face) != face_bytes(max(1, cube.size >> level), cube.format) for face in faces):
            raise ValueError('A cubemap mip must contain all six complete faces.')
    payload = b''.join(cube.mips[level][face] for face in range(6) for level in range(len(cube.mips)))
    if len(payload) + 148 > MAX_BYTES:
        raise ValueError('The HDR cubemap exceeds 512 MB.')
    return bytes(header) + payload


def _texconv(source, output_dir, fmt, mips=1):
    tool = Path(config.TOOLS) / 'texconv.exe'
    if not tool.is_file() and not hostos.native_tool(str(tool)):
        raise ValueError('The bundled HDR texture converter is missing. Repair the tools in Settings.')
    output_dir = Path(output_dir); output_dir.mkdir(parents=True, exist_ok=True)
    result = hostos.run_exe([str(tool), '-nologo', '-y', '-dx10', '-nogpu', '-m', str(mips),
                             '-f', TEXCONV[fmt], '-ft', 'DDS', '-o', str(output_dir), str(source)],
                            capture_output=True, timeout=300, creationflags=config.CNW)
    target = next((path for path in output_dir.iterdir() if path.stem.casefold() == Path(source).stem.casefold()
                   and path.suffix.casefold() == '.dds'), None)
    if result.returncode or not target:
        raise ValueError('The HDR file could not be converted. Use a Radiance .hdr or a six-face HDR DDS.')
    if target.stat().st_size > MAX_BYTES:
        raise ValueError('The converted HDR texture exceeds 512 MB.')
    return target.read_bytes()


def float_faces(cube, scratch):
    Path(scratch).mkdir(parents=True, exist_ok=True)
    if cube.format not in ('PF_FloatRGBA', 'PF_A32B32G32R32F'):
        source = Path(scratch) / 'decode.dds'; source.write_bytes(write_dds(cube))
        cube = read_dds(_texconv(source, Path(scratch) / 'decoded', 'PF_A32B32G32R32F'))
    dtype = '<f2' if cube.format == 'PF_FloatRGBA' else '<f4'
    pixels = np.stack([np.frombuffer(face, dtype=dtype).reshape(cube.size, cube.size, 4)
                       for face in cube.mips[0]]).astype(np.float32)
    if not np.isfinite(pixels).all():
        raise ValueError('The HDR pixels contain infinity or invalid values.')
    return pixels


def _image_faces(pixels):
    height, width = pixels.shape[:2]
    if height == width * 6 and width <= MAX_FACE:
        return pixels.reshape(6, width, width, 4)
    if width == height * 6 and height <= MAX_FACE:
        return np.stack(np.split(pixels, 6, axis=1))
    if width != height * 2:
        raise ValueError('Use a 2:1 HDR panorama, a strip of six square faces, or a cubemap DDS.')
    size = width // 4
    if not 1 <= size <= MAX_FACE:
        raise ValueError('The HDR panorama must produce faces up to 2048 pixels.')
    u, v = np.meshgrid((np.arange(size, dtype=np.float32) + .5) * (2 / size) - 1,
                       (np.arange(size, dtype=np.float32) + .5) * (2 / size) - 1)
    one = np.ones_like(u)
    directions = ((one, -v, -u), (-one, -v, u), (u, one, v),
                  (u, -one, -v), (u, -v, one), (-u, -v, -one))
    result = []
    for x, y, z in directions:
        length = np.sqrt(x*x + y*y + z*z)
        sx = (np.arctan2(z, x) / (2*np.pi) + .5) * width - .5
        sy = np.clip(np.arccos(np.clip(y / length, -1, 1)) / np.pi * height - .5, 0, height - 1)
        ix, iy = np.floor(sx).astype(np.int32), np.floor(sy).astype(np.int32)
        fx, fy = (sx-ix)[..., None], (sy-iy)[..., None]
        a = pixels[iy, ix % width] * (1-fx) + pixels[iy, (ix+1) % width] * fx
        b = pixels[np.minimum(iy+1, height-1), ix % width] * (1-fx) + pixels[np.minimum(iy+1, height-1), (ix+1) % width] * fx
        result.append(a * (1-fy) + b * fy)
    return np.stack(result).astype(np.float32)


def from_float_faces(pixels, count=1):
    if pixels.ndim != 4 or pixels.shape[0] != 6 or pixels.shape[1] != pixels.shape[2] or pixels.shape[3] != 4:
        raise ValueError('An HDR cube must contain six square RGBA faces.')
    size = pixels.shape[1]
    if not 1 <= size <= MAX_FACE or count < 1:
        raise ValueError('Cubemap faces must be between 1 and 2048 pixels.')
    if not np.isfinite(pixels).all() or np.abs(pixels).max() > 65504:
        raise ValueError('HDR values must be finite and fit the template’s 16-bit float range (up to 65504).')
    mips = []
    for _ in range(min(count, 1 + int(math.log2(size)))):
        mips.append([face.astype('<f2').tobytes() for face in pixels])
        if pixels.shape[1] == 1:
            break
        next_size = max(1, pixels.shape[1] // 2)
        # Area averages in linear light, never 8-bit or gamma-encoded image values.
        cropped = pixels[:, :next_size*2, :next_size*2]
        pixels = cropped.reshape(6, next_size, 2, next_size, 2, 4).mean(axis=(2, 4))
    return Cube(size, 'PF_FloatRGBA', mips)


def prepare(data, filename, fmt, mip_count, scratch):
    scratch = Path(scratch); scratch.mkdir(parents=True, exist_ok=True)
    if len(data) > MAX_BYTES or not data:
        raise ValueError('Choose an HDR image up to 512 MB.')
    extension = Path(filename).suffix.lower()
    if extension == '.hdr':
        header = data[:65536]
        match = re.search(rb'(?:^|\n)([+-])Y\s+(\d+)\s+([+-])X\s+(\d+)\s*(?:\r?\n)', header)
        if not header.startswith((b'#?RADIANCE', b'#?RGBE')) or not match:
            raise ValueError('Choose a valid Radiance RGBE .hdr image.')
        height, width = int(match[2]), int(match[4])
        if width < 1 or height < 1 or width * height > MAX_PIXELS:
            raise ValueError('The HDR image is too large (maximum 32 megapixels).')
        source = scratch / 'source.hdr'; source.write_bytes(data)
        pixels = read_dds(_texconv(source, scratch/'float', 'PF_A32B32G32R32F'), cube=False)
        cube = from_float_faces(_image_faces(pixels), mip_count)
    elif extension == '.dds':
        cube = read_dds(data)
        # Validate all authored floating-point mips, not just the visible top face.
        if cube.format in ('PF_FloatRGBA', 'PF_A32B32G32R32F'):
            dtype = '<f2' if cube.format == 'PF_FloatRGBA' else '<f4'
            for faces in cube.mips:
                for face in faces:
                    values = np.frombuffer(face, dtype=dtype)
                    if not np.isfinite(values).all() or np.abs(values).max() > 65504:
                        raise ValueError('The HDR pixels exceed the template’s finite float range.')
    else:
        raise ValueError('TextureCube replacements need an HDR .hdr image or a six-face HDR .dds file.')
    if fmt not in ('PF_BC6H', 'PF_BC6H_Signed', 'PF_FloatRGBA'):
        raise ValueError('Choose a BC6H or FloatRGBA TextureCube game template.')
    if cube.format != fmt:
        values = float_faces(cube, scratch)
        if fmt == 'PF_BC6H' and values[..., :3].min() < 0:
            raise ValueError('This unsigned BC6H template cannot preserve negative HDR values.')
        source = scratch/'convert.dds'; source.write_bytes(write_dds(cube))
        cube = read_dds(_texconv(source, scratch/'converted', fmt, len(cube.mips)))
    return cube


def preview_png(cube, scratch):
    pixels = float_faces(cube, scratch)[..., :3]
    pixels = np.maximum(pixels, 0)
    mapped = np.power(pixels / (1 + pixels), 1/2.2)
    side = min(256, cube.size)
    image = Image.new('RGB', (side * 3, side * 2))
    for index, face in enumerate(mapped):
        tile = Image.fromarray(np.round(face * 255).astype('uint8')).resize((side, side), Image.Resampling.LANCZOS)
        image.paste(tile, ((index % 3)*side, (index // 3)*side))
    draw = ImageDraw.Draw(image)
    for index, name in enumerate(('+X', '-X', '+Y', '-Y', '+Z', '-Z')):
        draw.text(((index % 3)*side+4, (index // 3)*side+4), name, fill='white', stroke_width=1, stroke_fill='black')
    output = io.BytesIO(); image.save(output, 'PNG')
    return output.getvalue()


def texture_class(doc):
    exports = doc.get('Exports') or []
    if len(exports) != 1:
        return None
    index = exports[0].get('ClassIndex', 0)
    imports = doc.get('Imports') or []
    return imports[-index-1].get('ObjectName') if isinstance(index, int) and -len(imports) <= index < 0 else None


def document(base, scratch):
    scratch = Path(scratch); scratch.mkdir(parents=True, exist_ok=True)
    result = uat(['to_json', str(Path(str(base)+'.uasset').resolve()), config.USMAP, str(scratch.resolve())])
    target = scratch/(Path(base).name+'.json')
    if result.returncode or not target.is_file():
        raise ValueError('Could not read the HDR texture template.')
    return json.loads(target.read_text(encoding='utf-8-sig'))


def read_cooked(doc, base):
    if texture_class(doc) != 'TextureCube' or doc.get('ObjectVersionUE5') != 'DATA_RESOURCES':
        raise ValueError('Choose a cooked UE5 TextureCube template.')
    export = doc['Exports'][0]
    payload = Path(str(base)+'.uexp').read_bytes()
    raw = payload[:-4]
    if payload[-4:] != b'\xc1\x83\x2a\x9e' or export['SerialOffset'] != Path(str(base)+'.uasset').stat().st_size or export['SerialSize'] != len(raw):
        raise ValueError('The HDR template export range is invalid.')
    names = doc['NameMap']; fmt = (export.get('PlatformData') or {}).get('PixelFormat')
    if fmt not in ('PF_BC6H', 'PF_BC6H_Signed', 'PF_FloatRGBA') or fmt not in names:
        raise ValueError('Choose a BC6H or FloatRGBA TextureCube template.')
    marker = struct.pack('<II', names.index(fmt), 0)
    candidates = []
    for start in range(min(65536, len(raw)-16)):
        if raw[start:start+8] != marker:
            continue
        skip = struct.unpack_from('<q', raw, start+8)[0]
        end = start+8+skip
        if end+8 != len(raw) or raw[end:] != struct.pack('<II', names.index('None'), 0):
            continue
        cursor = start+16
        if cursor+41 > end:
            continue
        if raw[cursor:cursor+16] != bytes(16):
            continue
        cursor += 16
        width, height, packed, length = struct.unpack_from('<iiIi', raw, cursor); cursor += 16
        if packed != 0x80000006 or not 1 <= width <= MAX_FACE or width != height or not 1 <= length <= 64:
            continue
        if raw[cursor:cursor+length] != (fmt+'\0').encode():
            continue
        cursor += length
        if cursor+8 > end:
            continue
        first, count = struct.unpack_from('<ii', raw, cursor); cursor += 8
        if not 0 <= first <= 15 or not 1 <= count <= 15:
            continue
        mips = []
        top_size = None
        for _ in range(count):
            if cursor+4 > end:
                raise ValueError('The HDR template mip table is truncated.')
            index = struct.unpack_from('<i', raw, cursor)[0]; cursor += 4
            resources = doc.get('DataResources') or []
            if not 0 <= index < len(resources):
                raise ValueError('The HDR template has an invalid mip resource.')
            resource = resources[index]
            size = resource['SerialSize']
            if resource['LegacyBulkDataFlags'] != 72 or resource['SerialOffset'] != cursor or size < 1 or cursor+size+12 > end:
                raise ValueError('The HDR template requires complete inline face data. Re-import it or choose another cube template.')
            pixels = raw[cursor:cursor+size]; cursor += size
            w, h, depth = struct.unpack_from('<iii', raw, cursor); cursor += 12
            if w != h or not 1 <= w <= MAX_FACE or depth not in (1, 6) or size != 6*face_bytes(w, fmt):
                raise ValueError('The HDR template does not contain six complete square faces per mip.')
            if top_size is None: top_size = w
            if w != max(1, top_size >> len(mips)):
                raise ValueError('The HDR template mip dimensions are inconsistent.')
            mips.append([pixels[i*size//6:(i+1)*size//6] for i in range(6)])
        if cursor+4 != end or raw[cursor:end] != bytes(4):
            raise ValueError('Virtual or trailing HDR cube data is not supported.')
        if face_bytes(top_size, fmt) != len(mips[0][0]):
            raise ValueError('The HDR template mip dimensions are inconsistent.')
        candidates.append((Cube(top_size, fmt, mips), raw[:start], start))
    if len(candidates) != 1:
        raise ValueError('The HDR template format chain is ambiguous or unsupported.')
    return candidates[0]


def inject(base, output, cube, scratch, *, doc=None, group=None):
    scratch = Path(scratch); scratch.mkdir(parents=True, exist_ok=True)
    doc = copy.deepcopy(doc) if doc else document(base, scratch/'template')
    original, prefix, _start = read_cooked(doc, base)
    if cube.format != original.format:
        raise ValueError('The HDR replacement must retain the game template’s pixel format.')
    if group:
        prop = next((p for p in doc['Exports'][0].get('Data', []) if p.get('Name') == 'LODGroup'), None)
        if not prop:
            raise ValueError('This cubemap template has no editable texture group. Keep its original group.')
        old = prop.get('Value')
        if old != group:
            prefix = _group_prefix(doc, prefix, group, scratch/'group')
    fmt = (cube.format+'\0').encode()
    platform = bytearray(bytes(16)+struct.pack('<iiIi', cube.size, cube.size, 0x80000006, len(fmt))+fmt+
                         struct.pack('<ii', 0, len(cube.mips)))
    resources = []
    for level, faces in enumerate(cube.mips):
        size = max(1, cube.size >> level)
        if len(faces) != 6 or any(len(face) != face_bytes(size, cube.format) for face in faces):
            raise ValueError('The HDR replacement is missing a face.')
        pixels = b''.join(faces)
        platform += struct.pack('<i', level)
        resources.append({'$type': 'UAssetAPI.UnrealTypes.FObjectDataResource, UAssetAPI',
                          'Flags': 'None', 'CookedIndex': 0, 'SerialOffset': len(prefix)+16+len(platform),
                          'DuplicateSerialOffset': -1, 'SerialSize': len(pixels), 'RawSize': len(pixels),
                          'OuterIndex': 0, 'LegacyBulkDataFlags': 72})
        platform += pixels + struct.pack('<iii', size, size, 1)
    platform += bytes(4)
    raw = prefix + struct.pack('<IIq', doc['NameMap'].index(cube.format), 0, len(platform)+8) + platform + struct.pack('<II', doc['NameMap'].index('None'), 0)
    doc['DataResources'] = resources
    export = doc['Exports'][0]
    export['$type'] = 'UAssetAPI.ExportTypes.RawExport, UAssetAPI'
    export['Data'] = base64.b64encode(raw).decode(); export['Extras'] = ''
    target = Path(output); target.parent.mkdir(parents=True, exist_ok=True)
    source = scratch/'cube.json'; source.write_text(json.dumps(doc), encoding='utf-8')
    result = uat(['from_json', str(source.resolve()), str(target.resolve()), config.USMAP])
    if result.returncode or not target.is_file() or target.with_suffix('.uexp').read_bytes() != raw+b'\xc1\x83\x2a\x9e':
        raise ValueError('The HDR cubemap failed its byte-preservation check.')
    verified = document(str(target.with_suffix('')), scratch/'readback')
    actual, _prefix, _offset = read_cooked(verified, str(target.with_suffix('')))
    if actual != cube:
        raise ValueError('The encoded HDR cubemap did not retain all faces and mips.')
    return {'texture_class': 'TextureCube', 'hdr': True, 'size': [cube.size, cube.size],
            'format': cube.format.removeprefix('PF_'), 'faces': 6, 'mips': len(cube.mips)}


def _group_prefix(doc, prefix, group, scratch):
    """Let the pinned serializer resolve the mapped enum, then copy only verified property bytes."""
    scratch.mkdir(parents=True, exist_ok=True)
    prefixes = []
    for name, value in (('before', None), ('after', group)):
        record = copy.deepcopy(doc)
        if value is not None:
            prop = next(p for p in record['Exports'][0]['Data'] if p.get('Name') == 'LODGroup')
            prop['Value'] = value; prop['IsZero'] = False
        source = scratch/(name+'.json'); source.write_text(json.dumps(record), encoding='utf-8')
        target = scratch/(name+'.uasset')
        result = uat(['from_json', str(source.resolve()), str(target.resolve()), config.USMAP])
        if result.returncode or not target.is_file():
            raise ValueError('The HDR texture group could not be serialized. Keep its original group.')
        raw = target.with_suffix('.uexp').read_bytes()
        platform = record['Exports'][0]['PlatformData']
        marker = struct.pack('<II', record['NameMap'].index(platform['PixelFormat']), 0)
        dimensions = struct.pack('<iiI', platform['SizeX'], platform['SizeY'], platform['PackedData'])
        candidates = [i for i in range(min(65536, len(raw)-44)) if raw[i:i+8] == marker
                      and raw[i+16:i+32] == bytes(16) and raw[i+32:i+44] == dimensions]
        if len(candidates) != 1:
            raise ValueError('The HDR texture group prefix could not be validated. Keep its original group.')
        prefixes.append(raw[:candidates[0]])
    before, after = prefixes
    if not before.startswith(prefix) or len(before) != len(after) or before[len(prefix):] != after[len(prefix):]:
        raise ValueError('The HDR texture group altered unrelated serialized data. Keep its original group.')
    return after[:len(prefix)]


def candidate(base):
    """Cheap hint only; the export's actual class is validated before accepting it."""
    try:
        with open(str(base)+'.uasset', 'rb') as stream:
            header = stream.read(1024*1024)
        # Rebuilt legacy packages may use compact names without a trailing NUL.
        return b'TextureCube' in header or 'TextureCube'.encode('utf-16-le') in header
    except OSError:
        return False


def project_info(base):
    try:
        with open(str(base)+'.dds', 'rb') as stream: header = stream.read(148)
        if len(header) != 148 or header[:4] != b'DDS ' or header[84:88] != b'DX10':
            return {}
        dxgi, dimension, misc, arrays, _ = struct.unpack_from('<5I', header, 128)
        if dxgi not in FORMATS or dimension != 3 or not misc & 4 or arrays != 1:
            return {}
        return {'texture_class': 'TextureCube', 'hdr': True, 'faces': 6,
                'format': FORMATS[dxgi].removeprefix('PF_'),
                'mips': struct.unpack_from('<I', header, 28)[0] or 1}
    except OSError:
        return {}


def extract_files(destination, base):
    """Write an HDR DDS and a separate tone-mapped preview into an owned scratch directory."""
    if not candidate(base): return False
    os.makedirs(config._CACHE, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='hdr-read-', dir=config._CACHE) as work:
        doc = document(base, Path(work)/'json')
        if texture_class(doc) != 'TextureCube': return False
        cube, _prefix, _start = read_cooked(doc, base)
        preview = preview_png(cube, Path(work)/'preview')
        Path(str(destination)+'.dds').write_bytes(write_dds(cube))
        Path(str(destination)+'.png').write_bytes(preview)
    return True


def replace_project(game_rel, filename, data):
    from atelier.handlers import texture
    from atelier.storage import publish_project_files
    config.validate_game_rel(game_rel)
    root = config.get_import_root(); destination = config.project_base(game_rel)
    before = {ext: hashlib.sha256(Path(destination+ext).read_bytes()).hexdigest()
              if Path(destination+ext).is_file() else None for ext in ('.png', '.dds')}
    base = texture.ensure_work_base(game_rel)
    if not base or not candidate(base):
        raise ValueError('Choose a TextureCube asset for an HDR cubemap replacement.')
    os.makedirs(config._CACHE, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='hdr-replace-', dir=config._CACHE) as work:
        work = Path(work); doc = document(base, work/'template')
        original, _, _ = read_cooked(doc, base)
        cube = prepare(data, filename, original.format, len(original.mips), work/'prepare')
        files = {'.dds': write_dds(cube), '.png': preview_png(cube, work/'preview')}
        changes = []
        for ext, payload in files.items():
            source = work/('replacement'+ext); source.write_bytes(payload)
            changes.append({'path': game_rel+ext, 'before': before[ext], 'source': str(source)})
        publish_project_files(root, changes)
    return {'texture_class': 'TextureCube', 'hdr': True, 'faces': 6,
            'size': [cube.size, cube.size], 'format': cube.format.removeprefix('PF_'), 'mips': len(cube.mips)}


def stage(stage, game_rel, base, import_base, opts):
    from atelier.handlers import texture
    path = Path(import_base+'.dds')
    if not path.is_file():
        raise ValueError('Re-import this cubemap or replace it with an HDR image or cubemap DDS before exporting.')
    if path.stat().st_size > MAX_BYTES:
        raise ValueError('The HDR cubemap exceeds 512 MB.')
    with tempfile.TemporaryDirectory(prefix='hdr-stage-', dir=config._CACHE) as work:
        work = Path(work); doc = document(base, work/'template')
        original, _, _ = read_cooked(doc, base)
        cube = prepare(path.read_bytes(), path.name, original.format, len(original.mips), work/'prepare')
        if opts.get('no_mips'): cube = Cube(cube.size, cube.format, cube.mips[:1])
        if opts.get('blank'):
            blank = from_float_faces(np.zeros((6, cube.size, cube.size, 4), dtype=np.float32), len(cube.mips))
            cube = prepare(write_dds(blank), 'blank.dds', original.format, len(cube.mips), work/'blank')
        output = Path(str(Path(stage).joinpath(*texture.pak_game_path(game_rel).split('/')))+'.uasset')
        inject(base, output, cube, work/'inject', doc=doc, group=opts.get('lod_group'))
        notes = ['HDR TextureCube', f'{len(cube.mips)} mip' if len(cube.mips) == 1 else f'{len(cube.mips)} mips']
        if opts.get('blank'): notes.append('blanked to black')
        if opts.get('lq_twin'):
            notes.append('+Marvel_LQ copy' if texture.stage_lq_twin(stage, game_rel, str(output)) else 'no Marvel_LQ mount in these paks')
    return os.path.basename(game_rel)+' ('+', '.join(notes)+')'
