"""Model Studio discovery and exact glTF -> cooked material-slot identities.

Names in a decoded glTF are slot labels, not necessarily material asset names.
Resolve through the cooked mesh's import table before reading a material or
offering an export edit. Ambiguous labels remain viewable but cannot be hidden.
"""
import os
import re
import struct
import tempfile
from pathlib import Path
from types import SimpleNamespace

from atelier import config, jobs

MESH_SKIP = re.compile(r"skeleton|physics|collision|shell|_lobby|lobby_|_vfx|vfxmesh|_lod", re.I)
_NON_PREVIEW_MESH = re.compile(r"(?:^|_)(?:pa|1p|fpp|fpphands)(?:_|$)", re.I)
_PROP_PATH = re.compile(r"(?:^|/)(?:emote|mvp|bullet\w*|projectile\w*|turret\w*|effects?|vfx|summons?|minions?|pets?|demon)(?:/|$)", re.I)
# Capwolf stores its full human transformation mesh beside its shield in Weapons.
# This is a selectable body form, not equipment to attach over the current body.
_BODY_FORM_PATH = re.compile(r"/weapons/caption/meshes/", re.I)
# These ability/body-part rigs live under Weapons but are not held equipment.
# Keep them selectable; attaching one automatically can dwarf the body and camera.
_OPTIONAL_WEAPON = re.compile(r"(?:^|_)(?:DevouringSymbiote(?:_Hand)?|SpikedTentacles|Head|Plane\d*)(?:_|$)", re.I)


def skin_meshes(skin_id):
    from atelier.paths import skin_entries
    if not re.fullmatch(r"\d{7}", skin_id or ""):
        return []
    result, seen = [], set()
    for path, _ in skin_entries(skin_id):
        name = os.path.basename(path)
        if not name.lower().startswith(("sk_", "sm_")) or not name.lower().endswith(".uasset"):
            continue
        name = name[:-7]
        if MESH_SKIP.search(name) or _NON_PREVIEW_MESH.search(name) or '/fpphands/' in path.lower():
            continue
        weapon = "/weapons/" in path.lower() and not _BODY_FORM_PATH.search(path)
        if not weapon and '/slots/' in path.lower():
            continue
        if weapon and (_PROP_PATH.search(path) or re.search(r"(?:^|_)(?:1p|bullet\w*|projectile\w*)(?:_|$)", name, re.I)):
            continue
        gr = path[:-7]
        if gr.casefold() in seen:
            continue
        seen.add(gr.casefold())
        result.append({"name": name, "game_rel": gr, "kind": "weapon" if weapon else "body",
                       **({'auto_equip': not bool(_OPTIONAL_WEAPON.search(name))} if weapon else {})})
    return sorted(result, key=lambda r: (r["kind"] == "weapon", r["game_rel"].casefold()))


def cooked_slots(game_rel):
    from atelier.handlers.texture import ensure_work_base
    from atelier.handlers.mesh import skeletal_name_table, resolve_materials
    from atelier.handlers.meshsurvey import find_extras
    from atelier.handlers.meshmat import resolve_mesh_materials
    config.validate_game_rel(game_rel)
    base = ensure_work_base(game_rel, prefer_exact=True)
    if not base or not os.path.isfile(base + '.uasset'):
        raise ValueError('The original mesh is unavailable; section export cannot be mapped.')
    jobs.checkpoint()
    # Slot identity needs the material header and package imports. Constructing
    # an editable Mesh scans every geometry buffer and streamed LOD for no gain.
    _, names = skeletal_name_table(Path(base + '.uasset').read_bytes(), os.path.basename(base))
    extras = find_extras(Path(base + '.uexp').read_bytes())
    mesh = SimpleNamespace(materials=resolve_materials(extras['materials'], names))
    slots = resolve_mesh_materials(game_rel, mesh, base)
    return [{**s, "index": i} for i, s in enumerate(slots)]


def embedded_weapon_slots(body, weapons):
    """Complete body sections replaced by separately loaded held-weapon meshes.

    Require a weapon-labelled slot and every vertex in every use of that slot to
    be weighted to the held rig's own articulated weapon bones. A material shared
    with armour/skin is never sufficient evidence to suppress a section. This is
    presentation metadata for the portable Blender scene, not a project mod edit.
    """
    import numpy as np
    weapon_name=re.compile(r'weapon|sword|gun|blade|hammer|bow|staff|dagger|shield|pistol|spear|axe',re.I)
    names={bone['name'].casefold() for model in weapons for bone in model.bones
           if weapon_name.search(bone['name']) and not re.search(r'^root$|^pelvis$|^ik_|^weapon_[lr]$',bone['name'],re.I)}
    if not names:return set()
    lod=body.lods[0];indices,weights=body.skin_weights(lod)
    belongs=np.asarray([bone['name'].casefold() in names for bone in body.bones])
    decisions={}
    for section in lod['sections']:
        index=section['mat']
        if not weapon_name.search(body.materials[index]['slot_name']):continue
        lo=section['base_vertex'];hi=lo+section['num_verts']
        mapping=np.asarray(body.section_bonemap(section))
        influence=belongs[mapping[indices[lo:hi]]]
        total=weights[lo:hi].sum(axis=1);covered=(weights[lo:hi]*influence).sum(axis=1)
        duplicate=len(total)>0 and bool(np.all(total>.001) and np.all(covered/np.maximum(total,.001)>.999))
        decisions[index]=decisions.get(index,True) and duplicate
    return {index for index,duplicate in decisions.items() if duplicate}


