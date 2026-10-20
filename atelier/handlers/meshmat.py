"""Resolve a SkeletalMesh's material slots down to the textures they sample, and stage those
textures into the active project folder.

This is what lets the Blender round-trip carry a character's real surfaces: the mesh names its
material slots, each slot is a MaterialInstance, and each MI's TextureParameterValues point at
the T_* assets. The PNG written here is the SAME file the texture pipeline already ships
(texture.stage_inject) and the 3D viewport already watches -- so saving an image in Blender is
an edit everywhere, with no extra bookkeeping and no new injection mechanism.

Two ways to get from a slot to its MI, in order of trust:
  1. the mesh's IMPORT TABLE -- FSkeletalMaterial.MaterialInterface is a real FPackageIndex
     (mesh.Mesh.materials[i]["pkg_idx"]), so `uat to_json` on the mesh plus the same import walk
     material.py uses for texture params gives the exact answer. Costs one big cached JSON.
  2. by NAME through the pak index -- a fallback when the import cannot be resolved.
     Model Studio now uses this same resolver; a coincidentally valid name must never
     override the cooked mesh's actual material reference.
"""
import concurrent.futures
from contextvars import copy_context
import hashlib
import json
import os
import shutil
import sys
from atelier import jobs

from atelier.config import CACHE_3DVIEW, USMAP, get_import_root, project_base, project_base_legacy
from atelier.tools import uat

# Texture parameter name -> the PBR role the Blender wiring understands. Matched case-insensitively
# on the parameter name with non-alphanumerics stripped, so "Base Color"/"BaseColorMap" both land.
# Unmatched game-effect inputs remain named editable group inputs and are reported
# separately from mapped surface inputs. Dye masks have an explicit region shader.
_ROLE_ALIASES = {
    "basecolor": "basecolor", "base": "basecolor", "diffuse": "basecolor", "albedo": "basecolor",
    "basecolormap": "basecolor", "basecolortexture": "basecolor", "diffusemap": "basecolor",
    "normal": "normal", "normalmap": "normal", "normals": "normal", "normaltexture": "normal",
    "orm": "orm", "ormmap": "orm", "ormtexture": "orm", "maskmap": "orm", "mrao": "orm", "arm": "orm",
    "emissive": "emissive", "emissivemap": "emissive", "emission": "emissive",
    "emissivetexture": "emissive", "emissivecolor": "emissive",
    "opacity": "opacity", "opacitymap": "opacity", "opacitymask": "opacity",
    "opacitytexture": "opacity", "alphamap": "opacity", "alphamask": "opacity",
    "shadowcoloruv1": "ao", "ambientocclusion": "ao", "aomap": "ao",
    "speculartexture": "specular", "specularmap": "specular",
    "anisotropybrightness": "anisotropy", "specularshift": "anisotropy_rotation",
    "dyeingtexture": "dye", "sclerabasecolor": "sclera", "irisbasecolor": "iris",
    "irisbaseao": "iris_ao", "irisheight": "iris_height", "highlightmask": "highlight",
}


def _canon(name):
    return "".join(c for c in (name or "").lower() if c.isalnum())


def texture_role(param_name):
    """Surface role, or None for an auxiliary game-effect group input."""
    return _ROLE_ALIASES.get(_canon(param_name))


def _index_candidates(asset_name):
    """game_rels in the paks whose basename matches asset_name (no extension)."""
    from atelier.index import by_basename
    return by_basename(asset_name)


def _best_candidate(candidates, mesh_game_rel):
    """Prefer the candidate living closest to the mesh (same skin folder wins outright)."""
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    mesh_parts = mesh_game_rel.lower().split("/")

    def shared(gr):
        parts = gr.lower().split("/")
        n = 0
        for a, b in zip(mesh_parts, parts):
            if a != b:
                break
            n += 1
        return n
    return sorted(candidates, key=lambda gr: (-shared(gr), len(gr)))[0]


