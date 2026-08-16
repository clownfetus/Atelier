"""Cross-character grafts: point one of a mesh's material slots at ANOTHER character's
MaterialInstance, so geometry transplanted from that character keeps its original surface.

WHY THIS IS THE WHOLE FEATURE. A section's identity in the cooked format is its material --
sections are vertex-contiguous, never share a vertex, and glb_to_sections matches Blender
primitives back to sections by material NAME (mesh.py S3.9). So moving a donor's hair onto a
target is really two separate jobs: put the vertices in the target's hair section (done in
Blender, by assigning them to that section's existing material slot), and make that section
render with the DONOR's material instead of the target's. Only the second one needs code --
and without it the transplanted hair shows up wearing the target's own hair texture.

Nothing extra ships. The donor's MaterialInstance and its textures are ordinary base-game
packages; a hard reference to one resolves at runtime the same way the target's own materials
do. That is what makes a later retexture of the DONOR show up on the target automatically --
there is no copied material to drift out of sync.

HOW THE REFERENCE IS ADDED. FSkeletalMaterial.MaterialInterface is an FPackageIndex into the
package's import table, and the import table lives in the .uasset while the material array
lives in the .uexp. The two halves are therefore patched by different means:

  .uasset -- two imports are appended (a Package import naming the donor's package path, and
             a MaterialInstanceConstant import whose OuterIndex points at it) via
             `uat to_json` -> mutate -> `uat from_json`. Growing the import table shifts the
             name table, every summary offset and every export's SerialOffset; UAssetAPI
             recomputes all of that on write, so none of it is done by hand here.
  .uexp   -- MaterialInterface is overwritten in place, 4 bytes, no resize (offset captured as
             `pkg_off` by mesh._try_extras).

The .uexp emitted by from_json is byte-identical to the one fed in (verified on
SK_10290_1029304: 5,966,143 bytes, zero differences), so the staged .uexp we built is kept and
only the .uasset is taken from the round-trip -- the geometry that ships is always the geometry
this pipeline produced, never a re-serialisation of it.

ON THE ROUND-TRIP BEING "LOSSY". from_json does perturb the .uasset: Marvel Rivals ships
cooked packages with ZEROED name-table hashes and the JSON carries names as plain strings, so
UAssetAPI recomputes them on write (2,292 bytes over 587 name entries on the reference mesh;
`uat fix`, which reads and writes binary directly, is byte-exact by comparison). This does not
reach the game. Verified by building the same mesh twice through create_mod_iostore, once from
the vanilla .uasset and once from the round-tripped one, into the SAME output name: the
resulting .ucas, .utoc and .pak are byte-identical. The Zen conversion rebuilds the name map
from scratch and discards the legacy hashes entirely. (Both containers must be built under the
same output name to compare -- the container ID is derived from it, and differing names alone
account for an 8-byte .ucas difference that has nothing to do with the package contents.)
"""
import json
import os
import shutil
import struct
import sys
import tempfile

from atelier.config import USMAP
from atelier.tools import uat

_GAME_PREFIX = "/Game/Marvel/"


def _pkg_path(donor_mi):
    """Donor MI as a full UE package path, accepting either form the project uses.

    `game_rel` ('Characters/1024/1024307/Material/MI_x') is what meshmat._mi_from_imports
    returns and what the graft sidecar is written with; a full '/Game/...' path is passed
    through so a path copied straight out of an import table also works.
    """
    p = (donor_mi or "").strip().replace("\\", "/")
    if p.lower().endswith(".uasset"):
        p = p[:-len(".uasset")]
    if not p.strip("/"):
        raise ValueError("empty donor material path")
    if p.startswith("/"):
        return p                                  # already a full package path
    return _GAME_PREFIX + p


