import os, re, json, hashlib, threading, urllib.request
from atelier.catalogue import catalogue
from atelier.config import ROOT, TOOLS, get_import_root, project_base, project_base_legacy, project_game_rel
from atelier.index import ensure_index
from atelier.paths import (skin_entries, skin_rel, game_rel_for_skin,
                           char_id as get_char_id)
from atelier.skin_name_fixes import correct_skin_name, merge_reference

def _imported_exists(game_rel, ext):
    """A project copy exists at the unique subfolder path, or at the legacy flat path (back-compat)."""
    return (ext == '.blend' and os.path.exists(project_base(game_rel)+'.mesh.json')) or (os.path.exists(project_base(game_rel) + ext)
            or os.path.exists(project_base_legacy(game_rel) + ext))

def _edited_swatches(game_rel, limit=6):
    """An edited material's colours for its card, as the editor shows them: each stored value
    divided by its HDR intensity, max(rgb, 1). Distinct colours only, in parameter order."""
    from atelier.handlers.material import _mat_params
    for base in (project_base(game_rel), project_base_legacy(game_rel)):
        try:
            with open(base + '.json', encoding='utf-8-sig') as f:
                colors, _ = _mat_params(json.load(f))
        except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError):
            continue
        out = []
        for color in colors:
            r, g, b = color['rgba'][:3]
            scale = max(r, g, b, 1)
            value = '#' + ''.join(f'{round(min(1, max(0, v / scale)) * 255):02x}' for v in (r, g, b))
            if value not in out:
                out.append(value)
            if len(out) == limit:
                break
        return out
    return []

_REMOTE_MD_URL   = "https://raw.githubusercontent.com/donutman07/MarvelRivalsCharacterIDs/refs/heads/main/MarvelRivalsCharacterIDs.md"
_update_callback = None   # set by routes.py to _push_sse after it's defined
_fetch_attempted = False
_fetch_lock      = threading.Lock()

# Paths (relative to Marvel/Content/Marvel/) where skin browsing is used
# (immediate children are char IDs, grandchildren are skin IDs navigated via _browse_skin).
HERO_PATHS = ["Characters"]

# Paths where 4-digit children = char IDs and 7-digit grandchildren = skin IDs for label display.
# Browsing inside these (at skin level) uses _browse_pak_level, not _browse_skin.
CHAR_LABEL_PATHS = ["Characters", "VFX/Materials/Characters"]

# Folders pinned to the top at the root level (in order).
ROOT_PINNED = ("characters", "vfx", "ui", "nameplates", "plugins", "marvel_lq")

# Nameplates are three separate assets that must ALL be replaced for one plate to change, and
# nothing in the tree says so: winterwintour found the blueprint node empty, ghostex101 and diiea
# both hunted for the files, and shafsta had to post the paths by hand. They live far apart under
# UI/Textures, so a curated section is the only place they can be seen together.
NAMEPLATE_PATHS = [
    ("UI/Textures/Show/NameplateFrame",  "In game — the plate shown over your head"),
    ("UI/Textures/Item/NameplateFrame",  "Cosmetic menu — the selection grid"),
    ("UI/Textures/Show/PlayerheadFrame", "Cropped icon — the round frame on your portrait"),
]

def _parse_char_md_text(text):
    """Parse MD table text -> {char_id: {name, skins:{skin_id:name}}}"""
    chars = {}
    cur   = None
    for line in text.splitlines():
        m = re.match(r'\|\s*(\d{4})\s*\|\s*([^|]+?)\s*\|(?:\s*(\d{7})\s*\|\s*([^|]*?)\s*\|)?', line)
        if m and m.group(1):
            cur  = m.group(1)
            name = m.group(2).strip()
            if name and name.upper() != "NAME":
                chars.setdefault(cur, {"name": name, "skins": {}})
                if m.group(3):
                    chars[cur]["skins"][m.group(3)] = correct_skin_name(m.group(3), (m.group(4) or "").strip())
            continue
        m2 = re.match(r'\|\s*\|\s*\|\s*(\d{7})\s*\|\s*([^|]*?)\s*\|', line)
        if m2 and cur and cur in chars:
            chars[cur]["skins"][m2.group(1)] = correct_skin_name(m2.group(1), m2.group(2).strip())
    return chars

