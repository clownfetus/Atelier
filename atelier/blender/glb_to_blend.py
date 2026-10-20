"""Headless Blender: turn an exported .glb into the .blend the user actually edits.

Run by atelier.handlers.meshedit; not meant to be invoked by hand.
    blender --background --python glb_to_blend.py -- <in.glb> <out.blend> [materials.json]

The optional manifest (written by atelier.handlers.meshmat) maps each material slot to the
textures its MaterialInstance samples, already staged as PNGs in the user's project folder.
Edit-in-Blender images stay linked to the project files that the mod builder
injects. The standalone Model Studio port sets pack_images in the manifest so
the scene remains portable after its preparation directory is removed.
"""
import json
import os
import struct
import sys
import tempfile

import bpy
import numpy as np

argv = sys.argv[sys.argv.index("--") + 1:]
src, dst = argv[0], argv[1]
manifest_path = argv[2] if len(argv) > 2 else None
manifest=json.load(open(manifest_path,encoding='utf-8')) if manifest_path and os.path.isfile(manifest_path) else {}
portable=bool(manifest.get('pack_images'))


# ── morph tracking attributes, past Blender's importer ─────────────────────────
# mesh.export_glb writes three per-vertex custom attributes the rebuild needs back:
# _ATELIER_MORPH_REST (VEC3), _ATELIER_MORPH_ID and _ATELIER_MORPH_LOD (SCALAR). Blender's glTF
# importer (4.5 through 5.1) collects custom attribute NAMES into a set but their DATA into a list
# in file order, then zips the two -- so whenever a primitive has two or more, the pairing follows
# the interpreter's per-run string hashing. One run in two crashes concatenating a VEC3 with a
# SCALAR ("along dimension 1, the array at index 0 has size 3 and ... size 1"); some of the rest
# swap the ID and LOD columns without any error. Upstream later fixed the ordering, but the user's
# Blender is whatever it is.
#
# With ONE custom attribute there is nothing to mispair. _ATELIER_MORPH_ID is a vertex's index in
# the cooked LOD, unique across every primitive, so it alone goes through the importer and the
# other two are rebuilt from the GLB's own data by looking each vertex up by its ID.
_RESTORED = ("_ATELIER_MORPH_REST", "_ATELIER_MORPH_LOD")
_WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


def _read_glb(path):
    data = open(path, "rb").read()
    magic, _version, _total = struct.unpack_from("<III", data, 0)
    jlen, jtype = struct.unpack_from("<II", data, 12)
    if magic != 0x46546C67 or jtype != 0x4E4F534A:
        raise SystemExit(f"{path} is not a binary glTF")
    gltf = json.loads(data[20:20 + jlen])
    off = 20 + jlen
    blen = struct.unpack_from("<I", data, off)[0] if off + 8 <= len(data) else 0
    return gltf, data[off + 8:off + 8 + blen]


def _float_accessor(gltf, binary, index):
    a = gltf["accessors"][index]
    view = gltf["bufferViews"][a["bufferView"]]
    width = _WIDTH[a["type"]]
    if a.get("componentType") != 5126 or view.get("byteStride", 4 * width) != 4 * width:
        raise SystemExit("morph tracking attributes must be tightly packed float32")
    start = view.get("byteOffset", 0) + a.get("byteOffset", 0)
    return np.frombuffer(binary, "<f4", a["count"] * width, start).reshape(a["count"], width)


def _strip_tracking(path):
    """(path to import, {id: (rest xyz, lod)} or None). Writes a copy whose primitives carry only
    _ATELIER_MORPH_ID; the buffer is untouched, so every other accessor reads exactly as before."""
    gltf, binary = _read_glb(path)
    ids, rests, lods = [], [], []
    for mesh in gltf.get("meshes", []):
        for prim in mesh.get("primitives", []):
            at = prim.get("attributes", {})
            if "_ATELIER_MORPH_ID" not in at or not all(k in at for k in _RESTORED):
                continue
            ids.append(_float_accessor(gltf, binary, at["_ATELIER_MORPH_ID"])[:, 0])
            rests.append(_float_accessor(gltf, binary, at["_ATELIER_MORPH_REST"]))
            lods.append(_float_accessor(gltf, binary, at["_ATELIER_MORPH_LOD"])[:, 0])
            for k in _RESTORED:
                del at[k]
    if not ids:
        return path, None
    ids = np.rint(np.concatenate(ids)).astype(np.int64)
    if ids.min() < 0 or len(np.unique(ids)) != len(ids):
        raise SystemExit("morph tracking IDs are not unique vertex indices; cannot import safely")
    table = {"ids": ids, "rest": np.concatenate(rests), "lod": np.concatenate(lods)}
    js = json.dumps(gltf).encode("utf-8")
    js += b" " * (-len(js) % 4)
    fd, out = tempfile.mkstemp(prefix="atelier-import-", suffix=".glb")   # never in the project folder
    with os.fdopen(fd, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(binary)))
        f.write(struct.pack("<II", len(js), 0x4E4F534A)); f.write(js)
        f.write(struct.pack("<II", len(binary), 0x004E4942)); f.write(binary)
    return out, table


