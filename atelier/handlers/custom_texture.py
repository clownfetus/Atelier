"""Brand-new textures made from the user's own images, assigned to one material's texture slot.

WHY NOT JUST REPLACE THE GAME TEXTURE. "Replace with Image" overwrites a package that other
materials may sample — a skin's diffuse is often shared by every chroma of that skin — so painting
it changes all of them. A custom texture ships as a NEW package that only the material it was
assigned to references, and the game texture is left exactly as it is.

HOW IT SHIPS. Both halves are built while the material is staged (material.stage_material), so a
custom texture is only ever in a mod together with the material that uses it:

  1. The texture package. The slot's current game texture is the template. The user's image is
     injected into a copy of it — inject_texture keeps the template's pixel format, sRGB and
     compression settings and texture group, so a normal-map slot gets a normal-map texture — and
     the copy is renamed: its top-level export takes the new asset name and it is staged at the new
     package path. The cooked package name comes from that staging path (create_mod_iostore), as for
     every other staged asset; the export name is what the material's import resolves against.
     The rename is a to_json -> mutate -> from_json pass over the injected asset that keeps the
     injected .ubulk/.uptnl, the same pass texture.set_texture_group uses for the texture group,
     and the result must decode to exactly the pixels the injected package does (_verify_rename).
  2. The material. Two imports are appended — a Package import naming the new package and a
     Texture2D import whose outer is that package, both cloned from the slot's current pair exactly
     as meshgraft does for mesh material slots — and the slot's TextureParameterValue is pointed at
     the new Texture2D import.

WHERE IT LIVES. Images are stored content-addressed in <project>/.atelier/custom_textures/: inside
.atelier so the edit-list walker never mistakes one for a texture edit, and inside the project so
duplicating, renaming and exporting a project carry them along. The slot assignments are the
material's `custom_textures` asset option (project_meta), so deleting or reverting the material
drops them; unreferenced images are pruned the next time an assignment changes.

WHERE THE NEW PACKAGE GOES. /Game/Marvel/Atelier/Custom/<key>/<T_name>, where <key> hashes the
material and slot. Nothing in the game lives under Atelier/, and two slots can never collide — even
the same image in a BaseColor and a Normal slot becomes two packages, as it must, because each is
encoded in its own slot's format.
"""
import hashlib
import io
import json
import os
import re
import shutil
import sys
import threading

from atelier import project_meta
from atelier.config import USMAP, get_import_root
from atelier.tools import uat

GAME_PREFIX = "/Game/Marvel/"
CUSTOM_ROOT = "Atelier/Custom"
_OPT = "custom_textures"
_STORE = os.path.join(".atelier", "custom_textures")
_FILE_RE = re.compile(r"^[0-9a-f]{20}\.png$")
_NAME_RE = re.compile(r"^T_[A-Za-z0-9_]{1,60}$")
MIN_SIDE, MAX_SIDE = 4, 8192
_lock = threading.Lock()


# ── names and paths ──────────────────────────────────────────────────────────────

def texture_name(filename):
    """A UE-safe asset name from the user's file name: 'my paint v3.png' -> 'T_my_paint_v3'.

    The name is what modders see in FModel/UAssetGUI, so it keeps the user's words; anything that is
    not a letter, digit or underscore becomes '_' because it ends up in an FName and a package path.
    """
    stem = os.path.splitext(os.path.basename((filename or "").replace("\\", "/")))[0]
    stem = re.sub(r"[^A-Za-z0-9_]+", "_", stem).strip("_")
    stem = re.sub(r"_+", "_", stem)[:48].strip("_") or "Custom"
    return stem if stem[:2].upper() == "T_" and len(stem) > 2 else "T_" + stem


def package_game_rel(material_game_rel, slot, name):
    """Storage-relative path of the new texture package (see the module docstring)."""
    key = hashlib.sha1(f"{material_game_rel}|{slot}".encode("utf-8")).hexdigest()[:10]
    return f"{CUSTOM_ROOT}/{key}/{name}"


def store_dir(project_dir=None):
    return os.path.join(project_dir or get_import_root(), _STORE)