def load_graft(blend_path):
    """Read `<blend>.graft.json` (written by hand or by the agent driving Blender).

    Shape:
        {"slots": {"<cooked slot name>": {"repoint": "<donor MI game_rel>",
                                          "reweight": "all"|"zero_weight"|null}}}
    Returns {} when there is no sidecar, so the ordinary edit path is unaffected.
    """
    path = graft_path(blend_path)
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        cfg = json.load(fh) or {}
    slots = cfg.get("slots") or {}
    if not isinstance(slots, dict):
        raise ValueError(f"{path}: 'slots' must be an object keyed by cooked slot name")
    for name, rec in slots.items():
        if not isinstance(rec, dict):
            raise ValueError(f"{path}: slot {name!r} must map to an object")
        rw = rec.get("reweight", "all")
        if rw not in ("all", "zero_weight", None):
            raise ValueError(f"{path}: slot {name!r} has reweight={rw!r}; "
                             f"expected 'all', 'zero_weight' or null")
    return cfg


def graft_path(blend_path):
    return os.path.splitext(blend_path)[0] + ".graft.json" if blend_path else None


def repoints_from(cfg):
    """{slot name: donor MI} for the slots that ask for a repoint."""
    return {name: rec["repoint"]
            for name, rec in ((cfg or {}).get("slots") or {}).items()
            if rec.get("repoint")}


def reweights_from(cfg):
    """{slot name: 'all'|'zero_weight'} for the slots that ask to be re-rigged."""
    out = {}
    for name, rec in ((cfg or {}).get("slots") or {}).items():
        mode = rec.get("reweight", "all")
        if mode:
            out[name] = mode
    return out


def _verify_donor(pkg_path):
    """Fail loudly when the donor package isn't in the paks.

    A repoint at a path the game doesn't have is the one mistake that produces no error
    anywhere downstream: create_mod_iostore happily hashes any string into an import, and the
    engine then resolves nothing and renders the section with the default material. Since the
    path is typed by hand into the sidecar, a wrong folder ('Material/' for 'Materials/') is
    the likely failure -- catch it here, where the message can name the near-misses.
    """
    from atelier.handlers.meshmat import _index_candidates
    name = pkg_path.rsplit("/", 1)[-1]
    want = pkg_path[len(_GAME_PREFIX):] if pkg_path.startswith(_GAME_PREFIX) else None
    cands = _index_candidates(name)
    if want and want in cands:
        return
    if not cands:
        raise ValueError(f"donor material {name!r} is not in the game paks at all "
                         f"(looked for package {pkg_path})")
    raise ValueError(
        f"donor package {pkg_path} is not in the paks, though {len(cands)} asset(s) named "
        f"{name!r} are. Did you mean: " + ", ".join(_GAME_PREFIX + c for c in sorted(cands)[:4]))


def _find_slot(materials, slot_name):
    hits = [i for i, m in enumerate(materials) if m.get("slot_name") == slot_name]
    if not hits:
        known = ", ".join(sorted(str(m.get("slot_name")) for m in materials))
        raise ValueError(f"no material slot named {slot_name!r} on this mesh -- slots are: {known}")
    if len(hits) > 1:
        raise ValueError(f"material slot {slot_name!r} appears {len(hits)} times; "
                         f"cannot tell which one to repoint")
    return hits[0]


def _add_import(doc, object_name, outer_index, template):
    """Append an import cloned from `template`, swapping only the name and outer.

    The class fields are copied rather than spelled out: a repoint is always MI -> MI, so the
    donor's ClassPackage/ClassName are identical to the ones already on the slot being
    replaced, and cloning them removes any chance of naming a class the package doesn't
    otherwise reference.
    """
    imp = dict(template)
    imp["ObjectName"] = object_name
    imp["OuterIndex"] = outer_index
    doc["Imports"].append(imp)
    if object_name not in doc["NameMap"]:
        doc["NameMap"].append(object_name)
    return -len(doc["Imports"])              # FPackageIndex for the entry just appended


def _import_at(doc, pkg_idx):
    ii = -pkg_idx - 1
    imports = doc.get("Imports") or []
    if not (isinstance(pkg_idx, int) and pkg_idx < 0 and 0 <= ii < len(imports)):
        raise ValueError(f"material references package index {pkg_idx}, which is not an import")
    return imports[ii]


