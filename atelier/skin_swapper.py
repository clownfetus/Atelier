"""Project Galacta Skin Swapper mods: an edited mesh plus a cooked GAL_ModSkinConfig per form.

Galacta's integration conditions are the contract this module enforces. In short:

  1. FORMAT. Mesh and config share /Game/Marvel/ProjectGalacta/Meshes/{HeroID}/{SkinID}/{ModFolder}/.
     The config is Galacta's cooked template with its name map and property values patched: never
     built from scratch, never subclassed or renamed. Its package is GAL_{ModFolder}, or
     GAL_{ModFolder}_S{n} for form n; its class import is GAL_ModSkinConfig_C with the default
     object Default__GAL_ModSkinConfig_C, both in the class package; its properties are tagged
     (not unversioned) TargetHeroID, TargetSkinID, TargetSculptID, SkinName, Author and MeshToSwap,
     a hard reference to the mesh in the same folder. One config per mesh, all in one IoStore
     container with the meshes. Anything that fails a check is not exported.
  2. NO PAID-SKIN BYPASS. No game asset ships. A mesh with no edits, one whose cooked data equals the
     game's, or a replacement imported from a cooked game file is refused. Hero and skin IDs are
     never typed: they come from the edited mesh's own game path and are shown read-only.
  3. Only the Galacta folder is written; no game path is overridden.
  4. skins.txt belongs to the Companion App. Nothing here creates, reads or writes it, and the stage
     audit refuses a build that would contain one.
  5. Galacta can revoke this. Project Galacta publishes the switch itself (FLAG_URL), so every
     install follows it without an Atelier release; a build re-reads it before it starts. When it
     cannot be fetched the last value Atelier got is used, so offline users are not blocked, and
     Galacta's message for a shutdown is shown in the export review.

THE TEMPLATE is Galacta's file and may not be redistributed outside Atelier. This repository is
public, so the template is never committed: it is read from Tools/Galacta/ (Tools/ is ignored by
git), and installer builds stage it from there (scripts/stage_tools.py). Without it the format is
reported unavailable.

THE TEMPLATE AS SHIPPED names its class and default-object imports Export_0 and Export_1, as a
container unpack writes them when the class package is not at hand. Rule 1 requires the real names,
so patch_config renames them along with everything else; verify_config then checks the cooked result.

WHY A MESH CAN MOVE SAFELY. The edited mesh is cooked by meshedit.stage_mesh at its game path. Only
its package header has to change to live in the Galacta folder (its FolderName); the export data in
.uexp/.ubulk must not. _relocate rewrites the header through UAssetTool's JSON round-trip and refuses
the result unless the .uexp comes back byte-identical. Measured on SK_1035_1035503_Lobby: 6.7 MB of
.uexp identical, header 17,447 -> 17,545 bytes.
"""
import hashlib
import json
import math
import os
import re
import shutil
import sys
import threading
import time
import urllib.request

from atelier import config

GAME_PREFIX = "/Game/Marvel/"
GALACTA = "ProjectGalacta"
CLASS_PACKAGE = GAME_PREFIX + GALACTA + "/Blueprints/GAL_ModSkinConfig"
CLASS_NAME = "GAL_ModSkinConfig_C"
CDO_NAME = "Default__" + CLASS_NAME
PROPERTIES = (("TargetHeroID", "IntPropertyData"), ("TargetSkinID", "IntPropertyData"),
              ("TargetSculptID", "IntPropertyData"), ("SkinName", "StrPropertyData"),
              ("Author", "StrPropertyData"), ("MeshToSwap", "ObjectPropertyData"))
OPTIONAL_PROPERTIES = {"NativeClass"}          # present in the template; points at the class import
TEMPLATE_NAME = "GAL_ConfigTemplate"
FLAG_URL = "https://0xsaturno.github.io/ProjectGalacta/flags/skinswapper.json"   # Project Galacta's own
FLAG_MAX_AGE = 6 * 3600
MOD_FOLDER_RE = re.compile(r"^[A-Za-z0-9_]{1,48}$")
TEXT_LIMIT = 64
_SKIN_PATH_RE = re.compile(r"^Characters/(\d{4})/(\d{7})/")
_STAGE_ROOT = ("Marvel", "Content", "Marvel")   # /Game/Marvel/<x> stages at Marvel/Content/Marvel/<x>