def _mesh_json(mesh_game_rel, work_base):
    """`uat to_json` the mesh into CACHE_3DVIEW (cached). Returns the parsed dict, or None.

    The SkeletalMesh export is large and UAssetTool keeps its render data as one opaque blob, so
    this JSON is big and slow -- it exists only as the exact fallback when name resolution is
    ambiguous, and is cached so it happens at most once per mesh."""
    jp = project_base(mesh_game_rel, CACHE_3DVIEW) + ".json"
    if not os.path.exists(jp) or os.path.getmtime(jp) < os.path.getmtime(work_base + '.uasset'):
        sub = os.path.dirname(jp)
        os.makedirs(sub, exist_ok=True)
        uat(["to_json", os.path.abspath(work_base + ".uasset"), USMAP, os.path.abspath(sub)])
    if not os.path.exists(jp):
        return None
    try:
        return json.load(open(jp, encoding="utf-8-sig"))
    except Exception as e:
        print(f"[meshmat] mesh JSON unreadable for {mesh_game_rel}: {e}", file=sys.stderr, flush=True)
        return None


def _mi_from_imports(d, pkg_idx):
    """FPackageIndex -> MI game_rel via the import table (same walk as material._mat_textures)."""
    imports = (d or {}).get("Imports", [])
    if not isinstance(pkg_idx, int) or pkg_idx >= 0:
        return None
    ii = -pkg_idx - 1
    if not (0 <= ii < len(imports)):
        return None
    outer = imports[ii].get("OuterIndex")
    pkg = None
    if isinstance(outer, int) and outer < 0 and (-outer - 1) < len(imports):
        pkg = imports[-outer - 1].get("ObjectName")
    if isinstance(pkg, str) and pkg.startswith("/Game/Marvel/"):
        return pkg[len("/Game/Marvel/"):]
    return None


def resolve_mesh_materials(mesh_game_rel, mesh, work_base=None):
    """[{slot, mi, via}] for every material slot on the mesh; mi is None when unresolvable.

    The IMPORT TABLE is the primary source and the name lookup only a fallback, because on the
    reference mesh the names are wrong in three different ways at once: slot
    'MI_1029304_10290_Body_01' actually points at the asset MI_1029304_10290_Body, slot
    'MI_1029304_10290_Eye02' at MI_1029304_10290_Eyes_02, and slot 'MI_1029001_Magik_Weapon'
    at MI_1029304_10290_Weapon -- while a name search for the body slot finds a real asset of
    exactly that name sitting in a Lobby/ subfolder, i.e. the wrong material, silently. Names
    are only trusted where the import walk yields nothing."""
    d = _mesh_json(mesh_game_rel, work_base) if work_base else None
    out = []
    for m in mesh.materials:
        slot = m.get("slot_name") or ""
        mi = _mi_from_imports(d, m.get("pkg_idx")) if d else None
        via = "imports" if mi else None
        if mi and not _index_candidates(os.path.basename(mi)):
            mi, via = None, None       # import names a package the paks don't have — don't trust it
        if mi is None and slot:
            mi = _best_candidate(_index_candidates(slot), mesh_game_rel)
            via = "name" if mi else None
        out.append({"slot": slot, "mi": mi, "via": via, "pkg_idx": m.get("pkg_idx")})
    return out


def resolve_mesh_textures(slots):
    """Attach each slot's MI texture params: [{param, role, game_rel}] under key 'maps'."""
    cache = {}
    for rec in slots:
        rec["maps"] = []
        mi = rec.get("mi")
        if not mi:
            continue
        if mi not in cache:
            try:
                jobs.progress('Reading model material · '+os.path.basename(mi))
                cache[mi] = material_snapshot(mi)
            except jobs.Cancelled:
                raise
            except Exception as e:
                print(f"[meshmat] material read failed for {mi}: {e}", file=sys.stderr, flush=True)
                cache[mi] = {'material_error': str(e)}
        rec['parameters'] = cache[mi]
        for param, tex_gr in sorted(cache[mi].get('textures', {}).items()):
            rec["maps"].append({"param": param, "role": texture_role(param), "game_rel": tex_gr,
                                'uv': 1 if '(uv1)' in param.casefold() or _canon(param)=='anisotropybrightness' else 0})
    return slots


