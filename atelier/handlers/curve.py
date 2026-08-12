import os, json, copy
from atelier.config import (WORK_IMPORT_ROOT, PAKS, USMAP, _CACHE, get_import_root,
                            project_base, project_base_legacy)
from atelier.tools import uat
from atelier.paths import pak_game_path

# Curves = CurveLinearColor (C_*) / CurveVector|Float (Curve_*). A CurveLinearColor is 4 independent
# RichCurves (R,G,B,A); each has keys {Time, Value, InterpMode, tangents}. Values can be HDR/negative.
# Editing goes to_json -> edit -> from_json (VERIFIED faithful for curves incl. key-count changes,
# 2026-07-09). Beyond recolour we support: add/remove keys, edit TIME, InterpMode, and tangents —
# by REBUILDING a channel's Keys array from a full key list (each key cloned from a template so the
# UAssetAPI struct wrappers stay exact).

CHANNELS = ["R", "G", "B", "A"]
INTERP_MODES = ("RCIM_Linear", "RCIM_Cubic", "RCIM_Constant")

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
    # Unique subfolder path (no basename collisions); fall back to the legacy flat layout so
    # pre-existing projects still load.
    jp = project_base(game_rel, import_root) + ".json"
    if os.path.exists(jp): return jp
    legacy_jp = project_base_legacy(game_rel, import_root) + ".json"
    if os.path.exists(legacy_jp): return legacy_jp
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
    sub = os.path.dirname(jp)                          # the game_rel subfolder under import_root
    os.makedirs(sub, exist_ok=True)
    uat(["to_json", os.path.abspath(work_base + ".uasset"), USMAP, os.path.abspath(sub)])
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
    """{R:[{time,value,interp,arriveTangent,leaveTangent}], G:..., B:..., A:...} from the FloatCurves."""
    out = {}
    for ci, fc in enumerate(_float_curves(d)[:4]):
        ch = CHANNELS[ci]
        keys = []
        for k in _keys_of(fc):
            rk = _rich_key(k)
            keys.append({"time": _f(rk.get("Time")), "value": _f(rk.get("Value")),
                         "interp": rk.get("InterpMode", "RCIM_Linear"),
                         "arriveTangent": _f(rk.get("ArriveTangent")),
                         "arriveTangentWeight": _f(rk.get("ArriveTangentWeight")),
                         "leaveTangent": _f(rk.get("LeaveTangent")),
                         "leaveTangentWeight": _f(rk.get("LeaveTangentWeight")),
                         "tangentMode": rk.get("TangentMode", "RCTM_Auto"),
                         "tangentWeightMode": rk.get("TangentWeightMode", "RCTWM_WeightedNone")})
        keys.sort(key=lambda k: k["time"])
        out[ch] = keys
    return out

def _template_key(d):
    """A RichCurveKey struct to clone when adding keys — take the first real key in the asset so its
    UAssetAPI $type/Name wrappers are exact; fall back to a built-from-scratch one if the whole curve
    is empty."""
    for fc in _float_curves(d):
        ks = _keys_of(fc)
        if ks:
            return copy.deepcopy(ks[0])
    return {"$type": "UAssetAPI.PropertyTypes.Structs.StructPropertyData, UAssetAPI",
            "StructType": "RichCurveKey", "SerializeNone": True,
            "StructGUID": "{00000000-0000-0000-0000-000000000000}", "SerializationControl": "NoExtension",
            "Operation": "None", "OriginalStructHeader": None, "Name": "Keys", "ArrayIndex": 0,
            "IsZero": False, "PropertyTagFlags": "None", "PropertyTagExtensions": "NoExtension",
            "Value": [{"$type": "UAssetAPI.UnrealTypes.FRichCurveKey, UAssetAPI",
                       "InterpMode": "RCIM_Linear", "TangentMode": "RCTM_Auto",
                       "TangentWeightMode": "RCTWM_WeightedNone", "Time": 0.0, "Value": 0.0,
                       "ArriveTangent": 0.0, "ArriveTangentWeight": 0.0,
                       "LeaveTangent": 0.0, "LeaveTangentWeight": 0.0}]}

def _rebuild_channel(fc, key_list, template):
    """Replace a FloatCurve's Keys array with fresh keys built from key_list (each cloned from the
    template so the struct format is preserved). key_list: [{time,value,interp?,arriveTangent?,leaveTangent?}]."""
    arr = fc.get("Value")
    if not (isinstance(arr, list) and arr):
        return
    new_keys = []
    for kd in sorted(key_list, key=lambda k: float(k.get("time", 0))):
        nk = copy.deepcopy(template); rk = _rich_key(nk)
        rk["Time"] = float(kd.get("time", 0)); rk["Value"] = float(kd.get("value", 0))
        if kd.get("interp") in INTERP_MODES:
            rk["InterpMode"] = kd["interp"]
        if "arriveTangent" in kd:       rk["ArriveTangent"] = float(kd["arriveTangent"])
        if "arriveTangentWeight" in kd: rk["ArriveTangentWeight"] = float(kd["arriveTangentWeight"])
        if "leaveTangent" in kd:        rk["LeaveTangent"] = float(kd["leaveTangent"])
        if "leaveTangentWeight" in kd:  rk["LeaveTangentWeight"] = float(kd["leaveTangentWeight"])
        if kd.get("tangentMode"):       rk["TangentMode"] = kd["tangentMode"]
        if kd.get("tangentWeightMode"): rk["TangentWeightMode"] = kd["tangentWeightMode"]
        new_keys.append(nk)
    arr[0]["Value"] = new_keys

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
    """edits: {channel: EITHER a full key LIST [{time,value,interp,arriveTangent,leaveTangent}] ->
    rebuild the channel (add/remove/time/interp/tangents), OR the legacy {keyIndex: newValue} dict ->
    set values in place (kept so pre-existing project sidecars still apply)."""
    fcs = _float_curves(d)
    template = _template_key(d)
    for ci, ch in enumerate(CHANNELS):
        ch_edits = (edits or {}).get(ch)
        if ch_edits is None or ci >= len(fcs):
            continue
        if isinstance(ch_edits, list):                       # new: rebuild from full key list
            _rebuild_channel(fcs[ci], ch_edits, template)
        elif isinstance(ch_edits, dict):                     # legacy: value-only by index
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
    """Drop local edits: delete the project JSON (new + legacy paths) and re-derive from the .uasset."""
    for jp in (project_base(game_rel) + ".json", project_base_legacy(game_rel) + ".json"):
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
