"""Import replacement geometry onto the character's original armature and slots."""
import json
import os
import re
import sys
import math
import bpy
import bmesh
import numpy as np
from mathutils import Matrix, Vector, Euler
from mathutils.bvhtree import BVHTree
from mathutils.geometry import barycentric_transform

arguments=sys.argv[sys.argv.index('--')+1:]
template,source,destination,report=arguments[:4]
options={'keep_skeleton':True,'keep_weights':True,'keep_morphs':True,'keep_parts':True,**(json.loads(arguments[4]) if len(arguments)>4 else {})}
bpy.ops.wm.open_mainfile(filepath=template,load_ui=False,use_scripts=False)
original=bpy.data.objects.get('SkeletalMesh');armature=bpy.data.objects.get('Armature')
if not original or not armature:raise ValueError('The target character template is incomplete')
stock_materials=list(original.data.materials)
stock_names={mat.name:i for i,mat in enumerate(stock_materials) if mat}
known={bone.name for bone in armature.data.bones}
original.data.calc_loop_triangles()
triangles=list(original.data.loop_triangles)
world=[original.matrix_world@v.co for v in original.data.vertices]
bvh=BVHTree.FromPolygons(world,[list(t.vertices) for t in triangles],all_triangles=True)
original_weights=[{original.vertex_groups[g.group].name:g.weight for g in v.groups
                   if original.vertex_groups[g.group].name in known and g.weight>0} for v in original.data.vertices]
before=set(bpy.data.objects)
suffix=os.path.splitext(source)[1].lower()
scale_info=None
source_channels={}
if suffix=='.blend':
    with bpy.data.libraries.load(source,link=False) as (available,loaded):loaded.objects=available.objects
    for obj in loaded.objects:
        if obj:bpy.context.scene.collection.objects.link(obj)
elif suffix=='.fbx':bpy.ops.import_scene.fbx(filepath=source,use_anim=False)
elif suffix in ('.glb','.gltf'):bpy.ops.import_scene.gltf(filepath=source)
elif suffix in ('.psk','.pskx'):
    sys.path.insert(0,os.path.dirname(__file__))
    from psk_reader import read_psk,source_scale,unreal_points
    data=read_psk(source)
    if len(arguments)>5:
        with open(arguments[5],encoding='utf-8') as stream:target_bones=json.load(stream)
    else:
        target_bones={bone.name:(bone.parent.name,(bone.head_local-bone.parent.head_local).length) for bone in armature.data.bones if bone.parent}
    scale_info=source_scale(data,target_bones,options.get('source_units','auto'))
    scale_info['coordinates']='ActorX Y mirror converted to Unreal'
    mesh=bpy.data.meshes.new('Replacement')
    # ActorX's clockwise face order and the Y reflection cancel: preserving its
    # order here produces Blender's counter-clockwise fronts in game coordinates.
    faces=[[data['wedges'][w][0] for w in f[:3]] for f in data['faces']]
    mesh.from_pydata(unreal_points(data,scale_info['scale']),[],faces);mesh.update()
    obj=bpy.data.objects.new('Replacement',mesh);bpy.context.scene.collection.objects.link(obj)
    for name in data['materials']:mesh.materials.append(bpy.data.materials.new(name))
    uv=mesh.uv_layers.new(name='UVMap')
    for poly,face in zip(mesh.polygons,data['faces']):
        poly.material_index=face[3]
        poly.use_smooth=bool(face[-1])
        for loop,wedge in zip(poly.loop_indices,face[:3]):
            p,u,v=data['wedges'][wedge];uv.data[loop].uv=(u,1-v)
    for index,values in enumerate(data['extra_uvs'],1):
        extra=mesh.uv_layers.new(name='UVMap.'+str(index).zfill(3))
        for poly,face in zip(mesh.polygons,data['faces']):
            for loop,wedge in zip(poly.loop_indices,face[:3]):
                u,v=values[wedge];extra.data[loop].uv=(u,1-v)
    if data['normals']:mesh.normals_split_custom_set_from_vertices([(x,-y,z) for x,y,z in data['normals']])
    if data['colors']:
        colors=mesh.color_attributes.new(name='Color',type='FLOAT_COLOR',domain='CORNER')
        mesh.color_attributes.active_color=colors
        for poly,face in zip(mesh.polygons,data['faces']):
            for loop,wedge in zip(poly.loop_indices,face[:3]):colors.data[loop].color=tuple(value/255 for value in data['colors'][wedge])
    source_channels={'custom_normals':len(data['normals']),'vertex_colours':len(data['colors']),'secondary_uvs':len(data['extra_uvs'])}
    groups=[obj.vertex_groups.new(name=name) for name in data['bones']]
    for weight,point,bone in data['weights']:
        if weight:groups[bone].add([point],weight,'REPLACE')
