import os, json, shutil, tempfile, threading
from atelier.storage import atomic_json, publish_files
from atelier.config import (WORK_IMPORT_ROOT, PAKS, USMAP, _CACHE, CACHE_3DVIEW, get_import_root,
                            project_base, project_base_legacy)
from atelier.tools import uat
from atelier.paths import pak_game_path

_original_lock = threading.Lock()

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

def _mat_textures(d):
    """{slot: game_rel} for the MI's texture params (BaseColor/Normal/ORM/…), resolved through the
    Imports table. Each TextureParameterValue's ParameterValue is an import link (negative index);
    that import's outer Package holds the /Game/Marvel/… path → storage-relative game_rel."""
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
        pkg = None
        if isinstance(outer, int) and outer < 0 and (-outer - 1) < len(imports):
            pkg = imports[-outer - 1].get("ObjectName")
        if isinstance(pkg, str) and pkg.startswith("/Game/Marvel/"):
            out[nm] = pkg[len("/Game/Marvel/"):]
    return out

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
    uat(["to_json", os.path.abspath(work_base + ".uasset"), USMAP, os.path.abspath(sub)])
    if not os.path.exists(jp): raise RuntimeError("to_json produced no JSON")
    return jp

def read_material(game_rel, cache_only=False):
    """{colors:[{name,rgba}], scalars:[{name,value}], textures:{slot:game_rel}} for an MI instance.
    cache_only=True routes any freshly-extracted JSON into CACHE_3DVIEW instead of the project
    folder — used by the 3D viewport's automatic per-mesh material reads."""
    d = json.load(open(mat_json(game_rel, out_dir=CACHE_3DVIEW if cache_only else None), encoding="utf-8-sig"))
    colors, scalars = _mat_params(d)
    return {"colors": colors, "scalars": scalars, "textures": _mat_textures(d)}

def read_material_original(game_rel):
    """Read pristine game parameters without creating, changing or resetting a project copy.

    mat_json() deliberately prioritizes project edits, even for cache-only reads, so
    original comparison must use the vanilla viewport cache/extractor directly.
    Native output is parsed before atomic publication; failure keeps every existing
    project file and cache entry intact, and the next request can retry.
    """
    from atelier.handlers.texture import ensure_work_base, missing_reason
    from atelier.tools import tex_semaphore

    jp = project_base(game_rel, CACHE_3DVIEW) + ".json"

    def read(path):
        with open(path, encoding="utf-8-sig") as stream:
            data = json.load(stream)
        colors, scalars = _mat_params(data)
        return data, {"colors": colors, "scalars": scalars, "textures": _mat_textures(data)}

    # One original conversion at a time prevents duplicate work and same-asset
    # races without an unbounded table of per-asset locks.
    with _original_lock:
        if os.path.isfile(jp):
            try:
                return read(jp)[1]
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
                data, params = read(output)
                atomic_json(jp, data)
                return params

def save_material(game_rel, colors, scalars):
    """Apply color/scalar edits and PERSIST them into the material's on-disk JSON."""
    jp = mat_json(game_rel)
    d  = json.load(open(jp, encoding="utf-8-sig"))
    _apply_mat_edits(d, colors or {}, scalars or {})
    atomic_json(jp, d)
    cols, scals = _mat_params(d)
    return {"colors": cols, "scalars": scals}

def reset_material(game_rel):
    """Drop local edits: delete the project JSON (new + legacy paths) and re-derive from the .uasset."""
    for jp in (project_base(game_rel) + ".json", project_base_legacy(game_rel) + ".json"):
        if os.path.exists(jp): os.remove(jp)
    return read_material(game_rel)

def stage_material(stage, game_rel, colors, scalars, *, use_project=True):
    """Rebase saved values onto current vanilla, never serialize an old project package."""
    from atelier.handlers.texture import ensure_work_base, missing_reason
    saved_colors, saved_scalars = {}, {}
    project_bases = (project_base(game_rel), project_base_legacy(game_rel)) if use_project else ()
    for base in project_bases:
        if os.path.isfile(base + ".json"):
            with open(base + ".json", encoding="utf-8-sig") as stream:
                cols, scals = _mat_params(json.load(stream))
            saved_colors = {c["name"]: c["rgba"] for c in cols}
            saved_scalars = {s["name"]: s["value"] for s in scals}
            break
    # Explicit callers (including the repatcher) override project values.
    saved_colors.update(colors or {})
    saved_scalars.update(scalars or {})
    pak_gr = pak_game_path(game_rel)
    out_ua = os.path.join(stage, *pak_gr.split("/")) + ".uasset"
    os.makedirs(os.path.dirname(out_ua), exist_ok=True)
    work_base = ensure_work_base(game_rel)
    if not work_base or not os.path.isfile(work_base + ".uasset"):
        raise RuntimeError(missing_reason(game_rel, "material"))
    os.makedirs(_CACHE, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".material-export-", dir=_CACHE) as temporary:
        result = uat(["to_json", os.path.abspath(work_base + ".uasset"), USMAP, temporary])
        if result.returncode != 0:
            raise RuntimeError("Could not decode current material: " +
                               ((result.stderr or result.stdout or "to_json failed").strip()[-500:]))
        jp = os.path.join(temporary, os.path.basename(game_rel) + ".json")
        if not os.path.isfile(jp):
            raise RuntimeError("Current material conversion produced no JSON")
        with open(jp, encoding="utf-8-sig") as stream:
            d = json.load(stream)
        current_colors, current_scalars = _mat_params(d)
        missing = sorted((saved_colors.keys() - {c["name"] for c in current_colors}) |
                         (saved_scalars.keys() - {s["name"] for s in current_scalars}))
        if missing:
            raise RuntimeError("Current material no longer has saved parameters: " + ", ".join(missing))
        _apply_mat_edits(d, saved_colors, saved_scalars)
        with open(jp, "w", encoding="utf-8") as stream:
            json.dump(d, stream)
        compiled = os.path.join(temporary, "compiled", os.path.basename(out_ua))
        os.makedirs(os.path.dirname(compiled))
        result = uat(["from_json", jp, compiled, USMAP])
        if result.returncode != 0 or not os.path.isfile(compiled):
            raise RuntimeError("Material build failed: " +
                               ((result.stderr or result.stdout or "from_json produced no uasset").strip()[-500:]))
        # Failed conversions never leave partial packages in the shared stage.
        sources = [compiled[:-7] + ext for ext in (".uasset", ".uexp", ".ubulk", ".uptnl")
                   if os.path.isfile(compiled[:-7] + ext)]
        publish_files(sources, os.path.dirname(out_ua))
    return os.path.basename(game_rel)
