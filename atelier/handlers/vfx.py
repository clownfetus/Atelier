import os, re, json, copy, math, tempfile
from atelier.config import (IMPORT_ROOT, WORK_IMPORT_ROOT, PAKS, USMAP, _CACHE, get_import_root,
                            project_base, project_base_legacy)
from atelier.tools import uat
from atelier.paths import pak_game_path

# VFX = Niagara systems / data-interface assets. Editable content is NOT single scalar/color values
# (that's materials) — it's per-export CURVES baked into a flat LUT (sampleCount samples × channels):
#   channels 1 -> scalar curve   2 -> vector2   3 -> vector3   4 -> color (RGBA; color/emission/opacity)
# UAssetTool reads these with `niagara_details` and rewrites a whole export's LUT with
#   `niagara_edit ... --edits-file [{"exportIndex":N,"flatLut":[...]}]`  (flatLut length == floatCount).
#
# A system has MANY identical color curves (duplicates/LOD). We dedupe editable color/emission curves
# into GROUPS keyed by their (vanilla) gradient, edit each group's stops, and on export rebuild the
# full LUT for every export in the group. Edits persist as a <basename>.json sidecar in the project
# (same "edits on disk, applied at export" model as materials/curves); niagara_edit applies to vanilla.

PREVIEW_STOPS = 16   # gradient stops exposed for editing (the full LUT is rebuilt from them on export)

def is_mpc(path_or_name):
    """MPC_* = MaterialParameterCollection — UE's GLOBAL scalar/vector parameters."""
    return os.path.basename(path_or_name).lower().startswith("mpc_")

def is_vfx(path_or_name):
    nl = os.path.basename(path_or_name).lower()
    return nl.startswith(("ns_", "fx_", "vfx_", "nfx_", "p_", "niagara_", "mpc_"))

def _ensure_extracted(game_rel):
    from atelier.handlers.texture import ensure_work_base
    work_base = ensure_work_base(game_rel)      # retoc or UAssetTool per host; caches the result
    if work_base and os.path.exists(work_base + ".uasset"):
        return work_base
    from atelier.handlers.texture import missing_reason as TX_missing_reason
    raise RuntimeError(TX_missing_reason(game_rel, "VFX asset"))

def _classify(channels, samples):
    """Appearance category only; four-channel guesses never establish a Niagara property binding."""
    if channels < 4:
        return ({1: "scalar", 2: "vector2", 3: "vector3"}.get(channels, "scalar"), True)
    if not samples:
        return ("color", True)
    n = len(samples)
    sr = sg = sb = 0.0; mx = 0.0; all_zero = True
    for s in samples:
        r, g, b = (s + [0, 0, 0])[:3]
        sr += r; sg += g; sb += b
        mx = max(mx, r, g, b)
        if r or g or b: all_zero = False
    ar, ag, ab = sr / n, sg / n, sb / n
    gray = abs(ar - ag) < 0.02 and abs(ag - ab) < 0.02
    hdr  = mx > 1.05
    if all_zero or (gray and not hdr): return ("opacity", True)    # alpha/grayscale ramp — editable (transparency/mask over life)
    if hdr and not gray:               return ("emission", True)   # HDR glow
    return ("color", True)

def _downsample(samples, stops):
    if len(samples) <= stops: return samples
    # The editing/export model uses uniform positions. Sample those exact positions
    # rather than rounding to a nearby native index, which puts handles off the curve.
    channels = len(samples[0])
    flat = _rebuild_lut(samples, stops, channels)
    return [flat[i:i+channels] for i in range(0, len(flat), channels)]

# ── edit sidecar (persisted color-curve group edits) ──────────────────────────

def vfx_sidecar(game_rel):
    """Where a VFX's edit sidecar is written — the unique subfolder path (no basename collisions)."""
    return project_base(game_rel) + ".json"

