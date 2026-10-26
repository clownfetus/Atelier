"""Reversible section hiding by degenerating indices in every cooked render LOD.

Use the section's own first vertex for all three indices of each hidden triangle.
This removes its rasterized area while retaining section/triangle/vertex counts,
bone maps, morph data, bounds and package sizes. Lowering NumTriangles breaks the
game's GPU skin-cache/ray-tracing assumptions; an opacity-zero donor depends on
shader permutations and parent compatibility. Index-only edits avoid both risks.

Only copies in the export stage are changed. Each export starts from the original
mesh or the current Blender rebuild, then applies project options. Unhiding simply
removes an option, so the original index data is recovered on the next export.
All present sections of all LODs must be parsed and checked; unsupported/missing
geometry fails staging rather than silently exporting only the preview LOD.
Actual rendering in the game still needs an exported-mod test on its current build.
"""
import json
import os
from pathlib import Path
import tempfile

from atelier import config, jobs, project_meta
from atelier.storage import atomic_json, publish_files

OPTION = 'hidden_sections'


def hidden_sections(game_rel, root=None):
    raw = project_meta.get_asset_opts(root or config.get_import_root(), game_rel).get(OPTION) or []
    if not isinstance(raw, list):
        raise ValueError('Invalid saved mesh visibility')
    return raw


def set_hidden(game_rel, slot_index, slot_name, hidden):
    from atelier.handlers.meshstudio import cooked_slots, complete_mesh_source
    if type(slot_index) is not int or type(hidden) is not bool or not isinstance(slot_name, str):
        raise ValueError('Choose a valid mesh section and visibility')
    if hidden:
        complete_mesh_source(game_rel)
    slots = cooked_slots(game_rel)
    if not 0 <= slot_index < len(slots) or slots[slot_index]['slot'] != slot_name:
        raise ValueError('The model slots changed. Reopen the model before hiding this section.')
    slot = slots[slot_index]
    root = config.get_import_root()
    existing = hidden_sections(game_rel, root)
    saved = [s for s in existing if s.get('slot_index') != slot_index]
    if hidden:
        saved.append({'slot_index': slot_index, 'slot_name': slot_name, 'material': slot.get('mi')})
    saved.sort(key=lambda s: s['slot_index'])
    marker = Path(config.project_base(game_rel) + '.mesh.json')
    created = False
    # The ordinary mesh sidecar makes this edit participate in the Mod tray,
    # project archives, deletion/undo and existing mesh export selection.
    if saved and not marker.exists():
        atomic_json(str(marker), {'version': 1, 'game_rel': game_rel, 'state': 'original', 'visibility_only': True})
        created = True
    try:
        project_meta.set_asset_opts(root, game_rel, {OPTION: saved or None})
    except BaseException:
        if created:
            marker.unlink(missing_ok=True)
        raise
    if not saved and marker.is_file() and not Path(config.project_base(game_rel) + '.blend').exists():
        try: record = json.loads(marker.read_text(encoding='utf-8'))
        except (OSError,ValueError): record={}
        if record.get('visibility_only') and record.get('state') == 'original':
            marker.unlink()
    return {'ok': True, 'game_rel': game_rel, 'hidden_sections': saved}


def apply_to_staged(game_rel, uasset, sections=None):
    """Patch and read back the staged copy; never mutate extracted or project meshes."""
    from atelier.handlers.mesh import Mesh
    sections = hidden_sections(game_rel) if sections is None else sections
    if not sections:
        return []
    path = Path(uasset).resolve()
    base = str(path.with_suffix(''))
    # A caller must supply an export-stage copy, never the extracted input.
    from atelier.handlers.texture import find_extracted
    original = find_extracted(game_rel)
    if original and Path(original).resolve() == Path(base):
        raise ValueError('Mesh visibility requires an export-stage copy')
    if Path(config.project_base(game_rel)).resolve() == Path(base):
        raise ValueError('Mesh visibility cannot overwrite a project mesh')
    mesh = Mesh(base)
    from atelier.handlers import mesh_lods
    maps = mesh_lods.load_material_maps(original or base) if len(mesh.lods) > 1 else []
    if not mesh._layout or any(r.get('blob') == 'missing' for r in mesh._layout) or len(mesh.lods) != len(mesh._layout):
        raise ValueError('Cannot verify every cooked LOD for this mesh; visibility export was stopped.')
    indices = set()
    for section in sections:
        index = section.get('slot_index')
        if type(index) is not int or not 0 <= index < len(mesh.materials) or mesh.materials[index]['slot_name'] != section.get('slot_name'):
            raise ValueError('Saved hidden sections do not match the current cooked mesh slots. Reopen and restore them.')
        indices.add(index)
    applied = []
    found = set()
    for i, lod in enumerate(mesh.lods):
        jobs.checkpoint()
        count = 0
        source_index = lod.get('layout', {}).get('source_index', i)
        mapping = maps[source_index] if source_index < len(maps) else []
        for section in lod['sections']:
            material = mesh_lods.material_index(section, mapping)
            if material in indices:
                mesh.degenerate_triangles(lod, section, 0)
                found.add(material); count += 1
        applied.append({'lod': i, 'sections': count})
    if found != indices:
        raise ValueError('A hidden slot has no cooked render section; visibility export was stopped.')
    import struct
    with tempfile.TemporaryDirectory(prefix='atelier-hidden-sections-') as scratch:
        mesh.save(scratch,path.stem)
        verified = Mesh(os.path.join(scratch,path.stem))
        for i, lod in enumerate(verified.lods):
            fmt = '<I' if lod['idx_stride'] == 4 else '<H'
            blob = verified._blob(lod)
            source_index = lod.get('layout', {}).get('source_index', i)
            mapping = maps[source_index] if source_index < len(maps) else []
            for section in lod['sections']:
                if mesh_lods.material_index(section, mapping) not in indices:
                    continue
                start = lod['idx_off'] + section['base_index'] * lod['idx_stride']
                if any(struct.unpack_from(fmt, blob, start + i * lod['idx_stride'])[0] != section['base_vertex']
                       for i in range(section['num_tris'] * 3)):
                    raise ValueError('Staged hidden-section index verification failed')
        jobs.checkpoint()
        publish_files([str(p) for p in Path(scratch).iterdir() if p.is_file()],str(path.parent))
    return applied
