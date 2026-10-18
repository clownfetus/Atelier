"""Stage model replacements on the game's skeleton and validate every cooked LOD."""
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import tempfile

from atelier import config, jobs
from atelier.storage import atomic_json, publish_project_files

MODEL_EXTENSIONS={'.blend','.fbx','.glb','.psk','.pskx','.uasset','.zip'}
COMPANIONS={'.uexp','.ubulk','.json','.png'}
IMPORT_DEFAULTS={'keep_skeleton':True,'keep_weights':True,'keep_morphs':True}


def import_options(options=None):
    if options is not None:
        if not isinstance(options,dict):raise ValueError('Invalid model import options')
        for key,value in options.items():
            if key=='source_units':
                if value not in ('auto','metres','centimetres'):raise ValueError('Choose valid PSK units')
            elif key in ('normal_encoding','pbr_layout','ao_channel'):
                from atelier.handlers.meshtextures import CHOICES
                if value not in CHOICES[key]:raise ValueError('Choose valid texture packing options')
            elif key in ('scale','rotate_x','rotate_y','rotate_z','offset_x','offset_y','offset_z'):
                limit=1000 if key=='scale' else 360 if key.startswith('rotate_') else 10000
                if type(value) not in (int,float) or not math.isfinite(value) or abs(value)>limit or key=='scale' and value<.001:
                    raise ValueError('Choose a valid model scale, rotation or offset')
            elif key not in {*IMPORT_DEFAULTS,'keep_parts','repair_weights','fit_weapon','ao_invert'} or type(value) is not bool:
                raise ValueError('Invalid model import option: '+str(key))
    return {**IMPORT_DEFAULTS,**(options or {})}


