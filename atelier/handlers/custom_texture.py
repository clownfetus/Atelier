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

WHERE THE NEW PACKAGE GOES. Defaults to /Game/Marvel/Atelier/Custom/<key>/<T_name>, where <key>
hashes the material and slot. Users may choose a folder in /Game/Marvel/ and asset name. Explicit
locations are validated against the game, project assets and other slot assignments on save and
export. Two slots must never share a package: each is encoded in its own slot's format.
"""
import hashlib
import base64
import io
import json
import os
import re
import shutil
import sys
import threading
from pathlib import Path

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
    return 'T_' + stem[2:] if stem[:2].upper() == "T_" and len(stem) > 2 else "T_" + stem


def package_game_rel(material_game_rel, slot, name, folder=None):
    """Storage-relative path of the new texture package (see the module docstring)."""
    if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
        raise ValueError('Use a texture name beginning T_, followed by up to 60 letters, numbers or underscores.')
    key = hashlib.sha1(f"{material_game_rel}|{slot}".encode("utf-8")).hexdigest()[:10]
    if folder is None:
        folder = f"{CUSTOM_ROOT}/{key}"
    else:
        from atelier.added_assets import folder_path
        folder = folder_path(folder)
        if len(folder) > 160 or any(len(part) > 64 for part in folder.split('/')):
            raise ValueError('Choose a shorter game folder (up to 160 characters, 64 per folder name).')
    return f"{folder}/{name}" if folder else name


def _name(value):
    if not isinstance(value, str):
        raise ValueError('Enter a texture name.')
    value = value.strip()
    if value[:2].upper() == 'T_':
        value = 'T_' + value[2:]
    else:
        value = 'T_' + value
    package_game_rel('', '', value)
    return value


def _available(material_game_rel, slot, name, folder, project_dir):
    """Case-insensitive package identity, checked before metadata or staged files change."""
    target = package_game_rel(material_game_rel, slot, name, folder)
    if folder is not None:
        from atelier import config
        from atelier.added_assets import _available as asset_available
        with config.project_context(project_dir):
            asset_available(target)
    # Windows and Unreal treat package identity without case. Do the same on Linux, including
    # ordinary edited assets that have no .asset.json record for added_assets to discover.
    extensions = ('.mesh.json', '.asset.json', '.png', '.dds', '.json', '.blend', '.uasset', '.uexp', '.ubulk', '.uptnl')
    for directory, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in ('.atelier', '.atelier-trash')]
        for filename in files:
            relative = os.path.relpath(os.path.join(directory, filename), project_dir).replace('\\', '/')
            for extension in extensions:
                if relative.lower().endswith(extension) and relative[:-len(extension)].casefold() == target.casefold():
                    raise ValueError('An asset already exists in this project at this location. Choose another name or folder.')
    for material, opts in project_meta.get_asset_opts(project_dir).items():
        if not isinstance(opts, dict):
            continue
        for other_slot, rec in assignments(material, project_dir).items():
            if material == material_game_rel and other_slot == slot:
                continue
            other = package_game_rel(material, other_slot, rec['name'], rec.get('folder'))
            if target.casefold() == other.casefold():
                raise ValueError('Another material texture slot already uses this name and folder. Choose another location.')
    return target


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
                and _FILE_RE.fullmatch(str(rec.get("file", ""))) and _NAME_RE.fullmatch(str(rec.get("name", "")))):
            try:
                package_game_rel(material_game_rel, slot, rec['name'], rec.get('folder'))
            except ValueError:
                continue
            out[slot] = dict(rec)
    return out


def public(material_game_rel, project_dir=None):
    """What the editor shows for each custom slot."""
    result = {}
    for slot, rec in assignments(material_game_rel, project_dir).items():
        path = package_game_rel(material_game_rel, slot, rec['name'], rec.get('folder'))
        result[slot] = {"name": rec["name"], "file": rec["file"], "source": rec.get("source") or "",
                        "size": rec.get("size") or [], "template": rec.get("template") or "",
                        "folder": path.rsplit('/', 1)[0] if '/' in path else '', "game_rel": path}
    return result


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


def assign(material_game_rel, slot, filename, data, template_game_rel, project_dir=None, *, name=None, folder=None):
    """Store the user's image and assign it to one slot of one material. Returns public()."""
    project_dir = project_dir or get_import_root()
    png, size = _normalized_png(data)
    file = hashlib.sha256(png).hexdigest()[:20] + ".png"
    image_folder = store_dir(project_dir)
    target = os.path.join(image_folder, file)
    # Written under the lock: another assignment's prune must never see this file before the
    # record that uses it exists.
    with _lock:
        slots = assignments(material_game_rel, project_dir)
        previous = slots.get(slot, {})
        name = _name(name) if name is not None else previous.get('name', texture_name(filename))
        folder = folder if folder is not None else previous.get('folder')
        target_gr = _available(material_game_rel, slot, name, folder, project_dir)
        if not os.path.isfile(target):
            os.makedirs(image_folder, exist_ok=True)
            tmp = target + ".tmp"
            with open(tmp, "wb") as f:
                f.write(png)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, target)
        slots[slot] = {"name": name, "file": file, "size": list(size),
                       "source": os.path.basename((filename or "").replace("\\", "/"))[:120],
                       "template": template_game_rel,
                       **({'folder': target_gr.rsplit('/', 1)[0] if '/' in target_gr else ''} if folder is not None else {})}
        _write(project_dir, material_game_rel, slots)
        prune(project_dir)
    return public(material_game_rel, project_dir)


