"""Stage model replacements on the game's skeleton and validate every cooked LOD."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from atelier import config, jobs
from atelier.storage import atomic_json, publish_project_files

MODEL_EXTENSIONS={'.blend','.fbx','.glb','.psk','.pskx','.uasset'}
COMPANIONS={'.uexp','.ubulk'}
IMPORT_DEFAULTS={'keep_skeleton':True,'keep_weights':True,'keep_morphs':True}


def import_options(options=None):
    if options is not None and (not isinstance(options,dict) or any(key not in IMPORT_DEFAULTS or type(value) is not bool for key,value in options.items())):
        raise ValueError('Model import options must be boolean skeleton, weight and morph choices')
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


def prepare(game_rel,source,options=None):
    from atelier.handlers import meshedit,mesh,meshsurvey
    base=target_base(game_rel);root=config.get_import_root()
    options=import_options(options)
    suffixes=('.blend','.mesh.glb','.mesh.json')
    before={suffix:digest(base+suffix) for suffix in suffixes}
    source=Path(source)
    if source.suffix.lower() not in MODEL_EXTENSIONS:raise ValueError('Choose BLEND, FBX, GLB, PSK or cooked Unreal mesh files')
    jobs.progress('Reading the original character skeleton…')
    original=meshedit._resolve_base(game_rel)
    report=meshsurvey.probe(original)
    if report['status']!='ok':raise ValueError(meshsurvey.verdict_text(report))
    parent=Path(base).parent;parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='atelier-model-replacement-') as temporary:
        work=Path(temporary)
        if source.suffix.lower()=='.uasset':
            if not source.with_suffix('.uexp').is_file():raise ValueError('Select the cooked .uasset and its matching .uexp together; include .ubulk when present')
            donor=mesh.Mesh(str(source.with_suffix('')))
            imported=work/'source.glb';mesh.export_glb(donor,0,str(imported))
        else:imported=source
        template=work/'template.blend'
        jobs.progress('Preparing the default skeleton and material slots…')
        meshedit.extract_blend(game_rel,base_path=original,blend_path=str(template),with_materials=False)
        candidate=work/(Path(base).name+'.blend');summary=work/'report.json'
        jobs.progress('Applying the character skeleton and transferring weights…')
        meshedit._run_blender('replacement_to_blend.py',[str(template),str(imported),str(candidate),str(summary),json.dumps(options)],'REPLACEMENT')
        info=json.loads(summary.read_text(encoding='utf-8'))
        jobs.checkpoint();jobs.progress('Validating every LOD and the Unreal package…')
        validation=work/'validation'
        rebuilt=meshedit.stage_mesh(game_rel,str(validation),blend_path=str(candidate),base_path=original)
        info['lods']=len(rebuilt['applied'])
        info['morph_targets']=max((lod.get('morph_targets',0) for lod in rebuilt['applied']),default=0)
        info['morph_vertices']=sum(lod.get('morph_vertices',0) for lod in rebuilt['applied'])
        info['options']=options
        info['warnings']=[meshsurvey.WARNINGS.get(w,w) for w in report.get('warnings',[]) if w!='morphs']
        preview=work/(Path(base).name+'.mesh.glb')
        # Parse the rebuilt cooked result before publication. The preview therefore
        # uses the exact original skeleton and geometry that the mod will contain.
        verified=mesh.Mesh(str(Path(rebuilt['uasset']).with_suffix('')))
        expected=mesh.Mesh(original).bones
        if options['keep_skeleton'] and verified.bones!=expected:raise ValueError('The rebuilt model changed the original skeleton')
        if [(b['name'],b['parent']) for b in verified.bones]!=[(b['name'],b['parent']) for b in expected]:raise ValueError('The replacement skeleton is incompatible with this character')
        mesh.export_glb(verified,0,str(preview),with_morphs=options['keep_morphs'])
        record=work/(Path(base).name+'.mesh.json')
        atomic_json(str(record),{'version':1,'game_rel':game_rel,'state':'replacement',
            'source_name':source.name,'source_format':source.suffix.lower(),'options':options,'validation':info})
        changes=[{'path':os.path.relpath(base+suffix,root).replace('\\','/'),'before':before[suffix],'source':str(path)}
                 for suffix,path in zip(suffixes,(candidate,preview,record))]
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
    if not blend.is_file():return None
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