def repoint(base, repoints, usmap=None, verbose=True):
    """Repoint material slots on the staged mesh at `base` (a path with no extension).

    `repoints` is {cooked slot name: donor MI game_rel}. Rewrites base.uasset in place and
    patches base.uexp's FSkeletalMaterial entries. Returns a list of applied descriptions.

    Must run BEFORE `uat fix`, which stays the last word on the export's SerialSize (see
    BLENDER.md S3.13).
    """
    from atelier.handlers import mesh as _mesh

    if not repoints:
        return []
    usmap = usmap or USMAP
    uasset, uexp = base + ".uasset", base + ".uexp"
    for p in (uasset, uexp):
        if not os.path.exists(p):
            raise RuntimeError(f"missing {p} -- repoint runs on a staged mesh")

    blob = bytearray(open(uexp, "rb").read())
    extras = _mesh.find_extras(bytes(blob))
    names = _mesh.find_name_table(open(uasset, "rb").read())[1]
    materials = _mesh.resolve_materials(extras["materials"], names)

    tmp = tempfile.mkdtemp(prefix="atelier_graft_")
    try:
        r = uat(["to_json", os.path.abspath(uasset), usmap, os.path.abspath(tmp)])
        doc_path = os.path.join(tmp, os.path.basename(base) + ".json")
        if not os.path.exists(doc_path):
            raise RuntimeError("uat to_json produced no JSON: "
                               + ((r.stdout or "") + (r.stderr or ""))[-400:])
        with open(doc_path, encoding="utf-8-sig") as fh:
            doc = json.load(fh)

        applied, patches = [], []
        for slot_name, donor in repoints.items():
            mi = _find_slot(materials, slot_name)
            mat = materials[mi]
            old = _import_at(doc, mat["pkg_idx"])
            old_pkg = _import_at(doc, old["OuterIndex"])
            pkg_path = _pkg_path(donor)
            _verify_donor(pkg_path)
            obj_name = pkg_path.rsplit("/", 1)[-1]

            new_pkg_idx = _add_import(doc, pkg_path, 0, old_pkg)
            new_obj_idx = _add_import(doc, obj_name, new_pkg_idx, old)
            patches.append((mat["pkg_off"], new_obj_idx))
            applied.append(f"{slot_name}: {old['ObjectName']} -> {obj_name} ({pkg_path})")
            if verbose:
                print(f"[graft] repoint {slot_name!r}: import {mat['pkg_idx']} "
                      f"({old['ObjectName']}) -> {new_obj_idx} ({pkg_path})", flush=True)

        with open(doc_path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)

        out_dir = os.path.join(tmp, "out")
        os.makedirs(out_dir, exist_ok=True)
        out_uasset = os.path.join(out_dir, os.path.basename(uasset))
        r = uat(["from_json", os.path.abspath(doc_path), os.path.abspath(out_uasset), usmap])
        if not os.path.exists(out_uasset):
            raise RuntimeError("uat from_json produced no .uasset: "
                               + ((r.stdout or "") + (r.stderr or ""))[-400:])

        # Keep OUR .uexp: from_json re-emits one, and it is byte-identical to the input, but
        # the geometry that ships should be the geometry this pipeline built, not a
        # round-trip of it. Verify the assumption rather than trusting it.
        out_uexp = os.path.join(out_dir, os.path.basename(uexp))
        if os.path.exists(out_uexp):
            if open(out_uexp, "rb").read() != bytes(blob):
                raise RuntimeError(
                    "uat from_json changed the .uexp -- the export blob did not round-trip, "
                    "so the repoint cannot be applied without rebuilding geometry")
        shutil.copyfile(out_uasset, uasset)

        for off, new_idx in patches:
            struct.pack_into("<i", blob, off, new_idx)
        with open(uexp, "wb") as fh:
            fh.write(blob)
        return applied
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _main(argv):
    if len(argv) < 2:
        print("usage: python -m atelier.handlers.meshgraft repoint <base-no-ext> "
              "<slot>=<donor MI game_rel> [...]")
        return 2
    if argv[0] != "repoint":
        print(f"unknown command {argv[0]!r}")
        return 2
    base = argv[1]
    pairs = {}
    for a in argv[2:]:
        if "=" not in a:
            print(f"expected <slot>=<donor>, got {a!r}")
            return 2
        k, v = a.split("=", 1)
        pairs[k] = v
    for line in repoint(base, pairs):
        print("applied " + line)
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
