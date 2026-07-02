import os, json
from atelier.config import WORK_IMPORT_ROOT, PAKS, USMAP, _CACHE, get_import_root
from atelier.tools import uat
from atelier.paths import pak_game_path

# Curves = CurveLinearColor (C_*) / CurveVector|Float (Curve_*). A CurveLinearColor is 4 independent
# RichCurves (R,G,B,A); each has keys {Time, Value, InterpMode, tangents}. Values can be HDR/negative.
# We edit key *values* (the recolour) via to_json -> edit -> from_json, same round-trip as materials.

CHANNELS = ["R", "G", "B", "A"]

def is_curve(path_or_name):
    nl = os.path.basename(path_or_name).lower()
    return nl.startswith(("c_", "curve_"))

def _f(x):
    try: return float(x)          # UAssetAPI serialises 0.0 as the string "+0"
    except (TypeError, ValueError): return 0.0

def curve_json(game_rel):
    """Extract the curve + convert to JSON (flat in active project as <basename>.json). Returns json path."""
    import atelier.asset_cache as _ac
    from atelier.handlers.texture import extract_info, find_extracted
    import_root = get_import_root()
    import_base = os.path.join(import_root, os.path.basename(game_rel))
    jp = import_base + ".json"
    if os.path.exists(jp): return jp
    work_base = _ac.cache_base(game_rel)
    if not work_base or not os.path.exists(work_base + ".uasset"):
        pak_gr = pak_game_path(game_rel)
        os.makedirs(WORK_IMPORT_ROOT, exist_ok=True)
        uat(["extract_iostore_legacy", PAKS, os.path.abspath(WORK_IMPORT_ROOT),
             "--filter", os.path.basename(pak_gr)])
        cp, pak, pfx = extract_info(game_rel)
        if cp and os.path.exists(cp + ".uasset"):
            _ac.record(game_rel, cp, pak, pfx)
            work_base = cp
        else:
            work_base = find_extracted(game_rel)
    if not work_base or not os.path.exists(work_base + ".uasset"):
        raise RuntimeError("curve not found in game paks")
    os.makedirs(import_root, exist_ok=True)
    uat(["to_json", os.path.abspath(work_base + ".uasset"), USMAP, os.path.abspath(import_root)])
    if not os.path.exists(jp): raise RuntimeError("to_json produced no JSON")
    return jp

def _float_curves(d):
    """The FloatCurves struct-props of a CurveLinearColor export, in channel order (R,G,B,A)."""
    ex    = d["Exports"][0]
    props = ex.get("Data") or ex.get("Value") or []
    return [p for p in props if p.get("Name") == "FloatCurves"]

def _keys_of(fc):
    """RichCurveKey struct list for one FloatCurve (the entries under its 'Keys' array)."""
    arr = fc.get("Value")
    if not (isinstance(arr, list) and arr):
        return []
    return arr[0].get("Value") or []

def _rich_key(k):
    """The FRichCurveKey dict inside a RichCurveKey struct (mutating it edits the asset)."""
    inner = k.get("Value")
    if isinstance(inner, list) and inner and isinstance(inner[0].get("Value"), dict):
        return inner[0]["Value"]
    return {}

def _eval_channel(keys, t):
    """Linear sample of a channel (sorted [{time,value}]) at time t — for the gradient preview."""
    if not keys: return 0.0
    if t <= keys[0]["time"]:  return keys[0]["value"]
    if t >= keys[-1]["time"]: return keys[-1]["value"]
    for i in range(1, len(keys)):
        a, b = keys[i - 1], keys[i]
        if t <= b["time"]:
            span = b["time"] - a["time"]
            f = 0.0 if span == 0 else (t - a["time"]) / span
            return a["value"] + (b["value"] - a["value"]) * f
    return keys[-1]["value"]

def _channels(d):
    """{R:[{time,value}], G:..., B:..., A:...} from the CurveLinearColor's FloatCurves."""
    out = {}
    for ci, fc in enumerate(_float_curves(d)[:4]):
        ch = CHANNELS[ci]
        keys = [{"time": _f(_rich_key(k).get("Time")), "value": _f(_rich_key(k).get("Value"))}
                for k in _keys_of(fc)]
        keys.sort(key=lambda k: k["time"])
        out[ch] = keys
    return out

def _stops(channels):
    """Sampled RGBA gradient stops at the union of key times (for preview / colour-stop editing)."""
    times = sorted({k["time"] for ch in channels.values() for k in ch})
    return [{"time": round(t, 5),
             "rgba": [round(_eval_channel(channels.get(c, []), t), 5) for c in CHANNELS]}
            for t in times]

def read_curve(game_rel):
    """{ok, name, channels:{R:[{time,value}],...}, stops:[{time,rgba}]} for a CurveLinearColor."""
    d = json.load(open(curve_json(game_rel), encoding="utf-8-sig"))
    chans = _channels(d)
    return {"ok": True, "name": os.path.basename(game_rel), "channels": chans, "stops": _stops(chans)}

def _apply_curve_edits(d, edits):
    """edits: {channel: {keyIndex(str/int): newValue}} — set FRichCurveKey.Value in place."""
    fcs = _float_curves(d)
    for ci, ch in enumerate(CHANNELS):
        ch_edits = (edits or {}).get(ch)
        if not ch_edits or ci >= len(fcs):
            continue
        keys = _keys_of(fcs[ci])
        for idx, val in ch_edits.items():
            i = int(idx)
            if 0 <= i < len(keys):
                _rich_key(keys[i])["Value"] = float(val)

def save_curve(game_rel, edits):
    """Apply key-value edits and PERSIST them into the curve's on-disk JSON."""
    jp = curve_json(game_rel)
    d  = json.load(open(jp, encoding="utf-8-sig"))
    _apply_curve_edits(d, edits or {})
    json.dump(d, open(jp, "w"))
    chans = _channels(d)
    return {"ok": True, "channels": chans, "stops": _stops(chans)}

def reset_curve(game_rel):
    """Drop local edits: delete the cached JSON and re-derive vanilla keys from the .uasset."""
    jp = os.path.join(get_import_root(), os.path.basename(game_rel)) + ".json"
    if os.path.exists(jp): os.remove(jp)
    return read_curve(game_rel)

def stage_curve(stage, game_rel, edits):
    """Apply edits and from_json the curve into the export stage at its pak game path."""
    d = json.load(open(curve_json(game_rel), encoding="utf-8-sig"))
    _apply_curve_edits(d, edits or {})
    ej = os.path.join(_CACHE, "_curve_edit.json"); json.dump(d, open(ej, "w"))
    pak_gr = pak_game_path(game_rel)
    out_ua = os.path.join(stage, *pak_gr.split("/")) + ".uasset"
    os.makedirs(os.path.dirname(out_ua), exist_ok=True)
    uat(["from_json", os.path.abspath(ej), os.path.abspath(out_ua), USMAP])
    if not os.path.exists(out_ua): raise RuntimeError("from_json produced no uasset")
    return os.path.basename(game_rel)
