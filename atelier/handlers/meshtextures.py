"""Import a model's local material bundle through the existing custom-texture path.

JSON is data only. Texture names can resolve only to PNGs explicitly selected in
the same upload; no file path, URL, script or shader from a document is executed.
One-material weapon bundles have an unambiguous destination. Multi-material
models still use the material editor for explicit assignments.

Geometry, material JSON, images and project options publish in one recoverable
transaction after both the mesh and material have passed their native builds.
The original shader and packed maps are retained for inspection. Unity shader
effects have no equivalent in the game's existing master material; channel
choices describe a surface approximation, never an imported shader or physics.
"""
import hashlib
import io
import json
import os
from pathlib import Path,PurePosixPath
import re
import shutil
import stat
import zipfile

import numpy as np
from PIL import Image

from atelier import config, jobs, project_meta
from atelier.storage import atomic_json

CHOICES={
    'normal_encoding':('auto','unity_ag','opengl','directx'),
    'pbr_layout':('rough_r_metal_g','metal_r_rough_g','metal_r_smooth_a','orm'),
    'ao_channel':('a','r','g','b','none'),
}


def unpack_archive(source,destination):
    """Flatten explicitly supported files from one local model archive safely."""
    from atelier.handlers.meshreplace import MODEL_EXTENSIONS,COMPANIONS
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    models=[];companions=[];seen=set();total=0
    try:
        with zipfile.ZipFile(source) as archive:
            entries=[row for row in archive.infolist() if not row.is_dir()]
            if len(entries)>128:raise ValueError('This model archive contains too many files')
            for entry in entries:
                name=entry.filename.replace('\\','/');parts=PurePosixPath(name)
                if parts.is_absolute() or '..' in parts.parts or stat.S_ISLNK(entry.external_attr>>16):
                    raise ValueError('The model archive contains an unsafe file path')
                config.validate_game_rel(name)
                suffix=parts.suffix.lower()
                if suffix not in (MODEL_EXTENSIONS|COMPANIONS)-{'.zip'}:continue
                if len(seen)>=32 or parts.name.casefold() in seen:raise ValueError('The model archive has too many files or duplicate filenames')
                seen.add(parts.name.casefold());total+=entry.file_size
                if total>2*1024**3 or entry.flag_bits&1:raise ValueError('Choose an unencrypted model archive under 2 GB')
                target=destination/parts.name;written=0
                with archive.open(entry) as incoming,target.open('wb') as outgoing:
                    while chunk:=incoming.read(1024*1024):
                        written+=len(chunk)
                        if written>entry.file_size:raise ValueError('The archive file size could not be verified')
                        outgoing.write(chunk)
                if written!=entry.file_size:raise ValueError('The model archive is incomplete')
                (models if suffix in MODEL_EXTENSIONS else companions).append(target)
    except zipfile.BadZipFile as error:raise ValueError('This model ZIP is damaged or incomplete') from error
    if len(models)!=1:raise ValueError('Choose an archive containing one model and its textures')
    return models[0],companions


