"""Retain cooked vertex identity through Blender's multi-attribute glTF importer.

This is the same workaround used by Atelier's glb_to_blend.py, packaged for the
resident add-on. Blender releases before the custom-attribute ordering fix could
scramble _ATELIER_MORPH_ID, _REST and _LOD when imported simultaneously.
"""
import json
import os
from pathlib import Path
import struct
import tempfile

import numpy as np

_WIDTH = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4}
_RESTORED = ('_ATELIER_MORPH_REST', '_ATELIER_MORPH_LOD')


def read_glb(path):
    content = Path(path).read_bytes()
    magic, ver, total = struct.unpack_from('<III', content, 0)
    jlen, jtype = struct.unpack_from('<II', content, 12)
    if magic != 0x46546c67 or ver != 2 or jtype != 0x4e4f534a or total != len(content):
        raise ValueError('Atelier live import expects valid binary glTF 2.0')
    gltf = json.loads(content[20:20+jlen])
    offset = 20 + jlen
    length, kind = struct.unpack_from('<II', content, offset)
    if kind != 0x004e4942: raise ValueError('The mesh is missing binary geometry')
    return gltf, content[offset+8:offset+8+length]


def float_accessor(gltf, binary, index):
    access = gltf['accessors'][index]
    view = gltf['bufferViews'][access['bufferView']]
    width = _WIDTH[access['type']]
    if access.get('componentType') != 5126 or view.get('byteStride', 4*width) != 4*width:
        raise ValueError('Morph tracking attributes must be tightly packed float32')
    offset = view.get('byteOffset', 0) + access.get('byteOffset', 0)
    return np.frombuffer(binary, '<f4', access['count']*width, offset).reshape(access['count'], width)


def strip_tracking(path):
    """Import only morph ID, then restore the other two attributes by vertex ID."""
    gltf, binary = read_glb(path)
    ids, rest, lod = [], [], []
    for mesh in gltf.get('meshes', []):
        for primitive in mesh.get('primitives', []):
            attr = primitive.get('attributes', {})
            if '_ATELIER_MORPH_ID' not in attr or not all(key in attr for key in _RESTORED):
                continue
            ids.append(float_accessor(gltf,binary,attr['_ATELIER_MORPH_ID'])[:,0])
            rest.append(float_accessor(gltf,binary,attr['_ATELIER_MORPH_REST']))
            lod.append(float_accessor(gltf,binary,attr['_ATELIER_MORPH_LOD'])[:,0])
            for key in _RESTORED:del attr[key]
    if not ids:return path,None
    values = np.rint(np.concatenate(ids)).astype(np.int64)
    if values.min() < 0 or len(np.unique(values)) != len(values):
        raise ValueError('Morph tracking IDs are not unique')
    lookup = {'ids': values, 'rest': np.concatenate(rest), 'lod': np.concatenate(lod)}
    encoded = json.dumps(gltf).encode('utf-8')
    encoded += b' '*(-len(encoded)%4)
    handle, target = tempfile.mkstemp(prefix='atelier-live-', suffix='.glb')
    try:
        with os.fdopen(handle, 'wb') as out:
            out.write(struct.pack('<III', 0x46546c67, 2, 12+8+len(encoded)+8+len(binary)))
            out.write(struct.pack('<II',len(encoded),0x4e4f534a));out.write(encoded)
            out.write(struct.pack('<II',len(binary),0x004e4942));out.write(binary)
    except BaseException:
        Path(target).unlink(missing_ok=True)
        raise
    return target, lookup


def restore_tracking(mesh, lookup):
    import bpy  # only needed while Blender is executing an import
    attribute = mesh.attributes.get('_ATELIER_MORPH_ID')
    if attribute is None or attribute.domain != 'POINT':
        raise ValueError('Blender dropped the vertex identity attribute; refusing an unsafe import')
    result = np.empty(len(mesh.vertices), np.float32)
    attribute.data.foreach_get('value', result)
    indices = np.rint(result).astype(np.int64)
    maximum = max(lookup['ids'].max(initial=0), indices.max(initial=0))
    positions = np.full(int(maximum)+1,-1,np.int64)
    positions[lookup['ids']] = np.arange(len(lookup['ids']))
    rows = positions[np.clip(indices,0,len(positions)-1)]
    if (indices < 0).any() or (rows < 0).any():
        raise ValueError('Blender imported unmapped vertex identities')
    rest = mesh.attributes.new('_ATELIER_MORPH_REST','FLOAT_VECTOR','POINT')
    rest.data.foreach_set('vector',lookup['rest'][rows].astype(np.float32).ravel())
    lod = mesh.attributes.new('_ATELIER_MORPH_LOD','FLOAT','POINT')
    lod.data.foreach_set('value',lookup['lod'][rows].astype(np.float32))