def material_snapshot(game_rel):
    """Port a material's effective parameters, with child values overriding parents.

    Inspired by RivalsPorting's typed material export and recursive parameter
    collection. This is separate from the material editor's own-property reads:
    inherited defaults must not accidentally become edits to a child instance.
    """
    from atelier.handlers.material import mat_json, _mat_params, _mat_textures, _mat_surface, _gn, _ex_props
    colors, scalars, textures, chain, custom_paths, owners = {}, {}, {}, [], {}, {}
    current = game_rel
    surface = None
    while current:
        if current.casefold() in {p.casefold() for p in chain} or len(chain) >= 64:
            raise ValueError('Recursive material parent chain')
        chain.append(current)
        with open(mat_json(current, out_dir=CACHE_3DVIEW,prefer_exact=True), encoding='utf-8-sig') as stream:
            document=json.load(stream)
        c, s = _mat_params(document)
        for row in c: colors.setdefault(row['name'], row)
        for row in s: scalars.setdefault(row['name'], row)
        for name,path in _mat_textures(document).items():
            if name not in textures:textures[name]=path;owners[name]=current
        from atelier.handlers import custom_texture
        for name in custom_texture.assignments(current):
            if owners.get(name)==current:custom_paths.setdefault(name,custom_texture.image_path(current,name))
        if surface is None: surface=_mat_surface(document)
        parent = _gn(_ex_props(document['Exports'][0]), 'Parent') or {}
        index=parent.get('Value'); imports=document.get('Imports', [])
        if not isinstance(index,int) or not -len(imports)<=index<0: break
        reference=imports[-index-1]
        surface['parent']=reference.get('ObjectName','')
        if reference.get('ClassName')!='MaterialInstanceConstant': break
        current=_mi_from_imports(document,index)
    if 'eye' in (surface or {}).get('parent','').casefold() and 'glass' not in surface['parent'].casefold() and 'highlight' not in surface['parent'].casefold():
        # The game's eye master supplies these defaults without MI texture overrides.
        # RivalsPorting exposes the same four default inputs for its eye shader.
        for param,name in [('ScleraBaseColor','T_EyeSclera_D'),('IrisBaseColor','T_Common_Eyes_03_D'),
                           ('IrisHeight','T_Iris001_01_H'),('IrisBaseAO','T_Iris001_01_AO')]:
            if param not in textures:
                candidate=_best_candidate(_index_candidates(name),game_rel)
                if candidate: textures[param]=candidate
    return {'colors': list(colors.values()), 'scalars': list(scalars.values()), 'textures': textures,
            'surface': surface or {}, 'parent_chain': chain, 'custom_paths':custom_paths}


def _degenerate(png, limit=16):
    """True for the tiny placeholder a failed mip recovery leaves behind (the documented 4x4 tail).
    Real character textures are never this small; a decode that lands here has not found the data."""
    try:
        from PIL import Image
        w, h = Image.open(png).size
        return w < limit or h < limit
    except Exception:
        return False


def _is_black_placeholder(png):
    """True for a uniformly black texture -- MR fills unused MI slots with shared dummies like
    T_Common_LinearBlack / T_Common_Black. That means 'this master has no such map', NOT 'this
    channel is zero': wiring one into Roughness pins it to 0 and turns the surface into a mirror."""
    try:
        from PIL import Image
        return all(lo == hi == 0 for lo, hi in Image.open(png).convert("RGB").getextrema())
    except Exception:
        return False


# Roles where a black placeholder does real damage: 0 roughness is a mirror, and a black normal
# map decodes to a garbage basis. Emissive/BaseColor black just means "off"/"black", which is
# both harmless and probably what the material intends, so those stay wired.
_HARMFUL_IF_BLACK = ("orm", "normal")