def _load_edits(game_rel):
    # New subfolder path wins; fall back to the legacy flat path so pre-existing projects still load.
    for p in (vfx_sidecar(game_rel), project_base_legacy(game_rel) + ".json"):
        if os.path.exists(p):
            try:
                return json.load(open(p, encoding="utf-8-sig")).get("vfx_edits") or []
            except Exception:
                return []
    return []

def _vfx_labels(game_rel, base, *, metadata=False):
    """{exportIndex -> label} from to_json. Two sources, best first:
      1. each NiagaraScript's ResolvedDataInterfaces -> Name '<Emitter>.<Module>.<Input>' +
         ResolvedDataInterface (the DI export it drives). This NAMES WHAT THE CURVE DOES
         ('Glow2001 · ScaleSpriteSize002 · Uniform Curve Sprite Scale') and is unique per curve.
      2. fallback: the OuterIndex chain (curve -> owning script -> owning emitter) = 'Emitter · Script',
         which is identical for every curve on an emitter and so can't tell scale from opacity.
    Metadata retains precise bindings separately from owner-name fallbacks, which
    cannot establish a curve's meaning. Best-effort when to_json is unavailable."""
    cache = project_base(game_rel, os.path.join(_CACHE, "vfx_labels3")) + ".json"
    signature = []
    for path in (base + '.uasset', base + '.uexp', USMAP):
        try:
            stat = os.stat(path)
            signature.append([os.path.realpath(path), stat.st_size, stat.st_mtime_ns])
        except OSError:
            signature.append([str(path), None, None])
    def result(labels):
        return labels if metadata else {i: value["label"] for i, value in labels.items()}
    if os.path.exists(cache):
        try:
            with open(cache, encoding="utf-8") as stream:
                saved = json.load(stream)
            if saved.get('source') == signature:
                return result({int(k): v for k, v in saved['labels'].items()})
        except Exception:
            pass
    labels = {}
    try:
        os.makedirs(_CACHE, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="vfx-labels-", dir=_CACHE) as outdir:
            uat(["to_json", os.path.abspath(base + ".uasset"), USMAP, os.path.abspath(outdir)])
            with open(os.path.join(outdir, os.path.basename(game_rel) + ".json"), encoding="utf-8-sig") as stream:
                exps = json.load(stream).get("Exports") or []
        def oidx(e):
            o = e.get("OuterIndex")
            return (o.get("Index") if isinstance(o, dict) else o) or 0
        def ref(i):                      # OuterIndex is a 1-based positive export ref
            return exps[i - 1] if isinstance(i, int) and 0 < i <= len(exps) else None
        strip = lambda s: re.sub(r"_\d+$", "", s or "")

        # --- source 1: precise binding names via each script's ResolvedDataInterfaces ---
        def _walk(o, name, acc):
            if isinstance(o, dict):
                if o.get("Name") == name: acc.append(o)
                for v in o.values(): _walk(v, name, acc)
            elif isinstance(o, list):
                for v in o: _walk(v, name, acc)
        def _prop(lst, n):
            for p in lst or []:
                if isinstance(p, dict) and p.get("Name") == n: return p
        bind = {}
        for e in exps:
            acc = []; _walk(e.get("Data"), "ResolvedDataInterfaces", acc)
            for a in acc:
                for entry in (a.get("Value") or []):
                    if not isinstance(entry, dict): continue
                    nm = _prop(entry.get("Value"), "Name")
                    rd = _prop(entry.get("Value"), "ResolvedDataInterface")
                    if not nm or not rd: continue
                    tgt = rd.get("Value")
                    if isinstance(tgt, int) and 0 < tgt <= len(exps):
                        nv = str(nm.get("Value") or "").strip()
                        if nv and nv != "None":
                            names = bind.setdefault(tgt - 1, [])
                            if nv not in names:
                                names.append(nv)

        # --- source 2: OuterIndex chain fallback ---
        asset = strip(os.path.basename(game_rel))
        for i, e in enumerate(exps):
            if i in bind:                       # precise binding wins
                labels[i] = {"label": bind[i][0].replace(".", " · "), "source": "binding", "names": bind[i]}
                continue
            script = ref(oidx(e))
            if not script:
                continue
            sn = strip(script.get("ObjectName"))
            em = ref(oidx(script))
            en = strip(em.get("ObjectName")) if em else ""
            lbl = f"{en} · {sn}" if en and sn else (sn or en)
            # A DI owned by the system/package (not an emitter's script) walks up to the asset's own
            # name — that's not a label, it's "unknown", and it has no ResolvedDataInterfaces binding
            # either. Say so rather than printing the filename N times as if it identified the curve.
            labels[i] = {"label": "(unbound)" if (not lbl or strip(lbl) == asset) else lbl,
                         "source": "owner", "names": []}
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        from atelier.storage import atomic_json
        atomic_json(cache, {"source": signature, "labels": labels})
    except Exception:
        pass
    return result(labels)