def set_location(material_game_rel, slot, name, folder, project_dir=None):
    """Change only the package identity, preserving the source image and game texture."""
    project_dir = project_dir or get_import_root()
    name = _name(name)
    if not isinstance(folder, str):
        raise ValueError('Enter a folder within /Game/Marvel/.')
    with _lock:
        slots = assignments(material_game_rel, project_dir)
        if slot not in slots:
            raise ValueError('Assign an image to this slot before choosing its package location.')
        target = _available(material_game_rel, slot, name, folder, project_dir)
        slots[slot].update(name=name, folder=target.rsplit('/', 1)[0] if '/' in target else '')
        _write(project_dir, material_game_rel, slots)
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
    from atelier.unreal_names import add_names
    add_names(doc, new_name, new_package)
    folder = doc.get("FolderName")
    if isinstance(folder, str) and folder.startswith("/"):
        doc["FolderName"] = new_package


def _uat_error(result, fallback):
    return (((getattr(result, "stderr", "") or "") + (getattr(result, "stdout", "") or "")).strip()[-300:]
            or fallback)


def _preserve_export_bytes(doc, injected):
    """Keep UE5 DATA_RESOURCES texture payloads opaque during a package rename.

    The native JSON texture reader can lose inline mip bytes and mistake their
    pixel data for subsequent mip headers. Renaming only needs the export table,
    so use UAssetAPI's RawExport for each validated byte range. Name indices stay
    stable (new names are appended), resource offsets are unchanged, and this
    game's UE5 texture skip offsets are relative. The writer still recalculates
    the package header and export offsets. Require an identical .uexp afterwards.
    """
    if doc.get('ObjectVersionUE5') != 'DATA_RESOURCES':
        return False
    header=Path(injected).stat().st_size
    payload=Path(injected[:-7]+'.uexp').read_bytes()
    ranges=[]
    for export in doc.get('Exports',[]):
        offset,size=export.get('SerialOffset'),export.get('SerialSize')
        if type(offset) is not int or type(size) is not int or size<=0 or not 0<=offset-header<=len(payload)-size:
            raise RuntimeError('The encoded texture export range could not be validated')
        start=offset-header;ranges.append((start,start+size))
        export['$type']='UAssetAPI.ExportTypes.RawExport, UAssetAPI'
        export['Data']=base64.b64encode(payload[start:start+size]).decode('ascii')
        export['Extras']=''
    cursor=0
    for start,end in sorted(ranges):
        if start!=cursor:raise RuntimeError('The encoded texture has an unsupported export layout')
        cursor=end
    if cursor!=len(payload)-4 or payload[-4:]!=b'\xc1\x83\x2a\x9e':
        raise RuntimeError('The encoded texture payload could not be preserved completely')
    return True


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
    if r.returncode or not os.path.isfile(injected):
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
    opaque=_preserve_export_bytes(doc,injected)
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(doc, f)
    built = os.path.join(scratch, "out", *parts) + ".uasset"
    os.makedirs(os.path.dirname(built), exist_ok=True)
    r = uat(["from_json", os.path.abspath(jp), os.path.abspath(built), USMAP])
    if r.returncode or not os.path.isfile(built):
        raise RuntimeError("could not rename the encoded texture: " + _uat_error(r, "from_json produced no uasset"))
    if opaque and Path(injected[:-7]+'.uexp').read_bytes()!=Path(built[:-7]+'.uexp').read_bytes():
        raise RuntimeError('Renaming the texture altered its mip payload, so it was not shipped')
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
        new_gr = _available(material_game_rel, slot, rec["name"], rec.get('folder'), project_dir or get_import_root())
        files = build_texture(scratch, cur["game_rel"], png, new_gr)
        pkg_idx = _add_import(doc, GAME_PREFIX + new_gr, 0, cur["package"])
        obj_idx = _add_import(doc, rec["name"], pkg_idx, cur["import"])
        mark_changed(cur["entry"], cur["value"])
        cur["value"]["Value"] = obj_idx
        staged.append((files, new_gr))
    return staged
