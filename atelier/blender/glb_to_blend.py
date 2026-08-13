"""Headless Blender: turn an exported .glb into the .blend the user actually edits.

Run by atelier.handlers.meshedit; not meant to be invoked by hand.
    blender --background --python glb_to_blend.py -- <in.glb> <out.blend>
"""
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
src, dst = argv[0], argv[1]

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

bpy.ops.wm.save_as_mainfile(filepath=dst)
me = mesh_obj.data
print(f"BLEND_OK verts={len(me.vertices)} polys={len(me.polygons)} "
      f"materials={len(me.materials)} uvs={len(me.uv_layers)} bones={len(arm_obj.data.bones)}")