def _sha(path):
    path=Path(path)
    if not path.is_file():return None
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def convert(source, companions, options):
    """Read a selected Unity-style JSON/PNG bundle and produce game-ready maps."""
    from atelier.handlers.custom_texture import _normalized_png
    files=[Path(path) for path in companions if Path(path).suffix.lower() in ('.png','.json')]
    if not files:return None
    documents=[path for path in files if path.suffix.lower()=='.json']
    if len(documents)>1:raise ValueError('Choose one material JSON with this weapon')
    document={}
    if documents:
        if documents[0].stat().st_size>2*1024*1024:raise ValueError('Material JSON exceeds 2 MB')
        document=json.loads(documents[0].read_text(encoding='utf-8-sig'))
        if not isinstance(document,dict) or not isinstance(document.get('m_SavedProperties'),dict):
            raise ValueError('This material JSON is not a supported Unity material bundle. Assign its textures in the material editor.')
    images={};originals=[]
    for path in files:
        if path.suffix.lower()!='.png':continue
        key=path.stem.casefold()
        if key in images:raise ValueError('Texture names in this bundle must be unique')
        png,size=_normalized_png(path.read_bytes())
        with Image.open(io.BytesIO(png)) as image:images[key]=image.convert('RGBA').copy()
        originals.append({'name':path.name,'png':png,'size':size})
    envs=document.get('m_SavedProperties',{}).get('m_TexEnvs',{})
    if not isinstance(envs,dict):raise ValueError('Invalid material texture list')
    stem=Path(source).stem
    def find(parameter,suffix):
        entry=envs.get(parameter,{})
        if not isinstance(entry,dict):raise ValueError('Invalid material texture entry')
        reference=entry.get('m_Texture',{})
        if not isinstance(reference,dict):raise ValueError('Invalid material texture reference')
        name=reference.get('Name','') if not reference.get('IsNull') else ''
        if name and (not isinstance(name,str) or '/' in name or '\\' in name or ':' in name):
            raise ValueError('Material textures must name files selected with the model')
        key=Path(name).stem.casefold() if name else (stem+suffix).casefold()
        if name and key not in images:raise ValueError('Select the missing texture '+name+'.png with the model')
        image=images.get(key)
        if image is not None:
            for original in originals:
                if Path(original['name']).stem.casefold()==key:original['parameter']=parameter
        return image
    base=find('_MainTex','');normal=find('_BumpMap','NM');pbr=find('_PBRMask','PBR');ao=find('_MaskTex','AO')
    if base is None:raise ValueError('Select the base-colour PNG named in the JSON, or a PNG with the model’s filename')
    output={'basecolor':base};notes=[]
    encoding=options.get('normal_encoding','auto')
    if normal is not None:
        raw=np.asarray(normal).astype(np.float32)/255
        if encoding=='auto':
            encoding='unity_ag' if raw[:,:,0].min()>.98 and np.ptp(raw[:,:,3])>.02 else 'opengl' if documents else 'directx'
        x=raw[:,:,3]*raw[:,:,0] if encoding=='unity_ag' else raw[:,:,0]
        y=1-raw[:,:,1] if encoding in ('unity_ag','opengl') else raw[:,:,1]
        z=np.sqrt(np.maximum(0,1-(2*x-1)**2-(2*y-1)**2))*.5+.5
        output['normal']=Image.fromarray(np.rint(np.stack((x,y,z),axis=-1)*255).clip(0,255).astype('uint8'),'RGB')
    layout=options.get('pbr_layout','rough_r_metal_g');channel=options.get('ao_channel','a')
    size=pbr.size if pbr is not None else ao.size if ao is not None else (32,32)
    packed=np.asarray(pbr.resize(size)).copy() if pbr is not None else np.full((size[1],size[0],4),255,np.uint8)
    if pbr is None:rough=np.full(packed.shape[:2],153,np.uint8);metal=np.zeros_like(rough)
    elif layout=='rough_r_metal_g':rough,metal=packed[:,:,0],packed[:,:,1]
    elif layout=='metal_r_rough_g':metal,rough=packed[:,:,0],packed[:,:,1]
    elif layout=='metal_r_smooth_a':metal,rough=packed[:,:,0],255-packed[:,:,3]
    else:rough,metal=packed[:,:,1],packed[:,:,2]
    occlusion=packed[:,:,0] if pbr is not None and layout=='orm' else np.full(packed.shape[:2],255,np.uint8)
    if ao is not None and channel!='none':occlusion=np.asarray(ao.resize(size))[:,:,'rgba'.index(channel)]
    if options.get('ao_invert'):occlusion=255-occlusion
    output['orm']=Image.fromarray(np.stack((occlusion,rough,metal),axis=-1),'RGB')
    # Do not retain the original gun's detailed specular artwork under a new UV map.
    output['specular']=Image.new('RGB',(32,32),(128,128,128))
    if documents and pbr is not None:notes.append('Packed PBR channels use the selected layout; the source shader’s effects are approximated.')
    if ao is not None:notes.append('AO uses '+('a neutral value' if channel=='none' else channel.upper()+(' inverted' if options.get('ao_invert') else ''))+'. Change the AO channel if the source mask uses a different layout.')
    maps={}
    for role,image in output.items():
        stream=io.BytesIO();image.save(stream,'PNG');maps[role]={'png':stream.getvalue(),'size':list(image.size)}
    return {'maps':maps,'originals':originals,'document':document,'json_file':documents[0] if documents else None,
            'normal_encoding':encoding,'pbr_layout':layout,'ao_channel':channel,'notes':notes,
            'shader':str((document.get('m_Shader') or {}).get('Name',''))[:250]}


