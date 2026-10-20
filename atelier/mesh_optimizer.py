"""Attribute-aware LOD reduction using the pinned official meshoptimizer build.

The WebAssembly module has no imports and receives only bounded numeric arrays.
It changes triangle indices; every surviving vertex keeps its original UVs,
colours, weights and morph tracking. Borders and bone-palette seams are locked.
"""
from functools import lru_cache
import hashlib
import math
from pathlib import Path
import struct

import numpy as np

_WASM = Path(__file__).with_name('vendor')/'meshoptimizer'/'simplifier.wasm'
_SHA256 = 'a357a388a66eb7b039d888c8f44e3de1fd23c1e82f4ad19d89f48f080340e9b2'
_VERTEX_FIELDS = ('positions', 'normal', 'tangent', 'tan_w', 'uv', 'color', 'global_idx', 'weight',
                  'morph_rest', 'morph_ids', 'morph_lods')


@lru_cache(maxsize=1)
def _runtime():
    import wasmtime
    source = _WASM.read_bytes()
    if hashlib.sha256(source).hexdigest() != _SHA256:
        raise RuntimeError('The bundled meshoptimizer checksum does not match')
    config = wasmtime.Config()
    config.consume_fuel = True
    # This numeric core module needs none of the component, GC, exception or
    # concurrency proposals. Disable them, including the features implicated in
    # upstream's October 2026 GC/exception advisories for the available PyPI build.
    config.wasm_gc = False
    config.wasm_exceptions = False
    config.wasm_threads = False
    config.wasm_memory64 = False
    config.wasm_multi_memory = False
    engine = wasmtime.Engine(config)
    module = wasmtime.Module(engine, source)
    if module.imports:
        raise RuntimeError('The bundled meshoptimizer must have no host imports')
    return engine, module


def _simplify(indices, positions, attributes, weights, locks, target):
    import wasmtime
    engine, module = _runtime()
    with wasmtime.Store(engine) as store:
        store.set_limits(memory_size=512*1024*1024, instances=1, memories=1)
        store.set_fuel(1_000_000_000)
        instance = wasmtime.Instance(store, module, [])
        exports = instance.exports(store)
        exports['__wasm_call_ctors'](store)
        memory, allocate = exports['memory'], exports['sbrk']

        def reserve(data):
            pointer = allocate(store, len(data))
            if pointer < 0:
                raise ValueError('Mesh LOD exceeds the simplifier memory limit')
            memory.write(store, data, pointer)
            return pointer

        error = reserve(bytes(4))
        output = reserve(bytes(indices.nbytes))
        pos = reserve(positions.tobytes())
        attr = reserve(attributes.tobytes())
        factor = reserve(weights.tobytes())
        source = reserve(indices.tobytes())
        lock = reserve(locks.tobytes())
        # LockBorder | RegularizeLight: retain joins and favour stable triangles
        # without spending the entire error budget on strong regularization.
        count = exports['meshopt_simplifyWithAttributes'](store, output, source, indices.size,
            pos, len(positions), positions.shape[1]*4, attr, attributes.shape[1]*4,
            factor, len(weights), lock, target, .01, 1 | 64, error)
        result = np.frombuffer(memory.read(store, output, output+count*4), '<u4').copy()
        deviation, = struct.unpack('<f', memory.read(store, error, error+4))
    if count < 3 or count % 3 or count > indices.size or np.any(result >= len(positions)) or not math.isfinite(deviation):
        raise ValueError('Meshoptimizer returned an invalid triangle buffer')
    return result.reshape(-1, 3), deviation


def simplify_section(section, ratio):
    """Return a new section; topology restrictions may retain more than the budget."""
    if not math.isfinite(ratio) or not 0 < ratio <= 1:
        raise ValueError('Invalid LOD simplification ratio')
    positions = np.ascontiguousarray(section['positions'], dtype='<f4')
    triangles = np.ascontiguousarray(section['triangles'], dtype='<u4').reshape(-1, 3)
    count = len(positions)
    if positions.shape != (count, 3) or not count or np.any(triangles >= count) or not np.isfinite(positions).all():
        raise ValueError('Invalid LOD geometry')
    target = max(4, int(len(triangles)*ratio))*3
    if target >= triangles.size:
        return section, {'engine':'meshoptimizer', 'error':0, 'triangles':len(triangles)}
    values = [section['normal'], section['uv'].reshape(count, -1)]
    if section.get('color') is not None:
        values.append(section['color'])
    # Never collapse an edge across different bone support. Attribute weights
    # then account for the blend between those bones within each supported region.
    bone_weights = np.asarray(section['weight'])
    bones = np.where(bone_weights > 1e-6, section['global_idx'], 65535)
    order = np.argsort(bones, axis=1, kind='stable')
    bones = np.take_along_axis(bones, order, axis=1)
    values.append(np.take_along_axis(bone_weights, order, axis=1))
    attributes = np.ascontiguousarray(np.concatenate(values, axis=1), dtype='<f4')
    if attributes.shape[1] > 32 or not np.isfinite(attributes).all():
        raise ValueError('Unsupported LOD vertex attributes')
    edges = np.concatenate((triangles[:, :2], triangles[:, 1:], triangles[:, ::2]), axis=0)
    seams = np.any(bones[edges[:, 0]] != bones[edges[:, 1]], axis=1)
    locks = np.zeros(count, dtype='u1')
    locks[edges[seams].reshape(-1)] = 1
    factors = np.ones(attributes.shape[1], dtype='<f4')
    factors[:3] = .5
    indices, error = _simplify(triangles, positions, attributes, factors, locks, target)
    used, remap = np.unique(indices, return_inverse=True)
    result = dict(section, triangles=remap.reshape(-1, 3).astype('<u4'))
    for field in _VERTEX_FIELDS:
        data = section.get(field)
        if data is not None:
            if len(data) != count:
                raise ValueError('LOD vertex attributes have different lengths')
            result[field] = np.asarray(data)[used].copy()
    return result, {'engine':'meshoptimizer', 'error':error, 'triangles':len(indices)}