# ── assignments ──────────────────────────────────────────────────────────────────

def assignments(material_game_rel, project_dir=None):
    """{slot: record} stored for one material, with anything malformed dropped.

    The records come from the project's own JSON, but a project can arrive as a zip from someone
    else, so a file name is only ever accepted in the content-addressed form this module writes."""
    raw = project_meta.get_asset_opts(project_dir or get_import_root(), material_game_rel).get(_OPT)
    out = {}
    for slot, rec in (raw or {}).items() if isinstance(raw, dict) else ():
        if (isinstance(slot, str) and slot and isinstance(rec, dict)
                and _FILE_RE.match(str(rec.get("file", ""))) and _NAME_RE.match(str(rec.get("name", "")))):
            out[slot] = dict(rec)
    return out


def public(material_game_rel, project_dir=None):
    """What the editor shows for each custom slot."""
    return {slot: {"name": rec["name"], "file": rec["file"], "source": rec.get("source") or "",
                   "size": rec.get("size") or [], "template": rec.get("template") or "",
                   "game_rel": package_game_rel(material_game_rel, slot, rec["name"])}
            for slot, rec in assignments(material_game_rel, project_dir).items()}


def image_path(material_game_rel, slot, project_dir=None):
    rec = assignments(material_game_rel, project_dir).get(slot)
    return os.path.join(store_dir(project_dir), rec["file"]) if rec else None


def _write(project_dir, material_game_rel, slots):
    project_meta.set_asset_opts(project_dir, material_game_rel, {_OPT: slots or None})


def prune(project_dir=None):
    """Delete stored images no material in the project uses any more. Returns how many."""
    project_dir = project_dir or get_import_root()
    folder = store_dir(project_dir)
    if not os.path.isdir(folder):
        return 0
    used = set()
    for opts in project_meta.get_asset_opts(project_dir).values():
        for rec in (opts.get(_OPT) or {}).values() if isinstance(opts.get(_OPT), dict) else ():
            if isinstance(rec, dict):
                used.add(rec.get("file"))
    removed = 0
    for name in os.listdir(folder):
        if _FILE_RE.match(name) and name not in used:
            try:
                os.remove(os.path.join(folder, name))
                removed += 1
            except OSError:
                pass
    return removed


def _normalized_png(data):
    """(png bytes, (w, h)) for an uploaded image, or ValueError saying what is wrong with it.

    Sides must be powers of two: the game streams textures as a mip chain, and the encoder builds
    that chain by halving, so a 1000x1000 image has no valid chain to ship."""
    from PIL import Image, UnidentifiedImageError
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.load()
            img = im.convert("RGBA")
    except Image.DecompressionBombError:
        raise ValueError(f"That image is far too large; each side can be at most {MAX_SIDE} pixels.")
    except (UnidentifiedImageError, OSError) as e:
        raise ValueError(f"That file is not an image Atelier can read ({e.__class__.__name__}).")
    w, h = img.size
    for side in (w, h):
        if side < MIN_SIDE or side > MAX_SIDE or side & (side - 1):
            raise ValueError(f"The image is {w}×{h}. Each side must be a power of two between "
                             f"{MIN_SIDE} and {MAX_SIDE} (for example 1024 or 2048) so the game "
                             f"can build its mip chain.")
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue(), (w, h)


def assign(material_game_rel, slot, filename, data, template_game_rel, project_dir=None):
    """Store the user's image and assign it to one slot of one material. Returns public()."""
    project_dir = project_dir or get_import_root()
    png, size = _normalized_png(data)
    file = hashlib.sha256(png).hexdigest()[:20] + ".png"
    folder = store_dir(project_dir)
    target = os.path.join(folder, file)
    # Written under the lock: another assignment's prune must never see this file before the
    # record that uses it exists.
    with _lock:
        if not os.path.isfile(target):
            os.makedirs(folder, exist_ok=True)
            tmp = target + ".tmp"
            with open(tmp, "wb") as f:
                f.write(png)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, target)
        slots = assignments(material_game_rel, project_dir)
        slots[slot] = {"name": texture_name(filename), "file": file, "size": list(size),
                       "source": os.path.basename((filename or "").replace("\\", "/"))[:120],
                       "template": template_game_rel}
        _write(project_dir, material_game_rel, slots)
        prune(project_dir)
    return public(material_game_rel, project_dir)


