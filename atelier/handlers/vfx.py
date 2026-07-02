import os, re, json
from atelier.config import IMPORT_ROOT, WORK_IMPORT_ROOT, PAKS, USMAP, _CACHE, get_import_root
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

def is_vfx(path_or_name):
    nl = os.path.basename(path_or_name).lower()
    return nl.startswith(("ns_", "fx_", "vfx_", "nfx_", "p_", "niagara_"))

def _ensure_extracted(game_rel):
    import atelier.asset_cache as _ac
    from atelier.handlers.texture import extract_info, find_extracted
    work_base = _ac.cache_base(game_rel)
    if work_base and os.path.exists(work_base + ".uasset"):
        return work_base
    pak_gr = pak_game_path(game_rel)
    os.makedirs(WORK_IMPORT_ROOT, exist_ok=True)
    uat(["extract_iostore_legacy", PAKS, os.path.abspath(WORK_IMPORT_ROOT), "--filter", os.path.basename(pak_gr)])
    cp, pak, pfx = extract_info(game_rel)
    if cp and os.path.exists(cp + ".uasset"):
        _ac.record(game_rel, cp, pak, pfx)
        return cp
    work_base = find_extracted(game_rel)
    if work_base and os.path.exists(work_base + ".uasset"):
        return work_base
    raise RuntimeError("VFX asset not found in game paks")

def _classify(channels, samples):
    """-> (kind, editable). kind: color|emission|opacity (4ch) | scalar (1) | vector2 (2) | vector3 (3)."""
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
    if all_zero or (gray and not hdr): return ("opacity", False)   # alpha/grayscale ramp — not a recolor target
    if hdr and not gray:               return ("emission", True)   # HDR glow
    return ("color", True)

def _downsample(samples, stops):
    if len(samples) <= stops: return samples
    step = (len(samples) - 1) / (stops - 1)
    return [samples[round(i * step)] for i in range(stops)]

# ── edit sidecar (persisted color-curve group edits) ──────────────────────────

def vfx_sidecar(game_rel):
    return os.path.join(get_import_root(), os.path.basename(game_rel)) + ".json"

def _load_edits(game_rel):
    p = vfx_sidecar(game_rel)
    if os.path.exists(p):
        try:
            return json.load(open(p, encoding="utf-8-sig")).get("vfx_edits") or []
        except Exception:
            return []
    return []

def _vfx_labels(game_rel, base):
    """{exportIndex -> 'Emitter · Script'} resolved via the full to_json OuterIndex chain
    (curve -> owning NiagaraScript -> owning NiagaraEmitter). Cached to _cache/vfx_labels.
    Best-effort: returns {} if to_json is unavailable, so curves just show by kind/index instead."""
    cache = os.path.join(_CACHE, "vfx_labels", os.path.basename(game_rel) + ".json")
    if os.path.exists(cache):
        try:
            return {int(k): v for k, v in json.load(open(cache, encoding="utf-8")).items()}
        except Exception:
            pass
    labels = {}
    try:
        outdir = os.path.join(_CACHE, "vfx_labels", "_tj")
        os.makedirs(outdir, exist_ok=True)
        uat(["to_json", os.path.abspath(base + ".uasset"), USMAP, os.path.abspath(outdir)])
        jp   = os.path.join(outdir, os.path.basename(game_rel) + ".json")
        exps = json.load(open(jp, encoding="utf-8-sig")).get("Exports") or []
        def oidx(e):
            o = e.get("OuterIndex")
            return (o.get("Index") if isinstance(o, dict) else o) or 0
        def ref(i):                      # OuterIndex is a 1-based positive export ref
            return exps[i - 1] if isinstance(i, int) and 0 < i <= len(exps) else None
        strip = lambda s: re.sub(r"_\d+$", "", s or "")
        for i, e in enumerate(exps):
            script = ref(oidx(e))
            if not script:
                continue
            sn = strip(script.get("ObjectName"))
            em = ref(oidx(script))
            en = strip(em.get("ObjectName")) if em else ""
            labels[i] = f"{en} · {sn}" if en and sn else (sn or en)
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        json.dump(labels, open(cache, "w"))
        try:
            os.remove(jp)                # the 17MB dump isn't needed once the label map is cached
        except OSError:
            pass
    except Exception:
        pass
    return labels

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

# ── read / save / reset ───────────────────────────────────────────────────────