def complete_mesh_source(game_rel):
    """Recover streamed LOD bulk data omitted by the legacy Windows extractor."""
    from atelier.handlers.texture import ensure_work_base, extract_via_retoc
    from atelier.handlers.meshsurvey import probe
    from atelier import asset_cache
    base = ensure_work_base(game_rel)
    if not base:
        raise ValueError('Original mesh is unavailable')
    report = probe(base, read_tails=False, include_layout=True)
    if report['status'] == 'error':
        raise ValueError(report['error'])
    if any(r['blob'] == 'missing' for r in report.get('_layout', [])):
        jobs.progress('Reading every original mesh LOD…')
        extracted = extract_via_retoc([game_rel]).get(game_rel)
        if extracted:
            base, pak, prefix = extracted
            asset_cache.record(game_rel, base, pak, prefix)
        report = probe(base, read_tails=False, include_layout=True)
    if report['status'] != 'error' and any(r['blob'] == 'missing' for r in report.get('_layout', [])):
        _recover_streamed_bulk(game_rel, base, report)
        report = probe(base, read_tails=False, include_layout=True)
    if report['status'] == 'error' or not report.get('_layout') or any(r['blob'] == 'missing' for r in report['_layout']):
        raise ValueError('Streamed mesh LODs are unavailable. Editing and export need the complete original mesh.')
    return base


def _recover_streamed_bulk(game_rel, base, report):
    """A patch can reference a BulkData chunk that lives in a base container.

    UAssetTool's legacy extraction can omit it, and retoc cannot reconstruct some
    Rivals patch packages. Read that package's exact BulkData chunk using Atelier's
    existing IoStore reader. Validate resource sizes and every LOD before publishing
    an independent cache file. The game containers are read-only.
    """
    from atelier.handlers import pak_thumb
    from atelier.handlers.mesh import find_data_resource_map
    from atelier.handlers.meshsurvey import probe
    from atelier.index import index_lookup, _index_utocs
    import io_lib
    hit = index_lookup().get(game_rel.lower() + '.uasset')
    if not hit:
        return
    entry = pak_thumb._get_toc(hit[1])
    if not entry:
        return
    toc, _ = entry
    main = toc._dir.get(game_rel.lower())
    if main is None:
        return
    package = toc.chunk_ids[main][:8]
    identity = package + b'\x00\x00\x00\x02'
    uasset = Path(base + '.uasset').read_bytes()
    resources = len([r for r in report['_layout'] if r.get('data_resource') is not None])
    lengths = set()
    for offset in range(len(uasset)-4):
        if struct.unpack_from('<I', uasset, offset)[0] != resources:
            continue
        end = offset + 4 + resources*44
        if end > len(uasset) or not resources:
            continue
        start, size = struct.unpack_from('<q', uasset, end-40)[0], struct.unpack_from('<q', uasset, end-24)[0]
        total = start + size
        if total > 0 and find_data_resource_map(uasset, total) == offset:
            lengths.add(total)
    if len(lengths) != 1:
        raise ValueError('Streamed LOD resource sizes could not be validated')
    expected = lengths.pop()
    for path in reversed(_index_utocs()):
        jobs.checkpoint()
        candidate = toc if os.path.normcase(path) == os.path.normcase(toc.path) else io_lib.parse_toc(path)
        try:
            chunk = candidate.chunk_ids.index(identity)
        except ValueError:
            continue
        if candidate.offlen[chunk][1] != expected:
            continue
        data = io_lib.read_chunk(candidate, path[:-5] + '.ucas', chunk)
        if len(data) != expected:
            continue
        with tempfile.TemporaryDirectory(prefix='atelier-mesh-bulk-') as scratch:
            import shutil
            target = os.path.join(scratch, os.path.basename(base))
            for ext in ('.uasset', '.uexp'):
                shutil.copy2(base + ext, target + ext)
            Path(target + '.ubulk').write_bytes(data)
            checked = probe(target, read_tails=True, include_layout=True)
            if checked['status'] == 'error' or any(r['blob'] == 'missing' for r in checked.get('_layout', [])):
                continue
            jobs.checkpoint()
            descriptor, temporary = tempfile.mkstemp(prefix='.mesh-bulk-', dir=os.path.dirname(base))
            os.close(descriptor)
            try:
                Path(temporary).write_bytes(data)
                os.replace(temporary, base + '.ubulk')
            finally:
                Path(temporary).unlink(missing_ok=True)
        return