def clear(material_game_rel, slot=None, project_dir=None):
    """Put one slot (or, with slot=None, every slot) back on its game texture. Returns public()."""
    project_dir = project_dir or get_import_root()
    with _lock:
        slots = assignments(material_game_rel, project_dir)
        if slot is None:
            slots = {}
        else:
            slots.pop(slot, None)
        _write(project_dir, material_game_rel, slots)
        prune(project_dir)
    return public(material_game_rel, project_dir)


# ── export ───────────────────────────────────────────────────────────────────────

def rename_package(doc, old_name, new_name, new_package):
    """Rename a cooked texture's JSON in place: its one top-level export becomes `new_name`.

    The old names stay in the NameMap: other FNames may still use them, and an unreferenced name
    costs nothing (the Zen conversion rebuilds the name map). A summary FolderName that carries
    the old package path is rewritten too — left alone, a converter that reads it would register
    this package under the template's name and override the game texture for every material."""
    tops = [e for e in doc.get("Exports") or []
            if e.get("ObjectName") == old_name and not e.get("OuterIndex")]
    if len(tops) != 1:
        raise RuntimeError(f"the template texture has {len(tops)} top-level exports named "
                           f"{old_name!r}, so it cannot be renamed safely")
    tops[0]["ObjectName"] = new_name
    names = doc.setdefault("NameMap", [])
    for n in (new_name, new_package):
        if n not in names:
            names.append(n)
    folder = doc.get("FolderName")
    if isinstance(folder, str) and folder.startswith("/"):
        doc["FolderName"] = new_package


def _uat_error(result, fallback):
    return (((getattr(result, "stderr", "") or "") + (getattr(result, "stdout", "") or "")).strip()[-300:]
            or fallback)


def build_texture(scratch, template_game_rel, png, new_game_rel):
    """Encode `png` as a new texture package. Returns its files, all named after the new asset."""
    from atelier.handlers.texture import ensure_work_base, missing_reason
    name = new_game_rel.rsplit("/", 1)[-1]
    work = ensure_work_base(template_game_rel)
    if not work or not os.path.isfile(work + ".uasset"):
        raise RuntimeError(missing_reason(template_game_rel, "texture"))
    parts = new_game_rel.split("/")
    injected = os.path.join(scratch, "inject", *parts) + ".uasset"
    os.makedirs(os.path.dirname(injected), exist_ok=True)
    r = uat(["inject_texture", os.path.abspath(work + ".uasset"), os.path.abspath(png),
             os.path.abspath(injected), "--usmap", USMAP])
    if not os.path.isfile(injected):
        raise RuntimeError("your image could not be encoded: " + _uat_error(r, "inject_texture failed"))
    json_dir = os.path.join(scratch, "json", *parts[:-1])
    os.makedirs(json_dir, exist_ok=True)
    r = uat(["to_json", os.path.abspath(injected), USMAP, os.path.abspath(json_dir)])
    jp = os.path.join(json_dir, name + ".json")
    if not os.path.isfile(jp):
        raise RuntimeError("could not read the encoded texture: " + _uat_error(r, "to_json produced no JSON"))
    with open(jp, encoding="utf-8-sig") as f:
        doc = json.load(f)
    rename_package(doc, os.path.basename(template_game_rel), name, GAME_PREFIX + new_game_rel)
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(doc, f)
    built = os.path.join(scratch, "out", *parts) + ".uasset"
    os.makedirs(os.path.dirname(built), exist_ok=True)
    r = uat(["from_json", os.path.abspath(jp), os.path.abspath(built), USMAP])
    if not os.path.isfile(built):
        raise RuntimeError("could not rename the encoded texture: " + _uat_error(r, "from_json produced no uasset"))
    # .uasset/.uexp from the rename; the bulk mips exactly as inject_texture wrote them.
    for ext in (".ubulk", ".uptnl"):
        if os.path.isfile(injected[:-7] + ext):
            shutil.copyfile(injected[:-7] + ext, built[:-7] + ext)
    _verify_rename(scratch, injected, built, name)
    return [built[:-7] + ext for ext in (".uasset", ".uexp", ".ubulk", ".uptnl")
            if os.path.isfile(built[:-7] + ext)]


