"""Assemble a portable body/weapon scene from independently prepared mesh files."""
import json
import math
import sys

import bpy
import numpy as np
from mathutils import Matrix

path=sys.argv[sys.argv.index('--')+1]
with open(path,encoding='utf-8') as stream:manifest=json.load(stream)
bpy.ops.wm.read_factory_settings(use_empty=True)
to_blender=Matrix.Rotation(math.pi/2,4,'X')
for index,part in enumerate(manifest['parts']):
    collection=bpy.data.collections.new(part['name']);bpy.context.scene.collection.children.link(collection)
    with bpy.data.libraries.load(part['blend'],link=False) as (source,target):target.objects=source.objects
    objects=[obj for obj in target.objects if obj]
    transform=to_blender@Matrix(part['transform'])@to_blender.inverted()
    for obj in objects:
        collection.objects.link(obj)
        obj.name=part['name']+' · '+obj.name
        obj['atelier_game_rel']=part['game_rel']
        if obj.parent is None:obj.matrix_world=transform@obj.matrix_world
        if obj.type=='MESH':obj.hide_viewport=obj.hide_render=obj.hide_select=False
bpy.ops.file.pack_all()
report={'blender':bpy.app.version_string,'meshes':[],'images':[],'unconnected_textures':[],
        'armatures':[],'game_physics_simulated':False}
for obj in bpy.data.objects:
    if obj.type=='ARMATURE':
        report['armatures'].append({'name':obj.name,'bones':len(obj.data.bones),'reference_only':False,
            'nonzero_bone_heads':sum(bone.head_local.length>1e-6 for bone in obj.data.bones)})
    if obj.type!='MESH':continue
    report['meshes'].append({'name':obj.name,'game_rel':obj['atelier_game_rel'],'vertices':len(obj.data.vertices),
        'materials':[slot.material.name if slot.material else None for slot in obj.material_slots],
        'deformation_rig':any(mod.type=='ARMATURE' and mod.object for mod in obj.modifiers)})
    evaluated=obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh()
    try:
        before=np.array([tuple(vertex.co) for vertex in obj.data.vertices]);after=np.array([tuple(vertex.co) for vertex in evaluated.vertices])
        error=float(np.max(np.linalg.norm(before-after,axis=1),initial=0)) if before.shape==after.shape else float('inf')
        report['meshes'][-1]['rest_deformation_error']=error
        if error>1e-4:raise RuntimeError('The Blender bind pose changed the resting surface: '+obj.name)
    finally:obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh_clear()
for material in bpy.data.materials:
    if not material.use_nodes:continue
    for node in material.node_tree.nodes:
        if node.type=='TEX_IMAGE' and node.image and not any(output.links for output in node.outputs):
            report['unconnected_textures'].append(material.name+': '+node.label)
for image in bpy.data.images:
    if image.source=='FILE':report['images'].append({'name':image.name,'packed':bool(image.packed_file),'size':list(image.size)})
for area in bpy.context.screen.areas if bpy.context.screen else []:
    if area.type=='VIEW_3D':area.spaces.active.shading.type='MATERIAL'
if report['unconnected_textures'] or any(not image['packed'] for image in report['images']):
    raise RuntimeError('Portable scene has disconnected or unpacked textures')
bpy.ops.wm.save_as_mainfile(filepath=manifest['output'])
with open(manifest['report'],'w',encoding='utf-8') as stream:json.dump(report,stream,indent=2)
print('PORT_OK '+str(len(report['meshes']))+' meshes, '+str(len(report['images']))+' packed textures')