def preview_bindings(game_rel, requested):
    """Map each glTF material independently; array order is never an identity guess."""
    if not isinstance(requested, list) or len(requested) > 256:
        raise ValueError('Invalid model material list')
    from atelier import import_server
    slots = import_server.mesh_slots(game_rel) or cooked_slots(game_rel)
    out = []
    for item in requested:
        if not isinstance(item, dict) or not isinstance(item.get('key'), str) or not isinstance(item.get('name'), str):
            raise ValueError('Invalid model material identity')
        name = item['name']
        exact = [s for s in slots if s['slot'].casefold() == name.casefold()]
        candidates = exact or [s for s in slots if s.get('mi') and os.path.basename(s['mi']).casefold() == name.casefold()]
        # Repeated labels can only use the glTF index if the complete ordered list
        # matches every cooked slot. Otherwise an eye toggle would edit arbitrary geometry.
        if len(candidates) > 1 and len(requested) == len(slots) and all(
            r.get('material_index') == i and r.get('name', '').casefold() == s['slot'].casefold()
            for i, (r, s) in enumerate(zip(requested, slots))
        ):
            candidates = [slots[item['material_index']]]
        if len(candidates) > 1 and all(s.get('mi') for s in candidates) and len({s['mi'].casefold() for s in candidates}) == 1:
            # SharpGLTF merges material definitions shared by multiple cooked
            # slots. The material is unambiguous, but a single section is not.
            # Keep its textures/parameters without guessing a visibility target.
            out.append({'key': item['key'], 'mesh_game_rel': game_rel, 'slot_name': name,
                        'game_rel': candidates[0]['mi'], 'mapping_via': candidates[0]['via'],
                        'shared_slots': [{'slot_index': s['index'], 'slot_name': s['slot']} for s in candidates],
                        'gameplay_tags': sorted({tag for s in candidates for tag in s.get('gameplay_tags', [])}),
                        'visibility_warning': 'These parts share one preview material. Separate part visibility is unavailable.'})
            continue
        if len(candidates) != 1:
            out.append({"key": item['key'], "slot_name": name, "mapping_error": 'This section could not be matched uniquely to a cooked mesh slot.'})
            continue
        slot = candidates[0]
        out.append({"key": item['key'], "mesh_game_rel": game_rel, "slot_index": slot['index'],
                    "slot_name": slot['slot'], "game_rel": slot['mi'], "mapping_via": slot['via'],
                    'gameplay_tags': list(slot.get('gameplay_tags', []))})
    return out


def material_bindings(skin_id, meshes):
    """Exact own-skin slots, or unambiguous recolour counterparts on the same rig."""
    from atelier.paths import skin_entries
    from atelier.handlers.meshvisibility import hidden_sections
    if not isinstance(meshes, list) or len(meshes) > 32:
        raise ValueError('Invalid model list')
    for record in meshes:
        if not isinstance(record, dict):
            raise ValueError('Invalid model identity')
        config.validate_game_rel(record.get('game_rel', ''))
        requested = record.get('slots', [])
        if not isinstance(requested, list) or len(requested) > 256 or any(
            not isinstance(item, dict) or not isinstance(item.get('key'), str) or not isinstance(item.get('name'), str)
            for item in requested
        ):
            raise ValueError('Invalid model material identity')
    from atelier.handlers.texture import prefetch_exact
    try:
        from atelier import import_server
        if not import_server.available():
            prefetch_exact([record['game_rel'] for record in meshes])
    except jobs.Cancelled:
        raise
    except Exception:
        pass  # Per-mesh extraction below retains the compatibility fallback.
    candidates = {}
    canon = lambda n: re.sub(r'\d{6,}', '#', n.casefold())
    for path, _ in skin_entries(skin_id):
        name = os.path.basename(path)
        if name.lower().startswith('mi_') and name.lower().endswith('.uasset'):
            candidates.setdefault(canon(name[:-7]), []).append(path[:-7])
    for record in meshes:
        gr = record.get('game_rel', '')
        config.validate_game_rel(gr)
        requested = record.get('slots', [])
        try:
            bindings = preview_bindings(gr, requested)
        except jobs.Cancelled:
            raise
        except Exception as exc:
            bindings = []
            for item in requested:
                matches = candidates.get(canon(item['name']), [])
                bindings.append({'key': item['key'], 'slot_name': item['name'], 'mesh_game_rel': gr,
                                 'game_rel': matches[0] if len(matches) == 1 else None,
                                 'mapping_error': 'Cooked section mapping unavailable: ' + str(exc)})
        saved = hidden_sections(gr)
        for binding in bindings:
            material = binding.get('game_rel')
            own_skin = re.search(r'Characters/\d{4}/(\d{7})/', gr, re.I)
            if material and own_skin and own_skin[1] != skin_id:
                matches = candidates.get(canon(os.path.basename(material)), [])
                if len(matches) == 1:
                    binding['game_rel'] = matches[0]
                elif matches:
                    binding['material_warning'] = 'This recolour has ambiguous material variants; the mesh material was kept.'
            sections = binding.get('shared_slots') or [binding]
            binding['hidden'] = all(any(s.get('slot_index') == section.get('slot_index') and
                                       s.get('slot_name') == section['slot_name'] for s in saved) for section in sections)
            yield binding