def _sig(stops):
    return tuple(round(v, 4) for s in stops for v in s)

def _at(s, c):
    return s[c] if c < len(s) else 0.0

def _rebuild_lut(stops, sample_count, channels):
    """Interpolate `sample_count` LUT samples of `channels` floats from evenly-spaced stops; flat list."""
    n = len(stops)
    if not n or not sample_count:
        return []
    flat = []
    for j in range(sample_count):
        if n == 1 or sample_count == 1:
            s = stops[0]
        else:
            pos = j / (sample_count - 1) * (n - 1)
            i0 = int(pos); i1 = min(i0 + 1, n - 1); f = pos - i0
            a, b = stops[i0], stops[i1]
            s = [_at(a, c) + (_at(b, c) - _at(a, c)) * f for c in range(channels)]
        flat.extend(float(_at(s, c)) for c in range(channels))
    return flat

# ── MaterialParameterCollection (global scalar / vector parameters) ───────────
# A skin's VFX glow colour is frequently not a Niagara curve at all — it is a GLOBAL parameter in an
# MPC, read by every material that references the collection. That is what diiea was editing in UE
# on 1031306 ("the four orange colors in the global parameters"), and Atelier had no way to see it:
# MPC_* classified as "other" and was hidden from the browser entirely.
#
# These are plain typed properties, so the edit model is material.py's exactly — to_json into the
# project, edit the JSON in place, from_json at export — not the Niagara LUT sidecar above.
#
# WARNING worth keeping in mind when reading the UI copy: the collection is global. Every material
# that references it changes, not just the skin that led you here.

def _gn(lst, n):
    for p in lst or []:
        if isinstance(p, dict) and p.get("Name") == n:
            return p
    return None

def _ex_props(e):
    return e.get("Data") or e.get("Value") or []

def _f(x):
    try: return float(x)          # UAssetAPI serialises 0.0 as the string "+0"
    except (TypeError, ValueError): return 0.0

def _unwrap(v, depth=4):
    """UAssetAPI wraps a struct's payload in one or more {"Value": …} layers, and the depth differs
    between property kinds. Walk down to the first dict that looks like an FLinearColor."""
    for _ in range(depth):
        if isinstance(v, dict):
            if "R" in v and "G" in v and "B" in v:
                return v
            v = v.get("Value")
        elif isinstance(v, list):
            if not v:
                return None
            v = v[0]
        else:
            return None
    return v if isinstance(v, dict) and "R" in v else None

def _param_name(entry):
    """The FName under this collection entry's ParameterName property."""
    pn = _gn(entry.get("Value"), "ParameterName")
    if not pn:
        return None
    v = pn.get("Value")
    if isinstance(v, dict):
        v = v.get("Value")
    return v if isinstance(v, str) else None

def _mpc_lists(d):
    """(scalar_entries, vector_entries) — the raw JSON entries, so edits mutate the document."""
    ex = d["Exports"][0]
    sp = _gn(_ex_props(ex), "ScalarParameters")
    vp = _gn(_ex_props(ex), "VectorParameters")
    return ((sp or {}).get("Value") or []), ((vp or {}).get("Value") or [])

