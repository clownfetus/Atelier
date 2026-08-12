"""World assets = level sublevels (.umap). Editable content: LIGHTS (intensity/color), FOG,
post-process GRADE, and component VISIBILITY. Same edit model as materials/vfx/curves — edits
persist as a <basename>.json sidecar in the project and are applied to the vanilla asset at export,
so a world edit bundles into the SAME unified mod as any texture/material/vfx edit.

Build = FAITHFUL BINARY-PATCH (NOT from_json). from_json re-serializes the whole level into a
different byte layout, and create_mod_iostore then mis-resolves a PostProcessVolume reference on
large maps (NewYorkE01 1564 exports, Arakko 2242) -> in-game "Bad export index" crash. So instead
we keep the vanilla .uasset/.uexp byte-for-byte and splice only the edited VALUES, located WITHIN
the target export's byte range (SerialOffset/SerialSize from to_json) so it's exact and unique.
All patches are same-size (doubles/floats/color bytes) -> no SerialSize fix, no re-layout, no crash.
Reads still use to_json. Patch-resilient: config.USMAP is auto-updated."""
import os, re, glob, json, struct, hashlib, shutil, subprocess
from atelier.config import WORK_IMPORT_ROOT, PAKS, USMAP, _CACHE, TOOLS, CNW, ROOT, get_aes_key, \
    project_base, project_base_legacy
from atelier.tools import uat
from atelier.paths import pak_game_path
import io_lib

# Zen-DIRECT build tooling. create_mod_iostore corrupts the name map of BIG level packages during
# legacy->Zen conversion (a no-op repack of Arakko crashes in-game), so level mods are built the
# mr_app way instead: patch the VALUE bytes into the vanilla Zen chunk read from the game container,
# and rebuild the container with io_lib. retoc is used only to pack a 1-sublevel TEMPLATE container.
RETOC = os.path.join(TOOLS, "shaders", "retoc-rivals-cli.exe")
# UAssetGUI = the FAITHFUL level round-trip writer. UAssetTool's from_json corrupts a level's
# PostProcessVolume object refs (WeightedBlendables/cubemap/curves) -> in-game "Bad export/import
# index" crash; UAssetGUI's fromjson (the writer that shipped the whole S8.5 roster) re-serializes
# levels cleanly. So ADD-OVERRIDE grades go: UAssetGUI tojson -> edit -> UAssetGUI fromjson -> retoc
# pack. (UAssetTool from_json is still fine for textures/materials — this is a level-asset problem.)
UAG = os.path.join(TOOLS, "UAssetGUI.exe")
_UAG_MAP = "Atelier_S9"