def _restore_tracking(me, table):
    """Recreate REST/LOD on the imported mesh, keyed by each vertex's _ATELIER_MORPH_ID -- the same
    names, types and POINT domain the importer itself would have created."""
    idattr = me.attributes.get("_ATELIER_MORPH_ID")
    if idattr is None or idattr.domain != "POINT":
        # An importer that skips custom attributes altogether: the mesh still edits and rebuilds
        # (mesh.glb_to_sections falls back without them), exactly as it did before this existed.
        print("[glb_to_blend] warning: the importer kept no custom attributes; morph tracking skipped",
              flush=True)
        return
    n = len(me.vertices)
    got = np.empty(n, np.float32)
    idattr.data.foreach_get("value", got)
    got = np.rint(got).astype(np.int64)
    slot = np.full(int(max(table["ids"].max(), got.max(initial=0))) + 1, -1, np.int64)
    slot[table["ids"]] = np.arange(len(table["ids"]))
    rows = slot[np.clip(got, 0, len(slot) - 1)]
    if (got < 0).any() or (rows < 0).any():
        raise SystemExit("imported vertices carry IDs the GLB never wrote; morph tracking would be wrong")
    rest = me.attributes.new("_ATELIER_MORPH_REST", "FLOAT_VECTOR", "POINT")
    rest.data.foreach_set("vector", table["rest"][rows].astype(np.float32).ravel())
    lod = me.attributes.new("_ATELIER_MORPH_LOD", "FLOAT", "POINT")
    lod.data.foreach_set("value", table["lod"][rows].astype(np.float32))


bpy.ops.wm.read_factory_settings(use_empty=True)
import_path, tracking = _strip_tracking(src)
try:
    bpy.ops.import_scene.gltf(filepath=import_path)
finally:
    if import_path != src and os.path.exists(import_path):
        os.remove(import_path)

# Third-party add-ons in the user's Blender profile can drop helper objects into an
# otherwise-empty scene (fast64 adds a bone-shape Icosphere). Anything that is not ours
# would be exported back out and rebuilt into the mod as stray geometry.
KEEP = {"Armature", "SkeletalMesh"}
for o in list(bpy.data.objects):
    if o.name not in KEEP:
        bpy.data.objects.remove(o, do_unlink=True)

mesh_obj = bpy.data.objects.get("SkeletalMesh")
arm_obj = bpy.data.objects.get("Armature")
if mesh_obj is None or arm_obj is None:
    raise SystemExit("expected both 'SkeletalMesh' and 'Armature' after import")
if tracking is not None:
    _restore_tracking(mesh_obj.data, tracking)

# Keep the ordinary geometry round trip in component space while sculpting.
# Portable exports retain the working deformation rig. Correct column-major
# inverse bind matrices now keep its bone heads and resting surface intact.
if not portable:
    for mod in [m for m in mesh_obj.modifiers if m.type == "ARMATURE"]:mesh_obj.modifiers.remove(mod)
arm_obj.hide_viewport = arm_obj.hide_select = not portable
arm_obj.hide_render = True
arm_obj.lock_location = arm_obj.lock_rotation = arm_obj.lock_scale = (not portable,)*3

bpy.context.view_layer.objects.active = mesh_obj
mesh_obj.select_set(True)


# ── material wiring ───────────────────────────────────────────────────────────
# Socket names moved between Blender releases ("Emission" -> "Emission Color" in 4.x), so look
# a socket up by any of its historical names rather than pinning one version.
def _socket(node, *names):
    for n in names:
        if n in node.inputs:
            return node.inputs[n]
    return None


def _image_node(mat, path, colorspace, x, y, label):
    img = bpy.data.images.load(path, check_existing=True)
    if img.users and img.colorspace_settings.name != colorspace:
        img=img.copy()
    try:
        img.colorspace_settings.name = colorspace
    except Exception:
        pass                      # an unusual colour-management config must not fail the extract
    node = mat.node_tree.nodes.new("ShaderNodeTexImage")
    node.image = img
    node.label = label
    node.location = (x, y)
    return node


def _math(nt, op, x, y, a=None, b=None, c=None):
    n = nt.nodes.new("ShaderNodeMath")
    n.operation = op
    n.location = (x, y)
    for i, v in enumerate((a, b, c)):
        if v is not None:
            n.inputs[i].default_value = v
    return n