def mpc_json(game_rel):
    """The collection's JSON in the active project, extracting + to_json'ing it on first use.
    Mirrors material.mat_json: the project copy IS the edit, so the sidebar sees it as imported."""
    import atelier.asset_cache as _ac
    from atelier.handlers.texture import extract_info, find_extracted
    import_root = get_import_root()
    jp = project_base(game_rel, import_root) + ".json"
    if os.path.exists(jp):
        return jp
    legacy_jp = project_base_legacy(game_rel, import_root) + ".json"
    if os.path.exists(legacy_jp):
        return legacy_jp
    work_base = _ac.cache_base(game_rel)
    if not work_base or not os.path.exists(work_base + ".uasset"):
        work_base = _ensure_extracted(game_rel)
    sub = os.path.dirname(jp)
    os.makedirs(sub, exist_ok=True)
    uat(["to_json", os.path.abspath(work_base + ".uasset"), USMAP, os.path.abspath(sub)])
    if not os.path.exists(jp):
        raise RuntimeError("to_json produced no JSON for " + os.path.basename(game_rel))
    return jp

def read_mpc(game_rel):
    """{ok, kind:'mpc', name, scalars:[{name,value}], vectors:[{name,rgba}]} for a collection."""
    d = json.load(open(mpc_json(game_rel), encoding="utf-8-sig"))
    sl, vl = _mpc_lists(d)
    scalars, vectors = [], []
    for e in sl:
        nm = _param_name(e)
        dv = _gn(e.get("Value"), "DefaultValue")
        if nm and dv is not None:
            scalars.append({"name": nm, "value": round(_f(dv.get("Value")), 5)})
    for e in vl:
        nm = _param_name(e)
        dv = _gn(e.get("Value"), "DefaultValue")
        lc = _unwrap(dv.get("Value")) if dv is not None else None
        if nm and lc:
            vectors.append({"name": nm, "rgba": [round(_f(lc.get(k)), 5) for k in "RGBA"]})
    return {"ok": True, "kind": "mpc", "name": os.path.basename(game_rel),
            "global_params": True, "scalars": scalars, "vectors": vectors,
            "summary": {"vector": len(vectors), "scalar": len(scalars)}, "groups": []}

def _apply_mpc_edits(d, scalars, vectors):
    from atelier.properties import mark_changed
    sl, vl = _mpc_lists(d)
    for e in sl:
        nm = _param_name(e)
        if nm in (scalars or {}):
            dv = _gn(e.get("Value"), "DefaultValue")
            if dv is not None:
                mark_changed(e, dv)
                dv["Value"] = float(scalars[nm])
    for e in vl:
        nm = _param_name(e)
        if nm in (vectors or {}):
            dv = _gn(e.get("Value"), "DefaultValue")
            lc = _unwrap(dv.get("Value")) if dv is not None else None
            if lc:
                mark_changed(e, dv)
                r, g, b, a = (list(vectors[nm]) + [0, 0, 0, 1])[:4]
                lc["R"], lc["G"], lc["B"], lc["A"] = float(r), float(g), float(b), float(a)

def save_mpc(game_rel, scalars, vectors):
    """Apply edits and PERSIST them into the collection's on-disk project JSON."""
    jp = mpc_json(game_rel)
    d  = json.load(open(jp, encoding="utf-8-sig"))
    _apply_mpc_edits(d, scalars or {}, vectors or {})
    from atelier.storage import atomic_json
    atomic_json(jp, d)
    return read_mpc(game_rel)

def reset_mpc(game_rel):
    """Drop local edits: delete the project JSON (new + legacy) and re-derive from the .uasset."""
    for jp in (project_base(game_rel) + ".json", project_base_legacy(game_rel) + ".json"):
        if os.path.exists(jp):
            os.remove(jp)
    return read_mpc(game_rel)