def digest(path):
    if not Path(path).is_file():return None
    with open(path,'rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def target_base(game_rel):
    config.validate_game_rel(game_rel)
    from atelier.web.browse import _classify_file
    if _classify_file(os.path.basename(game_rel))!='mesh':raise ValueError('Choose a mesh asset')
    return config.project_base(game_rel)


def add(game_rel):
    base=target_base(game_rel);path=Path(base+'.mesh.json')
    if not path.exists():atomic_json(str(path),{'version':1,'game_rel':game_rel,'state':'original'})
    return {'ok':True,'game_rel':game_rel,'state':json.loads(path.read_text(encoding='utf-8'))['state']}


def prepare(game_rel,source,options=None,companions=()):
    from atelier.handlers import meshedit,mesh,meshsurvey
    if Path(source).suffix.lower()=='.zip':
        from atelier.handlers.meshtextures import unpack_archive
        jobs.progress('Reading the model and textures from the ZIP…')
        with tempfile.TemporaryDirectory(prefix='atelier-model-archive-') as unpacked:
            model,files=unpack_archive(source,unpacked)
            result=prepare(game_rel,model,options,[*files,*companions])
            result['archive_name']=Path(source).name
            return result
    base=target_base(game_rel);root=config.get_import_root()
    # Keep the stored legacy rig-options schema stable; coverage is an import
    # choice, enabled for a new replacement even when an older caller omits it.
    options={'keep_parts':True,'repair_weights':True,'fit_weapon':'/weapons/' in game_rel.lower(),**import_options(options)}
    suffixes=('.blend','.mesh.glb','.mesh.json')
    before={suffix:digest(base+suffix) for suffix in suffixes}
    source=Path(source)
    if source.suffix.lower() not in MODEL_EXTENSIONS:raise ValueError('Choose a model ZIP, BLEND, FBX, GLB, PSK or cooked Unreal mesh files')
    jobs.progress('Reading the original character skeleton…')
    original=meshedit._resolve_base(game_rel)
    report=meshsurvey.probe(original)
    if any(lod.get('blob')=='missing' for lod in report.get('lods',[])):
        from atelier.handlers.meshstudio import complete_mesh_source
        original=complete_mesh_source(game_rel)
        report=meshsurvey.probe(original)
    if report['status']!='ok':raise ValueError(meshsurvey.verdict_text(report))
    parent=Path(base).parent;parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='atelier-model-replacement-') as temporary:
        work=Path(temporary)
        from atelier.handlers import meshtextures
        bundle=meshtextures.prepare(game_rel,source,companions,options,work/'bundle',original)
        if source.suffix.lower()=='.uasset':
            if not source.with_suffix('.uexp').is_file():raise ValueError('Select the cooked .uasset and its matching .uexp together; include .ubulk when present')
            donor=mesh.Mesh(str(source.with_suffix('')))
            imported=work/'source.glb';mesh.export_glb(donor,0,str(imported))
        else:imported=source
        template=work/'template.blend'
        # Measure ActorX units against cooked parent-local translations directly,
        # independently of Blender's object transforms and editing armature.
        reference=work/'reference-bones.json'
        bones=mesh.Mesh(original).bones if source.suffix.lower() in ('.psk','.pskx') else []
        atomic_json(str(reference),{bone['name']:(bones[bone['parent']]['name'],
            sum(value*value for value in bone['translation'])**.5/100)
            for bone in bones if bone['parent']>=0})
        jobs.progress('Preparing the default skeleton and material slots…')
        meshedit.extract_blend(game_rel,base_path=original,blend_path=str(template),with_materials=False)
        candidate=work/(Path(base).name+'.blend');summary=work/'report.json'
        jobs.progress('Applying the character skeleton and transferring weights…')
        meshedit._run_blender('replacement_to_blend.py',[str(template),str(imported),str(candidate),str(summary),json.dumps(options),str(reference)],'REPLACEMENT')
        info=json.loads(summary.read_text(encoding='utf-8'))
        jobs.checkpoint();jobs.progress('Validating every LOD and the Unreal package…')
        validation=work/'validation'
        rebuilt=meshedit.stage_mesh(game_rel,str(validation),blend_path=str(candidate),base_path=original,preserve_parts=info.get('preserved_parts',[]))
        info['lods']=len(rebuilt['applied'])
        info['morph_targets']=max((lod.get('morph_targets',0) for lod in rebuilt['applied']),default=0)
        info['morph_vertices']=sum(lod.get('morph_vertices',0) for lod in rebuilt['applied'])
        info['repaired_weight_vertices']=rebuilt['applied'][0].get('repaired_weight_vertices',0) if rebuilt['applied'] else 0
        info['options']=options
        info['material_bundle']=bundle['summary'] if bundle else None
        info['warnings']=[meshsurvey.WARNINGS.get(w,w) for w in report.get('warnings',[]) if w!='morphs']
        if info.get('source_scale',{} ) and info['source_scale']['detected'] and info['source_scale']['matching_bones']<4:
            info['warnings'].append('PSK units could not be confirmed from matching bones. Review the size in 3D or choose metres or centimetres explicitly')
        preview=work/(Path(base).name+'.mesh.glb')
        # Parse the rebuilt cooked result before publication. The preview therefore
        # uses the exact original skeleton and geometry that the mod will contain.
        verified=mesh.Mesh(str(Path(rebuilt['uasset']).with_suffix('')))
        cooked_report=meshsurvey.probe(str(Path(rebuilt['uasset']).with_suffix('')))
        if cooked_report['status']!='ok':raise ValueError(meshsurvey.verdict_text(cooked_report))
        expected=mesh.Mesh(original).bones
        info['skeleton_preserved']=verified.bones==expected
        info['rig_bones']=len(expected)
        if options['keep_skeleton'] and not info['skeleton_preserved']:raise ValueError('The rebuilt model changed the original skeleton')
        if [(b['name'],b['parent']) for b in verified.bones]!=[(b['name'],b['parent']) for b in expected]:raise ValueError('The replacement skeleton is incompatible with this character')
        mesh.export_glb(verified,0,str(preview),with_morphs=options['keep_morphs'])
        if bundle:
            jobs.progress('Connecting the imported textures in Blender…')
            meshedit._run_blender('wire_import_materials.py',[str(candidate),str(bundle['manifest'])],'IMPORT_MATERIALS')
        record=work/(Path(base).name+'.mesh.json')
        atomic_json(str(record),{'version':1,'game_rel':game_rel,'state':'replacement',
            'source_name':source.name,'source_format':source.suffix.lower(),'options':options,'validation':info,
            'bundle':bundle['record'] if bundle else None,'blend_sha256':digest(candidate)})
        changes=[{'path':os.path.relpath(base+suffix,root).replace('\\','/'),'before':before[suffix],'source':str(path)}
                 for suffix,path in zip(suffixes,(candidate,preview,record))]
        if bundle:changes.extend(bundle['changes'])
        jobs.checkpoint();jobs.begin_publication('Saving the validated replacement…')
        publish_project_files(root,changes)
    return {'ok':True,'game_rel':game_rel,'state':'replacement','validation':info}


