"""Headless Blender: turn an exported .glb into the .blend the user actually edits.

Run by atelier.handlers.meshedit; not meant to be invoked by hand.
    blender --background --python glb_to_blend.py -- <in.glb> <out.blend> [materials.json]

The optional manifest (written by atelier.handlers.meshmat) maps each material slot to the
textures its MaterialInstance samples, already staged as PNGs in the user's project folder.
Those images are LINKED, never packed: the file on disk is the same one the mod builder
injects, so painting it here and saving is the edit that ships.
"""
import json
import os
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
src, dst = argv[0], argv[1]
manifest_path = argv[2] if len(argv) > 2 else None

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)

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

# UNBIND the armature for editing.
#
# The exported bone rest transforms are not trustworthy: positions convert cleanly between
# UE and glTF, but the rotation quaternions do not survive the left-handed -> right-handed
# change with only an axis rotation applied, so posed (Object Mode) display explodes the
# mesh into spikes even though the underlying vertex data is correct. None of that reaches
# the game -- the rebuild reuses the cooked skeleton verbatim and reads back only vertex
# positions and weights -- so rather than ship a broken preview, drop the Armature modifier
# and hide the armature. Vertex groups live on the MESH and are unaffected, so weights
# survive editing untouched; blend_to_glb.py re-binds before export so skinning is written.
for mod in [m for m in mesh_obj.modifiers if m.type == "ARMATURE"]:
    mesh_obj.modifiers.remove(mod)
arm_obj.hide_viewport = True
arm_obj.hide_render = True
arm_obj.hide_select = True
arm_obj.lock_location = arm_obj.lock_rotation = arm_obj.lock_scale = (True, True, True)

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


def _principled(mat):
    for n in mat.node_tree.nodes:
        if n.type == "BSDF_PRINCIPLED":
            return n
    out = next((n for n in mat.node_tree.nodes if n.type == "OUTPUT_MATERIAL"), None) \
        or mat.node_tree.nodes.new("ShaderNodeOutputMaterial")
    bsdf = mat.node_tree.nodes.new("ShaderNodeBsdfPrincipled")
    mat.node_tree.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return bsdf


def _image_node(mat, path, colorspace, x, y, label):
    img = bpy.data.images.load(path, check_existing=True)
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


def wire_material(mat, maps):
    """Wire one material's PBR roles. Unknown params are still loaded, just unconnected --
    MR's ColorID/dyeing masks are real editable textures with no sane shader role to guess."""
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = _principled(mat)
    n = 0
    for i, mp in enumerate(maps):
        path, role = mp.get("path"), mp.get("role")
        if not path or not os.path.exists(path):
            continue
        srgb = role in ("basecolor", "emissive")
        y = -320 * i
        tex = _image_node(mat, path, "sRGB" if srgb else "Non-Color", -900, y, mp.get("param") or "")
        n += 1
        if role == "basecolor":
            nt.links.new(tex.outputs["Color"], _socket(bsdf, "Base Color"))
        elif role == "normal":
            _wire_normal(nt, tex, bsdf, y)
        elif role == "orm":
            sep = nt.nodes.new("ShaderNodeSeparateColor"); sep.location = (-620, y)
            nt.links.new(tex.outputs["Color"], sep.inputs["Color"])
            nt.links.new(sep.outputs[1], _socket(bsdf, "Roughness"))     # G
            nt.links.new(sep.outputs[2], _socket(bsdf, "Metallic"))      # B
        elif role == "emissive":
            em = _socket(bsdf, "Emission Color", "Emission")
            if em:
                nt.links.new(tex.outputs["Color"], em)
            st = _socket(bsdf, "Emission Strength")
            if st:
                st.default_value = 1.0
    return n


wired_mats = wired_imgs = 0
if manifest_path and os.path.exists(manifest_path):
    slots = (json.load(open(manifest_path, encoding="utf-8")) or {}).get("slots", {})
    for mat in mesh_obj.data.materials:
        # Match by NAME: the slot name is the key the rebuild matches sections on, so it is also
        # the only stable identity a material has here. Renaming one breaks the build either way.
        rec = slots.get(mat.name) if mat else None
        if not rec:
            continue
        got = wire_material(mat, rec.get("maps") or [])
        if got:
            wired_mats += 1
            wired_imgs += got

bpy.ops.wm.save_as_mainfile(filepath=dst)
me = mesh_obj.data
print(f"BLEND_OK verts={len(me.vertices)} polys={len(me.polygons)} "
      f"materials={len(me.materials)} uvs={len(me.uv_layers)} bones={len(arm_obj.data.bones)} "
      f"textured={wired_mats} images={wired_imgs}")