_flag_lock = threading.RLock()
_fetch_lock = threading.Lock()
_refreshing = threading.Event()


# ── availability: template and Galacta's switch ─────────────────────────────────────

def template_files():
    base = os.path.join(config.TOOLS, "Galacta", TEMPLATE_NAME)
    return base + ".uasset", base + ".uexp"


def _flag_path():
    # Revocation is persistent integration state, not disposable decode/build cache.
    return os.path.join(config.DATA_ROOT, "_state", "skinswapper-flag.json")


def parse_flag(payload):
    """Galacta's published switch, {"enabled": bool, "message": str}, or None if malformed."""
    if not isinstance(payload, dict) or not isinstance(payload.get("enabled"), bool):
        return None
    message = payload.get("message") if isinstance(payload.get("message"), str) else ""
    return {"enabled": payload["enabled"], "message": message.strip()[:300]}


def _load_flag(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        flag = parse_flag(data)
        if flag is None:
            return {}
        checked = data.get("checked_at", 0)
        flag["checked_at"] = checked if (type(checked) in (int, float) and 0 <= checked <= time.time()
                                         and math.isfinite(checked)) else 0
        return flag
    except (OSError, ValueError):
        return {}


def _save_flag(flag):
    from atelier.storage import atomic_json
    atomic_json(_flag_path(), flag)


def _read_flag():
    with _flag_lock:
        flag = _load_flag(_flag_path())
        if flag:
            return flag
        # Preserve the last known decision when upgrading from either earlier cache name.
        for name in ("skinswapper-flag.json", "integrations-flag.json"):
            flag = _load_flag(os.path.join(config.DATA_ROOT, "_cache", name))
            if flag:
                _save_flag(flag)
                return flag
        return {}


def refresh_flag(timeout=5):
    """Fetch Galacta's switch and cache it. Unreachable or unpublished keeps the last known value."""
    # Serialize the fetch as well as publication: an older response must never undo a newer one.
    with _fetch_lock:
        try:
            req = urllib.request.Request(FLAG_URL, headers={"User-Agent": "Atelier"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read(64 * 1024 + 1)
                if len(raw) > 64 * 1024:
                    return False
                flag = parse_flag(json.loads(raw.decode("utf-8")))
        except (OSError, ValueError):
            return False
        if flag is None:
            return False
        flag["checked_at"] = time.time()
        with _flag_lock:
            _save_flag(flag)
        return True


def refresh_flag_async():
    """Refresh a stale switch without making the caller wait for the network."""
    with _flag_lock:
        if time.time() - (_read_flag().get("checked_at") or 0) < FLAG_MAX_AGE or _refreshing.is_set():
            return
        _refreshing.set()

    def run():
        try:
            refresh_flag()
        finally:
            with _flag_lock:
                _refreshing.clear()
    try:
        threading.Thread(target=run, name="galacta-flag", daemon=True).start()
    except BaseException:
        with _flag_lock:
            _refreshing.clear()
        raise


def flag_state():
    """(enabled, message). Never published or never reached means generation stays available."""
    data = _read_flag()
    if isinstance(data.get("enabled"), bool):
        return data["enabled"], data.get("message") or ""
    return True, ""


def status():
    uasset, uexp = template_files()
    template = all(os.path.isfile(p) and os.path.getsize(p) for p in (uasset, uexp))
    enabled, message = flag_state()
    reasons = []
    if not template:
        reasons.append("The Skin Swapper template is not installed (Tools/Galacta).")
    if not enabled:
        reasons.append(message or "Project Galacta has switched Skin Swapper export off.")
    return {"available": template and enabled, "template": template, "enabled": enabled,
            "reasons": reasons}


# ── planning: IDs, names and edit checks ─────────────────────────────────────────────

def target_ids(game_rel):
    """(hero_id, skin_id) from an edited mesh's own game path, or None. Never user input."""
    m = _SKIN_PATH_RE.match(game_rel or "")
    if not m or not m.group(2).startswith(m.group(1)):
        return None
    return m.group(1), m.group(2)


def config_name(mod_folder, sculpt):
    """GAL_{ModFolder}, with _S{n} for form n. Form 0 is the default form and has no suffix."""
    return f"GAL_{mod_folder}" + (f"_S{sculpt}" if sculpt else "")


def _edit_problem(game_rel):
    """Why this mesh may not ship (rule 2), or None."""
    from atelier.handlers.meshreplace import is_original, target_base
    label = os.path.basename(game_rel)
    try:
        base = target_base(game_rel)
    except ValueError as e:
        return f"{label}: {e}"
    if not os.path.isfile(base + ".blend") or is_original(game_rel):
        return (f"{label} has no edits. Skin Swapper mods may only carry your own model, "
                f"never the game's.")
    try:
        with open(base + ".mesh.json", encoding="utf-8") as f:
            record = json.load(f)
    except (OSError, ValueError):
        record = {}
    if record.get("state") == "replacement" and record.get("source_format") == ".uasset":
        return (f"{label} was replaced with a cooked game mesh ({record.get('source_name') or 'a .uasset'}). "
                f"Game assets may not ship in a Skin Swapper mod; import your own BLEND, FBX, GLB or PSK model.")
    return None


def _text_problem(label, value):
    if not isinstance(value, str) or not value.strip():
        return f"{label} is required."
    if len(value.strip()) > TEXT_LIMIT or any(ord(c) < 32 for c in value):
        return f"{label} must be one line of at most {TEXT_LIMIT} characters."
    return None


def plan(mod_folder, meshes, skin_name, author, check_edits=True):
    """Validate a request and lay out every package. Returns {entries, problems, hero_id, skin_id}."""
    problems = []
    folder_ok = isinstance(mod_folder, str) and bool(MOD_FOLDER_RE.fullmatch(mod_folder))
    if not folder_ok:
        problems.append("The mod name becomes the Galacta folder name, so it may only use letters, "
                        "digits and underscores (up to 48).")
    problems += [p for p in (_text_problem("Skin name", skin_name), _text_problem("Author", author)) if p]
    if not meshes:
        problems.append("Select at least one edited character mesh.")
    entries, targets, sculpts, names = [], set(), set(), set()
    for item in meshes or []:
        game_rel = item.get("game_rel") if isinstance(item, dict) else None
        sculpt = item.get("sculpt", 0) if isinstance(item, dict) else None
        label = os.path.basename(game_rel or "") or "A mesh"
        ids = target_ids(game_rel or "")
        if ids is None:
            problems.append(f"{label} is not a character skin mesh, so its hero and skin cannot be identified.")
            continue
        if type(sculpt) is not int or not 0 <= sculpt <= 9:
            problems.append(f"{label}: the form must be a number from 0 to 9.")
            continue
        if sculpt in sculpts:
            problems.append(f"Two meshes use form {sculpt}. Each form needs its own mesh.")
        if label in names:
            problems.append(f"{label} is listed twice.")
        sculpts.add(sculpt); names.add(label); targets.add(ids)
        if check_edits:
            edit = _edit_problem(game_rel)
            if edit:
                problems.append(edit)
        if folder_ok:
            folder = f"{GALACTA}/Meshes/{ids[0]}/{ids[1]}/{mod_folder}"
            name = config_name(mod_folder, sculpt)
            entries.append({"game_rel": game_rel, "hero_id": ids[0], "skin_id": ids[1], "sculpt": sculpt,
                            "folder": folder, "mesh_name": label, "mesh_game_rel": f"{folder}/{label}",
                            "config_name": name, "config_game_rel": f"{folder}/{name}"})
    if len(targets) > 1:
        problems.append("All meshes in one Skin Swapper mod must belong to the same skin.")
    hero, skin = next(iter(targets)) if len(targets) == 1 else (None, None)
    return {"entries": entries, "problems": problems, "hero_id": hero, "skin_id": skin}


# ── the config: patch Galacta's template, then hold the result to every rule ──────────

def _import(doc, index):
    imports = doc.get("Imports") or []
    if not isinstance(index, int) or isinstance(index, bool) or index >= 0 or -index > len(imports):
        raise ValueError(f"the config references import {index!r}, which does not exist")
    return imports[-index - 1]


def _layout(doc):
    """The template's parts, found by their roles rather than by the template's own names."""
    exports = doc.get("Exports") or []
    if len(exports) != 1:
        raise ValueError(f"the config must hold exactly one export, not {len(exports)}")
    export = exports[0]
    props = {p.get("Name"): p for p in export.get("Data") or [] if isinstance(p, dict)}
    cls = _import(doc, export.get("ClassIndex"))
    cdo = _import(doc, export.get("TemplateIndex"))
    package = _import(doc, cls.get("OuterIndex"))
    mesh = _import(doc, (props.get("MeshToSwap") or {}).get("Value"))
    mesh_package = _import(doc, mesh.get("OuterIndex"))
    return export, props, cls, cdo, package, mesh, mesh_package


def patch_config(doc, entry, skin_name, author):
    """Turn Galacta's template JSON into this mesh's config, in place. Names only change in place
    or are appended, so every index the export data and imports hold stays valid."""
    export, props, cls, cdo, package, mesh, mesh_package = _layout(doc)
    for name, kind in PROPERTIES:
        if name not in props or kind not in str(props[name].get("$type")):
            raise ValueError(f"the template has no {name} property of the expected type")
    config_package = GAME_PREFIX + entry["config_game_rel"]
    mesh_path = GAME_PREFIX + entry["mesh_game_rel"]
    renames = {doc.get("FolderName"): config_package, export.get("ObjectName"): entry["config_name"],
               cls.get("ObjectName"): CLASS_NAME, cdo.get("ObjectName"): CDO_NAME,
               mesh_package.get("ObjectName"): mesh_path, mesh.get("ObjectName"): entry["mesh_name"]}
    names = doc.setdefault("NameMap", [])
    for i, name in enumerate(names):
        new = renames.get(name)
        if new is not None and new not in names:
            names[i] = new
    for name in (config_package, entry["config_name"], CLASS_PACKAGE, CLASS_NAME, CDO_NAME,
                 "/Script/Engine", "/Script/CoreUObject", "Package", "BlueprintGeneratedClass",
                 "SkeletalMesh", mesh_path, entry["mesh_name"]):
        if name not in names:
            names.append(name)
    doc["FolderName"] = config_package
    export["ObjectName"] = entry["config_name"]
    package.update(ObjectName=CLASS_PACKAGE, ClassPackage="/Script/CoreUObject", ClassName="Package")
    cls.update(ObjectName=CLASS_NAME, ClassPackage="/Script/Engine", ClassName="BlueprintGeneratedClass")
    cdo.update(ObjectName=CDO_NAME, ClassPackage=CLASS_PACKAGE, ClassName=CLASS_NAME)
    mesh_package.update(ObjectName=mesh_path, ClassPackage="/Script/CoreUObject", ClassName="Package")
    mesh.update(ObjectName=entry["mesh_name"], ClassPackage="/Script/Engine", ClassName="SkeletalMesh")
    props["TargetHeroID"]["Value"] = int(entry["hero_id"])
    props["TargetSkinID"]["Value"] = int(entry["skin_id"])
    props["TargetSculptID"]["Value"] = entry["sculpt"]
    props["SkinName"]["Value"] = skin_name
    props["Author"]["Value"] = author
    return doc


def verify_config(doc, entry, skin_name, author):
    """Every rule-1 requirement checked against a cooked config's JSON. Returns the problems found."""
    problems = []
    try:
        export, props, cls, cdo, package, mesh, mesh_package = _layout(doc)
    except ValueError as e:
        return [str(e)]
    config_package = GAME_PREFIX + entry["config_game_rel"]
    mesh_path = GAME_PREFIX + entry["mesh_game_rel"]

    def expect(label, actual, wanted):
        if actual != wanted:
            problems.append(f"{label} is {actual!r}, expected {wanted!r}")

    if doc.get("HasUnversionedProperties") is not False:
        problems.append("properties must be saved with property tags, not unversioned")
    expect("package path", doc.get("FolderName"), config_package)
    expect("asset name", export.get("ObjectName"), entry["config_name"])
    expect("class package import", (package.get("ObjectName"), package.get("ClassName")), (CLASS_PACKAGE, "Package"))
    expect("class import", (cls.get("ObjectName"), cls.get("ClassPackage"), cls.get("ClassName")),
           (CLASS_NAME, "/Script/Engine", "BlueprintGeneratedClass"))
    expect("default object import", (cdo.get("ObjectName"), cdo.get("ClassPackage"), cdo.get("ClassName")),
           (CDO_NAME, CLASS_PACKAGE, CLASS_NAME))
    if cdo.get("OuterIndex") != cls.get("OuterIndex"):
        problems.append("the class and default object imports are in different packages")
    wanted = {name for name, _ in PROPERTIES}
    extra = set(props) - wanted - OPTIONAL_PROPERTIES
    missing = wanted - set(props)
    if missing:
        problems.append("missing properties: " + ", ".join(sorted(missing)))
    if extra:
        problems.append("unexpected properties: " + ", ".join(sorted(extra)))
    for name, kind in PROPERTIES:
        if name in props and kind not in str(props[name].get("$type")):
            problems.append(f"{name} has the wrong type")
    values = {"TargetHeroID": int(entry["hero_id"]), "TargetSkinID": int(entry["skin_id"]),
              "TargetSculptID": entry["sculpt"], "SkinName": skin_name, "Author": author}
    for name, value in values.items():
        if name in props:
            expect(name, props[name].get("Value"), value)
    sculpt = (props.get("TargetSculptID") or {}).get("Value")
    if not isinstance(sculpt, int) or not 0 <= sculpt <= 9:
        problems.append("TargetSculptID must be 0-9")
    if not re.fullmatch(r"\d{7}", str((props.get("TargetSkinID") or {}).get("Value"))):
        problems.append("TargetSkinID must have 7 digits")
    expect("MeshToSwap", (mesh.get("ObjectName"), mesh.get("ClassName")), (entry["mesh_name"], "SkeletalMesh"))
    expect("MeshToSwap package", mesh_package.get("ObjectName"), mesh_path)
    if mesh_path.rsplit("/", 1)[0] != config_package.rsplit("/", 1)[0]:
        problems.append("the mesh and its config are not in the same folder")
    folder = f"{GAME_PREFIX}{GALACTA}/Meshes/{entry['hero_id']}/{entry['skin_id']}/"
    if not config_package.startswith(folder):
        problems.append("the config's folder does not match its hero and skin IDs")
    for imp in doc.get("Imports") or []:
        name = imp.get("ObjectName") or ""
        if imp.get("ClassName") == "Package" and not name.startswith("/Script/") \
                and name not in (CLASS_PACKAGE, mesh_path):
            problems.append(f"the config references another package: {name}")
    return problems


# ── building ───────────────────────────────────────────────────────────────────────────

def _stage_path(stage, game_rel):
    return os.path.join(stage, *_STAGE_ROOT, *game_rel.split("/"))


def _same_file(a, b):
    if os.path.isfile(a) != os.path.isfile(b):
        return False
    if not os.path.isfile(a):
        return True
    if os.path.getsize(a) != os.path.getsize(b):
        return False

    def digest(path):
        with open(path, "rb") as f:
            return hashlib.file_digest(f, "sha256").hexdigest()
    return digest(a) == digest(b)


def _same_geometry(original, rebuilt, tolerance=1e-3):
    """Compare LOD0 surfaces in game centimetres, ignoring exporter vertex/face ordering.

    Blender splits vertices at UV/normal seams and cooking regenerates lower LODs and metadata.
    None of that is a model edit. Match positions within float round-trip precision, then compare
    triangle multiplicities using the original positions as stable IDs. Lower LODs cannot make an
    untouched top LOD eligible for Skin Swapper export.
    """
    import numpy as np
    from scipy.spatial import cKDTree

    source_lod, target_lod = original.lods[0], rebuilt.lods[0]
    source = np.asarray(original.positions(source_lod), dtype="f8")
    target = np.asarray(rebuilt.positions(target_lod), dtype="f8")
    if not len(source) or not len(target) or not np.isfinite(source).all() or not np.isfinite(target).all():
        raise ValueError("The mesh has empty or non-finite geometry; it was not exported.")
    # The metre/centimetre and coordinate transforms introduce several float32 ULPs. At seams,
    # even two original positions can differ by less than that noise; give them the same ID so
    # a round trip choosing the neighbouring position cannot look like a topology edit.
    tolerance = max(tolerance, float(np.max(np.abs(source))) * np.finfo("f4").eps * 8)
    points, source_ids = np.unique(source, axis=0, return_inverse=True)
    tree = cKDTree(points)
    distance, target_ids = tree.query(target)
    if np.any(distance > tolerance):
        return False
    parent = np.arange(len(points))

    def representative(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for a, b in tree.query_pairs(tolerance, output_type="ndarray"):
        a, b = representative(a), representative(b)
        parent[max(a, b)] = min(a, b)
    labels = np.array([representative(i) for i in range(len(points))])
    source_ids, target_ids = labels[source_ids], labels[target_ids]

    def triangles(model, lod, ids):
        count = sum(section["num_tris"] for section in lod["sections"]) * 3
        indices = np.frombuffer(model._blob(lod), dtype=f"<u{lod['idx_stride']}",
                                count=count, offset=lod["idx_off"])
        faces = np.sort(ids[indices].reshape(-1, 3), axis=1)
        return faces[np.lexsort((faces[:, 2], faces[:, 1], faces[:, 0]))]

    return np.array_equal(triangles(original, source_lod, source_ids),
                          triangles(rebuilt, target_lod, target_ids))


def _uat_error(result, fallback):
    return (((getattr(result, "stderr", "") or "") + (getattr(result, "stdout", "") or "")).strip()[-300:]
            or fallback)


def _to_json(uasset, out_dir):
    from atelier.config import USMAP
    from atelier.tools import uat
    os.makedirs(out_dir, exist_ok=True)
    r = uat(["to_json", os.path.abspath(uasset), USMAP, os.path.abspath(out_dir)])
    path = os.path.join(out_dir, os.path.basename(uasset)[:-len(".uasset")] + ".json")
    if not os.path.isfile(path):
        raise RuntimeError(f"could not read {os.path.basename(uasset)}: " + _uat_error(r, "no JSON"))
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f), path


def _from_json(doc, json_path, uasset):
    from atelier.config import USMAP
    from atelier.tools import uat
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(doc, f)
    os.makedirs(os.path.dirname(uasset), exist_ok=True)
    r = uat(["from_json", os.path.abspath(json_path), os.path.abspath(uasset), USMAP])
    if not os.path.isfile(uasset):
        raise RuntimeError(f"could not write {os.path.basename(uasset)}: " + _uat_error(r, "no package"))


def _relocate(src, target, package, scratch):
    """Move a cooked mesh package to `package`, changing only its header. src/target are stems."""
    doc, json_path = _to_json(src + ".uasset", os.path.join(scratch, "json", os.path.basename(target)))
    doc["FolderName"] = package
    if package not in doc.setdefault("NameMap", []):
        doc["NameMap"].append(package)
    _from_json(doc, json_path, target + ".uasset")
    for ext in (".ubulk", ".uptnl"):
        if os.path.isfile(src + ext):
            shutil.copy2(src + ext, target + ext)
    if not _same_file(src + ".uexp", target + ".uexp"):
        raise RuntimeError(f"moving {os.path.basename(src)} into the Galacta folder changed its mesh data, "
                           f"so it was not exported")
    moved, _ = _to_json(target + ".uasset", os.path.join(scratch, "check", os.path.basename(target)))
    if moved.get("FolderName") != package:
        raise RuntimeError(f"{os.path.basename(src)} did not take its Galacta package path")


def _stage_mesh(entry, scratch, stage):
    from atelier.handlers import meshedit
    problem = _edit_problem(entry["game_rel"])
    if problem:
        raise RuntimeError(problem)
    staged = meshedit.stage_mesh(entry["game_rel"], os.path.join(scratch, "mesh", entry["mesh_name"]))
    src = staged["uasset"][:-len(".uasset")]
    base = meshedit._resolve_base(entry["game_rel"])
    if all(_same_file(src + ext, base + ext) for ext in (".uexp", ".ubulk")):
        raise RuntimeError(f"{entry['mesh_name']} cooks to exactly the game's mesh. Game assets may not "
                           f"ship in a Skin Swapper mod.")
    from atelier.handlers.mesh import Mesh
    if _same_geometry(Mesh(base), Mesh(src)):
        raise RuntimeError(f"{entry['mesh_name']} has no geometry edits. Re-saving or recooking the "
                           "game's model does not make it an edited mesh for Skin Swapper export.")
    _relocate(src, _stage_path(stage, entry["mesh_game_rel"]), GAME_PREFIX + entry["mesh_game_rel"], scratch)
    return f"mesh {entry['mesh_name']} -> {GAME_PREFIX}{entry['folder']}/"


def _stage_config(entry, scratch, stage, skin_name, author):
    work = os.path.join(scratch, "config", entry["config_name"])
    os.makedirs(work, exist_ok=True)
    for src in template_files():
        shutil.copy2(src, os.path.join(work, os.path.basename(src)))
    doc, json_path = _to_json(os.path.join(work, TEMPLATE_NAME + ".uasset"), os.path.join(work, "json"))
    patch_config(doc, entry, skin_name, author)
    target = _stage_path(stage, entry["config_game_rel"])
    _from_json(doc, json_path, target + ".uasset")
    # Read the cooked config back and hold it to every rule before it can ship.
    built, _ = _to_json(target + ".uasset", os.path.join(work, "check"))
    problems = verify_config(built, entry, skin_name, author)
    if problems:
        raise RuntimeError(f"{entry['config_name']} failed Galacta's checks: " + "; ".join(problems))
    return (f"config {entry['config_name']} (hero {entry['hero_id']}, skin {entry['skin_id']}, "
            f"form {entry['sculpt']})")


def audit_stage(stage, entries):
    """Rules 3 and 4: the stage holds only the planned Galacta packages, and never skins.txt."""
    allowed = {}
    for entry in entries:
        for key in ("mesh_game_rel", "config_game_rel"):
            allowed[os.path.normcase(_stage_path(stage, entry[key]))] = entry[key]
    problems = []
    for dirpath, _dirs, files in os.walk(stage):
        for name in files:
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, stage).replace("\\", "/")
            if name.lower() == "skins.txt":
                problems.append(f"{rel}: skins.txt is the Companion App's file")
            elif os.path.normcase(os.path.splitext(path)[0]) not in allowed:
                problems.append(f"{rel} is outside the planned Galacta packages")
    if problems:
        raise RuntimeError("The Skin Swapper stage is not clean: " + "; ".join(problems))


def build(mod_folder, meshes, skin_name, author, out_dir, password=None):
    """Build one IoStore container holding each mesh and its config, then publish it to out_dir."""
    from atelier import jobs
    from atelier.config import USMAP
    from atelier.handlers import texture as T
    from atelier.storage import container_files, publish_files
    from atelier.tools import uat
    refresh_flag()                       # rule 5: a revocation must reach a build that was already open
    state = status()
    if not state["available"]:
        return {"ok": False, "error": " ".join(state["reasons"])}
    layout = plan(mod_folder, meshes, skin_name, author)
    if layout["problems"]:
        return {"ok": False, "problems": layout["problems"],
                "error": "This Skin Swapper mod was not built: " + " ".join(layout["problems"])}
    skin_name, author = skin_name.strip(), author.strip()
    if not T._build_lock.acquire(blocking=False):
        return {"ok": False, "error": "Another mod build is in progress; try again when it finishes."}
    work = None
    try:
        work = jobs.build_workspace(T._CACHE)
        stage, scratch, out = (os.path.join(work, n) for n in ("assets", "scratch", "output"))
        for folder in (stage, scratch, out):
            os.makedirs(folder)
        applied = []
        for entry in layout["entries"]:
            jobs.checkpoint()
            jobs.progress("Building mesh " + entry["mesh_name"])
            applied.append(_stage_mesh(entry, scratch, stage))
            jobs.progress("Writing Skin Swapper config " + entry["config_name"])
            applied.append(_stage_config(entry, scratch, stage, skin_name, author))
        audit_stage(stage, layout["entries"])
        jobs.checkpoint()
        jobs.progress("Packing the Skin Swapper container…")
        base = os.path.join(out, f"{mod_folder}_9999999_P")
        r = uat(["create_mod_iostore", os.path.abspath(base), os.path.abspath(stage), "--usmap", USMAP])
        if not os.path.exists(base + ".utoc"):
            return {"ok": False, "error": "create_mod_iostore failed: " + _uat_error(r, "no container")}
        if password:
            from atelier.handlers import modlock
            modlock.embed(base, password)
        sources = container_files(base)
        jobs.begin_publication()
        artifacts = publish_files(sources, out_dir)
        print(f"[skin_swapper] built {mod_folder}: " + "; ".join(applied), file=sys.stderr, flush=True)
        return {"ok": True, "applied": applied, "skipped": [], "artifacts": artifacts,
                "pak": os.path.join(os.path.abspath(out_dir), os.path.basename(base) + ".pak"),
                "folder": GAME_PREFIX + layout["entries"][0]["folder"]}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        if work:
            shutil.rmtree(work, ignore_errors=True)
        T._build_lock.release()