def stage_original(game_rel,stage):
    """An added, unchanged mesh can share the mod with other edits without Blender."""
    from atelier.handlers import meshedit
    from atelier.paths import pak_game_path
    source=meshedit._resolve_base(game_rel)
    destination=Path(stage,*pak_game_path(game_rel).split('/'))
    destination.parent.mkdir(parents=True,exist_ok=True)
    for extension in ('.uasset','.uexp','.ubulk'):
        if Path(source+extension).is_file():shutil.copy2(source+extension,str(destination)+extension)
    return {'applied':[],'uasset':str(destination)+'.uasset','unchanged':True}


def is_original(game_rel):
    base=target_base(game_rel)
    try: record=json.loads(Path(base+'.mesh.json').read_text(encoding='utf-8'))
    except (OSError,ValueError): return False
    return record.get('state')=='original' and (not Path(base+'.blend').exists() or
        record.get('original_blend_sha256')==digest(base+'.blend'))


def revert(game_rel):
    from atelier.handlers import meshedit
    base=target_base(game_rel);root=config.get_import_root()
    suffixes=('.blend','.mesh.glb','.mesh.json') if Path(base+'.blend').is_file() else ('.mesh.json',)
    before={suffix:digest(base+suffix) for suffix in suffixes}
    with tempfile.TemporaryDirectory(prefix='atelier-model-original-') as temporary:
        work=Path(temporary);record={'version':1,'game_rel':game_rel,'state':'original'}
        if '.blend' in suffixes:
            jobs.progress('Restoring the original model and skeleton…')
            candidate=work/'original.blend'
            meshedit.extract_blend(game_rel,base_path=meshedit._resolve_base(game_rel),blend_path=str(candidate),with_materials=False)
            preview=work/'original.mesh.glb'
            meshedit._run_blender('blend_to_glb.py',[str(candidate),str(preview),'1','preview'],'GLB')
            record['original_blend_sha256']=digest(candidate)
            files=(candidate,preview,work/'original.mesh.json')
        else: files=(work/'original.mesh.json',)
        atomic_json(str(files[-1]),record)
        jobs.checkpoint();jobs.begin_publication('Restoring the original model…')
        publish_project_files(root,[{'path':os.path.relpath(base+suffix,root),'before':before[suffix],'source':str(path)}
            for suffix,path in zip(suffixes,files)])
    return {'ok':True,'game_rel':game_rel,'state':'original'}


def preview(game_rel):
    from atelier.handlers import meshedit,mesh
    base=target_base(game_rel);blend=Path(base+'.blend');target=Path(base+'.mesh.glb')
    if not blend.is_file():
        from atelier.added_assets import source_base
        original = source_base(game_rel)
        if not original:
            return None
        if not target.is_file():
            descriptor, temporary = tempfile.mkstemp(suffix='.glb', prefix='.added-mesh-preview-', dir=target.parent)
            os.close(descriptor)
            try:
                mesh.export_glb(mesh.Mesh(original), 0, temporary)
                os.replace(temporary, target)
            finally:
                Path(temporary).unlink(missing_ok=True)
        return str(target)
    if not target.is_file() or target.stat().st_mtime_ns<blend.stat().st_mtime_ns:
        descriptor,temporary=tempfile.mkstemp(suffix='.glb',prefix='.mesh-preview-',dir=target.parent);os.close(descriptor)
        try:
            output=meshedit._run_blender('blend_to_glb.py',[str(blend),temporary,'1','preview'],'GLB')
            options=import_options(json.loads(next((line[len('ATELIER_IMPORT_OPTIONS '):] for line in output.splitlines() if line.startswith('ATELIER_IMPORT_OPTIONS ')),'{}')))
            original=mesh.Mesh(meshedit._resolve_base(game_rel))
            if not options['keep_skeleton']:original.apply_skeleton_from_glb(temporary)
            original.rebuild_lod(0,mesh.glb_to_sections(original,0,temporary),keep_morphs=options['keep_morphs'])
            mesh.export_glb(original,0,temporary,with_morphs=options['keep_morphs'])
            os.replace(temporary,target)
        finally:Path(temporary).unlink(missing_ok=True)
    return str(target)
