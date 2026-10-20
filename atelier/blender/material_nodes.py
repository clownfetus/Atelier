"""Build inspectable Blender materials from Atelier's typed material manifest.

RivalsPorting's material-family/parameter mapping is the reference for the export
shape. These nodes are generated locally, with no addon or external shader-library
dependency. Every exported texture is linked to its named material-group input;
game-specific auxiliary inputs are explicitly recorded instead of disappearing.
"""
import json
import os
import re

import bpy


def _input(group, name, kind, default=None):
    socket=group.interface.new_socket(name=name,in_out='INPUT',socket_type=kind)
    if default is not None:socket.default_value=default
    return socket


def image_node(material,path,colorspace,x,y,label):
    image=bpy.data.images.load(path,check_existing=True)
    if image.users and image.colorspace_settings.name!=colorspace:image=image.copy()
    image.colorspace_settings.name=colorspace
    node=material.node_tree.nodes.new('ShaderNodeTexImage');node.image=image;node.label=label;node.location=(x,y)
    return node


def normal_builder(tree,texture,shader,y):
    def math(operation,a,b):
        node=tree.nodes.new('ShaderNodeMath');node.operation=operation
        for index,value in enumerate((a,b)):
            if isinstance(value,(int,float)):node.inputs[index].default_value=value
            else:tree.links.new(value,node.inputs[index])
        return node.outputs[0]
    split=tree.nodes.new('ShaderNodeSeparateColor');tree.links.new(texture.outputs['Color'],split.inputs['Color'])
    x=math('SUBTRACT',math('MULTIPLY',split.outputs[0],2),1)
    z=math('SUBTRACT',math('MULTIPLY',split.outputs[1],2),1)
    length=math('MAXIMUM',0,math('SUBTRACT',1,math('ADD',math('MULTIPLY',x,x),math('MULTIPLY',z,z))))
    root=tree.nodes.new('ShaderNodeMath');root.operation='SQRT';tree.links.new(length,root.inputs[0])
    combine=tree.nodes.new('ShaderNodeCombineColor')
    tree.links.new(split.outputs[0],combine.inputs[0]);tree.links.new(math('SUBTRACT',1,split.outputs[1]),combine.inputs[1])
    tree.links.new(math('ADD',math('MULTIPLY',root.outputs[0],.5),.5),combine.inputs[2])
    node=tree.nodes.new('ShaderNodeNormalMap');tree.links.new(combine.outputs['Color'],node.inputs['Color']);tree.links.new(node.outputs['Normal'],shader.inputs['Normal'])
    return node