else:raise ValueError('Unsupported replacement file')
if not options['keep_skeleton']:
    donors=[obj for obj in bpy.data.objects if obj not in before and obj.type=='ARMATURE']
    if len(donors)!=1:raise ValueError('This file must contain one compatible armature when Keep original skeleton is off')
    donor=donors[0]
    if {b.name for b in donor.data.bones}!=known or any((b.parent.name if b.parent else None)!=(armature.data.bones[b.name].parent.name if armature.data.bones[b.name].parent else None) for b in donor.data.bones):
        raise ValueError('The replacement armature must use the original character bone names and hierarchy. Enable Keep original skeleton to retarget the model automatically.')
    donor.data.transform(donor.matrix_world);donor.matrix_world=Matrix.Identity(4)
    bpy.data.objects.remove(armature,do_unlink=True);armature=donor;armature.name='Armature'
widgets={bone.custom_shape for obj in bpy.data.objects if obj.type=='ARMATURE' and obj.pose
         for bone in obj.pose.bones if bone.custom_shape}
meshes=[obj for obj in bpy.data.objects if obj not in before and obj not in widgets and obj.type=='MESH'
        and not obj.hide_render and obj.visible_get() and len(obj.data.polygons)]
if not meshes:raise ValueError('The selected file contains no mesh geometry')
bpy.ops.object.select_all(action='DESELECT')
for obj in meshes:
    transform=obj.matrix_world.copy()
    if obj.data.users>1:obj.data=obj.data.copy()
    obj.parent=None
    obj.data.transform(transform,shape_keys=True);obj.matrix_world=Matrix.Identity(4)
    for modifier in list(obj.modifiers):obj.modifiers.remove(modifier)
    obj.hide_set(False);obj.hide_viewport=False;obj.hide_select=False