def _uag(args, timeout=240):
    """Run UAssetGUI CLI. Bad/insufficient args make it launch the GUI and hang -> always timeout+kill.
    tojson: [tojson, asset, out.json, VER_UE5_3, <map>]  fromjson: [fromjson, in.json, out.uasset, <map>]."""
    try:
        r = subprocess.run([UAG] + args, capture_output=True, text=True, creationflags=CNW, timeout=timeout)
        return (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        subprocess.run(["taskkill", "/F", "/IM", "UAssetGUI.exe"], capture_output=True)
        return "TIMEOUT"

def _uag_mapping():
    """Register config.USMAP under a stable name in every dir UAssetGUI might scan; return the name."""
    for md in (os.path.join(os.environ.get("LOCALAPPDATA", ""), "UAssetGUI", "Mappings"),
               os.path.join(TOOLS, "Mappings"), os.path.join(os.path.dirname(UAG), "Mappings")):
        try:
            os.makedirs(md, exist_ok=True)
            dst = os.path.join(md, _UAG_MAP + ".usmap")
            if not os.path.exists(dst) or os.path.getsize(dst) != os.path.getsize(USMAP):
                shutil.copy(USMAP, dst)
        except Exception:
            pass
    return _UAG_MAP

FRIENDLY = {
    "Arakko": ("Arakko", "Convoy"), "AsgardE01": ("Yggdrasil Path", "Convoy"),
    "AsgardPalace": ("Royal Palace", "Domination"), "GardenCQ01": ("Grand Garden", "Conquest"),
    "HydraC": ("Hell's Heaven", "Domination"), "Klyntar": ("Symbiotic Surface", "Convergence"),
    "KlyntarC": ("Celestial Husk", "Domination"), "KlyntarEC01": ("Throne of Knull", "Resource Rumble"),
    "KrakoaBeach": ("Hellfire Bay Beach", "Hub"), "KrakoaC": ("Krakoa", "Domination"),
    "KunlunEC01": ("Shenloong Arena", "Conquest"), "KunlunH01": ("Heart of Heaven", "Convergence"),
    "MuseumE01": ("Museum of Contemplation", "Convoy"), "NewYorkE01": ("Midtown", "Convoy"),
    "NewYorkH01": ("Central Park", "Convergence"), "NewYorkM01": ("Sanctum Sanctorum", "Doom Match"),
    "NewyorkH02": ("Lower Manhattan", "Convergence"), "NuevaYork": ("Alchemax Headquarters", "Doom Match"),
    "PracticeRange": ("Practice Range", "Hub"), "TimeSquare": ("Time Square", "Hub"),
    "TokyoCQ01": ("Ninomaru", "Conquest"), "TokyoE01": ("Spider Islands", "Convoy"),
    "TokyoH01": ("Shin Shibuya", "Convergence"), "Wakanda": ("Birnin T'Challa", "Domination"),
    "WakandaMC01": ("Hall of Djalia", "Convergence"),
}

GRADE_VEC = ["ColorSaturation", "ColorContrast", "ColorGain", "ColorGamma", "ColorOffset",
             "ColorGainShadows", "ColorContrastShadows", "ColorSaturationShadows",
             "ColorSaturationMidtones", "ColorSaturationHighlights"]
GRADE_SCALAR = ["BloomIntensity", "VignetteIntensity", "FilmGrainIntensity"]
GRADE = GRADE_VEC + GRADE_SCALAR
# UE defaults so EVERY grade setting can be shown/added on any map (build_world_uag adds absent ones),
# not just the subset a given PPV happens to serialize. Offset defaults to 0s, other color vecs to 1s.
GRADE_DEFAULT = {n: ([0.0, 0.0, 0.0, 0.0] if n == "ColorOffset" else [1.0, 1.0, 1.0, 1.0]) for n in GRADE_VEC}
GRADE_DEFAULT.update(BloomIntensity=0.675, VignetteIntensity=0.4, FilmGrainIntensity=0.0)
ENABLE = ["bVisible", "bHiddenInGame", "bHidden", "bIsActive", "bAffectsWorld", "bUnbound"]


def is_world(path_or_name):
    return os.path.basename(path_or_name).lower().endswith(".umap")

# ── map/sublevel enumeration for the browse "Maps" section (maps aren't in the pak-asset index) ──
_MAPS = None
def _cont_prio(name):
    n = name.lower()
    if "pakchunkmap" in n: return 0
    if n.startswith("pakchunk0"): return 1
    if n.startswith("patch"): return 2
    return 3

def _enum():
    """{mapname: [{sub, game_rel}]} for every .umap sublevel across all containers. Cached."""
    global _MAPS
    if _MAPS is not None: return _MAPS
    byk = {}
    for utoc in sorted(glob.glob(PAKS + "/*.utoc"),
                       key=lambda u: (_cont_prio(os.path.basename(u)), os.path.basename(u))):
        try:
            t = io_lib.parse_toc(utoc); entries = io_lib.parse_dir_index(t)
        except Exception:
            continue
        cont = os.path.basename(utoc)
        for p, _ud in entries:
            pl = p.lower()
            if not (pl.endswith(".umap") and "/maps/" in pl): continue
            mm = re.search(r"/Maps/([^/]+)/", p, re.I)
            if not mm: continue
            e = byk.get(pl)
            if e is None:
                gr = re.sub(r"^(\.\./)+", "", p.replace("\\", "/"))
                gr = re.sub(r"^Marvel/Content/Marvel/", "", gr, flags=re.I)   # -> Maps/.../X.umap
                e = byk[pl] = {"sub": os.path.basename(p)[:-5], "map": mm.group(1),
                               "game_rel": gr, "path": p, "conts": []}    # path keeps the ../../../ mount prefix
            if cont not in e["conts"]: e["conts"].append(cont)
    m = {}
    for e in byk.values():
        m.setdefault(e["map"], []).append({"sub": e["sub"], "game_rel": e["game_rel"],
                                           "path": e["path"], "conts": e["conts"]})
    _MAPS = {k: sorted(v, key=lambda x: x["sub"]) for k, v in sorted(m.items())}
    return _MAPS

def _locate(game_rel):
    """Return (full ../../../ mount path, [containers]) for a level game_rel, from the map enum."""
    gr = _norm(game_rel).lower()
    for subs in _enum().values():
        for s in subs:
            if s["game_rel"].lower() == gr:
                return s["path"], s["conts"]
    return None, []

def list_maps():
    return sorted(_enum().keys())

def map_friendly(mapname):
    return FRIENDLY.get(mapname, (mapname, ""))

def list_map_sublevels(mapname):
    return _enum().get(mapname, [])

def _norm(game_rel):
    """Level game_rels carry the .umap extension (unlike .uasset assets)."""
    gr = game_rel.replace("\\", "/")
    return gr if gr.lower().endswith(".umap") else gr + ".umap"

# ── extraction (same extractor the whole app uses) ──────────────────────────────
def _ensure_extracted(game_rel):
    """Extract the sublevel to a legacy .uasset (named <sub>.umap.uasset). Returns the base (no ext)."""
    pak_gr = pak_game_path(_norm(game_rel))                       # Marvel/Content/Marvel/Maps/.../X.umap
    base = os.path.join(WORK_IMPORT_ROOT, *pak_gr.split("/"))
    if os.path.exists(base + ".uasset"):
        return base
    os.makedirs(WORK_IMPORT_ROOT, exist_ok=True)
    uat(["extract_iostore_legacy", PAKS, os.path.abspath(WORK_IMPORT_ROOT),
         "--filter", os.path.basename(pak_gr)])
    if os.path.exists(base + ".uasset"):
        return base
    raise RuntimeError("level asset not found in game paks: " + pak_gr)

def _to_json(base):
    outdir = os.path.join(_CACHE, "world_tj"); os.makedirs(outdir, exist_ok=True)
    uat(["to_json", os.path.abspath(base + ".uasset"), USMAP, os.path.abspath(outdir)])
    jp = os.path.join(outdir, os.path.basename(base) + ".json")
    if not os.path.exists(jp):
        raise RuntimeError("to_json produced no JSON")
    return jp

# ── model parse (lights / fog / grade / components) ─────────────────────────────
def _pt(p): return str(p.get("$type", "")).split(".")[-1].split(",")[0]

def _vec(v):
    if not isinstance(v, dict): return None
    if "X" in v: return [round(float(v.get(k, 0)), 4) for k in "XYZW"]
    if "R" in v: return [round(float(v.get(k, 0)), 4) for k in "RGBA"]
    return None

XFORM = ("RelativeLocation", "RelativeRotation", "RelativeScale3D")

def _xform_vals(p):
    """[a,b,c] for a transform StructProperty, or None. FVector serializes X,Y,Z and FRotator
    Pitch,Yaw,Roll — both 3 doubles (UE5 is double-precision), so both patch at a fixed 24 bytes."""
    if p.get("Name") not in XFORM: return None
    v = p.get("Value")
    if not (isinstance(v, list) and v and isinstance(v[0], dict)): return None
    iv = v[0].get("Value")
    if not isinstance(iv, dict): return None
    for keys in (("X", "Y", "Z"), ("Pitch", "Yaw", "Roll")):
        if all(k in iv for k in keys):
            try: return [float(iv[k]) for k in keys]
            except Exception: return None
    return None

def _xform_enc(p):
    v = _xform_vals(p)
    return struct.pack("<ddd", *v) if v else None

def _color_str(v):
    if isinstance(v, list) and v and isinstance(v[0], dict) and isinstance(v[0].get("Value"), str):
        try: return [int(float(x)) for x in v[0]["Value"].split(",")][:3]
        except Exception: return None
    return None

def _flat(props, vals, ov):
    for p in props:
        if not isinstance(p, dict): continue
        n = p.get("Name", "?")
        if n.startswith("bOverride_") and _pt(p) == "BoolPropertyData":
            if p.get("Value"): ov.add(n[10:])
            continue
        v = p.get("Value"); ve = _vec(v)
        if ve is not None: vals[n] = ve
        elif isinstance(v, list): _flat(v, vals, ov)
        elif isinstance(v, (int, float)): vals[n] = v

def _parse(jpath):
    d = json.load(open(jpath, encoding="utf-8-sig"))
    imp = d.get("Imports", [])
    exps = d.get("Exports", [])
    def cls(e):
        ci = e.get("ClassIndex", 0)
        return imp[-ci - 1].get("ObjectName", "?") if isinstance(ci, int) and ci < 0 and -ci - 1 < len(imp) else "?"
    # A component's OWN name is useless for targeting — every light in a level is "LightComponent0"
    # (TimeSquare_HighQuality: 473 lights, 2 distinct names). Identity lives one hop up, in the
    # owning actor (OuterIndex -> DirectionalLight_1 / PointLight_104 / ...), which IS unique
    # (473/473 there). Label components by their owner so they can be told apart.
    def _outer_idx(e):
        o = e.get("OuterIndex")
        return (o.get("Index") if isinstance(o, dict) else o) or 0
    def owner_of(e):
        oi = _outer_idx(e)
        oe = exps[oi - 1] if isinstance(oi, int) and 0 < oi <= len(exps) else None
        if not oe:
            return None
        on = oe.get("ObjectName")
        # a component parented straight to the level has no meaningful actor name
        return None if not on or str(on) == "PersistentLevel" else str(on)
    def label_of(e):
        own = owner_of(e)
        cn = str(e.get("ObjectName", "?"))
        return f"{own} · {cn}" if own else cn
    comps, lights, fog = [], [], None
    for i, e in enumerate(d.get("Exports", [])):
        cn = cls(e); data = e.get("Data") or []
        en, vals, ov, ppv, has_loc, intensity, color = {}, {}, set(), False, False, None, None
        xf = {}
        for p in data:
            if not isinstance(p, dict): continue
            nm = p.get("Name", "?")
            if nm in ENABLE and _pt(p) == "BoolPropertyData": en[nm] = bool(p.get("Value"))
            if nm in XFORM:
                xv = _xform_vals(p)
                if xv: xf[nm] = [round(q, 3) for q in xv]
            if nm == "RelativeLocation": has_loc = True
            if nm == "Settings" and isinstance(p.get("Value"), list): ppv = True; _flat(p["Value"], vals, ov)
            if nm == "Intensity" and isinstance(p.get("Value"), (int, float)): intensity = p["Value"]
            if nm == "LightColor": color = _color_str(p.get("Value"))
        if "Light" in cn and (intensity is not None or color is not None):
            lights.append({"idx": i, "name": label_of(e), "owner": owner_of(e),
                           "component": e.get("ObjectName", "?"), "cls": cn,
                           "intensity": intensity, "color": color})
        if fog is None and cn.endswith("HeightFogComponent"):
            fd = fc = fpos = None
            for p in data:
                if not isinstance(p, dict): continue
                nm = p.get("Name")
                if nm == "FogDensity" and isinstance(p.get("Value"), (int, float)): fd = p["Value"]
                elif nm in ("FogInscatteringLuminance", "FogInscatteringColor") and isinstance(p.get("Value"), list) and p["Value"]:
                    cv = _vec((p["Value"][0] or {}).get("Value"))
                    if cv: fc = [round(x, 4) for x in cv[:3]]
                elif nm == "RelativeLocation" and isinstance(p.get("Value"), list) and p["Value"]:
                    lv = _vec((p["Value"][0] or {}).get("Value"))
                    if lv: fpos = [round(x, 2) for x in lv[:3]]
            fog = {"idx": i, "density": fd, "color": fc, "pos": fpos}
        grade = {s: ({"value": vals[s], "override": s in ov, "present": True} if s in vals
                     else {"value": GRADE_DEFAULT[s], "override": False, "present": False})
                 for s in GRADE} if ppv else {}
        comps.append({"idx": i, "name": label_of(e), "owner": owner_of(e),
                      "component": e.get("ObjectName", "?"), "cls": cn, "enables": en,
                      "is_ppv": ppv, "grade": grade,
                      "pos": xf.get("RelativeLocation"), "rot": xf.get("RelativeRotation"),
                      "scale": xf.get("RelativeScale3D"),
                      "hideable": cn.endswith("Component") or ("bVisible" in en) or has_loc})
    return {"components": comps, "lights": lights, "fog": fog}

# ── edit sidecar (persisted, same model as vfx/curve) ───────────────────────────
def world_sidecar(game_rel):
    return project_base(_norm(game_rel)) + ".json"

def _load_edits(game_rel):
    for p in (world_sidecar(game_rel), project_base_legacy(_norm(game_rel)) + ".json"):
        if os.path.exists(p):
            try: return json.load(open(p, encoding="utf-8-sig")).get("world_edits") or {}
            except Exception: return {}
    return {}

def read_world(game_rel):
    """{ok, name, components, lights, fog, edits} for the level editor. Overlays saved edits."""
    base = _ensure_extracted(game_rel)
    model = _parse(_to_json(base))
    model.update({"ok": True, "name": os.path.basename(_norm(game_rel))[:-5], "edits": _load_edits(game_rel)})
    return model

def save_world(game_rel, edits):
    _ensure_extracted(game_rel)
    clean = {
        "lights":     {str(k): {"intensity": v.get("intensity"), "color": v.get("color")}
                       for k, v in (edits.get("lights") or {}).items()},
        "fog":        {k: edits["fog"][k] for k in ("color", "density", "pos") if (edits.get("fog") or {}).get(k) is not None},
        "grade":      dict(edits.get("grade") or {}),
        "visibility": {str(k): bool(v) for k, v in (edits.get("visibility") or {}).items()},
    }
    p = world_sidecar(game_rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump({"world_edits": clean}, open(p, "w"))
    return read_world(game_rel)

def reset_world(game_rel):
    for p in (world_sidecar(game_rel), project_base_legacy(_norm(game_rel)) + ".json"):
        if os.path.exists(p): os.remove(p)
    return read_world(game_rel)

# ── edit application (all honored by from_json) ─────────────────────────────────
def _bP(n, v):
    return {"$type": "UAssetAPI.PropertyTypes.Objects.BoolPropertyData, UAssetAPI", "Name": n,
            "ArrayIndex": 0, "PropertyGuid": None, "IsZero": (not v), "PropertyTagFlags": "None",
            "PropertyTypeName": None, "PropertyTagExtensions": "NoExtension", "Value": v}

def _fP(n, v):
    return {"$type": "UAssetAPI.PropertyTypes.Objects.FloatPropertyData, UAssetAPI", "Name": n,
            "ArrayIndex": 0, "PropertyGuid": None, "IsZero": (v == 0.0), "PropertyTagFlags": "None",
            "PropertyTypeName": None, "PropertyTagExtensions": "NoExtension", "Value": v}

def _mkvec4(n, x, y, z, w=1.0):
    inner = {"$type": "UAssetAPI.PropertyTypes.Structs.Vector4PropertyData, UAssetAPI", "Name": n,
             "ArrayIndex": 0, "PropertyGuid": None, "IsZero": False, "PropertyTagFlags": "None",
             "PropertyTypeName": None, "PropertyTagExtensions": "NoExtension",
             "Value": {"$type": "UAssetAPI.UnrealTypes.FVector4, UAssetAPI", "X": x, "Y": y, "Z": z, "W": w}}
    return {"$type": "UAssetAPI.PropertyTypes.Structs.StructPropertyData, UAssetAPI",
            "StructType": "Vector4", "SerializeNone": True,
            "StructGUID": "{00000000-0000-0000-0000-000000000000}", "SerializationControl": "NoExtension",
            "Operation": "None", "Name": n, "ArrayIndex": 0, "PropertyGuid": None, "IsZero": False,
            "PropertyTagFlags": "None", "PropertyTypeName": None, "PropertyTagExtensions": "NoExtension",
            "Value": [inner]}

def _apply(d, edits):
    ex = d.get("Exports", []); applied = []
    grade = edits.get("grade") or {}
    fog   = edits.get("fog") or {}
    vis   = {int(k): bool(v) for k, v in (edits.get("visibility") or {}).items()}
    lights = {int(k): v for k, v in (edits.get("lights") or {}).items()}
    for i, e in enumerate(ex):
        data = e.get("Data") or []
        if i in vis:
            for nm, val in (("bVisible", vis[i]), ("bHiddenInGame", not vis[i])):
                hit = next((p for p in data if isinstance(p, dict) and p.get("Name") == nm and "Bool" in str(p.get("$type", ""))), None)
                if hit: hit["Value"] = val; hit["IsZero"] = (not val)
                else: data.append(_bP(nm, val))
            e["Data"] = data; applied.append(f"#{i} visible={vis[i]}")
        if i in lights:
            spec = lights[i]
            if spec.get("intensity") is not None:
                for p in data:
                    if isinstance(p, dict) and p.get("Name") == "Intensity" and isinstance(p.get("Value"), (int, float)):
                        p["Value"] = float(spec["intensity"]); p["IsZero"] = False; applied.append(f"#{i} intensity={spec['intensity']}"); break
            if spec.get("color"):
                for p in data:
                    if isinstance(p, dict) and p.get("Name") == "LightColor" and isinstance(p.get("Value"), list) and p["Value"]:
                        cur = p["Value"][0].get("Value")
                        n = len(str(cur).split(",")) if isinstance(cur, str) else 3
                        rgb = [str(int(c)) for c in spec["color"][:3]] + (["255"] if n >= 4 else [])
                        p["Value"][0]["Value"] = ", ".join(rgb[:n]); applied.append(f"#{i} color={spec['color']}"); break
        sprop = next((p for p in data if isinstance(p, dict) and p.get("Name") == "Settings" and isinstance(p.get("Value"), list)), None)
        if sprop is not None and grade:
            sv = sprop["Value"]; sp = {x.get("Name"): x for x in sv if isinstance(x, dict)}
            def isv4(x): return (isinstance(x.get("Value"), list) and x["Value"] and isinstance(x["Value"][0], dict)
                                 and isinstance(x["Value"][0].get("Value"), dict) and "X" in x["Value"][0]["Value"])
            def setb(name, v):
                if name in sp: sp[name]["Value"] = v; sp[name]["IsZero"] = (not v)
                else: sv.append(_bP(name, v)); sp[name] = sv[-1]
            for name, val in grade.items():
                if isinstance(val, (list, tuple)):
                    x, y, z = (list(val) + [0, 0, 0])[:3]
                    if name in sp and isv4(sp[name]):
                        vv = sp[name]["Value"][0]["Value"]; vv["X"], vv["Y"], vv["Z"] = x, y, z
                    else:
                        np = _mkvec4(name, x, y, z); sv.append(np); sp[name] = np
                elif name in sp and isinstance(sp[name].get("Value"), (int, float)):
                    sp[name]["Value"] = float(val)
                else:                                    # scalar not present -> add it (e.g. BloomIntensity)
                    sv.append(_fP(name, float(val))); sp[name] = sv[-1]
                setb("bOverride_" + name, True); applied.append(f"{name}={val}")
        if fog and any(isinstance(p, dict) and p.get("Name") in ("FogInscatteringLuminance", "FogDensity") for p in data):
            found_density = False
            for p in data:
                if not isinstance(p, dict): continue
                nm = p.get("Name")
                if fog.get("color") and nm in ("FogInscatteringLuminance", "FogInscatteringColor") and isinstance(p.get("Value"), list) and p["Value"]:
                    cv = p["Value"][0].get("Value")
                    if isinstance(cv, dict) and "R" in cv: cv["R"], cv["G"], cv["B"] = fog["color"][:3]; applied.append(f"fog color={fog['color']}")
                elif fog.get("density") is not None and nm == "FogDensity" and isinstance(p.get("Value"), (int, float)):
                    p["Value"] = float(fog["density"]); found_density = True; applied.append(f"fog density={fog['density']}")
                elif fog.get("pos") and nm == "RelativeLocation" and isinstance(p.get("Value"), list) and p["Value"]:
                    vv = p["Value"][0].get("Value")
                    if isinstance(vv, dict) and "X" in vv:
                        vv["X"], vv["Y"], vv["Z"] = [float(x) for x in fog["pos"][:3]]; applied.append(f"fog pos={fog['pos']}")
            if fog.get("density") is not None and not found_density:   # property absent -> add it
                data.append(_fP("FogDensity", float(fog["density"]))); e["Data"] = data
                applied.append(f"fog density={fog['density']} (added)")
    return list(dict.fromkeys(applied))

# ── faithful binary-patch build (see module docstring) ──────────────────────────
def _export_ranges(d):
    """{export_idx: (uexp_start, size)} — each export's byte span in the .uexp, from SerialOffset/
    SerialSize rebased so the first-serialized export starts at 0 (SerialOffset is package-relative;
    the smallest one marks where .uexp data begins)."""
    offs = [(i, e.get("SerialOffset"), e.get("SerialSize"))
            for i, e in enumerate(d.get("Exports", []))
            if isinstance(e.get("SerialOffset"), int) and isinstance(e.get("SerialSize"), int)]
    if not offs:
        return {}
    base = min(o for _, o, _ in offs)
    return {i: (o - base, s) for i, o, s in offs}

def _raw_ppv(d):
    """Un-rounded current values (for exact byte matching), keyed to their export index:
    (ppv_idx, pp{name:[x,y,z,w]|float}, ov{overridden names}, fog{idx,color,density,pos},
    lights{idx:{intensity, color:[r,g,b]}})."""
    imp = d.get("Imports", [])
    def cls(e):
        ci = e.get("ClassIndex", 0)
        return imp[-ci - 1].get("ObjectName", "?") if isinstance(ci, int) and ci < 0 and -ci - 1 < len(imp) else "?"
    def F(v):
        try: return float(v)
        except (TypeError, ValueError): return 0.0
    ppv_idx, pp, ov, fog, lights = None, {}, set(), {}, {}
    for i, e in enumerate(d.get("Exports", [])):
        cn = cls(e); data = e.get("Data") or []
        is_light = "Light" in cn; is_fog = cn.endswith("HeightFogComponent"); li = {}
        for pr in data:
            if not isinstance(pr, dict): continue
            nm = pr.get("Name"); v = pr.get("Value")
            if nm == "Settings" and isinstance(v, list):
                ppv_idx = i
                for x in v:
                    if not isinstance(x, dict): continue
                    xn = x.get("Name", "")
                    if xn.startswith("bOverride_") and x.get("Value") is True: ov.add(xn[10:])
                    xv = x.get("Value")
                    if isinstance(xv, list) and xv and isinstance(xv[0], dict):
                        iv = xv[0].get("Value")
                        if isinstance(iv, dict) and "X" in iv: pp[xn] = [F(iv.get(k, 0)) for k in "XYZW"]
                    elif isinstance(xv, (int, float)): pp.setdefault(xn, float(xv))
            if is_fog:
                if nm in ("FogInscatteringLuminance", "FogInscatteringColor") and isinstance(v, list) and v:
                    iv = v[0].get("Value")
                    if isinstance(iv, dict) and "R" in iv: fog.update(idx=i, color=[F(iv.get(k, 0)) for k in "RGBA"])
                elif nm == "FogDensity" and isinstance(v, (int, float)): fog.update(idx=i, density=float(v))
                elif nm == "RelativeLocation" and isinstance(v, list) and v:
                    iv = v[0].get("Value")
                    if isinstance(iv, dict) and "X" in iv: fog.update(idx=i, pos=[F(iv.get(k, 0)) for k in "XYZ"])
            if is_light:
                if nm == "Intensity" and isinstance(v, (int, float)): li["intensity"] = float(v)
                elif nm == "LightColor":
                    c = _color_str(v)
                    if c: li["color"] = c
        if is_light and li: lights[i] = li
    return ppv_idx, pp, ov, fog, lights

def stage_world(stage, game_rel, edits=None):
    """Faithfully binary-patch the edited VALUES into the vanilla sublevel and write it into the
    shared export stage. Keeps every other byte identical (no from_json re-serialization), so the
    Zen conversion can't mis-resolve references. Same-size patches only -> no SerialSize change."""
    base = _ensure_extracted(game_rel)
    ed = edits if edits is not None else _load_edits(game_rel)
    if not ed:
        raise RuntimeError("no world edits to stage")
    ua = open(base + ".uasset", "rb").read()
    ux = bytearray(open(base + ".uexp", "rb").read())
    d = json.load(open(_to_json(base), encoding="utf-8-sig"))
    ranges = _export_ranges(d)
    ppv_idx, pp, ov, fog, lights = _raw_ppv(d)
    applied, skipped = [], []

    def patch_in(idx, old, new, lbl):
        if idx is None or idx not in ranges:
            skipped.append(lbl + " (no export range)"); return
        if len(old) != len(new):
            skipped.append(lbl + " (size change)"); return
        s, sz = ranges[idx]; seg = ux[s:s + sz]; c = seg.count(old)
        if c == 1:
            j = seg.find(old); ux[s + j:s + j + len(old)] = new; applied.append(lbl)
        else:
            skipped.append(lbl + (" (not found in export)" if c == 0 else f" (x{c} in export)"))

    # GRADE vec4 — only OVERRIDDEN settings render; patch the doubles inside the PPV export.
    for name, val in (ed.get("grade") or {}).items():
        if not isinstance(val, (list, tuple)):
            skipped.append(f"grade {name} (scalar — not supported by faithful patch)"); continue
        cur = pp.get(name)
        if not cur:
            skipped.append(f"grade {name} (not in this PPV)"); continue
        if name not in ov:
            skipped.append(f"grade {name} (not overridden — would not render)"); continue
        patch_in(ppv_idx, struct.pack("<dddd", *cur),
                 struct.pack("<dddd", float(val[0]), float(val[1]), float(val[2]), cur[3]), f"grade {name}")
    # FOG (color = FLinearColor floats, density = float, pos = FVector doubles)
    f = ed.get("fog") or {}
    if f.get("color") and fog.get("color"):
        fc = fog["color"]
        patch_in(fog.get("idx"), struct.pack("<ffff", *fc),
                 struct.pack("<ffff", float(f["color"][0]), float(f["color"][1]), float(f["color"][2]), fc[3]), "fog color")
    if f.get("density") is not None and isinstance(fog.get("density"), float):
        patch_in(fog.get("idx"), struct.pack("<f", fog["density"]), struct.pack("<f", float(f["density"])), "fog density")
    if f.get("pos") and fog.get("pos"):
        fp = fog["pos"]
        patch_in(fog.get("idx"), struct.pack("<ddd", *fp),
                 struct.pack("<ddd", float(f["pos"][0]), float(f["pos"][1]), float(f["pos"][2])), "fog pos")
    # LIGHTS (intensity = float; color = FColor stored B,G,R in memory — patch BGR, keep alpha)
    for k, spec in (ed.get("lights") or {}).items():
        idx = int(k); lc = lights.get(idx, {})
        if spec.get("intensity") is not None and isinstance(lc.get("intensity"), float):
            patch_in(idx, struct.pack("<f", lc["intensity"]), struct.pack("<f", float(spec["intensity"])), f"light#{idx} intensity")
        if spec.get("color") and lc.get("color"):
            oc, nc = lc["color"], spec["color"]
            patch_in(idx, bytes([oc[2] & 255, oc[1] & 255, oc[0] & 255]),
                     bytes([int(nc[2]) & 255, int(nc[1]) & 255, int(nc[0]) & 255]), f"light#{idx} color")
    if ed.get("visibility"):
        skipped.append(f"{len(ed['visibility'])} visibility toggle(s) (bitmask bool — not supported by faithful patch)")

    if not applied:
        raise RuntimeError("no world edits could be applied faithfully: " + "; ".join(skipped[:6]))

    pak_gr = pak_game_path(_norm(game_rel))                       # Marvel/Content/Marvel/Maps/.../X.umap
    # stage as X.uasset (NOT X.umap.uasset) so the package id matches vanilla (create_mod_iostore
    # hashes the file path — the extra .umap makes a NEW package instead of an override).
    if pak_gr.lower().endswith(".umap"):
        pak_gr = pak_gr[:-5]
    out = os.path.join(stage, *pak_gr.split("/"))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out + ".uasset", "wb").write(ua)
    open(out + ".uexp", "wb").write(bytes(ux))
    return os.path.basename(_norm(game_rel))[:-5]


# ── ZEN-DIRECT build (the real level build — create_mod_iostore corrupts big maps) ──────────────
def _store_entry(vt, ucas, pkg8):
    """Faithful imported-packages + shader-map hashes for one package id, from the container header."""
    hi = next(i for i, c in enumerate(vt.chunk_ids) if c[11] == 6)
    vch = io_lib.read_chunk(vt, ucas, hi)
    u = lambda o: struct.unpack_from("<I", vch, o)[0]
    npkg = u(16); ids = 20
    k = next(j for j in range(npkg) if bytes(vch[ids + j*8:ids + j*8 + 8]) == pkg8)
    eh = ids + npkg*8 + 4 + k*16
    ipn, ipo, shn, sho = u(eh), u(eh+4), u(eh+8), u(eh+12)
    imp = [bytes(vch[eh + ipo + j*8: eh + ipo + j*8 + 8]) for j in range(ipn)]
    sh = [bytes(vch[(eh+8) + sho + j*20: (eh+8) + sho + j*20 + 20]) for j in range(shn)]
    return imp, sh

def _grade_value_offsets(d, idx, ranges, ux_leg):
    """Exact .uexp offset of each PostProcessSettings value property, resolved by walking the
    sub-props in serialization order (== byte order) and consuming value matches left-to-right with
    a monotonic cursor. This disambiguates properties that share a value (e.g. several ColorXXX left
    at the 1,1,1,1 default) — greedy in-order assignment gives each its own consecutive occurrence.
    vec4 (X/Y/Z/W or R/G/B/A) → 32 bytes; scalar float → 4 bytes; bools/objects/arrays are skipped
    (bools emit no value bytes; the rest are rare before the graded fields)."""
    exps = d.get("Exports", d.get("exports")) or []
    if idx is None or idx >= len(exps) or idx not in ranges:
        return {}
    s, sz = ranges[idx]; seg = ux_leg[s:s + sz]
    props = None
    for pr in (exps[idx].get("Data") or exps[idx].get("Properties") or []):
        if isinstance(pr, dict) and pr.get("Name") == "Settings" and isinstance(pr.get("Value"), list):
            props = pr["Value"]; break
    if not props:
        return {}
    out = {}; cur = 0
    for x in props:
        if not isinstance(x, dict) or x.get("IsZero"):
            continue
        xv = x.get("Value"); enc = None
        if isinstance(xv, list) and xv and isinstance(xv[0], dict):
            iv = xv[0].get("Value")
            if isinstance(iv, dict) and "X" in iv:
                enc = struct.pack("<dddd", *[float(iv.get(k, 0)) for k in "XYZW"])
            elif isinstance(iv, dict) and "R" in iv:
                enc = struct.pack("<ffff", *[float(iv.get(k, 0)) for k in "RGBA"])
        elif isinstance(xv, (int, float)) and not isinstance(xv, bool):
            enc = struct.pack("<f", float(xv))
        if enc is None:
            continue
        j = seg.find(enc, cur)
        if j < 0:
            j = seg.find(enc)
        if j < 0:
            continue
        out[x.get("Name", "")] = s + j
        cur = j + len(enc)
    return out

def _export_prop_offsets(d, idx, ranges, ux_leg):
    """Exact .uexp offset of an export's OWN top-level value properties — same ordered walk as
    _grade_value_offsets, but one level up (Intensity/LightColor/FogDensity live directly on the
    component, not inside a Settings struct).

    Without this, lights/fog reach patch() with only an export index, so they rely on the value being
    unique INSIDE the export and otherwise fall back to a chunk-wide search. That fails on exactly the
    values people edit: a DirectionalLight at Intensity 2.0 is `00 00 00 40`, which recurs thousands of
    times in a 2 MB chunk -> "(not unique)". Measured: KunlunEC01 light#62 and NewyorkH02 light#34 both
    failed this way while every other light on those same maps patched fine."""
    exps = d.get("Exports", d.get("exports")) or []
    if idx is None or idx >= len(exps) or idx not in ranges:
        return {}
    s, sz = ranges[idx]; seg = ux_leg[s:s + sz]
    out = {}; cur = 0
    for x in (exps[idx].get("Data") or exps[idx].get("Properties") or []):
        if not isinstance(x, dict) or x.get("IsZero"):
            continue
        t = _pt(x); xv = x.get("Value"); enc = None
        if t == "FloatPropertyData" and isinstance(xv, (int, float)) and not isinstance(xv, bool):
            enc = struct.pack("<f", float(xv))
        elif t == "ColorPropertyData":
            c = _color_str(xv)                      # FColor serializes B,G,R,A; patch() writes the BGR
            if c: enc = bytes([c[2] & 255, c[1] & 255, c[0] & 255])
        else:
            enc = _xform_enc(x)                     # RelativeLocation/Rotation/Scale3D -> 3 doubles
        if enc is None:
            continue
        j = seg.find(enc, cur)
        if j < 0:
            j = seg.find(enc)
        if j < 0:
            continue
        out[x.get("Name", "")] = s + j
        cur = j + len(enc)
    return out

def build_world_mod(game_rel, edits, out_base):
    """Patch the edited VALUES into the vanilla Zen chunk (read from the game container) and rebuild
    the container with io_lib — NEVER create_mod_iostore (it corrupts big level packages). Writes
    out_base.{pak,ucas,utoc}. Grade/fog patch by byte-unique value; lights are best-effort (colors
    aren't unique in the Zen chunk). Returns {ok, applied, skipped}."""
    gr = _norm(game_rel)
    if edits is None:
        edits = _load_edits(game_rel)
    path, conts = _locate(gr)
    if not path:
        return {"ok": False, "error": "sublevel not found in the map enum: " + gr}
    sub = os.path.basename(gr)[:-5]
    aes = "0x" + get_aes_key()
    ua = os.path.join(_CACHE, "world_zen", re.sub(r"\W+", "_", gr).strip("_") + "_u")
    if not glob.glob(ua + "/**/*.uasset", recursive=True):
        shutil.rmtree(ua, ignore_errors=True)
        for cc in conts:
            subprocess.run([RETOC, "-a", aes, "unpack", os.path.join(PAKS, cc), "--filter", path,
                            "--game-paks-dir", PAKS, "-o", ua], capture_output=True, creationflags=CNW)
            if glob.glob(ua + "/**/*.uasset", recursive=True): break
    if not glob.glob(ua + "/**/*.uasset", recursive=True):
        return {"ok": False, "error": "retoc unpack produced no .uasset for " + sub}
    out = os.path.join(_CACHE, "world_zen_out"); os.makedirs(out, exist_ok=True)
    stage = os.path.join(_CACHE, "world_zen_stage", sub)
    shutil.rmtree(stage, ignore_errors=True); os.makedirs(os.path.dirname(stage), exist_ok=True)
    shutil.copytree(ua, stage)
    rp = subprocess.run([RETOC, "-a", aes, "pack", stage, "-o", out, "--game-paks-dir", PAKS],
                        capture_output=True, text=True, creationflags=CNW)
    tmpl = sorted(glob.glob(f"{out}/{sub}_*_P.utoc"))
    if not tmpl:
        return {"ok": False, "error": "retoc template pack failed:\n" + ((rp.stdout or "") + (rp.stderr or ""))[-500:]}
    MB = tmpl[-1][:-5]; mt = io_lib.parse_toc(MB + ".utoc")
    if mt.phash_seed_count or mt.chunks_wo_phash or mt.signed:
        return {"ok": False, "error": "template has phash/signature sections (unsupported)"}
    i1 = next(i for i, c in enumerate(mt.chunk_ids) if c[11] == 6)
    i0 = next((i for i in range(len(mt.chunk_ids)) if mt.chunk_ids[i][11] != 6), None)
    if i0 is None:
        return {"ok": False, "error": "template has no data chunk"}
    TARGET = mt.chunk_ids[i0]
    c0 = vt = vcas = None
    for cc in conts:
        t = io_lib.parse_toc(os.path.join(PAKS, cc))
        if TARGET in t.chunk_ids:
            vcas = os.path.join(PAKS, cc)[:-5] + ".ucas"
            c0 = bytearray(io_lib.read_chunk(t, vcas, t.chunk_ids.index(TARGET))); vt = t; break
    if c0 is None:
        return {"ok": False, "error": "vanilla chunk not found in any container for " + sub}

    base_leg = _ensure_extracted(gr)
    d = json.load(open(_to_json(base_leg), encoding="utf-8-sig"))
    ux_leg = open(base_leg + ".uexp", "rb").read()
    ranges = _export_ranges(d)
    _ppv_idx, pp, ov, fog, lights = _raw_ppv(d)
    goff = _grade_value_offsets(d, _ppv_idx, ranges, ux_leg)  # {propname: exact .uexp offset}
    applied, skipped, gc0 = [], [], {}  # gc0: grade name -> located byte offset in c0
    # export idx -> (c0 offset - ux_leg offset). The context-window locate reads the window from the
    # PRISTINE legacy .uexp but searches c0, which earlier patches have already modified — so editing
    # two ADJACENT properties of one export (pos/rot/scale sit side by side) makes the second locate
    # miss its window and silently skip. The export's bytes are contiguous and identical in both, so
    # once any one property is pinned the delta is constant for the whole export; reuse it.
    expdelta = {}
    def patch(old, new, lbl, idx=None, at=None):
        # Region-local locate: bare value-search fails when a grade value is a common number
        # (0.5, 1.0 …) that recurs across the ~2 MB Zen chunk. The export DATA is byte-identical
        # between the legacy .uexp and the Zen chunk, so a context window from the legacy export
        # (value + surrounding property bytes) pins the RIGHT byte in c0. `at` is the property's
        # exact .uexp offset (from the ordered walk) so it works even when the value repeats inside
        # the export; else fall back to a unique-in-export value, else a bare chunk-wide search.
        if len(old) != len(new): skipped.append(lbl + " (size)"); return
        vpos = None
        if at is not None and ux_leg[at:at + len(old)] == old:
            vpos = at
        elif idx is not None and idx in ranges:
            s, sz = ranges[idx]; seg = ux_leg[s:s + sz]
            if seg.count(old) == 1: vpos = s + seg.find(old)
        if vpos is not None and idx is not None and idx in expdelta:
            vp = vpos + expdelta[idx]                       # this export is already pinned in c0
            if vp >= 0 and bytes(c0[vp:vp + len(old)]) == old:
                c0[vp:vp + len(old)] = new; applied.append(lbl)
                if lbl.startswith("grade "): gc0[lbl[6:]] = vp
                return
        if vpos is not None:
            for pad in (24, 48, 96, 160, 256):
                ws = max(0, vpos - pad); we = vpos + len(old) + pad
                win = ux_leg[ws:we]
                if c0.count(win) == 1:
                    vp = c0.find(win) + (vpos - ws)
                    if bytes(c0[vp:vp + len(old)]) == old:
                        c0[vp:vp + len(old)] = new; applied.append(lbl)
                        if idx is not None: expdelta[idx] = vp - vpos
                        if lbl.startswith("grade "): gc0[lbl[6:]] = vp
                        return
                    break  # window found but value shifted → framing differs, drop to bare
        n = c0.count(old)
        if n == 1:
            i = c0.find(old); c0[i:i + len(old)] = new; applied.append(lbl)
            if idx is not None and vpos is not None: expdelta[idx] = i - vpos
            if lbl.startswith("grade "): gc0[lbl[6:]] = i
        else:
            skipped.append(lbl + (" (not found)" if n == 0 else " (not unique)"))
    for name, val in (edits.get("grade") or {}).items():
        if isinstance(val, (list, tuple)):
            cur = pp.get(name)
            if not cur: skipped.append(f"grade {name} (not in PPV)"); continue
            if name not in ov: skipped.append(f"grade {name} (not overridden)"); continue
            patch(struct.pack("<dddd", *cur),
                  struct.pack("<dddd", float(val[0]), float(val[1]), float(val[2]), cur[3]), f"grade {name}", _ppv_idx, goff.get(name))
        else:
            cur = pp.get(name)
            if isinstance(cur, float) and name in ov:
                patch(struct.pack("<f", cur), struct.pack("<f", float(val)), f"grade {name}", _ppv_idx, goff.get(name))
            else:
                skipped.append(f"grade {name} (scalar not overridden)")
    # Delta-anchor recovery: a grade field wedged between an equal-valued neighbor and a framing
    # boundary can't form a unique window. The ColorXXX doubles are a contiguous, byte-identical run
    # in both the legacy .uexp and the Zen chunk, so a skipped field's chunk position = a located
    # sibling's position + the .uexp offset delta. The round-trip check keeps it correct.
    for name, val in (edits.get("grade") or {}).items():
        if name not in goff or f"grade {name}" in applied:
            continue
        if not any(s.startswith(f"grade {name} ") for s in skipped):
            continue
        cur = pp.get(name)
        if isinstance(val, (list, tuple)) and cur:
            old = struct.pack("<dddd", *cur)
            new = struct.pack("<dddd", float(val[0]), float(val[1]), float(val[2]), cur[3])
        elif isinstance(cur, float):
            old = struct.pack("<f", cur); new = struct.pack("<f", float(val))
        else:
            continue
        for an, avp in sorted(gc0.items(), key=lambda kv: abs(goff.get(kv[0], 1 << 60) - goff[name])):
            if an not in goff:
                continue
            vp = avp + (goff[name] - goff[an])
            if 0 <= vp <= len(c0) - len(old) and bytes(c0[vp:vp + len(old)]) == old:
                c0[vp:vp + len(old)] = new
                applied.append(f"grade {name}")
                skipped[:] = [s for s in skipped if not s.startswith(f"grade {name} ")]
                gc0[name] = vp
                break
    f = edits.get("fog") or {}
    if f.get("color") and fog.get("color"):
        fc = fog["color"]
        patch(struct.pack("<ffff", *fc),
              struct.pack("<ffff", float(f["color"][0]), float(f["color"][1]), float(f["color"][2]), fc[3]), "fog color", fog.get("idx"))
    if f.get("density") is not None and isinstance(fog.get("density"), float):
        fo = _export_prop_offsets(d, fog.get("idx"), ranges, ux_leg)
        patch(struct.pack("<f", fog["density"]), struct.pack("<f", float(f["density"])), "fog density",
              fog.get("idx"), fo.get("FogDensity"))
    if f.get("pos") and fog.get("pos"):
        fp = fog["pos"]
        patch(struct.pack("<ddd", *fp),
              struct.pack("<ddd", float(f["pos"][0]), float(f["pos"][1]), float(f["pos"][2])), "fog pos", fog.get("idx"))
    for k, spec in (edits.get("lights") or {}).items():
        lc = lights.get(int(k), {})
        lo = _export_prop_offsets(d, int(k), ranges, ux_leg)
        if spec.get("intensity") is not None and isinstance(lc.get("intensity"), float):
            patch(struct.pack("<f", lc["intensity"]), struct.pack("<f", float(spec["intensity"])),
                  f"light#{k} intensity", int(k), lo.get("Intensity"))
        if spec.get("color") and lc.get("color"):
            oc, nc = lc["color"], spec["color"]
            patch(bytes([oc[2] & 255, oc[1] & 255, oc[0] & 255]),
                  bytes([int(nc[2]) & 255, int(nc[1]) & 255, int(nc[0]) & 255]),
                  f"light#{k} color", int(k), lo.get("LightColor"))
    # TRANSFORMS (move/rotate/scale any component). Fixed-width like fog pos — FVector/FRotator are
    # 3 doubles — so geometry is the EASY case: pure overwrite, no export growth, no add-override.
    # Only components whose transform vanilla already serialized can move (a mesh left at its default
    # has no bytes to patch); TimeSquare_Art serializes 1814 locations / 1490 rotations / 754 scales.
    exps_all = d.get("Exports", d.get("exports")) or []
    for k, spec in (edits.get("comps") or {}).items():
        i = int(k)
        if not (0 <= i < len(exps_all)): skipped.append(f"comp#{k} (bad index)"); continue
        props = {p.get("Name"): p for p in (exps_all[i].get("Data") or []) if isinstance(p, dict)}
        offs = _export_prop_offsets(d, i, ranges, ux_leg)
        for key, nm in (("pos", "RelativeLocation"), ("rot", "RelativeRotation"), ("scale", "RelativeScale3D")):
            val = spec.get(key)
            if val is None: continue
            cur = _xform_vals(props.get(nm) or {})
            if cur is None:
                skipped.append(f"comp#{k} {key} ({nm} not serialized — can't move what vanilla left default)")
                continue
            # read_world rounds for display, so an untouched axis comes back as round(cur,3) and would
            # be rewritten as the ROUNDED double — nudging axes the user never edited. Snap any axis
            # that still matches its rounded self back to vanilla's exact bits; only real edits land.
            new = [float(x) for x in val[:3]]
            new = [cur[j] if round(cur[j], 3) == round(new[j], 3) else new[j] for j in range(3)]
            if new == cur:
                skipped.append(f"comp#{k} {key} (unchanged)")
                continue
            patch(struct.pack("<ddd", *cur), struct.pack("<ddd", *new), f"comp#{k} {key}", i, offs.get(nm))
    if edits.get("visibility"):
        skipped.append(f"{len(edits['visibility'])} visibility toggle(s) (not supported by Zen-direct)")
    if not applied:
        return {"ok": False, "error": "nothing patched faithfully: " + "; ".join(skipped[:6])}

    imp, sh = _store_entry(vt, vcas, bytes(TARGET[:8]))
    chh0 = io_lib.read_chunk(mt, MB + ".ucas", i1)
    ip_data = b"".join(imp); sh_data = b"".join(sh); sh_off = (16 + len(ip_data)) - 8 if sh else 0
    blob = struct.pack("<IIII", len(imp), 16, len(sh), sh_off) + ip_data + sh_data
    ose = struct.unpack_from("<I", chh0, 0x1c)[0]
    chh = bytes(chh0[:0x1c]) + struct.pack("<I", len(blob)) + blob + bytes(chh0[0x20 + ose:])
    CB = mt.cblk_size
    def split(dd): return [dd[x:x + CB] for x in range(0, len(dd), CB)] or [b""]
    data_for = lambda idx: bytes(c0) if idx == i0 else (chh if idx == i1 else io_lib.read_chunk(mt, MB + ".ucas", idx))
    ucas = bytearray(); blk = []; offl = {}; metas = {}
    for idx in range(mt.entry_count):
        dat = data_for(idx); offl[idx] = (len(blk) * CB, len(dat)); metas[idx] = hashlib.sha1(dat).digest()
        for b in split(dat): blk.append((len(ucas), len(b), len(b), 0)); ucas += b
    hdr = bytearray(mt.buf[:144]); struct.pack_into("<I", hdr, 28, len(blk))
    buf = bytearray(hdr) + mt.buf[mt.off_chunkids: mt.off_chunkids + 12 * mt.entry_count]
    for idx in range(mt.entry_count):
        o, l = offl[idx]; buf += o.to_bytes(5, "big") + l.to_bytes(5, "big")
    for bo, cs, us, mi in blk:
        buf += bo.to_bytes(5, "little") + cs.to_bytes(3, "little") + us.to_bytes(3, "little") + bytes([mi])
    buf += mt.buf[mt.off_methods: mt.off_methods + mt.cm_name_count * mt.cm_name_len]
    buf += mt.buf[mt.off_dirindex: mt.off_dirindex + mt.dir_index_size]
    for idx in range(mt.entry_count):
        m = bytearray(mt.meta[idx]); m[:20] = metas[idx]; buf += bytes(m)
    os.makedirs(os.path.dirname(out_base), exist_ok=True)
    open(out_base + ".utoc", "wb").write(buf); open(out_base + ".ucas", "wb").write(ucas)
    if os.path.abspath(MB + ".pak") != os.path.abspath(out_base + ".pak"):
        shutil.copy(MB + ".pak", out_base + ".pak")
    return {"ok": True, "applied": applied, "skipped": skipped}


# ── UAssetGUI ADD-OVERRIDE build (turn settings ON, not just edit already-on ones) ──────────────
def _zero_name_hashes(path):
    """MR's vanilla packages ship FName hashes ZEROED; UAssetGUI's fromjson computes and writes real
    ones for every name in the map. Verified on TimeSquare_HighQuality: a pure round-trip (and even a
    real light edit) leaves the .uexp byte-identical and changes the .uasset in EXACTLY 154 places —
    all of them zero->hash, zero legitimate edits. Every name mismatches, including the
    BlueprintGeneratedClass entries (BP_Common_Lighting_03_C, BP_Color, /Script/MarvelAI), which is
    what broke blueprint references on world builds. Zero them back in place.

    The summary is walked (not hardcoded) because FolderName is variable-length, so NameCount/
    NameOffset don't sit at fixed offsets across levels."""
    b = bytearray(open(path, "rb").read())
    o = 4                                              # skip Tag
    (legacy,) = struct.unpack_from("<i", b, o); o += 4
    o += 4                                             # LegacyUE3Version
    o += 4                                             # FileVersionUE4
    if legacy <= -8: o += 4                            # FileVersionUE5
    o += 4                                             # FileVersionLicenseeUE4
    (cv,) = struct.unpack_from("<i", b, o); o += 4      # CustomVersions: GUID(16) + int32 each
    o += cv * 20
    o += 4                                             # TotalHeaderSize
    (fn,) = struct.unpack_from("<i", b, o); o += 4      # FolderName (FString)
    o += fn if fn >= 0 else (-fn) * 2
    o += 4                                             # PackageFlags
    (name_count,) = struct.unpack_from("<i", b, o); o += 4
    (name_offset,) = struct.unpack_from("<i", b, o)
    p = name_offset
    zeroed = 0
    for _ in range(name_count):
        (n,) = struct.unpack_from("<i", b, p); p += 4
        p += n if n >= 0 else (-n) * 2                 # the name string
        if p + 4 > len(b): break
        if b[p:p + 4] != b"\x00\x00\x00\x00":
            b[p:p + 4] = b"\x00\x00\x00\x00"           # NonCasePreserving + CasePreserving hashes
            zeroed += 1
        p += 4
    open(path, "wb").write(bytes(b))
    return zeroed

def _uag_bool(n):
    return {"$type": "UAssetAPI.PropertyTypes.Objects.BoolPropertyData, UAssetAPI", "Name": n,
            "ArrayIndex": 0, "PropertyGuid": None, "IsZero": False, "PropertyTagFlags": "None",
            "PropertyTypeName": None, "PropertyTagExtensions": "NoExtension", "Value": True}

def _uag_float(n, v):
    return {"$type": "UAssetAPI.PropertyTypes.Objects.FloatPropertyData, UAssetAPI", "Name": n,
            "ArrayIndex": 0, "PropertyGuid": None, "IsZero": (v == 0.0), "PropertyTagFlags": "None",
            "PropertyTypeName": None, "PropertyTagExtensions": "NoExtension", "Value": v}

def _uag_vec4(n, x, y, z, w=1.0):
    # build an FVector4 grade prop from scratch (grade_pp-proven) — used when the PPV has no existing
    # Vector4 grade prop to clone as a template, so ANY color setting can be added on ANY map.
    return {"$type": "UAssetAPI.PropertyTypes.Structs.StructPropertyData, UAssetAPI", "StructType": "Vector4",
            "SerializeNone": True, "StructGUID": "{00000000-0000-0000-0000-000000000000}",
            "SerializationControl": "NoExtension", "Operation": "None", "Name": n, "ArrayIndex": 0,
            "PropertyGuid": None, "IsZero": False, "PropertyTagFlags": "None", "PropertyTypeName": None,
            "PropertyTagExtensions": "NoExtension",
            "Value": [{"$type": "UAssetAPI.PropertyTypes.Structs.Vector4PropertyData, UAssetAPI", "Name": n,
                       "ArrayIndex": 0, "PropertyGuid": None, "IsZero": False, "PropertyTagFlags": "None",
                       "PropertyTypeName": None, "PropertyTagExtensions": "NoExtension",
                       "Value": {"$type": "UAssetAPI.UnrealTypes.FVector4, UAssetAPI", "X": x, "Y": y, "Z": z, "W": w}}]}

def _apply_uag_edits(d, edits):
    """Apply the editor's {grade, fog, lights} onto a UAssetGUI JSON, grade_pp-style: SET the value and
    turn the bOverride_ ON (adding either from scratch if absent — a Vector4 grade prop is deepcopied as
    the template). This is what makes 'dimmed' (off) settings actually apply. Returns the applied list."""
    import copy as _copy
    ex = d.get("Exports", []); im = d.get("Imports", [])
    def clsname(i):
        if not isinstance(i, int) or i == 0: return None
        return ex[i-1].get("ObjectName") if 0 < i <= len(ex) else (im[-i-1].get("ObjectName") if i < 0 and -i-1 < len(im) else None)
    applied = []
    grade = edits.get("grade") or {}
    fog = edits.get("fog") or {}
    lights = {int(k): v for k, v in (edits.get("lights") or {}).items()}
    for ei, e in enumerate(ex):
        cls = str(clsname(e.get("ClassIndex")))
        if grade:  # PPV identified by a Settings-list property, NOT ObjectName (Arakko's is "Post_Global_0")
            for p in e.get("Data", []):
                if not (isinstance(p, dict) and p.get("Name") == "Settings" and isinstance(p.get("Value"), list)):
                    continue
                sv = p["Value"]; sp = {x.get("Name"): x for x in sv if isinstance(x, dict)}
                def isv4(x):
                    return isinstance(x.get("Value"), list) and x["Value"] and isinstance(x["Value"][0], dict) \
                        and isinstance(x["Value"][0].get("Value"), dict) and "X" in x["Value"][0]["Value"]
                tmpl = next((sp[k] for k in sp if isv4(sp[k])), None)
                for name, val in grade.items():
                    if isinstance(val, (list, tuple)) and len(val) >= 3:
                        if name in sp and isv4(sp[name]):
                            vv = sp[name]["Value"][0]["Value"]; vv["X"], vv["Y"], vv["Z"] = float(val[0]), float(val[1]), float(val[2])
                        elif tmpl is not None:
                            np = _copy.deepcopy(tmpl); np["Name"] = name; np["Value"][0]["Name"] = name
                            vv = np["Value"][0]["Value"]; vv["X"], vv["Y"], vv["Z"] = float(val[0]), float(val[1]), float(val[2])
                            if "W" in vv: vv["W"] = 1.0
                            sv.append(np); sp[name] = np
                        else:
                            sv.append(_uag_vec4(name, float(val[0]), float(val[1]), float(val[2])))
                            sp[name] = sv[-1]
                    else:
                        v = float(val)
                        if name in sp and isinstance(sp[name].get("Value"), (int, float)):
                            sp[name]["Value"] = v
                        else:
                            sv.append(_uag_float(name, v)); sp[name] = sv[-1]
                    k = "bOverride_" + name
                    if k in sp: sp[k]["Value"] = True; sp[k]["IsZero"] = False
                    else: sv.append(_uag_bool(k)); sp[k] = sv[-1]
                    applied.append("grade " + name)
        if cls == "ExponentialHeightFogComponent" and fog:
            for p in e.get("Data", []):
                nm2 = p.get("Name") if isinstance(p, dict) else None
                if nm2 in ("FogInscatteringLuminance", "FogInscatteringColor") and fog.get("color") \
                        and isinstance(p.get("Value"), list) and p["Value"]:
                    iv = p["Value"][0].get("Value")
                    if isinstance(iv, dict) and "R" in iv:
                        c = fog["color"]; iv["R"], iv["G"], iv["B"] = float(c[0]), float(c[1]), float(c[2]); applied.append("fog color")
                elif nm2 == "FogDensity" and fog.get("density") is not None and isinstance(p.get("Value"), (int, float)):
                    p["Value"] = float(fog["density"]); applied.append("fog density")
                elif nm2 == "RelativeLocation" and fog.get("pos") and isinstance(p.get("Value"), list) and p["Value"]:
                    iv = p["Value"][0].get("Value")
                    if isinstance(iv, dict) and "X" in iv:
                        pos = fog["pos"]; iv["X"], iv["Y"], iv["Z"] = float(pos[0]), float(pos[1]), float(pos[2]); applied.append("fog pos")
        if ei in lights or (ei + 1) in lights:
            spec = lights.get(ei) or lights.get(ei + 1) or {}
            for p in e.get("Data", []):
                if not isinstance(p, dict): continue
                if p.get("Name") == "Intensity" and spec.get("intensity") is not None and isinstance(p.get("Value"), (int, float)):
                    p["Value"] = float(spec["intensity"]); applied.append("light#%d intensity" % ei)
                elif p.get("Name") == "LightColor" and spec.get("color"):
                    # LightColor is a StructPropertyData whose Value is a LIST holding one
                    # ColorPropertyData whose Value is the STRING "R, G, B" (471/471 in
                    # TimeSquare_HighQuality — no alpha variants). The old code tested
                    # isinstance(Value, dict) and indexed R/G/B keys, which never matched a list,
                    # so every colour edit silently did nothing while intensity edits worked.
                    v = p.get("Value")
                    if isinstance(v, list) and v and isinstance(v[0], dict) and isinstance(v[0].get("Value"), str):
                        c = spec["color"]
                        v[0]["Value"] = "%d, %d, %d" % (int(c[0]), int(c[1]), int(c[2]))
                        applied.append("light#%d color" % ei)
    return applied

def build_world_uag(game_rel, edits, out_base):
    """ADD-OVERRIDE level build via the faithful UAssetGUI round-trip + retoc pack. Turns settings ON
    (grade/fog/lights), not just edits already-on ones. retoc unpack gives the container path structure;
    UAssetTool extracts the vanilla legacy asset; UAssetGUI tojson->edit->fromjson re-serializes it
    faithfully (UAssetTool from_json would corrupt the PPV refs); retoc packs it. Writes out_base.{pak,
    ucas,utoc}. Returns {ok, applied, skipped}."""
    gr = _norm(game_rel)
    if edits is None:
        edits = _load_edits(game_rel)
    if not edits:
        return {"ok": False, "error": "no world edits to build"}
    path, conts = _locate(gr)
    if not path:
        return {"ok": False, "error": "sublevel not found: " + gr}
    sub = os.path.basename(gr)[:-5]; aes = "0x" + get_aes_key()
    mapname = _uag_mapping()

    ua = os.path.join(_CACHE, "uag_unpack", re.sub(r"\W+", "_", gr).strip("_"))
    shutil.rmtree(ua, ignore_errors=True); os.makedirs(ua, exist_ok=True)
    for cc in conts:
        subprocess.run([RETOC, "-a", aes, "unpack", os.path.join(PAKS, cc), "--filter", path,
                        "--game-paks-dir", PAKS, "-o", ua], capture_output=True, creationflags=CNW)
        if glob.glob(ua + "/**/*.uasset", recursive=True): break
    rlist = [f for f in glob.glob(ua + "/**/*.uasset", recursive=True) if os.path.basename(f)[:-7] == sub]
    if not rlist:
        return {"ok": False, "error": "retoc unpack produced no .uasset for " + sub}
    r_ua = rlist[0]; r_ux = r_ua[:-7] + ".uexp"

    # Round-trip UAssetTool's extract, NOT retoc's unpacked copy.
    # Tempting to use retoc's (it carries RetocRawExp_ encodings for imports it can't name), but
    # MEASURED: vanilla's Zen import map is 1328 bytes = 166 imports, matching UAT's extract 1:1.
    # retoc's unpack EXPANDS those to 199 legacy imports and its pack does not collapse them back,
    # so round-tripping retoc's copy inflates the packed import map to 199 (+264 bytes), shifts
    # every summary offset by +256 and drops an 8-byte export hash. UAT's copy re-packs at the
    # correct 166.
    cb = _ensure_extracted(gr)
    for e in (".uasset", ".uexp", ".ubulk"):
        if os.path.exists(cb + e):
            try: os.remove(cb + e)
            except OSError: pass
    cb = _ensure_extracted(gr)
    td = os.path.join(_CACHE, "uag_edit", re.sub(r"\W+", "_", gr).strip("_"))
    shutil.rmtree(td, ignore_errors=True); os.makedirs(td)
    base = os.path.join(td, "a")
    for e in (".uasset", ".uexp", ".ubulk"):
        if os.path.exists(cb + e): shutil.copy(cb + e, base + e)

    # UAssetGUI tojson (retry: it intermittently emits a partial parse)
    jf = base + ".json"; d = None
    for _ in range(8):
        if os.path.exists(jf):
            try: os.remove(jf)
            except OSError: pass
        _uag(["tojson", os.path.abspath(base + ".uasset"), os.path.abspath(jf), "VER_UE5_3", mapname])
        if os.path.exists(jf):
            try: dd = json.load(open(jf, encoding="utf-8-sig"))
            except Exception: continue
            if any(isinstance(p, dict) and p.get("Name") == "Settings" and isinstance(p.get("Value"), list)
                   and len(p["Value"]) > 20 for e in dd.get("Exports", []) for p in (e.get("Data") or [])):
                d = dd; break
    if d is None:
        return {"ok": False, "error": "UAssetGUI tojson never fully parsed the PPV for " + sub}

    applied = _apply_uag_edits(d, edits)
    if not applied:
        return {"ok": False, "error": "no edits applied (nothing to grade/fog/light on " + sub + ")"}
    json.dump(d, open(jf, "w", encoding="utf-8"), indent=2, ensure_ascii=False)

    out_ua = base + "_out.uasset"
    for e in (".uasset", ".uexp"):
        p = base + "_out" + e
        if os.path.exists(p):
            try: os.remove(p)
            except OSError: pass
    _uag(["fromjson", os.path.abspath(jf), os.path.abspath(out_ua), mapname])
    if not os.path.exists(base + "_out.uexp"):
        return {"ok": False, "error": "UAssetGUI fromjson produced no .uexp for " + sub}
    # fromjson writes real FName hashes where MR ships zeros -> every name (incl. the
    # BlueprintGeneratedClass entries) mismatches and blueprint refs break in-game. Restore them.
    _zero_name_hashes(out_ua)
    shutil.copy(out_ua, r_ua); shutil.copy(base + "_out.uexp", r_ux)

    out = os.path.join(_CACHE, "uag_pack", re.sub(r"\W+", "_", gr).strip("_"))
    shutil.rmtree(out, ignore_errors=True); os.makedirs(out)
    rp = subprocess.run([RETOC, "-a", aes, "pack", ua, "-o", out, "--game-paks-dir", PAKS],
                        capture_output=True, text=True, creationflags=CNW)
    tocs = sorted(glob.glob(out + "/*.utoc"))
    if not tocs:
        return {"ok": False, "error": "retoc pack failed:\n" + ((rp.stdout or "") + (rp.stderr or ""))[-400:]}
    MB = tocs[-1][:-5]
    os.makedirs(os.path.dirname(out_base), exist_ok=True)
    for ext in (".utoc", ".ucas", ".pak"):
        if os.path.exists(MB + ext): shutil.copy(MB + ext, out_base + ext)
    return {"ok": True, "applied": applied, "skipped": []}