def stage_mpc(stage, game_rel):
    """from_json the edited collection into the export stage at its pak game path."""
    d  = json.load(open(mpc_json(game_rel), encoding="utf-8-sig"))
    ej = os.path.join(_CACHE, "_mpc_edit.json"); json.dump(d, open(ej, "w"))
    pak_gr = pak_game_path(game_rel)
    out_ua = os.path.join(stage, *pak_gr.split("/")) + ".uasset"
    os.makedirs(os.path.dirname(out_ua), exist_ok=True)
    uat(["from_json", os.path.abspath(ej), os.path.abspath(out_ua), USMAP])
    if not os.path.exists(out_ua):
        raise RuntimeError("from_json produced no uasset")
    return os.path.basename(game_rel)


# ── read / save / reset ───────────────────────────────────────────────────────

def read_vfx(game_rel, *, original=False):
    """Enumerate supported Niagara LUTs with editing stops, full originals and binding evidence.
    Returns {ok, name, total_exports, color_exports, summary, groups:[{group_id, export_indices,
    channels, sample_count, lut_floats, kind, is_hdr, stops:[[r,g,b,a]…]}]}.

    An MPC is not a Niagara asset and has no LUTs — it goes to read_mpc, which returns the same
    editor payload shape with `kind: "mpc"` instead of curve groups."""
    if is_mpc(game_rel):
        return read_mpc(game_rel)
    base = _ensure_extracted(game_rel)
    r = uat(["niagara_details", os.path.abspath(base + ".uasset"), "--usmap", USMAP])
    try:
        d = json.loads(r.stdout)
    except Exception:
        raise RuntimeError("niagara_details failed: " + (((r.stderr or "") + (r.stdout or "")).strip()[-200:] or "no output"))

    labels = _vfx_labels(game_rel, base, metadata=True)
    order, groups, summary, unsupported = [], {}, {}, []
    for e in d.get("exports", []):
        lut      = e.get("shaderLut") or {}
        samples  = lut.get("samples") or []
        channels = e.get("channels", 1)
        count = lut.get("sampleCount", len(samples))
        valid = (type(channels) is int and 1 <= channels <= 4 and type(count) is int and count > 0
                 and len(samples) == count and lut.get("floatCount", count * channels) == count * channels
                 and all(isinstance(s, list) and len(s) == channels and
                         all(type(x) in (int, float) and math.isfinite(x) for x in s) for s in samples))
        if not valid:
            unsupported.append({"export_index": e.get("exportIndex"), "name": e.get("name", ""),
                                "reason": "No supported finite 1–4 channel LUT with matching dimensions"})
            continue
        kind, editable = _classify(channels, samples)
        summary[kind] = summary.get(kind, 0) + 1
        if not editable:
            continue
        stops = copy.deepcopy(_downsample(samples, PREVIEW_STOPS))
        # Size-aware key: same-class curves come in different LUT sizes ("clones") — never merge them,
        # or the group's single rebuilt LUT would be the wrong length for the odd-sized exports.
        time_range = [lut.get("minTime"), lut.get("maxTime")]
        if not all(type(t) in (int, float) and math.isfinite(t) for t in time_range) or time_range[1] <= time_range[0]:
            time_range = None
        # Never merge curves whose full LUTs differ outside the editing stops.
        # Existing sidecars still match by export indices, independent of grouping.
        sig = (tuple(tuple(s) for s in samples), count, channels, tuple(time_range or []))
        g = groups.get(sig)
        if not g:
            g = {"export_indices": [], "channels": channels,
                 "sample_count": count,
                 "lut_floats":   count * channels,
                 "kind": kind,
                 "classification_source": "samples" if channels == 4 else "dimensions",
                 "label": "", "bindings": [], "exports": [], "time_range": time_range,
                 "is_hdr": max((max(s[:3]) for s in samples if s), default=0.0) > 1.05,
                 "stops": stops, "original_stops": copy.deepcopy(stops),
                 "original_samples": copy.deepcopy(samples), "has_saved_edit": False}
            groups[sig] = g; order.append(sig)
        g["export_indices"].append(e["exportIndex"])
        info = labels.get(e["exportIndex"], {})
        if isinstance(info, str):
            info = {"label": info, "source": "unknown", "names": []}
        g["bindings"].append({"export_index": e["exportIndex"], **info})
        g["exports"].append({"index": e["exportIndex"], "name": e.get("name", ""), "class": e.get("classType", "")})

    # A clone-group's members don't all carry a binding, and "label" above is set from whichever
    # export created the group — often an unbound clone. Re-pick the most specific label any member
    # has: a binding name ('Glow2001 · ScaleSpriteSize002 · Uniform Curve Sprite Scale', 2 separators)
    # beats the OuterIndex fallback ('Glow2001 · SpawnScript', 1), which is identical across an
    # emitter's curves and can't tell sprite-scale from opacity.
    for sig in order:
        g = groups[sig]
        best = max((info.get("label", "") for info in g["bindings"]),
                   key=lambda s: (s.count(" · "), len(s)), default="")
        if best:
            g["label"] = best

    # overlay saved edits onto matching groups (match by shared export indices)
    unmatched = []
    for ed in ([] if original else _load_edits(game_rel)):
        idxset = set(ed.get("export_indices", []))
        stops  = ed.get("stops")
        if not stops:
            continue
        matched = set()
        for sig in order:
            if idxset & set(groups[sig]["export_indices"]):
                if (ed.get("channels", 4) != groups[sig]["channels"] or
                        ed.get("sample_count") != groups[sig]["sample_count"] or
                        not _valid_stops(stops, groups[sig]["channels"])):
                    continue
                groups[sig]["stops"] = copy.deepcopy(stops)
                groups[sig]["has_saved_edit"] = True
                matched.update(idxset & set(groups[sig]["export_indices"]))
        if idxset - matched:
            unmatched.append(ed)

    glist = [groups[s] for s in order]
    for i, g in enumerate(glist):
        g["group_id"] = i
    return {"ok": True, "name": os.path.basename(game_rel),
            "total_exports": d.get("totalExports"), "color_exports": d.get("colorExports"),
            "summary": summary, "groups": glist, "unsupported_exports": unsupported,
            "unmatched_edits": len(unmatched)}