def _parse_char_md():
    path = os.path.join(TOOLS, "MarvelRivalsCharacterIDs.md")
    try:
        return _parse_char_md_text(open(path, encoding="utf-8").read())
    except Exception:
        return {}

def _fetch_char_data():
    global _CHAR_DATA
    try:
        req = urllib.request.Request(
            _REMOTE_MD_URL,
            headers={"User-Agent": "Atelier-ModTool/1.0 (character-id-sync)"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            text = r.read().decode("utf-8")
    except Exception:
        return
    new_data = _parse_char_md_text(text)
    if not new_data:
        return  # do not publish an empty/broken catalogue
    merged, changed = merge_reference(_CHAR_DATA, new_data)
    if changed:
        # Publish a complete consistent snapshot; existing names can be renamed.
        # The remote raw source is preserved locally and verified display overrides
        # are applied during parsing, so an incorrect donor label cannot win.
        _CHAR_DATA = merged
        # write updated file back so next launch starts with fresh data
        try:
            path = os.path.join(TOOLS, "MarvelRivalsCharacterIDs.md")
            tmp = path + '.atlas-update.tmp'
            try:
                with open(tmp, 'w', encoding='utf-8') as f:
                    f.write(text)
                os.replace(tmp, path)
            finally:
                try: os.unlink(tmp)
                except FileNotFoundError: pass
        except Exception:
            pass
        if _update_callback:
            _update_callback({"toast": f"Character names updated — {changed} entries added or corrected", "toast_type": "success"})

def _try_fetch_once():
    global _fetch_attempted
    with _fetch_lock:
        if _fetch_attempted:
            return
        _fetch_attempted = True
    threading.Thread(target=_fetch_char_data, daemon=True).start()

_CHAR_DATA = _parse_char_md()

def char_name(cid):
    name = _CHAR_DATA.get(cid, {}).get("name")
    if not name:
        _try_fetch_once()
    return name or f"Character {cid}"

def skin_name(sid):
    cid  = get_char_id(sid)
    name = _CHAR_DATA.get(cid, {}).get("skins", {}).get(sid)
    if not name:
        _try_fetch_once()
    return name or sid

def token(game_rel):
    return hashlib.md5(game_rel.encode()).hexdigest()[:20]

def game_rel_from_token(tok):
    """Reverse-lookup game_rel from a token by scanning the active project (subfolder-mirrored)."""
    import atelier.asset_cache as _ac
    import_root = get_import_root()
    if not os.path.isdir(import_root): return None
    for dirpath, _dirs, files in os.walk(import_root):
        _dirs[:] = [d for d in _dirs if d not in ('.atelier', '.atelier-trash')]
        for fname in files:
            if not fname.endswith(".png"): continue
            gr = project_game_rel(os.path.join(dirpath, fname), import_root)
            if "/" not in gr and not os.path.isfile(project_base(gr, import_root) + '.asset.json'):
                gr = _ac.by_name(gr) or gr
            if token(gr) == tok:
                return gr
    return None

# Only these asset kinds are surfaced in the browser. Everything else
# (blueprints, data tables, …) is hidden.
LISTED_FILE_TYPES = ("material", "texture", "vfx", "curve", "mesh", "world", "text")
# Editable non-texture assets persist as <basename>.json in the active project (textures use .png).
JSON_EDIT_TYPES = ("material", "curve", "vfx", "world", "text")

def _classify_file(name, rel_path=""):
    nl = name.lower()
    if nl.endswith(".uasset"): nl = nl[:-7]
    if nl.endswith(".umap"):            # level sublevel — lighting/components/fog/grade editing
        return "world"
    if nl.endswith("_st"):              # StringTable — editable key->string text
        return "text"
    if nl.startswith("t_"):
        return "texture"
    # MPC_* = MaterialParameterCollection: UE's GLOBAL scalar/vector parameters, which is what a
    # skin's VFX glow colours are driven from (diiea, 1031306 — "global vector parameters"). Handled
    # by the VFX editor, so it rides the "vfx" type through browse/import/export rather than adding
    # a whole asset kind for one parameter list.
    if nl.startswith(("ns_", "fx_", "vfx_", "nfx_", "p_", "niagara_", "mpc_")):
        return "vfx"
    # C_* = CurveLinearColor, Curve_* = CurveVector/Float (confirmed via UAssetTool `detect`).
    if nl.startswith(("c_", "curve_")):
        return "curve"
    if nl.startswith("mi_"):
        return "material"
    # Renderable meshes (skeletal/static) — exclude skeleton/physics/anim helper assets.
    if nl.startswith(("sk_", "sm_")) and not any(s in nl for s in ("_skeleton", "physics", "_anim")):
        return "mesh"
    # Path-context fallback: anything sitting inside a Textures folder is a texture.
    if "/textures/" in ("/" + rel_path.lower() + "/"):
        return "texture"
    return "other"

def _label_folder(rel_path, folder_name):
    """Return display label for folder_name found at rel_path under Marvel/Content/Marvel/."""
    if not rel_path and folder_name.lower() == "marvel_lq":
        # Its own root since v13 of the index. It used to be flattened onto the main tree, where
        # every LQ asset collided with its HQ twin and lost — so the node people were told to look
        # for could not appear even on an install that had one (fawnls, 2026-08-22).
        return "Marvel_LQ — the low-quality twin mount (UI mods may need this copy too)"
    if not rel_path and folder_name.lower() == "plugins":
        # Name the mount the way FModel does, so "Marvel/Plugins/MarvelGAS/..." from a guide or a
        # screenshot leads somewhere. shafsta's team-up ability icons were in here the whole time,
        # under a path that matched nothing anyone had been told to look for.
        return "Plugins — separately-mounted game content (MarvelGAS, …)"
    if rel_path in CHAR_LABEL_PATHS and re.match(r"^\d{4}$", folder_name):
        return f"{folder_name} — {char_name(folder_name)}"
    for hp in CHAR_LABEL_PATHS:
        m = re.match(rf"^{re.escape(hp)}/(\d{{4}})$", rel_path, re.IGNORECASE)
        if m and re.match(r"^\d{7}$", folder_name):
            sname  = skin_name(folder_name)
            suffix = folder_name[-3:]
            return f"{suffix} — Skin {suffix}" if sname == folder_name else f"{suffix} — {sname}"
    return folder_name

def _browse_pak_level(rel_path):
    """List immediate children (folders AND asset files) at rel_path from the pak index.
    rel_path is virtual (relative to the content mount, e.g. 'UI/Textures/HeroGallery_V3')."""
    rel_path   = rel_path.strip("/")
    search_pfx = (rel_path.lower() + "/") if rel_path else ""

    folders = {}  # lower_name -> original_name (first seen)
    files   = {}  # lower_name -> original_name (first seen), .uasset basenames sans ext
    for virt_path, *_ in ensure_index():
        vl = virt_path.lower()
        if search_pfx and not vl.startswith(search_pfx):
            continue
        rest = virt_path[len(search_pfx):]
        if not rest:
            continue
        if "/" in rest:                          # descendant -> immediate subfolder
            fname_orig = rest.split("/")[0]
            folders.setdefault(fname_orig.lower(), fname_orig)
        elif rest.lower().endswith(".uasset"):   # asset file directly at this level
            name = rest[:-7]
            files.setdefault(name.lower(), name)

    result = []
    for fname_lower in sorted(folders):
        fname = folders[fname_lower]
        label = _label_folder(rel_path, fname)
        child = f"{rel_path}/{fname}" if rel_path else fname
        portrait = catalogue.describe(child)
        item = {"type": "folder", "name": fname, "label": label, "rel_path": child}
        if portrait:
            if portrait['name']:
                label_id = fname[-3:] if len(fname) == 7 else fname
                item['label'] = f"{label_id} — {portrait['name']}"
            item.update(thumbnail=portrait['thumbnail'], hero_fallback=portrait['hero_fallback'])
            if portrait['banner']:
                item['banner'] = portrait['banner']
        result.append(item)
    if not rel_path:
        pinned = [r for r in result if r["name"].lower() in ROOT_PINNED]
        others = [r for r in result if r["name"].lower() not in ROOT_PINNED]
        result = sorted(pinned, key=lambda r: ROOT_PINNED.index(r["name"].lower())) + others
    for name_lower in sorted(files):
        name     = files[name_lower]
        ft       = _classify_file(name, rel_path)
        if ft not in LISTED_FILE_TYPES:        # hide meshes/curves/blueprints/vfx/etc.
            continue
        gr       = f"{rel_path}/{name}" if rel_path else name
        is_mat   = ft == "material"
        imported = _imported_exists(gr, ".blend" if ft == 'mesh' else ".json" if ft in JSON_EDIT_TYPES else ".png")
        result.append({
            "type":      "asset",
            "file_type": ft,
            "name":      name,
            "label":     name,
            "rel_path":  gr,
            "game_rel":  gr,
            "imported":  imported,
            "token":     token(gr) if imported else None,
            **({"swatches": _edited_swatches(gr)} if is_mat and imported else {}),
        })
    return result

def _browse_skin(skin_id, subpath):
    """Browse immediate children of subpath inside skin_id (unchanged traversal logic)."""
    entries = skin_entries(skin_id)
    subpath = subpath.strip("/")
    prefix  = (subpath + "/") if subpath else ""

    folders = {}
    files   = {}

    for pak_path, _cont in entries:
        rel = skin_rel(pak_path, skin_id)
        if not rel.lower().startswith(prefix.lower()):
            continue
        rest = rel[len(prefix):]
        if not rest:
            continue
        if "/" in rest:
            folder_name = rest.split("/")[0]
            folder_path = (prefix + folder_name).strip("/")
            folders[folder_name] = folder_path
        else:
            gr = game_rel_for_skin(skin_id, (prefix + rest).strip("/"))
            files[rest] = {"rel_path": (prefix + rest).strip("/"), "game_rel": gr}

    result = []
    for name in sorted(folders, key=str.lower):
        result.append({"type": "folder", "name": name, "label": name, "rel_path": folders[name]})
    for name in sorted(files, key=str.lower):
        td     = files[name]
        ft     = _classify_file(name, td["rel_path"])
        if ft not in LISTED_FILE_TYPES:        # hide meshes/curves/blueprints/vfx/etc.
            continue
        is_mat   = ft == "material"
        imported = _imported_exists(td["game_rel"], ".blend" if ft == 'mesh' else ".json" if ft in JSON_EDIT_TYPES else ".png")
        tok      = token(td["game_rel"]) if imported else None
        result.append({
            "type":      "asset",
            "file_type": ft,
            "name":      name,
            "label":     name,
            "rel_path":  td["rel_path"],
            "game_rel":  td["game_rel"],
            "imported":  imported,
            "token":     tok,
            **({"swatches": _edited_swatches(td["game_rel"])} if is_mat and imported else {}),
        })
    return result

def _browse_maps(path):
    """Level browsing: 'Maps' -> map folders; 'Maps/<map>' -> its .umap sublevels as world assets.
    Maps aren't in the pak-asset index (that's characters/textures/vfx), so they're enumerated
    straight from the map containers via the world handler."""
    import atelier.handlers.world as _world
    rest = path[4:].strip("/")           # after "Maps"
    if not rest:
        out = []
        for mp in _world.list_maps():
            fr, mode = _world.map_friendly(mp)
            out.append({"type": "folder", "name": mp,
                        "label": fr + (f" · {mode}" if mode else ""), "rel_path": f"Maps/{mp}"})
        return out
    mapname = rest.split("/")[0]
    out = []
    for s in _world.list_map_sublevels(mapname):
        gr = s["game_rel"]
        imported = _imported_exists(gr, ".json")
        out.append({"type": "asset", "file_type": "world", "name": s["sub"], "label": s["sub"],
                    "rel_path": gr, "game_rel": gr, "imported": imported,
                    "token": token(gr) if imported else None})
    return out

def _browse_nameplates():
    """The curated Nameplates section: the three real UI/Textures paths, side by side.

    Each entry is an ordinary folder pointing straight at its real location, so navigating in lands
    in the normal tree (breadcrumbs, import-all and thumbnails all keep working) — this only answers
    "where are they", which is the part that cost three people an afternoon each. A path the current
    paks don't have is listed anyway and said to be missing, because "it isn't there" is itself the
    answer to the question, and silently hiding it would recreate the empty node people reported."""
    have = set()
    for virt_path, *_ in ensure_index():
        vl = virt_path.lower()
        for rp, _desc in NAMEPLATE_PATHS:
            if vl.startswith(rp.lower() + "/"):
                have.add(rp)
    out = []
    for rp, desc in NAMEPLATE_PATHS:
        missing = rp not in have
        out.append({"type": "folder", "name": rp.split("/")[-1],
                    "label": f"{desc}{' · not in your paks' if missing else ''}",
                    "rel_path": rp})
    return out

def _browse_text(path):
    """StringTable browsing under the synthetic 'Text' root (not in the pak-asset index)."""
    import atelier.handlers.text as _text
    out = []
    for s in _text.list_stringtables():
        gr = s["game_rel"]
        imported = _imported_exists(gr, ".json")
        out.append({"type": "asset", "file_type": "text", "name": s["name"], "label": s["name"],
                    "rel_path": gr, "game_rel": gr, "imported": imported,
                    "token": token(gr) if imported else None})
    return out

def _browse_game_dispatch(path):
    """Unified browse entry point. path is relative to Marvel/Content/Marvel/."""
    path = (path or "").strip("/")
    if not path:                         # root: pin synthetic "Maps" + "Text" sections (not indexed)
        res = _browse_pak_level("")
        res.insert(0, {"type": "folder", "name": "Nameplates",
                       "label": "Nameplates (all three paths)", "rel_path": "Nameplates"})
        res.insert(0, {"type": "folder", "name": "Text", "label": "Text (StringTables)", "rel_path": "Text"})
        res.insert(0, {"type": "folder", "name": "Maps", "label": "Maps", "rel_path": "Maps"})
        return res
    if path.lower() == "nameplates":
        return _browse_nameplates()
    if path.lower() == "maps" or path.lower().startswith("maps/"):
        return _browse_maps(path)
    if path.lower() == "text" or path.lower().startswith("text/"):
        return _browse_text(path)
    for hp in HERO_PATHS:
        m = re.match(rf"^{re.escape(hp)}/(\d{{4}})/(\d{{7}})(?:/(.*))?$", path, re.IGNORECASE)
        if m:
            cid      = m.group(1)
            skin_id  = m.group(2)
            subpath  = (m.group(3) or "").strip("/")
            items    = _browse_skin(skin_id, subpath)
            skin_pfx = f"{hp}/{cid}/{skin_id}"
            for item in items:
                if item["type"] == "folder":
                    item["rel_path"] = f"{skin_pfx}/{item['rel_path']}"
            return items
    return _browse_pak_level(path)


def browse_dispatch(path):
    from atelier.added_assets import library_items
    path = (path or '').strip('/')
    items = _browse_game_dispatch(path)
    existing = {item.get('rel_path', item.get('game_rel', '')).casefold() for item in items}
    items.extend(item for item in library_items(path) if item['rel_path'].casefold() not in existing)
    return items

# ── kept for backwards compat (CLI / any callers) ────────────────────────────

def all_char_ids():
    seen = set()
    for p, *_ in ensure_index():
        m = re.match(r"Characters/(\d{4})/", p, re.IGNORECASE)
        if m: seen.add(m.group(1))
    return sorted(seen)

def char_skin_ids(cid):
    seen = set()
    pfx  = f"Characters/{cid}/".lower()
    for p, *_ in ensure_index():
        pl = p.lower()
        if not pl.startswith(pfx): continue
        rest = pl[len(pfx):]
        sid  = rest.split("/")[0]
        if re.match(r"^\d{7}$", sid): seen.add(sid)
    return sorted(seen)

_HERO_LABEL_RES = [re.compile(rf"^{re.escape(hp)}/(\d{{4}})/(\d{{7}})/", re.IGNORECASE)
                   for hp in CHAR_LABEL_PATHS]

def all_imported():
    """Walk the active project dir (subfolder-mirrored by game_rel) and return all imported assets.
    Files stored under a subfolder path carry their own game_rel; legacy flat files (no subfolder)
    are resolved through asset_cache by basename."""
    import atelier.asset_cache as _ac
    import atelier.project_meta as _pm
    import_root = get_import_root()
    if not os.path.isdir(import_root): return []
    deselected = _pm.get_deselected(import_root)
    # Export options are invisible on the asset itself — a texture set to ship blank looks exactly
    # like one that ships normally — so the sidebar has to be able to mark them.
    all_opts = _pm.get_asset_opts(import_root)
    items = []
    for dirpath, _dirs, files in os.walk(import_root):
        # Atelier's own per-project bookkeeping, not user edits. Pruned by name rather than left
        # to _classify_file, which rejects "manifest"/"project" only by accident of prefix.
        _dirs[:] = [d for d in _dirs if d not in ('.atelier', '.atelier-trash')]
        for fname in sorted(files):
            fpath = os.path.join(dirpath, fname)
            if fname.endswith('.asset.json'):
                continue
            if fname.endswith('.mesh.json'):
                gr=project_game_rel(fpath[:-len('.mesh.json')]+'.blend',import_root)
                ext='.blend'
            elif fname.endswith('.blend') and fname[:-len('.blend')]+'.mesh.json' in files:
                continue
            elif fname.endswith(".png"):
                ext = ".png"
            elif fname.endswith(".blend.mat.json"):
                continue                                # meshedit's texture manifest, not an edit
            elif fname.endswith(".json"):
                ext = ".json"
            elif fname.endswith(".blend"):
                ext = ".blend"
            else:
                continue
            if not fname.endswith('.mesh.json'):gr = project_game_rel(fpath, import_root)
            if "/" not in gr and not os.path.isfile(project_base(gr, import_root) + '.asset.json'):
                gr = _ac.by_name(gr) or gr
            name = os.path.basename(gr)
            if ext == ".png":
                ft = "texture"
            elif ext == ".blend":
                ft = "mesh"                             # a Blender mesh edit awaiting build
                if _classify_file(name) != "mesh":
                    continue
            else:
                ft = _classify_file(name)               # material | curve | vfx
                if ft not in JSON_EDIT_TYPES:
                    continue
            cid = sid = None
            for hr in _HERO_LABEL_RES:
                m = hr.match(gr)
                if m:
                    cid, sid = m.group(1), m.group(2)
                    break
            items.append({
                "token": token(gr), "game_rel": gr, "name": name,
                "file_type": ft,
                "skin_id":   sid or "", "char_id": cid or "",
                "char_name": char_name(cid) if cid else "",
                "skin_name": skin_name(sid) if sid else "",
                "mtime": int(os.path.getmtime(fpath)),
                # Default ON: only an asset the user explicitly switched off is deselected, so
                # anything new to the project arrives included in the next export.
                "selected": gr not in deselected,
                "opts": all_opts.get(gr) or {},
            })
    return items