def _decoded(uasset, out_png):
    """(size, sha256 of RGBA pixels) of what UAssetTool decodes from a texture package, or None."""
    from PIL import Image
    uat(["extract_texture", os.path.abspath(uasset), os.path.abspath(out_png), "--usmap", USMAP])
    if not os.path.isfile(out_png):
        return None
    with Image.open(out_png) as im:
        img = im.convert("RGBA")
        return img.size, hashlib.sha256(img.tobytes()).hexdigest()


def _verify_rename(scratch, injected, built, name):
    """Refuse a renamed texture that no longer decodes to what was injected.

    The rename rewrites the package header (two names are added) and re-emits the .uexp, while the
    bulk mips are carried over untouched. That is the same pass set_texture_group relies on, but a
    header that grew is the one thing a group change never does, so it is checked rather than
    trusted: the injected package and the renamed one must decode to identical pixels. Comparing
    the two isolates the rename — whatever inject_texture chose for the mip chain is the baseline.
    When the injected package itself cannot be decoded there is no baseline, and the texture ships
    as an ordinary texture edit would (stage_inject does not decode its output either)."""
    folder = os.path.join(scratch, "verify")
    os.makedirs(folder, exist_ok=True)
    before = _decoded(injected, os.path.join(folder, name + ".injected.png"))
    if before is None:
        print(f"  [warn] {name}: the encoded texture could not be decoded, so the rename is unverified",
              file=sys.stderr, flush=True)
        return
    after = _decoded(built, os.path.join(folder, name + ".renamed.png"))
    if after != before:
        got = f"{after[0][0]}×{after[0][1]}" if after else "nothing"
        raise RuntimeError(f"renaming the encoded texture changed it (decoded {got} instead of "
                           f"{before[0][0]}×{before[0][1]}), so it was not shipped")


def apply(doc, material_game_rel, slots, scratch, project_dir=None):
    """Build each assigned texture and point its slot at it, editing the material JSON `doc`.

    Returns [(files, new_game_rel)] for the caller to publish once the material itself has built,
    so a failure anywhere leaves nothing half-staged. Slots are resolved against the CURRENT game
    material (stage_material rebases onto vanilla), and a slot that no longer exists is an error
    rather than a silent drop — the same rule stage_material applies to colours and scalars."""
    from atelier.handlers.material import texture_slots
    from atelier.handlers.meshgraft import _add_import
    from atelier.properties import mark_changed
    if not slots:
        return []
    current = texture_slots(doc)
    missing = sorted(set(slots) - set(current))
    if missing:
        raise RuntimeError("Current material no longer has texture slots: " + ", ".join(missing))
    doc.setdefault("NameMap", [])
    folder = store_dir(project_dir)
    staged = []
    for slot in sorted(slots):
        rec, cur = slots[slot], current[slot]
        if cur["class"] != "Texture2D":
            raise RuntimeError(f"{slot}: only Texture2D slots can use your own image "
                               f"(this slot holds a {cur['class'] or 'non-texture'} asset)")
        png = os.path.join(folder, rec["file"])
        if not os.path.isfile(png):
            raise RuntimeError(f"{slot}: your image {rec.get('source') or rec['file']} is missing "
                               f"from the project — choose it again in the material editor")
        new_gr = package_game_rel(material_game_rel, slot, rec["name"])
        files = build_texture(scratch, cur["game_rel"], png, new_gr)
        pkg_idx = _add_import(doc, GAME_PREFIX + new_gr, 0, cur["package"])
        obj_idx = _add_import(doc, rec["name"], pkg_idx, cur["import"])
        mark_changed(cur["entry"], cur["value"])
        cur["value"]["Value"] = obj_idx
        staged.append((files, new_gr))
    return staged
