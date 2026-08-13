"""Headless Blender: export the user's edited .blend back to .glb, optionally decimated.

A decimate ratio < 1 is used to generate the lower LODs from the same edited mesh, so the
user only ever edits LOD0. The Decimate modifier is applied explicitly here rather than
via the exporter's export_apply, because export_apply also evaluates the Armature modifier
and that interferes with exporting clean skinning data.

    blender --background --python blend_to_glb.py -- <in.blend> <out.glb> [ratio]
"""
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
src, dst = argv[0], argv[1]
ratio = float(argv[2]) if len(argv) > 2 else 1.0

bpy.ops.wm.open_mainfile(filepath=src)

for o in list(bpy.data.objects):
    if o.name not in ("Armature", "SkeletalMesh"):
        bpy.data.objects.remove(o, do_unlink=True)

obj = bpy.data.objects.get("SkeletalMesh")
if obj is None:
    raise SystemExit("no 'SkeletalMesh' object in the .blend -- do not rename it")

bpy.context.view_layer.objects.active = obj
obj.select_set(True)
if obj.mode != "OBJECT":
    bpy.ops.object.mode_set(mode="OBJECT")

before = (len(obj.data.vertices), len(obj.data.polygons))
if ratio < 1.0:
    mod = obj.modifiers.new(name="AtelierLOD", type="DECIMATE")
    mod.decimate_type = "COLLAPSE"
    mod.ratio = ratio
    mod.use_collapse_triangulate = True     # emit triangles; the cooked format has no quads
    bpy.ops.object.modifier_apply(modifier=mod.name)
after = (len(obj.data.vertices), len(obj.data.polygons))
print(f"DECIMATE ratio={ratio} verts {before[0]}->{after[0]} polys {before[1]}->{after[1]}")

# Re-bind the armature that glb_to_blend.py unbound for editing. The glTF exporter decides
# what to write as a skin from the mesh's ARMATURE modifier, so without this the export
# silently omits JOINTS/WEIGHTS and every vertex would come back unweighted. Added AFTER
# the decimate is applied so the modifier stack order stays clean.
arm = bpy.data.objects.get("Armature")
if arm is None:
    raise SystemExit("no 'Armature' object in the .blend -- do not delete it; it is hidden, not unused")
arm.hide_viewport = False
arm.hide_render = False
arm.hide_select = False
if not any(m.type == "ARMATURE" for m in obj.modifiers):
    mod = obj.modifiers.new(name="Armature", type="ARMATURE")
    mod.object = arm
    print("REBOUND armature for export")
if obj.parent is None:
    obj.parent = arm

# Report surviving materials so the caller can fail loudly if decimation wiped a section
# out entirely, rather than discovering it as a confusing "material not found" later.
used = sorted({obj.data.materials[p.material_index].name
               for p in obj.data.polygons
               if obj.data.materials and obj.data.materials[p.material_index]})
print("MATERIALS " + "|".join(used))

bpy.ops.export_scene.gltf(
    filepath=dst, export_format="GLB", use_selection=False, export_apply=False,
    export_yup=True, export_texcoords=True, export_normals=True, export_tangents=True,
    export_vertex_color="ACTIVE", export_all_vertex_colors=True,
    export_skins=True,
    # The cooked mesh stores up to 8 influences. Blender defaults to 4 and only warns that
    # it keeps "the 4 with highest weight", which would quietly degrade skinning at
    # shoulders and hips before the data ever reached the rebuilder.
    export_all_influences=True, export_influence_nb=8,
    export_morph=False, export_materials="EXPORT",
)
print("GLB_OK", dst)
