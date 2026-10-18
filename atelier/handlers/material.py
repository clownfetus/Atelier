import os, json, shutil, tempfile, threading, hashlib
from atelier.storage import atomic_json, publish_files, publish_project_json
from atelier.config import (WORK_IMPORT_ROOT, PAKS, USMAP, _CACHE, CACHE_3DVIEW, get_import_root, validate_game_rel,
                            project_base, project_base_legacy)
from atelier.tools import uat
from atelier import jobs
from atelier.paths import pak_game_path

_original_lock = threading.Lock()
_SOURCE_KEY = "_atelier_material_source"

def is_material(path_or_name):
    return os.path.basename(path_or_name).upper().startswith("MI_")

def _f(x):
    try: return float(x)
    except (TypeError, ValueError): return 0.0

def _gn(lst, n):
    for p in lst or []:
        if isinstance(p, dict) and p.get("Name") == n: return p
    return None

def _ex_props(e): return e.get("Data") or e.get("Value") or []

def _mat_pname(entry):
    pinfo = _gn(entry["Value"], "ParameterInfo")
    return (_gn(pinfo["Value"], "Name") or {}).get("Value") if pinfo else None

def _mat_color(entry):
    pv = _gn(entry["Value"], "ParameterValue"); v = pv.get("Value") if pv else None
    if (isinstance(v, list) and v and isinstance(v[0], dict)
            and isinstance(v[0].get("Value"), dict) and "R" in v[0]["Value"]):
        return v[0]["Value"]
    return None

def _mat_params(d):
    ex = d["Exports"][0]
    vp = _gn(_ex_props(ex), "VectorParameterValues")
    sp = _gn(_ex_props(ex), "ScalarParameterValues")
    colors, scalars = [], []
    for e in (vp or {}).get("Value", []):
        nm = _mat_pname(e); lc = _mat_color(e)
        if nm and lc: colors.append({"name": nm, "rgba": [round(_f(lc[k]), 5) for k in "RGBA"]})
    for e in (sp or {}).get("Value", []):
        nm = _mat_pname(e); pv = _gn(e["Value"], "ParameterValue")
        if nm and pv is not None and not isinstance(pv.get("Value"), (list, dict)):
            scalars.append({"name": nm, "value": round(_f(pv.get("Value")), 5)})
    return colors, scalars

def texture_slots(d):
    """{slot: {entry, value, import, package, game_rel, class}} for the MI's texture params
    (BaseColor/Normal/ORM/…), resolved through the Imports table. Each TextureParameterValue's
    ParameterValue is an import link (negative index); that import's outer Package holds the
    /Game/Marvel/… path → storage-relative game_rel. `entry`/`value` are the live JSON nodes, so a
    caller can repoint the slot (custom_texture does); only slots under /Game/Marvel are listed."""
    ex = d["Exports"][0]
    tp = _gn(_ex_props(ex), "TextureParameterValues")
    imports = d.get("Imports", [])
    out = {}
    for e in (tp or {}).get("Value", []):
        nm = _mat_pname(e)
        pv = _gn(e["Value"], "ParameterValue")
        idx = pv.get("Value") if pv else None
        if not nm or not isinstance(idx, int) or idx >= 0:
            continue
        ii = -idx - 1
        if not (0 <= ii < len(imports)):
            continue
        outer = imports[ii].get("OuterIndex")
        pkg_import = None
        if isinstance(outer, int) and outer < 0 and (-outer - 1) < len(imports):
            pkg_import = imports[-outer - 1]
        pkg = (pkg_import or {}).get("ObjectName")
        if isinstance(pkg, str) and pkg.startswith("/Game/Marvel/"):
            out[nm] = {"entry": e, "value": pv, "import": imports[ii], "package": pkg_import,
                       "game_rel": pkg[len("/Game/Marvel/"):],
                       "class": imports[ii].get("ClassName") or ""}
    return out

def _mat_textures(d):
    """{slot: game_rel} for the MI's texture params — see texture_slots."""
    return {slot: s["game_rel"] for slot, s in texture_slots(d).items()}

def _mat_texture_classes(d):
    """{slot: UE class name} ('Texture2D', 'TextureCube', …) — only Texture2D slots can take a
    custom texture, and the editor says so instead of offering a button that would fail."""
    return {slot: s["class"] for slot, s in texture_slots(d).items()}

