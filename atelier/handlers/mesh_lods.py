"""Keep authored material atlases when a sculpt deforms remapped game LODs.

Some lower LODs merge the face/body into a baked material and renumber the other
sections through LODMaterialMap. Re-decimating the top LOD's named materials into
those raw indices assigns unrelated geometry and bone palettes. Transfer a
verified sculpt's deformation to the original lower surface instead, retaining
its UV atlas, material map, topology, colours and skinning.
"""
import hashlib
import json
from pathlib import Path
import tempfile

import numpy as np

from atelier import config, jobs


def material_maps(document, asset_name):
    exports = [e for e in (document or {}).get('Exports', []) if e.get('ObjectName') == asset_name]
    if len(exports) != 1:
        raise ValueError('Could not identify the mesh for its LOD material mapping')
    properties = exports[0].get('Data') or []
    if not isinstance(properties, list):
        raise ValueError('Could not read the mesh LOD material properties')
    info = next((p.get('Value') or [] for p in properties if p.get('Name') == 'LODInfo'), [])
    maps = []
    for lod in info:
        array = next((p.get('Value') or [] for p in lod.get('Value', []) if p.get('Name') == 'LODMaterialMap'), [])
        values = [p.get('Value') for p in array]
        if any(type(value) is not int or value < -1 for value in values):
            raise ValueError('The mesh has an invalid LOD material map')
        maps.append(values)
    return maps


def load_material_maps(base):
    """Cache only the maps, keyed by the actual package and mapping file version."""
    from atelier.tools import uat
    from atelier.storage import atomic_json
    paths = [Path(str(base)+extension) for extension in ('.uasset', '.uexp')]
    paths.append(Path(config.USMAP))
    stamp = [(str(path.resolve()), path.stat().st_size, path.stat().st_mtime_ns) for path in paths if path.is_file()]
    key = hashlib.sha256(json.dumps(stamp).encode()).hexdigest()
    cache = Path(config._CACHE)/'lod-materials'/(key+'.json')
    if cache.is_file():
        return json.loads(cache.read_text(encoding='utf-8'))
    with tempfile.TemporaryDirectory(prefix='atelier-lod-materials-') as temporary:
        result = uat(['to_json', str(Path(str(base)+'.uasset').resolve()), config.USMAP, temporary])
        document = Path(temporary)/(Path(base).name+'.json')
        if result.returncode or not document.is_file():
            raise ValueError('Could not read the mesh LOD material mapping')
        maps = material_maps(json.loads(document.read_text(encoding='utf-8-sig')), Path(base).name)
    cache.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(str(cache), maps)
    return maps


def material_index(section, mapping):
    index = section['mat']
    return mapping[index] if index < len(mapping) and mapping[index] >= 0 else index


def _triangles(mesh, lod, section):
    return np.frombuffer(mesh._blob(lod), '<u4' if lod['idx_stride'] == 4 else '<u2',
        section['num_tris']*3, lod['idx_off']+section['base_index']*lod['idx_stride']).reshape(-1, 3).astype('i8')


def _ordered(triangles):
    # Cyclic corner rotations preserve winding; reversing a face does not.
    starts = np.argmin(triangles, axis=1)
    canonical = np.take_along_axis(triangles, (starts[:, None]+np.arange(3)) % 3, axis=1)
    return canonical[np.lexsort(canonical.T[::-1])]