def _valid_stops(stops, channels):
    return (isinstance(stops, list) and 0 < len(stops) <= 4096 and
            all(isinstance(s, list) and len(s) == channels and
                all(type(x) in (int, float) and math.isfinite(x) and abs(x) <= 3.4028234663852886e38 for x in s) for s in stops))


def _clean_vfx_groups(groups, available):
    """Validate the existing sidecar shape against real LUT dimensions before publication/export."""
    if not isinstance(groups, list):
        raise ValueError("VFX edits must be a list of curve groups")
    expected = {index: group for group in available for index in group["export_indices"]}
    clean, used = [], set()
    for group in groups:
        if not isinstance(group, dict):
            raise ValueError("Invalid VFX curve group")
        indices, channels, count = group.get("export_indices"), group.get("channels", 4), group.get("sample_count")
        if (not isinstance(indices, list) or not indices or type(channels) is not int or type(count) is not int
                or not _valid_stops(group.get("stops"), channels)):
            raise ValueError("Invalid VFX LUT dimensions or non-finite curve values")
        for index in indices:
            actual = expected.get(index) if type(index) is int else None
            if not actual or actual["channels"] != channels or actual["sample_count"] != count:
                raise ValueError("Saved VFX export no longer has the supported LUT dimensions; restore the effect or use the matching game version")
            if index in used:
                raise ValueError("A VFX export may be edited only once")
            used.add(index)
        clean.append({"export_indices": list(indices), "stops": copy.deepcopy(group["stops"]),
                      "sample_count": count, "channels": channels})
    return clean