def _apply_mat_edits(d, colors, scalars):
    from atelier.properties import mark_changed
    ex = d["Exports"][0]
    vp = _gn(_ex_props(ex), "VectorParameterValues")
    sp = _gn(_ex_props(ex), "ScalarParameterValues")
    for e in (vp or {}).get("Value", []):
        nm = _mat_pname(e)
        if nm in colors:
            lc = _mat_color(e)
            if lc:
                mark_changed(e, _gn(e["Value"], "ParameterValue"))
                r, g, b, a = colors[nm]
                lc["R"], lc["G"], lc["B"], lc["A"] = float(r), float(g), float(b), float(a)
    for e in (sp or {}).get("Value", []):
        nm = _mat_pname(e)
        if nm in scalars:
            pv = _gn(e["Value"], "ParameterValue")
            if pv is not None:
                mark_changed(e, pv)
                pv["Value"] = float(scalars[nm])

def mat_json(game_rel, out_dir=None):
    """Extract the MI + convert to JSON as <basename>.json. Returns the json path.
    The active project dir always takes priority (edits/explicit imports live there); if no
    project copy exists, the JSON is produced in out_dir (defaults to the project dir — the
    explicit import/edit flows). Pass out_dir=CACHE_3DVIEW for viewport-only reads that shouldn't
    pollute the project folder."""
    from atelier.handlers.texture import ensure_work_base
    import_root = get_import_root()
    # Project copy wins. Unique subfolder path (no basename collisions); fall back to the legacy flat
    # layout so pre-existing projects still load.
    project_jp  = project_base(game_rel, import_root) + ".json"
    if os.path.exists(project_jp): return project_jp
    legacy_jp   = project_base_legacy(game_rel, import_root) + ".json"
    if os.path.exists(legacy_jp): return legacy_jp
    out_dir = out_dir or import_root
    jp = project_base(game_rel, out_dir) + ".json"
    if os.path.exists(jp): return jp
    if out_dir != CACHE_3DVIEW:
        # reuse the vanilla copy the viewport already cached instead of re-extracting from paks
        cached_jp = project_base(game_rel, CACHE_3DVIEW) + ".json"
        if os.path.exists(cached_jp):
            os.makedirs(os.path.dirname(jp), exist_ok=True)
            shutil.copyfile(cached_jp, jp)
            return jp
    # One extractor for every handler: it picks retoc or UAssetTool per host and records the
    # asset cache itself (texture.ensure_work_base).
    work_base = ensure_work_base(game_rel)
    if not work_base or not os.path.exists(work_base + ".uasset"):
        from atelier.handlers.texture import missing_reason as TX_missing_reason
        raise RuntimeError(TX_missing_reason(game_rel, "material"))
    sub = os.path.dirname(jp)                         # the game_rel subfolder under out_dir
    os.makedirs(sub, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.material-', dir=sub) as scratch:
        uat(["to_json", os.path.abspath(work_base + ".uasset"), USMAP, os.path.abspath(scratch)])
        converted = os.path.join(scratch, os.path.basename(jp))
        if not os.path.exists(converted): raise RuntimeError("to_json produced no JSON")
        with open(converted, encoding='utf-8-sig') as stream:
            json.load(stream)
        jobs.checkpoint()
        os.replace(converted, jp)
    return jp

def read_material(game_rel, cache_only=False):
    """{colors:[{name,rgba}], scalars:[{name,value}], textures:{slot:game_rel}} for an MI instance.
    cache_only=True routes any freshly-extracted JSON into CACHE_3DVIEW instead of the project
    folder — used by the 3D viewport's automatic per-mesh material reads."""
    d = json.load(open(mat_json(game_rel, out_dir=CACHE_3DVIEW if cache_only else None), encoding="utf-8-sig"))
    colors, scalars = _mat_params(d)
    return {"colors": colors, "scalars": scalars, "textures": _mat_textures(d),
            "texture_classes": _mat_texture_classes(d), "material_source": d.get(_SOURCE_KEY, "")}

def _original_document(game_rel):
    """Read a pristine document without creating, changing or resetting a project copy.

    mat_json() deliberately prioritizes project edits, even for cache-only reads, so
    original comparison must use the vanilla viewport cache/extractor directly.
    Native output is parsed before atomic publication; failure keeps every existing
    project file and cache entry intact, and the next request can retry.
    """
    from atelier.handlers.texture import ensure_work_base, missing_reason
    from atelier.tools import tex_semaphore

    from atelier.added_assets import source_base
    added = source_base(game_rel)
    if added:
        # Added packages may share a path in different projects; their originals are project-owned.
        from atelier.added_assets import _read_package
        with tempfile.TemporaryDirectory(prefix='atelier-added-material-') as temporary:
            return _read_package(added, temporary)

    jp = project_base(game_rel, CACHE_3DVIEW) + ".json"

    def read(path):
        with open(path, encoding="utf-8-sig") as stream:
            data = json.load(stream)
        _mat_params(data)  # validate before cache publication
        _mat_textures(data)
        return data

    # One original conversion at a time prevents duplicate work and same-asset
    # races without an unbounded table of per-asset locks.
    with _original_lock:
        if os.path.isfile(jp):
            try:
                return read(jp)
            except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                pass  # An incomplete old cache can be repaired after a successful decode.
        with tex_semaphore:
            work_base = ensure_work_base(game_rel)
            if not work_base or not os.path.isfile(work_base + ".uasset"):
                raise RuntimeError(missing_reason(game_rel, "material"))
            os.makedirs(CACHE_3DVIEW, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=".material-original-", dir=CACHE_3DVIEW) as temporary:
                result = uat(["to_json", os.path.abspath(work_base + ".uasset"), USMAP,
                              os.path.abspath(temporary)])
                if result.returncode != 0:
                    raise RuntimeError("Could not read original material: " +
                                       ((result.stderr or result.stdout or "to_json failed").strip()[-500:]))
                output = os.path.join(temporary, os.path.basename(jp))
                if not os.path.isfile(output):
                    raise RuntimeError("Original material conversion produced no JSON")
                data = read(output)
                atomic_json(jp, data)
                return data


def read_material_original(game_rel):
    """Original comparison bypasses saved edits, including a replacement's donor snapshot."""
    d = _original_document(game_rel)
    colors, scalars = _mat_params(d)
    return {"colors": colors, "scalars": scalars, "textures": _mat_textures(d)}


def _material_path(game_rel):
    """Accept a browser path or a copied UE object/package path, never a filesystem path."""
    from atelier.index import get_content_prefix
    if not isinstance(game_rel, str):
        raise ValueError("Choose a material path")
    gr = game_rel.strip().replace("\\", "/")
    if gr.startswith("/Game/Marvel/"):
        gr = gr[len("/Game/Marvel/"):]
    if gr.lower().endswith(".uasset"):
        gr = gr[:-7]
    elif "." in gr.rsplit("/", 1)[-1]:
        package, obj = gr.rsplit(".", 1)
        if obj == package.rsplit("/", 1)[-1]:
            gr = package
    validate_game_rel(gr)
    if not is_material(gr) or "." in gr.rsplit("/", 1)[-1]:
        raise ValueError("Choose a material instance (MI_…)")
    # These are the package paths understood by the material/texture readers.
    if gr.casefold().startswith(("plugins/", "marvel_lq/")) or \
            get_content_prefix(gr).rstrip("/").casefold() != "marvel/content/marvel":
        raise ValueError("Choose a material from the main game content")
    return gr


def _material_export(d, game_rel):
    tops = [e for e in d.get("Exports", [])
            if not e.get("OuterIndex") and e.get("ObjectName") == os.path.basename(game_rel)]
    if len(tops) != 1:
        raise ValueError("Material must have one matching top-level export")
    index = tops[0].get("ClassIndex")
    imports = d.get("Imports", [])
    if not isinstance(index, int) or index >= 0 or -index > len(imports) or \
            imports[-index - 1].get("ObjectName") != "MaterialInstanceConstant":
        raise ValueError("Only MaterialInstanceConstant assets can be used as replacements")
    return tops[0]


def _retarget_material(d, source, target):
    """Keep the entire donor (including shader data and import indices); rename only its identity."""
    ex = _material_export(d, source)
    ex["ObjectName"] = os.path.basename(target)
    old, new = "/Game/Marvel/" + source, "/Game/Marvel/" + target
    # Exact package/object self references only. Never rewrite the donor character's
    # texture/parent paths: those must continue to resolve to the installed game assets.
    def visit(value):
        if isinstance(value, str):
            if value == old:
                return new
            obj = old + "." + os.path.basename(source)
            if value == obj or value.startswith(obj + ":"):
                return new + "." + os.path.basename(target) + value[len(obj):]
        elif isinstance(value, list):
            return [visit(v) for v in value]
        elif isinstance(value, dict):
            return {k: visit(v) for k, v in value.items()}
        return value
    d = visit(d)
    for name in (os.path.basename(target), new):
        if name not in d.setdefault("NameMap", []):
            d["NameMap"].append(name)
    if isinstance(d.get("FolderName"), str) and d["FolderName"].startswith("/"):
        d["FolderName"] = new
    return d


def _check_replacement_parents(d, source, target):
    """Overriding an ancestor of the donor would make its parent chain recursive."""
    visited = {source.casefold()}
    while True:
        ex = _material_export(d, source)
        parent = _gn(_ex_props(ex), "Parent")
        idx = (parent or {}).get("Value")
        imports = d.get("Imports", [])
        if not isinstance(idx, int) or idx >= 0:
            return
        if -idx > len(imports):
            raise ValueError("Material has an invalid parent reference")
        imp = imports[-idx - 1]
        outer = imp.get("OuterIndex")
        if not isinstance(outer, int) or outer >= 0 or -outer > len(imports):
            raise ValueError("Material has an invalid parent package")
        package = imports[-outer - 1].get("ObjectName", "")
        if package.casefold() == ("/Game/Marvel/" + target).casefold():
            raise ValueError("This source inherits from the target material. Choose a source with a different parent chain.")
        if imp.get("ClassName") != "MaterialInstanceConstant":
            return
        source = _material_path(package)
        if source.casefold() in visited or len(visited) >= 64:
            raise ValueError("Source material has a recursive or excessively deep parent chain")
        visited.add(source.casefold())
        d = _original_document(source)


def replace_material(game_rel, source_game_rel):
    """Save an independent donor snapshot at the target; the donor's project edits are untouched.

    Provenance travels inside the project JSON so it and the snapshot publish atomically.
    Export consumes that marker itself and rebuilds from the current vanilla donor.
    """
    target, source = _material_path(game_rel), _material_path(source_game_rel)
    if target != game_rel:
        raise ValueError("Use the target's browser asset path")
    if target.casefold() == source.casefold():
        raise ValueError("Choose a different material, or restore game defaults")
    _material_export(_original_document(target), target)
    d = _original_document(source)
    _check_replacement_parents(d, source, target)
    d = _retarget_material(d, source, target)
    d[_SOURCE_KEY] = source
    jobs.checkpoint()
    _publish_replacement(target, d)
    return read_material(target)


def _publish_replacement(game_rel, d):
    """Replace the document and clear incompatible options in one recoverable transaction."""
    from atelier import project_meta
    root = get_import_root()
    target = project_base(game_rel) + ".json"

    def change(path, data):
        with open(path, "rb") as stream:
            before = hashlib.file_digest(stream, "sha256").hexdigest()
        return {"path": os.path.relpath(path, root).replace("\\", "/"), "before": before, "data": data}

    changes = [change(target, d) if os.path.isfile(target) else
               {"path": os.path.relpath(target, root).replace("\\", "/"), "before": None, "data": d}]
    meta_path = os.path.join(root, ".atelier", "project.json")
    if os.path.isfile(meta_path):
        meta_change = change(meta_path, None)
        metadata = project_meta.load(root)
        options = metadata["asset_opts"].get(game_rel, {})
        for key in ("custom_textures", "color_inten", "dye_off"):
            options.pop(key, None)
        if not options:
            metadata["asset_opts"].pop(game_rel, None)
        metadata["last_version"] = project_meta.current_version() or metadata["last_version"]
        meta_change["data"] = metadata
        changes.append(meta_change)
    publish_project_json(root, changes)

def save_material(game_rel, colors, scalars):
    """Apply color/scalar edits and PERSIST them into the material's on-disk JSON."""
    jp = mat_json(game_rel)
    d  = json.load(open(jp, encoding="utf-8-sig"))
    _apply_mat_edits(d, colors or {}, scalars or {})
    atomic_json(jp, d)
    cols, scals = _mat_params(d)
    return {"colors": cols, "scalars": scals}

def reset_material(game_rel):
    """Read pristine data before replacing saved edits; extraction failure preserves the project."""
    d = _original_document(game_rel)
    _publish_replacement(game_rel, d)
    return read_material(game_rel)

def stage_material(stage, game_rel, colors, scalars, *, use_project=True):
    """Rebase saved values onto current vanilla, never serialize an old project package.

    Custom textures assigned to the material's slots (custom_texture) are built and staged with it.
    The repatcher passes use_project=False and so ships none: it rebuilds a mod from that mod's own
    material values, which name no project images."""
    from atelier.handlers.texture import ensure_work_base, missing_reason
    from atelier.handlers import custom_texture
    custom = custom_texture.assignments(game_rel) if use_project else {}
    saved_colors, saved_scalars = {}, {}
    source = game_rel
    project_bases = (project_base(game_rel), project_base_legacy(game_rel)) if use_project else ()
    for base in project_bases:
        if os.path.isfile(base + ".json"):
            with open(base + ".json", encoding="utf-8-sig") as stream:
                saved = json.load(stream)
                cols, scals = _mat_params(saved)
                if saved.get(_SOURCE_KEY):
                    source = _material_path(saved[_SOURCE_KEY])
            saved_colors = {c["name"]: c["rgba"] for c in cols}
            saved_scalars = {s["name"]: s["value"] for s in scals}
            break
    # Explicit callers (including the repatcher) override project values.
    saved_colors.update(colors or {})
    saved_scalars.update(scalars or {})
    pak_gr = pak_game_path(game_rel)
    out_ua = os.path.join(stage, *pak_gr.split("/")) + ".uasset"
    os.makedirs(os.path.dirname(out_ua), exist_ok=True)
    work_base = ensure_work_base(source)
    if not work_base or not os.path.isfile(work_base + ".uasset"):
        raise RuntimeError(missing_reason(source, "material"))
    os.makedirs(_CACHE, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".material-export-", dir=_CACHE) as temporary:
        result = uat(["to_json", os.path.abspath(work_base + ".uasset"), USMAP, temporary])
        if result.returncode != 0:
            raise RuntimeError("Could not decode current material: " +
                               ((result.stderr or result.stdout or "to_json failed").strip()[-500:]))
        jp = os.path.join(temporary, os.path.basename(source) + ".json")
        if not os.path.isfile(jp):
            raise RuntimeError("Current material conversion produced no JSON")
        with open(jp, encoding="utf-8-sig") as stream:
            d = json.load(stream)
        if source != game_rel:
            _check_replacement_parents(d, source, game_rel)
            d = _retarget_material(d, source, game_rel)
        current_colors, current_scalars = _mat_params(d)
        missing = sorted((saved_colors.keys() - {c["name"] for c in current_colors}) |
                         (saved_scalars.keys() - {s["name"] for s in current_scalars}))
        if missing:
            raise RuntimeError("Current material no longer has saved parameters: " + ", ".join(missing))
        _apply_mat_edits(d, saved_colors, saved_scalars)
        textures = custom_texture.apply(d, game_rel, custom, os.path.join(temporary, "custom"))
        with open(jp, "w", encoding="utf-8") as stream:
            json.dump(d, stream)
        compiled = os.path.join(temporary, "compiled", os.path.basename(out_ua))
        os.makedirs(os.path.dirname(compiled))
        result = uat(["from_json", jp, compiled, USMAP])
        if result.returncode != 0 or not os.path.isfile(compiled):
            raise RuntimeError("Material build failed: " +
                               ((result.stderr or result.stdout or "from_json produced no uasset").strip()[-500:]))
        # Failed conversions never leave partial packages in the shared stage. Custom textures go
        # in first: an orphaned texture is inert, a material pointing at a missing one is not.
        for files, tex_gr in textures:
            tex_ua = os.path.join(stage, *pak_game_path(tex_gr).split("/")) + ".uasset"
            os.makedirs(os.path.dirname(tex_ua), exist_ok=True)
            publish_files(files, os.path.dirname(tex_ua))
        sources = [compiled[:-7] + ext for ext in (".uasset", ".uexp", ".ubulk", ".uptnl")
                   if os.path.isfile(compiled[:-7] + ext)]
        publish_files(sources, os.path.dirname(out_ua))
    if textures:
        return f"{os.path.basename(game_rel)} (+{len(textures)} custom texture{'s' if len(textures) != 1 else ''})"
    return os.path.basename(game_rel)