class Sculpt:
    def __init__(self, original, sections):
        lod = original.lods[0]
        self.original = original
        self.rest = original.positions(lod).astype('f8')
        self.triangles = {}
        totals = np.zeros_like(self.rest)
        counts = np.zeros(len(self.rest), 'i8')
        message = ('This mesh has baked materials in its lower detail levels. Keep the original '
                   'topology and Atelier tracking attributes when sculpting it. Topology-changing '
                   'replacements for its baked lower detail materials are not supported yet.')
        if len(sections) != len(lod['sections']):
            raise ValueError(message)
        for before, after in zip(lod['sections'], sections):
            ids = np.asarray(after.get('morph_ids', []))
            source_lods = np.asarray(after.get('morph_lods', []))
            positions = np.asarray(after['positions'], dtype='f8')
            if (len(ids) != len(positions) or len(source_lods) != len(positions)
                    or not np.isfinite(ids).all() or not np.isfinite(positions).all()
                    or np.any(abs(ids-np.rint(ids)) > 1e-6) or np.any(ids < 0) or np.any(ids >= len(self.rest))
                    or np.any(source_lods != lod.get('layout', {}).get('source_index', 0))):
                raise ValueError(message)
            ids = ids.astype('i8')
            rest = np.asarray(after.get('morph_rest', []))
            if rest.shape != positions.shape or np.any(np.linalg.norm(rest-self.rest[ids], axis=1) > 1e-3):
                raise ValueError(message)
            triangles = _triangles(original, lod, before)
            edited = ids[np.asarray(after['triangles'], dtype='i8').reshape(-1, 3)]
            if triangles.shape != edited.shape or not np.array_equal(_ordered(triangles), _ordered(edited)):
                raise ValueError(message)
            np.add.at(totals, ids, positions)
            np.add.at(counts, ids, 1)
            self.triangles.setdefault(before['mat'], []).append(triangles)
        self.used = counts > 0
        self.edited = self.rest.copy()
        self.edited[self.used] = totals[self.used]/counts[self.used, None]
        for section in sections:
            ids = np.asarray(section['morph_ids'], dtype='i8')
            if np.any(np.linalg.norm(self.edited[ids]-section['positions'], axis=1) > 1e-3):
                raise ValueError(message)
        self.triangles = {index: np.concatenate(parts) for index, parts in self.triangles.items()}
        delta = self.edited[self.used]-self.rest[self.used]
        self.translation = delta.mean(0) if len(delta) and np.ptp(delta, axis=0).max() <= 1e-4 else None

    def sections(self, lod_index, mapping):
        from atelier.handlers.mesh import material_slot_names, original_sections
        lod = self.original.lods[lod_index]
        resolved = [material_index(section, mapping) for section in lod['sections']]
        if any(index >= len(self.original.materials) for index in resolved):
            raise ValueError('A lower detail material map references a missing material')
        top, targets = set(self.triangles), set(resolved)
        merged, consumed = targets-top, top-targets
        if len(merged) > 1 or merged and not consumed:
            raise ValueError('This lower detail material merge is ambiguous')
        groups = {index: self.triangles[index] for index in targets & top}
        if merged:
            groups[next(iter(merged))] = np.concatenate([self.triangles[index] for index in sorted(consumed)])
        source = original_sections(self.original, lod_index, set(material_slot_names(self.original.materials)))
        result = []
        for index, material in enumerate(resolved):
            jobs.checkpoint()
            section = source[index]
            if self.translation is not None:
                section['positions'] = (section['positions']+self.translation).astype('f4')
            else:
                self._deform(section, groups[material])
            result.append(section)
        return result

    def _deform(self, section, triangles):
        from scipy.spatial import cKDTree
        from atelier.handlers.morph import closest_triangles
        before, after = self.rest[triangles], self.edited[triangles]
        edge = np.cross(before[:, 1]-before[:, 0], before[:, 2]-before[:, 0])
        valid = np.linalg.norm(edge, axis=1) > 1e-12
        before, after = before[valid], after[valid]
        if not len(before):
            raise ValueError('The sculpt has no usable reference surface for a lower detail section')
        def frames(geometry):
            first, second = geometry[:, 1]-geometry[:, 0], geometry[:, 2]-geometry[:, 0]
            normal = np.cross(first, second)
            size = np.linalg.norm(normal, axis=1)
            if np.any(size <= 1e-12):
                raise ValueError('The sculpt collapses a surface needed by a baked lower detail material')
            return np.stack((first, second, normal/np.sqrt(size)[:, None]), axis=-1)
        jacobian = frames(after) @ np.linalg.inv(frames(before))
        tree = cKDTree(before.mean(axis=1))
        positions = section['positions'].astype('f8')
        normals, tangents = section['normal'].copy(), section['tangent'].copy()
        for begin in range(0, len(positions), 2048):
            jobs.checkpoint()
            rows = np.arange(begin, min(begin+2048, len(positions)))
            count = min(16, len(before))
            candidates = tree.query(positions[rows], k=count)[1].reshape(len(rows), count)
            bary, distance = closest_triangles(positions[rows, None, :], before[candidates])
            best = np.argmin(distance, axis=1)
            chosen = candidates[np.arange(len(rows)), best]
            factors = bary[np.arange(len(rows)), best]
            old_surface = np.einsum('nij,ni->nj', before[chosen], factors)
            new_surface = np.einsum('nij,ni->nj', after[chosen], factors)
            transform = jacobian[chosen]
            positions[rows] = new_surface+np.einsum('nij,nj->ni', transform, positions[rows]-old_surface)
            normal = np.einsum('nji,nj->ni', np.linalg.inv(transform), normals[rows])
            normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-20)
            tangent = np.einsum('nij,nj->ni', transform, tangents[rows])
            tangent -= normal*np.sum(normal*tangent, axis=1, keepdims=True)
            tangent /= np.maximum(np.linalg.norm(tangent, axis=1, keepdims=True), 1e-20)
            normals[rows], tangents[rows] = normal, tangent
        section.update(positions=positions.astype('f4'), normal=normals, tangent=tangents)