def save_vfx(game_rel, groups, scalars=None, vectors=None):
    """Persist edited color-curve groups to the sidecar. groups: [{export_indices, stops, sample_count, channels}].
    For an MPC there are no groups — the named scalar/vector edits go to save_mpc instead."""
    if is_mpc(game_rel):
        return save_mpc(game_rel, scalars or {}, vectors or {})
    current = read_vfx(game_rel)
    clean = _clean_vfx_groups(groups if groups is not None else [], current["groups"])
    known = {index: g for g in current["groups"] for index in g["export_indices"]}
    submitted = {index for g in clean for index in g["export_indices"]}
    # Keep unavailable old exports and unrelated sidecar metadata. Motionboard
    # cannot edit them and must not silently discard another version's edits.
    for old in _load_edits(game_rel):
        remaining = [i for i in old.get("export_indices", []) if i not in submitted and
                     (i not in known or old.get("channels", 4) != known[i]["channels"] or
                      old.get("sample_count") != known[i]["sample_count"] or
                      not _valid_stops(old.get("stops"), known[i]["channels"]))]
        if remaining:
            clean.append({**old, "export_indices": remaining})
    p = vfx_sidecar(game_rel)
    document = {}
    for candidate in (p, project_base_legacy(game_rel) + ".json"):
        if os.path.isfile(candidate):
            with open(candidate, encoding="utf-8-sig") as stream:
                document = json.load(stream)
            break
    os.makedirs(os.path.dirname(p), exist_ok=True)
    from atelier.storage import atomic_json
    atomic_json(p, {**document, "vfx_edits": clean}, allow_nan=False)
    return read_vfx(game_rel)

def reset_vfx(game_rel):
    if is_mpc(game_rel):
        return reset_mpc(game_rel)
    pristine = read_vfx(game_rel, original=True)
    for p in (vfx_sidecar(game_rel), project_base_legacy(game_rel) + ".json"):
        if os.path.exists(p):
            os.remove(p)
    return pristine

def stage_vfx(stage, game_rel, edits=None):
    """Rebuild each edited group's LUT and niagara_edit the asset into the export stage.
    edits: [{export_indices, stops, sample_count, channels}] — defaults to the on-disk sidecar."""
    if is_mpc(game_rel):
        return stage_mpc(stage, game_rel)
    base   = _ensure_extracted(game_rel)
    groups = edits if edits is not None else _load_edits(game_rel)
    groups = _clean_vfx_groups(groups, read_vfx(game_rel)["groups"])
    payload = []
    for g in (groups or []):
        stops = g.get("stops") or []
        sc    = int(g.get("sample_count") or 0)
        ch    = int(g.get("channels") or 4)
        if not stops or not sc:
            continue
        flat = _rebuild_lut(stops, sc, ch)
        for idx in (g.get("export_indices") or []):
            payload.append({"exportIndex": idx, "flatLut": flat})
    pak_gr = pak_game_path(game_rel)
    out_ua = os.path.join(stage, *pak_gr.split("/")) + ".uasset"
    os.makedirs(os.path.dirname(out_ua), exist_ok=True)
    if not payload:
        # Saving all tracks back to original must preserve the original cooked
        # asset, rather than resampling its untouched LUTs through editing stops.
        from atelier.storage import publish_files
        publish_files([base + ext for ext in (".uasset", ".uexp", ".ubulk", ".uptnl")
                       if os.path.isfile(base + ext)], os.path.dirname(out_ua))
        return os.path.basename(game_rel)
    ej = os.path.join(_CACHE, "_vfx_edit.json"); json.dump(payload, open(ej, "w"))
    uat(["niagara_edit", os.path.abspath(base + ".uasset"), "--usmap", USMAP,
         "--output", os.path.abspath(out_ua), "--edits-file", os.path.abspath(ej)])
    if not os.path.exists(out_ua):
        raise RuntimeError("niagara_edit produced no uasset")
    return os.path.basename(game_rel)