def prepare(game_rel, source, companions, options, work, original):
    """Prepare validated project-file changes without publishing any of them."""
    converted=convert(source,companions,options)
    if not converted:return None
    from atelier.handlers import custom_texture, material, mesh, meshmat
    root=config.get_import_root();work=Path(work);work.mkdir(parents=True)
    resolved=meshmat.resolve_mesh_materials(game_rel,mesh.Mesh(original),original)
    materials={row['mi'] for row in resolved if row.get('mi')}
    if len(materials)!=1 or any(not row.get('mi') for row in resolved):
        raise ValueError('This texture bundle needs one destination material. Choose a separate weapon, or assign textures to each material in Model Studio.')
    target=next(iter(materials))
    with open(material.mat_json(target,out_dir=config.CACHE_3DVIEW),encoding='utf-8-sig') as stream:document=json.load(stream)
    slots=material.texture_slots(document)
    role_slots={}
    for name,record in slots.items():
        role=meshmat.texture_role(name)
        if role in converted['maps'] and record['class']=='Texture2D':role_slots.setdefault(role,[]).append(name)
    missing=converted['maps'].keys()-role_slots.keys()
    if missing:raise ValueError('The weapon material has no compatible '+', '.join(sorted(missing))+' texture slot. Use the material editor for explicit assignments.')
    # Snapshot every destination before native validation so a concurrent edit
    # fails publication cleanly instead of overwriting the user's newer work.
    changes=[];paths=set()
    def change(relative,path):
        relative=relative.replace('\\','/')
        if relative in paths:return
        paths.add(relative);changes.append({'path':relative,'before':_sha(config.project_base(relative,root)),'source':str(path)})
    staged=work/'project';staged.mkdir()
    metadata=Path(config.project_base('.atelier/project.json',root))
    staged_metadata=Path(config.project_base('.atelier/project.json',str(staged)))
    staged_metadata.parent.mkdir(parents=True,exist_ok=True)
    if metadata.is_file():shutil.copy2(metadata,staged_metadata)
    else:atomic_json(str(staged_metadata),project_meta.load(root))
    change('.atelier/project.json',staged_metadata)
    assignments=custom_texture.assignments(target,root)
    # Retained custom slots must also be available for the native preflight.
    for record in assignments.values():
        image=Path(custom_texture.store_dir(root),record['file'])
        if image.is_file():
            dest=Path(custom_texture.store_dir(str(staged)),record['file']);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(image,dest)
    manifest_maps=[]
    for role,names in role_slots.items():
        value=converted['maps'][role];png=value['png'];filename=hashlib.sha256(png).hexdigest()[:20]+'.png'
        relative='.atelier/custom_textures/'+filename;path=Path(config.project_base(relative,str(staged)))
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(png);change(relative,path)
        for name in names:
            assignments[name]={'name':custom_texture.texture_name(Path(source).stem+'_'+role),'file':filename,
                'size':value['size'],'source':Path(source).stem+' ('+role+')','template':slots[name]['game_rel']}
            manifest_maps.append({'param':name,'role':role,'path':str(path),'final_path':config.project_base(relative,root),'game_rel':slots[name]['game_rel']})
    colors,scalars=material._mat_params(document)
    neutral={'roughnesspower':1,'metallic':1,'metailic':1,'normalintensity':1,'emissivestrength':0,'glowstrength':0}
    material._apply_mat_edits(document,{row['name']:[1,1,1,1] for row in colors if row['name'].casefold() in ('basecolor','basetint','tint')},
        {row['name']:neutral[row['name'].casefold()] for row in scalars if row['name'].casefold() in neutral})
    mat_path=Path(config.project_base(target,str(staged))+'.json');mat_path.parent.mkdir(parents=True,exist_ok=True);atomic_json(str(mat_path),document)
    change(target+'.json',mat_path)
    project_meta.set_asset_opts(str(staged),target,{'custom_textures':assignments})
    identity=hashlib.sha256((json.dumps(options,sort_keys=True)+''.join(hashlib.sha256(row['png']).hexdigest() for row in converted['originals'])).encode()).hexdigest()[:20]
    sources=[]
    for row in converted['originals']:
        relative='.atelier/model_imports/'+identity+'/'+hashlib.sha256(row['png']).hexdigest()[:20]+'.png'
        path=Path(config.project_base(relative,str(staged)));path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(row['png']);change(relative,path)
        sources.append({'file':relative,'name':row['name'],'parameter':row.get('parameter','Source map')})
        if row.get('parameter')!='_MainTex':manifest_maps.append({'param':'Source · '+row.get('parameter',row['name']),
            'role':None,'path':str(path),'final_path':config.project_base(relative,root),'game_rel':''})
    if converted['json_file']:
        relative='.atelier/model_imports/'+identity+'/material.json';path=Path(config.project_base(relative,str(staged)))
        atomic_json(str(path),converted['document']);change(relative,path)
    jobs.progress('Checking the imported material and texture packages…')
    with config.project_context(str(staged)):
        material.stage_material(str(work/'validation'),target,{}, {})
    colors,scalars=material._mat_params(document)
    manifest=work/'materials.json'
    atomic_json(str(manifest),{'slots':{row['slot']:{'mi':target,'maps':manifest_maps,'colors':colors,'scalars':scalars,
        'surface':material._mat_surface(document)} for row in resolved}})
    record={'material':target,'sources':sources,'source_shader':converted['shader'],'notes':converted['notes']}
    return {'changes':changes,'manifest':manifest,'record':record,'summary':{'material':target,'textures':len(converted['maps']),
        'normal_encoding':converted['normal_encoding'],'pbr_layout':converted['pbr_layout'],'ao_channel':converted['ao_channel'],
        'notes':converted['notes'],'shared_material_possible':True}}