def read_vfx(game_rel):
    """Enumerate a Niagara asset's editable COLOR curves, deduped into groups with gradient stops.
    Returns {ok, name, total_exports, color_exports, summary, groups:[{group_id, export_indices,
    channels, sample_count, lut_floats, kind, is_hdr, stops:[[r,g,b,a]…]}]}."""
    base = _ensure_extracted(game_rel)
    r = uat(["niagara_details", os.path.abspath(base + ".uasset"), "--usmap", USMAP])
    try:
        d = json.loads(r.stdout)
    except Exception:
        raise RuntimeError("niagara_details failed: " + (((r.stderr or "") + (r.stdout or "")).strip()[-200:] or "no output"))

    labels = _vfx_labels(game_rel, base)
    order, groups, summary = [], {}, {}
    for e in d.get("exports", []):
        lut      = e.get("shaderLut") or {}
        samples  = lut.get("samples") or []
        channels = e.get("channels", 1)
        kind, editable = _classify(channels, samples)
        summary[kind] = summary.get(kind, 0) + 1
        if not editable:                 # color/emission/scalar/vector are editable; opacity ramps aren't
            continue
        stops = [[round(x, 5) for x in (s + [0, 0, 0, 0])[:channels]] for s in _downsample(samples, PREVIEW_STOPS)]
        # Size-aware key: same-class curves come in different LUT sizes ("clones") — never merge them,
        # or the group's single rebuilt LUT would be the wrong length for the odd-sized exports.
        sig   = (_sig(stops), lut.get("sampleCount", len(samples)), channels)
        g = groups.get(sig)
        if not g:
            g = {"export_indices": [], "channels": channels,
                 "sample_count": lut.get("sampleCount", len(samples)),
                 "lut_floats":   lut.get("floatCount", 0),
                 "kind": kind,
                 "label": labels.get(e["exportIndex"], ""),
                 "is_hdr": max((max(s[:3]) for s in samples if s), default=0.0) > 1.05,
                 "stops": stops}
            groups[sig] = g; order.append(sig)
        g["export_indices"].append(e["exportIndex"])

    # overlay saved edits onto matching groups (match by shared export indices)
    for ed in _load_edits(game_rel):
        idxset = set(ed.get("export_indices", []))
        stops  = ed.get("stops")
        if not stops:
            continue
        for sig in order:
            if idxset & set(groups[sig]["export_indices"]):
                groups[sig]["stops"] = stops

    glist = [groups[s] for s in order]
    for i, g in enumerate(glist):
        g["group_id"] = i
    return {"ok": True, "name": os.path.basename(game_rel),
            "total_exports": d.get("totalExports"), "color_exports": d.get("colorExports"),
            "summary": summary, "groups": glist}

def save_vfx(game_rel, groups):
    """Persist edited color-curve groups to the sidecar. groups: [{export_indices, stops, sample_count, channels}]."""
    _ensure_extracted(game_rel)
    clean = [{"export_indices": list(g.get("export_indices") or []),
              "stops":          g.get("stops") or [],
              "sample_count":   int(g.get("sample_count") or 0),
              "channels":       int(g.get("channels") or 4)}
             for g in (groups or []) if g.get("export_indices") and g.get("stops")]
    p = vfx_sidecar(game_rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump({"vfx_edits": clean}, open(p, "w"))
    return read_vfx(game_rel)

def reset_vfx(game_rel):
    p = vfx_sidecar(game_rel)
    if os.path.exists(p):
        os.remove(p)
    return read_vfx(game_rel)

def stage_vfx(stage, game_rel, edits=None):
    """Rebuild each edited group's LUT and niagara_edit the asset into the export stage.
    edits: [{export_indices, stops, sample_count, channels}] — defaults to the on-disk sidecar."""
    base   = _ensure_extracted(game_rel)
    groups = edits if edits is not None else _load_edits(game_rel)
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
    if not payload:
        raise RuntimeError("no VFX edits to stage")
    pak_gr = pak_game_path(game_rel)
    out_ua = os.path.join(stage, *pak_gr.split("/")) + ".uasset"
    os.makedirs(os.path.dirname(out_ua), exist_ok=True)
    ej = os.path.join(_CACHE, "_vfx_edit.json"); json.dump(payload, open(ej, "w"))
    uat(["niagara_edit", os.path.abspath(base + ".uasset"), "--usmap", USMAP,
         "--output", os.path.abspath(out_ua), "--edits-file", os.path.abspath(ej)])
    if not os.path.exists(out_ua):
        raise RuntimeError("niagara_edit produced no uasset")
    return os.path.basename(game_rel)