def _wire_normal(nt, tex, bsdf, y):
    """Normal map -> BSDF, rebuilding the Z channel the way the engine does at runtime.

    MR ships normal maps as BC5, which stores only TWO channels. The decoded PNG therefore has
    B == 0 everywhere, and feeding that straight to a Normal Map node decodes Z as 2*0-1 = -1:
    every normal points INTO the surface and the whole character reads inside-out/concave. The
    blue is not missing from our decode, it is absent from the format -- so it has to be
    reconstructed, never "fixed" in the PNG (that file is the game's own data and gets injected
    back verbatim).

        x = 2R-1, y = 2G-1, z = sqrt(1 - x^2 - y^2)

    Applied unconditionally: for a genuine 3-channel normal map this reproduces the stored blue,
    so there is nothing to detect. The green channel is inverted first because UE authors normals
    in the DirectX convention (green down) while Blender reads OpenGL (green up); Z is even in y,
    so the flip does not disturb the reconstruction."""
    sep = nt.nodes.new("ShaderNodeSeparateColor"); sep.location = (-960, y)
    nt.links.new(tex.outputs["Color"], sep.inputs["Color"])

    xs = _math(nt, "MULTIPLY_ADD", -790, y + 90, None, 2.0, -1.0)      # x = 2R-1
    ys = _math(nt, "MULTIPLY_ADD", -790, y - 90, None, 2.0, -1.0)      # y = 2G-1
    nt.links.new(sep.outputs[0], xs.inputs[0])
    nt.links.new(sep.outputs[1], ys.inputs[0])

    xsq = _math(nt, "MULTIPLY", -620, y + 90); nt.links.new(xs.outputs[0], xsq.inputs[0]); nt.links.new(xs.outputs[0], xsq.inputs[1])
    ysq = _math(nt, "MULTIPLY", -620, y - 90); nt.links.new(ys.outputs[0], ysq.inputs[0]); nt.links.new(ys.outputs[0], ysq.inputs[1])
    ssq = _math(nt, "ADD", -470, y); nt.links.new(xsq.outputs[0], ssq.inputs[0]); nt.links.new(ysq.outputs[0], ssq.inputs[1])
    inv = _math(nt, "SUBTRACT", -330, y, 1.0); nt.links.new(ssq.outputs[0], inv.inputs[1])
    zsq = _math(nt, "SQRT", -200, y); nt.links.new(inv.outputs[0], zsq.inputs[0])
    zb  = _math(nt, "MULTIPLY_ADD", -70, y, None, 0.5, 0.5)            # back to [0,1] for the node
    nt.links.new(zsq.outputs[0], zb.inputs[0])

    ginv = _math(nt, "SUBTRACT", -330, y - 220, 1.0)                   # DirectX -> OpenGL green
    nt.links.new(sep.outputs[1], ginv.inputs[1])

    comb = nt.nodes.new("ShaderNodeCombineColor"); comb.location = (80, y)
    nt.links.new(sep.outputs[0], comb.inputs[0])
    nt.links.new(ginv.outputs[0], comb.inputs[1])
    nt.links.new(zb.outputs[0], comb.inputs[2])

    nmap = nt.nodes.new("ShaderNodeNormalMap"); nmap.location = (240, y)
    nt.links.new(comb.outputs["Color"], nmap.inputs["Color"])
    nt.links.new(nmap.outputs["Normal"], _socket(bsdf, "Normal"))
    return nmap


sys.path.insert(0,os.path.dirname(__file__))
from material_nodes import wire_material as wire_surface

wired_mats = wired_imgs = 0
material_report=[]
if manifest_path and os.path.exists(manifest_path):
    slots = manifest.get("slots", {})
    for mat in mesh_obj.data.materials:
        # Match by NAME: the slot name is the key the rebuild matches sections on, so it is also
        # the only stable identity a material has here. Renaming one breaks the build either way.
        rec = slots.get(mat.name) if mat else None
        if not rec:
            continue
        report=wire_surface(mat,rec,_image_node,_wire_normal)
        material_report.append(report)
        if report['textures']:
            wired_mats += 1
            wired_imgs += report['textures']
    if manifest.get('pack_images'):
        bpy.ops.file.pack_all()

print('MATERIAL_REPORT '+json.dumps({'materials':material_report,'images':wired_imgs,'blender':bpy.app.version_string,
               'missing_images':[image.filepath for image in bpy.data.images if image.source=='FILE' and not image.packed_file and not os.path.isfile(bpy.path.abspath(image.filepath))]}))

bpy.ops.wm.save_as_mainfile(filepath=dst)
me = mesh_obj.data
print(f"BLEND_OK verts={len(me.vertices)} polys={len(me.polygons)} "
      f"materials={len(me.materials)} uvs={len(me.uv_layers)} bones={len(arm_obj.data.bones)} "
      f"textured={wired_mats} images={wired_imgs}")