def wire_material(material, record, image_node=image_node, normal_builder=normal_builder):
    material.use_nodes=True
    tree=material.node_tree;tree.nodes.clear()
    output=tree.nodes.new('ShaderNodeOutputMaterial');output.location=(520,80)
    shader=tree.nodes.new('ShaderNodeGroup');shader.location=(120,80)
    group=bpy.data.node_groups.new('Atelier · '+material.name,'ShaderNodeTree')
    group.interface.new_socket(name='Surface',in_out='OUTPUT',socket_type='NodeSocketShader')
    source=group.nodes.new('NodeGroupInput');source.location=(-1100,80)
    finish=group.nodes.new('NodeGroupOutput');finish.location=(650,80)
    bsdf=group.nodes.new('ShaderNodeBsdfPrincipled');bsdf.location=(350,80)
    group.links.new(bsdf.outputs['BSDF'],finish.inputs['Surface'])
    shader.node_tree=group;tree.links.new(shader.outputs['Surface'],output.inputs['Surface'])
    colors={c['name']:c['rgba'] for c in record.get('colors',[])}
    scalars={s['name']:s['value'] for s in record.get('scalars',[])}
    values={};textures={};used=set();auxiliary=[]
    for name,rgba in colors.items():
        key='Colour · '+name;_input(group,key,'NodeSocketColor',tuple(rgba));values[name.casefold()]=source.outputs[key]
    for name,value in scalars.items():
        key='Value · '+name;_input(group,key,'NodeSocketFloat',value);values[name.casefold()]=source.outputs[key]

    def scalar(*names, default=1):
        for name in names:
            if name.casefold() in values:return values[name.casefold()]
        node=group.nodes.new('ShaderNodeValue');node.outputs[0].default_value=default
        return node.outputs[0]

    def colour(*names,default=(1,1,1,1)):
        for name in names:
            if name.casefold() in values:return values[name.casefold()]
        node=group.nodes.new('ShaderNodeRGB');node.outputs[0].default_value=default
        return node.outputs[0]

    def math(op,a,b=None):
        node=group.nodes.new('ShaderNodeMath');node.operation=op
        for i,value in enumerate((a,b)):
            if value is None:continue
            if isinstance(value,(int,float)):node.inputs[i].default_value=value
            else:group.links.new(value,node.inputs[i])
        return node.outputs[0]

    def mix(a,b,factor=1,mode='MULTIPLY'):
        node=group.nodes.new('ShaderNodeMixRGB');node.blend_type=mode
        for index,value in ((0,factor),(1,a),(2,b)):
            if isinstance(value,(int,float)):node.inputs[index].default_value=value
            else:group.links.new(value,node.inputs[index])
        return node.outputs[0]

    def separate(socket):
        node=group.nodes.new('ShaderNodeSeparateColor');group.links.new(socket,node.inputs['Color']);return node.outputs

    def texture(role):
        matches=[p for p in textures.values() if p['role']==role]
        if not matches:return None
        used.add(matches[0]['param']);return matches[0]

    for index,mp in enumerate(record.get('maps',[])):
        if not mp.get('path') or not os.path.isfile(mp['path']):continue
        param=mp['param'];role=mp.get('role');key='Texture · '+param;alpha=key+' · Alpha'
        _input(group,key,'NodeSocketColor');_input(group,alpha,'NodeSocketFloat',1)
        tex=image_node(material,mp['path'],'sRGB' if role in ('basecolor','emissive','sclera','iris') else 'Non-Color',-550,-index*220,param)
        tex.image.alpha_mode='CHANNEL_PACKED'
        tree.links.new(tex.outputs['Color'],shader.inputs[key]);tree.links.new(tex.outputs['Alpha'],shader.inputs[alpha])
        if mp.get('uv'):
            uv=tree.nodes.new('ShaderNodeUVMap');uv.uv_map='UVMap.'+str(mp['uv']).zfill(3);uv.location=(-800,-index*220)
            # glTF's importer uses UVMap, UVMap.001, …; preserve the source channel.
            tree.links.new(uv.outputs['UV'],tex.inputs['Vector'])
        if role=='dye':tex.interpolation='Closest'
        textures[param]={'param':param,'role':role,'color':source.outputs[key],'alpha':source.outputs[alpha]}

    base=texture('basecolor');sclera=texture('sclera');iris=texture('iris')
    diffuse=base['color'] if base else sclera['color'] if sclera else colour('BaseColor','BaseTint','Tint')
    if base or sclera:diffuse=mix(diffuse,colour('BaseTint','BaseColor','Tint'))
    if iris:
        uv=group.nodes.new('ShaderNodeTexCoord');split=group.nodes.new('ShaderNodeSeparateXYZ');group.links.new(uv.outputs['UV'],split.inputs[0])
        radius=math('SQRT',math('ADD',math('POWER',math('SUBTRACT',split.outputs['X'],.5),2),math('POWER',math('SUBTRACT',split.outputs['Y'],.5),2)))
        mask=math('LESS_THAN',radius,scalar('IrisUVRadius',default=.24));diffuse=mix(diffuse,iris['color'],mask,'MIX')
        iris_ao=texture('iris_ao')
        if iris_ao:diffuse=mix(diffuse,mix(diffuse,iris_ao['color']),mask,'MIX')
        height=texture('iris_height')
        if height:
            bump=group.nodes.new('ShaderNodeBump');bump.inputs['Distance'].default_value=.001
            group.links.new(height['color'],bump.inputs['Height']);group.links.new(bump.outputs['Normal'],bsdf.inputs['Normal'])

    dye=texture('dye')
    if dye:
        channels=separate(dye['color']);region=math('ROUND',math('MULTIPLY',dye['alpha'],7))
        for number in range(1,8):
            prefix='Region '+str(number)+' - '
            if (prefix+'ColorA') not in colors:continue
            target=mix(colour(prefix+'ColorA'),colour(prefix+'ColorB',prefix+'ColorA'),channels[0],'MIX')
            for channel,name in ((1,'ColorGChannel'),(2,'ColorBChannel')):
                if prefix+name in colors:target=mix(target,colour(prefix+name),channels[channel],'MIX')
            # Keep the source shading under the selected region tint. Raw mask,
            # diffuse and colour inputs remain editable in the graph.
            target=mix(diffuse,target)
            equal=group.nodes.new('ShaderNodeMath');equal.operation='COMPARE';equal.inputs[1].default_value=number;equal.inputs[2].default_value=.1
            group.links.new(region,equal.inputs[0]);diffuse=mix(diffuse,target,equal.outputs[0],'MIX')

    orm=texture('orm');ao=texture('ao')
    if orm:
        channels=separate(orm['color']);diffuse=mix(diffuse,channels[0])
        group.links.new(math('MULTIPLY',channels[1],scalar('RoughnessPower')),bsdf.inputs['Roughness'])
        group.links.new(math('MULTIPLY',channels[2],scalar('Metallic','Metailic')),bsdf.inputs['Metallic'])
    else:
        group.links.new(scalar('Roughness','ScleraRoughness','RoughnessPower',default=.6),bsdf.inputs['Roughness'])
        group.links.new(scalar('Metallic',default=0),bsdf.inputs['Metallic'])
    if ao:diffuse=mix(diffuse,ao['color'])
    group.links.new(diffuse,bsdf.inputs['Base Color'])
    normal=texture('normal')
    if normal:
        # Reuse the established DirectX green flip and BC5 Z reconstruction.
        proxy=type('NormalInput',(),{'outputs':{'Color':normal['color']}})()
        nmap=normal_builder(group,proxy,bsdf,-250)
        if nmap:group.links.new(scalar('NormalIntensity'),nmap.inputs['Strength'])
    emissive=texture('emissive')
    emission=emissive['color'] if emissive else colour('EmissiveColor','EmissionColor',default=(0,0,0,1))
    if emissive:emission=mix(emission,colour('EmissiveColor','EmissionColor'))
    group.links.new(emission,bsdf.inputs.get('Emission Color') or bsdf.inputs.get('Emission'))
    if bsdf.inputs.get('Emission Strength'):group.links.new(scalar('EmissiveStrength','GlowStrength'),bsdf.inputs['Emission Strength'])
    opacity=texture('opacity');surface=record.get('surface',{})
    alpha=opacity['color'] if opacity else base['alpha'] if base else scalar(default=1)
    alpha=math('MULTIPLY',alpha,scalar('OpacityMultiplier','Opacity',default=surface.get('opacity',1)))
    if re.search('masked',surface.get('blend_mode',''),re.I):alpha=math('GREATER_THAN',alpha,surface.get('mask_clip',.3333))
    if opacity or re.search('translucent|masked|additive',surface.get('blend_mode',''),re.I):group.links.new(alpha,bsdf.inputs['Alpha'])
    specular=texture('specular')
    if specular:group.links.new(specular['color'],bsdf.inputs.get('Specular IOR Level') or bsdf.inputs.get('Specular'))
    anisotropy=texture('anisotropy');shift=texture('anisotropy_rotation')
    if anisotropy and bsdf.inputs.get('Anisotropic IOR Level'):group.links.new(anisotropy['color'],bsdf.inputs['Anisotropic IOR Level'])
    if shift and bsdf.inputs.get('Anisotropic Rotation'):group.links.new(shift['color'],bsdf.inputs['Anisotropic Rotation'])
    highlight=texture('highlight')
    if highlight:
        group.links.new(math('MULTIPLY',highlight['color'],scalar('HighlightIntensity')),bsdf.inputs['Alpha'])
    if record.get('hidden'):
        group.links.new(scalar(default=0),bsdf.inputs['Alpha'])
    material.use_backface_culling=not surface.get('two_sided',False)
    if hasattr(material,'surface_render_method'):material.surface_render_method='DITHERED'
    elif hasattr(material,'blend_method'):material.blend_method='HASHED' if record.get('hidden') or re.search('translucent|masked',surface.get('blend_mode',''),re.I) else 'OPAQUE'
    auxiliary=[name for name in textures if name not in used]
    material['atelier_material']=record.get('mi') or ''
    material['atelier_parent']=surface.get('parent','')
    material['atelier_auxiliary_parameters']=json.dumps(auxiliary)
    # Keep internal nodes readable in columns, and expose all source values in
    # one named group instead of disconnected image nodes scattered around a BSDF.
    for index,node in enumerate(n for n in group.nodes if n not in (source,finish,bsdf)):
        node.location=(-850+(index%5)*210,-220-(index//5)*180)
    return {'material':material.name,'textures':len(textures),'connected_textures':len(textures),
            'shader_textures':len(used),'auxiliary':auxiliary,'parent':surface.get('parent',''),
            'hidden':bool(record.get('hidden')),'presentation_only_hidden':bool(record.get('presentation_only_hidden'))}