def _sha1(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_textures_to_project(tex_game_rels, root=None):
    """Make every texture available as an editable file in the active project.

    Returns {game_rel: {path, status, readonly}}. An existing project file is NEVER overwritten --
    a user's edit is the point of the folder. A texture that exists only as a hand-authored .dds is
    reported readonly: that .dds outranks a .png at inject time (texture.stage_inject), so writing
    a .png beside it would show edits in Blender that silently never ship."""
    from atelier.handlers.texture import decode_to_png, ensure_work_base
    root = root or get_import_root()
    project_root=get_import_root()
    grs = sorted(set(g for g in tex_game_rels if g))
    result = {}

    def _one(gr):
        dst = project_base(gr, root)
        if os.path.normcase(os.path.realpath(root)) != os.path.normcase(os.path.realpath(project_root)):
            for src in (project_base(gr,project_root)+'.png', project_base_legacy(gr,project_root)+'.png'):
                if os.path.isfile(src):
                    os.makedirs(os.path.dirname(dst),exist_ok=True);shutil.copy2(src,dst+'.png')
                    return gr, {'path':dst+'.png','status':'existing','readonly':False}
        for cand, ro in ((dst + ".png", False), (project_base_legacy(gr, root) + ".png", False),
                         (dst + ".dds", True), (project_base_legacy(gr, root) + ".dds", True)):
            if os.path.exists(cand):
                # ...unless it is the 4x4 husk of a failed mip recovery. Nobody paints one of
                # those, so it is a broken extract rather than an edit worth protecting; fall
                # through and re-decode, reporting the refresh.
                if cand.endswith(".png") and _degenerate(cand):
                    print(f"[meshmat] refreshing unusable {os.path.basename(cand)}", file=sys.stderr)
                    break
                return gr, {"path": cand, "status": "existing", "readonly": ro}
        # Decode into the viewport cache, then copy ONLY the .png across: decode_to_png leaves a
        # .dds beside its output, and a .dds in the project would outrank the user's painted .png.
        cache_base = project_base(gr, CACHE_3DVIEW)
        png = cache_base + ".png"
        hdr=cache_base+'.hdr'
        if os.path.isfile(hdr):
            os.makedirs(os.path.dirname(dst),exist_ok=True);shutil.copyfile(hdr,dst+'.hdr')
            return gr, {'path':dst+'.hdr','status':'existing','readonly':True,
                        'note':'HDR source retained as a named input; game texture painting is unavailable.'}
        # A cached 4x4 is the signature of a failed mip recovery (see texture.decode_dds), not a
        # real texture -- handing one over as "editable" invites painting it and injecting a
        # destroyed map. Drop it and decode again; the cache predates the caller either way.
        if os.path.exists(png) and _degenerate(png):
            os.remove(png)
        if not os.path.exists(png):
            wb = ensure_work_base(gr,prefer_exact=True)
            if not wb:
                return gr, {"path": None, "status": "missing", "readonly": False}
            png = decode_to_png(cache_base, wb)
        if not png or not os.path.exists(png) or _degenerate(png):
            from atelier.handlers.meshimages import recover_inline_hdr
            # Reuse the source lookup when a stale PNG was already present.
            if 'wb' not in locals():wb=ensure_work_base(gr,prefer_exact=True)
            hdr_record=recover_inline_hdr(wb,cache_base) if wb else None
            if hdr_record:
                os.makedirs(os.path.dirname(dst),exist_ok=True)
                shutil.copyfile(hdr_record['path'],dst+'.hdr')
                return gr,{**hdr_record,'path':dst+'.hdr'}
            return gr, {"path": None, "status": "failed", "readonly": False}
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        refreshed = os.path.exists(dst + ".png")
        shutil.copyfile(png, dst + ".png")
        return gr, {"path": dst + ".png", "status": "refreshed" if refreshed else "extracted",
                    "readonly": False}

    def safe_one(gr):
        from atelier import jobs
        from atelier.tools import tex_semaphore
        try:
            with jobs.cancellable_lock(tex_semaphore):
                jobs.progress('Preparing model texture · '+os.path.basename(gr))
                return _one(gr)
        except jobs.Cancelled:
            raise
        except Exception as error:
            return gr, {'path': None, 'status': 'failed', 'readonly': False, 'error': str(error)}
    if grs:
        # Textures with neither a project file nor a decoded viewport copy need extracting; do
        # that as one batch rather than one exact-path extraction per texture inside the loop.
        from atelier.handlers.texture import prefetch_exact
        need = [gr for gr in grs
                if not any(os.path.exists(c) for c in (project_base(gr, root) + ".png",
                                                       project_base(gr, root) + ".dds",
                                                       project_base(gr, CACHE_3DVIEW) + ".png"))]
        try:
            prefetch_exact(need)
        except jobs.Cancelled:
            raise
        except Exception as error:
            print(f"[meshmat] batched texture extract skipped: {error}", file=sys.stderr, flush=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(2, len(grs))) as ex:
            # ContextVars carry both the pinned project and the cancellation/job
            # token. Each worker needs its own copy; sharing one Context across
            # simultaneous threads is invalid.
            futures=[ex.submit(copy_context().run,safe_one,gr) for gr in grs]
            for future in futures:
                gr, rec = future.result()
                result[gr] = rec
    return result


def build_manifest(mesh_game_rel, mesh, work_base=None, root=None):
    """Resolve materials + textures, stage the textures, and return the manifest dict that
    glb_to_blend.py consumes to wire the .blend's shader nodes."""
    slots = resolve_mesh_textures(resolve_mesh_materials(mesh_game_rel, mesh, work_base))
    files = extract_textures_to_project(
        [mp["game_rel"] for rec in slots for mp in rec["maps"]], root=root)
    out_slots, warnings, incomplete = {}, [], []
    from atelier.handlers.meshvisibility import hidden_sections
    hidden=hidden_sections(mesh_game_rel)
    for index, rec in enumerate(slots):
        if not rec["slot"]:
            continue
        maps = []
        if rec.get('parameters',{}).get('material_error'):
            message=rec['slot']+': '+rec['parameters']['material_error'];warnings.append(message);incomplete.append(message)
        for mp in rec["maps"]:
            f = files.get(mp["game_rel"]) or {}
            custom=rec.get('parameters', {}).get('custom_paths',{}).get(mp['param'])
            if custom and os.path.isfile(custom):
                if root and os.path.normcase(os.path.realpath(root)) != os.path.normcase(os.path.realpath(get_import_root())):
                    identity=hashlib.sha1((rec['mi']+'|'+mp['param']).encode('utf-8')).hexdigest()
                    path=os.path.join(root,'.custom',identity+'.png');os.makedirs(os.path.dirname(path),exist_ok=True);shutil.copy2(custom,path)
                else:path=custom
                f={'path':path,'status':'custom','readonly':False}
            if not f.get("path"):
                message=f"{rec['slot']}: could not decode {os.path.basename(mp['game_rel'])}"
                warnings.append(message);incomplete.append(message)
                continue
            if f.get("readonly"):
                warnings.append(f.get('note') or f"{os.path.basename(mp['game_rel'])} is a hand-authored .dds — "
                                f"shown in Blender but painting it there will not ship")
            role = mp["role"]
            if role in _HARMFUL_IF_BLACK and _is_black_placeholder(f["path"]):
                role = None      # retain the unused source input without damaging the surface
            maps.append({"param": mp["param"], "role": role, "game_rel": mp["game_rel"], 'uv': mp.get('uv',0),
                         "path": os.path.abspath(f["path"]), "readonly": bool(f.get("readonly"))})
        out_slots[rec["slot"]] = {"mi": rec["mi"], "maps": maps, **rec.get('parameters', {}),
            'hidden':any(s['slot_index']==index and s['slot_name']==rec['slot'] for s in hidden)}
        from atelier.handlers.meshtextures import source_maps
        maps.extend(source_maps(mesh_game_rel,rec['mi'],root=root))
        if not rec["mi"]:
            message=f"{rec['slot']}: no material found — slot left untextured"
            warnings.append(message);incomplete.append(message)
    for gr, f in files.items():
        if f.get("status") in ("failed", "missing"):
            warnings.append(f"{os.path.basename(gr)}: could not decode ({f['status']}) — "
                            f"left out of the .blend")
    textures = {gr: {"path": os.path.abspath(f["path"]) if f.get("path") else None,
                     "status": f.get("status"),
                     "sha1": _sha1(f["path"]) if f.get("path") and
                             f.get("status") in ("extracted", "refreshed") else None}
                for gr, f in files.items()}
    return {"mesh": mesh_game_rel, "slots": out_slots, "textures": textures, "warnings": warnings, 'incomplete':incomplete}