bpy.context.view_layer.update()
bpy.ops.object.select_all(action='DESELECT')
for obj in meshes:obj.select_set(True)
bpy.context.view_layer.objects.active=meshes[0]
if len(meshes)>1:bpy.ops.object.join()
replacement=meshes[0]
alignment={'fitted':False}
points=np.array([tuple(v.co) for v in replacement.data.vertices],dtype=np.float64)
sample=points[::max(1,len(points)//256)]
distances=[bvh.find_nearest(Vector(point))[3] for point in sample] if options.get('fit_weapon') else []
on_surface=bool(distances) and all(distance is not None and distance<1e-5 for distance in distances)
if on_surface:alignment['already_aligned']=True
if options.get('fit_weapon') and not on_surface:
    target=np.array([tuple(v) for v in world],dtype=np.float64)
    def axes(values):
        center=values.mean(axis=0)
        _,basis=np.linalg.eigh(np.cov((values-center).T));basis=basis[:,::-1]
        if np.linalg.det(basis)<0:basis[:,-1]*=-1
        return center,basis,np.ptp((values-center)@basis,axis=0)
    center,basis,extent=axes(points);target_center,target_basis,target_extent=axes(target)
    if extent[0]<1e-7:raise ValueError('The weapon model has no usable dimensions')
    rotations=[target_basis@np.diag(signs)@basis.T for signs in ((1,1,1),(1,-1,-1),(-1,1,-1),(-1,-1,1))]
    rotation=max(rotations,key=np.trace);factor=target_extent[0]/extent[0]
    points=(points-center)@rotation.T*factor+target_center
    alignment={'fitted':True,'scale':float(factor),'rotation':rotation.tolist()}
center=points.mean(axis=0)
rotation=np.array(Euler(tuple(math.radians(options.get('rotate_'+axis,0)) for axis in 'xyz'),'XYZ').to_matrix())
offset=np.array([options.get('offset_'+axis,0)/100 for axis in 'xyz'])
points=(points-center)@rotation.T*options.get('scale',1)+center+offset
for vertex,point in zip(replacement.data.vertices,points):vertex.co=point
replacement.data.update()
surface_cache={}
def surface(vertex):
    if vertex.index not in surface_cache:
        point,normal,index,distance=bvh.find_nearest(vertex.co)
        if index is None:raise ValueError('Could not transfer surface data from the character')
        triangle=triangles[index]
        factors=barycentric_transform(point,*(world[i] for i in triangle.vertices),Vector((1,0,0)),Vector((0,1,0)),Vector((0,0,1)))
        surface_cache[vertex.index]=(triangle,factors)
    return surface_cache[vertex.index]
same_topology=len(replacement.data.vertices)==len(original.data.vertices) and len(replacement.data.polygons)==len(original.data.polygons) and all(tuple(a.vertices)==tuple(b.vertices) for a,b in zip(replacement.data.polygons,original.data.polygons))
retained=transferred=0
for vertex in replacement.data.vertices:
    weights={replacement.vertex_groups[g.group].name:g.weight for g in vertex.groups
             if replacement.vertex_groups[g.group].name in known and g.weight>0}
    if weights and options['keep_weights']:retained+=1
    elif same_topology and options['keep_weights']:weights=original_weights[vertex.index];retained+=1
    else:
        triangle,bary=surface(vertex);ids=triangle.vertices
        weights={}
        for i,factor in zip(ids,bary):
            for name,weight in original_weights[i].items():weights[name]=weights.get(name,0)+max(0,factor)*weight
        transferred+=1
    if not weights:raise ValueError(f'Vertex {vertex.index} has no transferable bone weights')
    for index in [g.group for g in vertex.groups]:replacement.vertex_groups[index].remove([vertex.index])
    total=sum(weights.values())
    divisor=1 if abs(total-1)<1e-5 else total
    for name,weight in weights.items():
        group=replacement.vertex_groups.get(name) or replacement.vertex_groups.new(name=name)
        group.add([vertex.index],weight/divisor,'REPLACE')
# PSK and many user-authored models omit vertex colours or secondary UVs that the
# game's shaders require. Recover absent channels from the closest original surface.
for channel in range(len(replacement.data.uv_layers),len(original.data.uv_layers)):
    source_uv=original.data.uv_layers[channel]
    target_uv=replacement.data.uv_layers.new(name=source_uv.name)
    for loop in replacement.data.loops:
        triangle,factors=surface(replacement.data.vertices[loop.vertex_index])
        target_uv.data[loop.index].uv=sum((source_uv.data[i].uv*factor for i,factor in zip(triangle.loops,factors)),Vector((0,0)))
source_color=original.data.color_attributes.active_color
if source_color and not replacement.data.color_attributes.active_color:
    target_color=replacement.data.color_attributes.new(name=source_color.name,type='FLOAT_COLOR',domain='POINT')
    replacement.data.color_attributes.active_color=target_color
    for vertex in replacement.data.vertices:
        triangle,factors=surface(vertex)
        indices=triangle.vertices if source_color.domain=='POINT' else triangle.loops
        target_color.data[vertex.index].color=sum((Vector(source_color.data[i].color)*factor for i,factor in zip(indices,factors)),Vector((0,0,0,0)))
# Match existing slots by name; otherwise use the closest original surface.
rest=replacement.data.attributes.get('_ATELIER_MORPH_REST')
if rest:replacement.data.attributes.remove(rest)
rest=replacement.data.attributes.new('_ATELIER_MORPH_REST','FLOAT_VECTOR','POINT')
original_rest=original.data.attributes.get('_ATELIER_MORPH_REST')
source_ids=original.data.attributes.get('_ATELIER_MORPH_ID')
source_lods=original.data.attributes.get('_ATELIER_MORPH_LOD')
tracking={}
for name in ('_ATELIER_MORPH_ID','_ATELIER_MORPH_LOD'):
    old=replacement.data.attributes.get(name)
    if old:replacement.data.attributes.remove(old)
    tracking[name]=replacement.data.attributes.new(name,'FLOAT','POINT')
for vertex in replacement.data.vertices:
    if same_topology:
        value=original_rest.data[vertex.index].vector if original_rest else world[vertex.index]*100
    else:
        triangle,factors=surface(vertex)
        value=sum(((original_rest.data[i].vector if original_rest else world[i]*100)*factor for i,factor in zip(triangle.vertices,factors)),Vector())
    rest.data[vertex.index].vector=value
    tracking['_ATELIER_MORPH_ID'].data[vertex.index].value=source_ids.data[vertex.index].value if same_topology and source_ids else -1
    tracking['_ATELIER_MORPH_LOD'].data[vertex.index].value=source_lods.data[0].value if source_lods else -1
assignments=[]
for face in replacement.data.polygons:
    mat=replacement.data.materials[face.material_index] if face.material_index<len(replacement.data.materials) else None
    name=(mat.name if mat.name in stock_names else re.sub(r'\.\d{3}$','',mat.name)) if mat else ''
    if name in stock_names:index=stock_names[name]
    else:
        center=sum((replacement.data.vertices[i].co for i in face.vertices),Vector())/len(face.vertices)
        nearest=bvh.find_nearest(center)[2]
        index=triangles[nearest].material_index
    assignments.append(index)
replacement.data.materials.clear()
for material in stock_materials:replacement.data.materials.append(material)
for face,index in zip(replacement.data.polygons,assignments):face.material_index=index
used=set(assignments);required={face.material_index for face in original.data.polygons}
missing_indices=required-used
missing=[mat.name for i,mat in enumerate(stock_materials) if i in missing_indices and mat]
preserved_parts=[]
if missing_indices:
    if not options['keep_parts']:
        raise ValueError('The replacement is missing these original parts: '+', '.join(missing)+'. Enable Keep untouched parts, select a separate weapon in Weapons, or assign faces to these material slots in Blender.')
    # A partial upload replaces only the sections it actually contains. Copy the
    # others from the template, preserving their UVs, colours, weights and morph
    # tracking attributes. Never invent tiny placeholder faces or drop sections.
    preserved=original.copy();preserved.data=original.data.copy()
    bpy.context.scene.collection.objects.link(preserved)
    preserved.shape_key_clear();preserved.parent=None
    preserved.data.transform(original.matrix_world);preserved.matrix_world=Matrix.Identity(4)
    for modifier in list(preserved.modifiers):preserved.modifiers.remove(modifier)
    geometry=bmesh.new()
    try:
        geometry.from_mesh(preserved.data)
        bmesh.ops.delete(geometry,geom=[face for face in geometry.faces if face.material_index not in missing_indices],context='FACES')
        bmesh.ops.delete(geometry,geom=[vertex for vertex in geometry.verts if not vertex.link_faces],context='VERTS')
        geometry.to_mesh(preserved.data)
    finally:geometry.free()
    preserved.hide_set(False);preserved.hide_viewport=preserved.hide_select=False
    bpy.ops.object.select_all(action='DESELECT');preserved.select_set(True);replacement.select_set(True)
    bpy.context.view_layer.objects.active=replacement;bpy.ops.object.join()
    preserved_parts=missing
for obj in list(bpy.data.objects):
    if obj not in (armature,replacement):bpy.data.objects.remove(obj,do_unlink=True)
replacement.name='SkeletalMesh';replacement.parent=None
replacement['atelier_import_options']=json.dumps(options)
armature.hide_viewport=armature.hide_render=armature.hide_select=True
bpy.context.view_layer.objects.active=replacement;replacement.select_set(True)
bpy.ops.wm.save_as_mainfile(filepath=destination)
with open(report,'w',encoding='utf-8') as stream:json.dump({'vertices':len(replacement.data.vertices),'faces':len(replacement.data.polygons),
    'retained_weight_vertices':retained,'transferred_weight_vertices':transferred,'default_skeleton':options['keep_skeleton'],
    'materials':list(stock_names),'preserved_parts':preserved_parts,'source_scale':scale_info,'alignment':alignment,'source_channels':source_channels},stream)
print('REPLACEMENT_OK',destination)