def dependencies(game_rel):
    try:
        with open(config.project_base(game_rel)+'.mesh.json',encoding='utf-8') as stream:bundle=json.load(stream).get('bundle') or {}
        material=bundle.get('material','');config.validate_game_rel(material)
        if os.path.basename(material).upper().startswith('MI_'):return [material]
    except (OSError,ValueError,TypeError):pass
    return []


def source_maps(game_rel,material,root=None):
    """Retain the supplied packed maps as named auxiliary Blender inputs."""
    try:
        with open(config.project_base(game_rel)+'.mesh.json',encoding='utf-8') as stream:bundle=json.load(stream).get('bundle') or {}
    except (OSError,ValueError,TypeError):return []
    if bundle.get('material')!=material:return []
    maps=[]
    for row in bundle.get('sources',[]):
        relative=row.get('file','')
        if row.get('parameter')=='_MainTex' or not re.fullmatch(r'\.atelier/model_imports/[0-9a-f]{20}/[0-9a-f]{20}\.png',relative):continue
        source=Path(config.project_base(relative))
        if not source.is_file():raise ValueError('The imported source texture is missing: '+str(row.get('name','')))
        if root:
            target=Path(config.project_base(relative,root));target.parent.mkdir(parents=True,exist_ok=True)
            if os.path.normcase(str(target.resolve()))!=os.path.normcase(str(source.resolve())):shutil.copy2(source,target)
        else:target=source
        maps.append({'param':'Source · '+str(row.get('parameter') or row.get('name')),'role':None,'path':str(target),'game_rel':'','readonly':True})
    return maps
