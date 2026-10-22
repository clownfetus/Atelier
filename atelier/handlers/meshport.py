"""Portable Blender export with materials, packed textures and held weapons.

The standalone scene is a porting artifact. Ordinary Edit in Blender files retain
their per-mesh, linked-image round trip. Neither route needs a Blender addon.
RivalsPorting's typed parameters and material families informed the manifest and
shader mapping; all graph construction here uses Atelier's bundled Python.
"""
import json
import os
import shutil
import time
from pathlib import Path
import re
import tempfile

import numpy as np

from atelier import config, jobs
from atelier.storage import publish_files
from atelier.handlers import mesh, meshedit, meshstudio, meshreplace, meshmat


def destination(game_rel):
    config.validate_game_rel(game_rel)
    project=os.path.basename(config.get_import_root()) or 'Unassigned'
    directory=Path(config.ASSETS)/'blender'/project
    return directory/(os.path.basename(game_rel)+'.blend')


def _bones(model):
    worlds,_=mesh._bone_world_matrices(model.bones)
    return {bone['name']:world for bone,world in zip(model.bones,worlds)}


def attachment_transform(body, weapon, hand='auto'):
    body_bones,weapon_bones=_bones(body),_bones(weapon)
    weapon_joint=lambda name: bool(re.search(r'weapon|sword|gun|blade|hammer|bow|staff|dagger|shield|pistol|spear|axe|cannon|launcher|rifle|katana|trident|wand|pole|rod|baton|stick|nunchaku|scepter|sickle|claw',name,re.I)
                                  and not re.search(r'^root$|^pelvis$|^ik_|^weapon_[lr]$',name,re.I))
    candidates=[name for name in weapon_bones if name in body_bones and weapon_joint(name)]
    side='l' if hand=='left' or (hand=='auto' and re.search(r'(?:^|_)(?:l|left)(?:_|$)|(?:cannon|launcher|gun|pistol|rifle|sword|katana|axe|stick|nunchaku)L(?:_|$)',os.path.basename(weapon.base),re.I)) else 'r'
    socket='weapon_'+side
    alignment=next((name for name in weapon_bones if re.fullmatch(r'align(?:ment)?',name,re.I)),None)
    if alignment and any(re.match(r'hand_[lr]_cannon',name,re.I) for name in weapon_bones) and 'hand_'+side in body_bones:
        socket='hand_'+side
    grip=next((name for name in weapon_bones if re.search(r'handle|grip',name,re.I)),None)
    authored_grip=next((bone['name'] for bone in weapon.bones if weapon_joint(bone['name']) and
                       (bone['parent']<0 or not weapon_joint(weapon.bones[bone['parent']]['name']))),None)
    source_socket='weapon_'+side
    grip=grip or (source_socket if source_socket in weapon_bones else None) or alignment or authored_grip or (candidates[0] if candidates else None)
    grip=grip or next((bone['name'] for bone in weapon.bones if bone['parent']<0),None)
    if socket not in body_bones:
        if hand=='auto' and candidates:
            anchor=candidates[0]
            return body_bones[anchor]@np.linalg.inv(weapon_bones[anchor]),anchor
        raise ValueError('No '+socket+' socket exists on this body')
    return body_bones[socket]@np.linalg.inv(weapon_bones[grip] if grip else np.eye(4)),socket


def export(game_rel, weapons=None):
    config.validate_game_rel(game_rel)
    if not isinstance(weapons or [],list) or len(weapons or [])>16:raise ValueError('Invalid weapon selection')
    skin=re.search(r'Characters/\d{4}/(\d{7})/',game_rel,re.I)
    allowed={row['game_rel'] for row in meshstudio.skin_meshes(skin[1]) if row['kind']=='weapon'} if skin else set()
    selected=[]
    for record in weapons or []:
        if not isinstance(record,dict) or record.get('game_rel') not in allowed or record.get('hand','auto') not in ('auto','left','right','both'):
            raise ValueError('Choose a weapon belonging to this skin')
        selected.append(record)
    target=destination(game_rel);target.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.prepare-',dir=target.parent) as temporary:
        scratch=Path(temporary);parts=[];warnings=['Deformation bones and weights are included. Game physics and animation controls are not recreated in Blender.'];reports=[]
        body_base=meshstudio.complete_mesh_source(game_rel);body=None
        weapon_sources={record['game_rel']:meshstudio.complete_mesh_source(record['game_rel']) for record in selected}
        weapon_models=[mesh.Mesh(base) for base in weapon_sources.values()]
        for index,record in enumerate([{'game_rel':game_rel,'body':True},*selected]):
            jobs.progress('Preparing Blender materials · '+os.path.basename(record['game_rel']))
            base=body_base if record.get('body') else weapon_sources[record['game_rel']]
            edited=config.project_base(record['game_rel'])+'.blend'
            if os.path.isfile(edited) and not meshreplace.is_original(record['game_rel']):
                # Reuse the same verified geometry rebuild as mod export. Never
                # silently replace a saved sculpt with the original game mesh.
                staged=meshedit.stage_mesh(record['game_rel'],str(scratch/('edited-'+str(index))),blend_path=edited,base_path=base)
                base=staged['uasset'][:-7]
            if record.get('body'):body=mesh.Mesh(base)
            duplicates=meshstudio.embedded_weapon_slots(body,weapon_models) if record.get('body') and weapon_models else set()
            prepared=meshedit.extract_blend(record['game_rel'],base_path=base,blend_path=str(scratch/(str(index)+'.blend')),
                force=True,texture_root=str(scratch/'textures'),pack_images=True,presentation_hidden=duplicates)
            if not prepared.get('material_manifest_complete'):
                raise ValueError('Blender export could not read every material and texture: '+
                                 '; '.join(prepared.get('material_issues') or [record['game_rel']]))
            from atelier.handlers.meshsurvey import WARNINGS
            warnings.extend(WARNINGS.get(w,w) for w in prepared['warnings']);reports.append(prepared['material_report'])
            if any(row.get('auxiliary') for row in prepared['material_report'].get('materials',[])):
                warnings.append('Game-specific shader effects are retained as named auxiliary inputs; their animation is not reproduced.')
            if not prepared['material_report'].get('materials'):
                raise ValueError('No Blender material graph was generated for '+record['game_rel'])
            hands=['right','left'] if record.get('hand')=='both' else [record.get('hand','auto')]
            for hand in hands:
                transform,anchor=(np.eye(4),'body') if record.get('body') else attachment_transform(body,mesh.Mesh(base),hand)
                parts.append({'game_rel':record['game_rel'],'name':os.path.basename(record['game_rel'])+((' · '+hand) if len(hands)>1 else ''),
                              'blend':prepared['blend'],'transform':transform.tolist(),'anchor':anchor})
        scene=scratch/'scene.blend';audit=scratch/'scene.json';manifest=scratch/'assembly.json'
        manifest.write_text(json.dumps({'parts':parts,'output':str(scene),'report':str(audit)}),encoding='utf-8')
        jobs.progress('Packing Blender scene and checking every texture connection…')
        meshedit._run_blender('assemble_studio.py',[str(manifest)],'PORT')
        report=json.loads(audit.read_text(encoding='utf-8'));report['materials']=reports
        report['parts']=[{key:value for key,value in part.items() if key!='blend'} for part in parts]
        # Publish the scene and its texture audit together, retaining the previous
        # complete export if either file cannot be replaced.
        published_scene=scratch/target.name;os.replace(scene,published_scene)
        published_report=published_scene.with_suffix('.materials.json')
        published_report.write_text(json.dumps(report,indent=2),encoding='utf-8')
        jobs.checkpoint();jobs.begin_publication('Saving Blender scene…')
        publish_files([str(published_scene),str(published_report)],str(target.parent))
    return {'ok':True,'blend':str(target),'meshes':len(report['meshes']), 'textures':len(report['images']),
            'materials':sum(len(r.get('materials',[])) for r in reports),'warnings':list(dict.fromkeys(warnings)),
            'material_report':report}


def _live_selection(game_rel, weapons):
    if weapons is None: weapons=[]
    if not isinstance(weapons,list) or len(weapons)>16:
        raise ValueError('Invalid weapon selection')
    skin=re.search(r'Characters/\d{4}/(\d{7})/',game_rel,re.I)
    allowed={row['game_rel'] for row in meshstudio.skin_meshes(skin[1])
             if row['kind']=='weapon'} if skin else set()
    result=[];seen=set()
    for record in weapons:
        if (not isinstance(record,dict) or record.get('game_rel') not in allowed or
                record.get('hand','auto') not in ('auto','left','right','both')):
            raise ValueError('Choose a weapon belonging to this skin')
        pair=(record['game_rel'],record.get('hand','auto'))
        if pair not in seen:
            seen.add(pair);result.append({'game_rel':pair[0],'hand':pair[1]})
    return result


def _live_edited_source(game_rel, original, work, index):
    """Never let the mesh rebuilder write beside a live artist project."""
    edited=Path(config.project_base(game_rel)+'.blend')
    if not edited.is_file() or meshreplace.is_original(game_rel):
        return original
    isolated=work/('edited-source-'+str(index))/edited.name
    isolated.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(edited,isolated)
    graft=Path(str(edited)+'.graft.json')
    if graft.is_file():shutil.copy2(graft,str(isolated)+'.graft.json')
    # The existing game-build pipeline checks all LODs on edited meshes.
    # The portable-export repair candidate narrows this to LOD0 separately.
    staged=meshedit.stage_mesh(game_rel,str(work/('edited-'+str(index))),
                               blend_path=str(isolated),base_path=original)
    return staged['uasset'][:-7]


def send_to_blender(game_rel, weapons=None):
    """Stage GLB + material metadata for the resident Blender add-on.

    Unlike export(), this does not start headless Blender, create a .blend, or
    change Mod tray entries. The running add-on imports directly and ACKs.
    """
    from atelier import blender_bridge
    from contextlib import nullcontext
    config.validate_game_rel(game_rel)
    selected=_live_selection(game_rel,weapons)
    root=blender_bridge.bridge_root()
    blender_bridge.receiver_status(root)  # no costly extraction without receiver
    job_id=blender_bridge.new_job_id()
    stage=root/'staging'/job_id
    stage.mkdir(parents=True,exist_ok=False)
    submitted=False
    warnings=[]
    started=time.perf_counter()
    try:
        cache=meshmat.resolution_cache() if hasattr(meshmat,'resolution_cache') else nullcontext()
        with cache:
            records=[{'game_rel':game_rel,'body':True},*selected]
            sources={};models={}
            for index,record in enumerate(records):
                gr=record['game_rel']
                if gr in models:continue
                jobs.checkpoint()
                jobs.progress('Reading live Blender mesh · '+os.path.basename(gr))
                source=meshstudio.complete_mesh_source(gr)
                sources[gr]=_live_edited_source(gr,source,stage,index)
                models[gr]=mesh.Mesh(sources[gr])
            body=models[game_rel]
            weapons_models=[models[gr] for gr in dict.fromkeys(r['game_rel'] for r in selected)]
            duplicates=meshstudio.embedded_weapon_slots(body,weapons_models) if weapons_models else set()
            prepared={}
            for index,(gr,model) in enumerate(models.items()):
                jobs.checkpoint()
                jobs.progress('Preparing live Blender materials · '+os.path.basename(gr))
                glb=stage/(str(index)+'.glb')
                mat_path=stage/(str(index)+'.materials.json')
                try:
                    manifest=meshmat.build_manifest(gr,model,work_base=sources[gr],
                                                    root=str(stage/'textures'))
                except jobs.Cancelled:
                    raise
                except Exception as error:
                    issue=os.path.basename(gr)+': material preparation failed: '+str(error)
                    manifest={'mesh':gr,'slots':{},'warnings':[issue],'incomplete':[issue]}
                warnings.extend(manifest.get('warnings',[]))
                if gr==game_rel:
                    for slot_id in duplicates:
                        slot=manifest['slots'].get(model.materials[slot_id]['slot_name'])
                        if slot is not None:
                            slot['hidden']=True
                            slot['presentation_only_hidden']=True
                mat_path.write_text(json.dumps(manifest),encoding='utf-8')
                mesh.export_glb(model,0,str(glb))
                prepared[gr]={'glb':str(glb),'materials':str(mat_path)}
            parts=[]
            for record in records:
                gr=record['game_rel']
                hands=['right','left'] if record.get('hand')=='both' else [record.get('hand','auto')]
                for hand in hands:
                    transform,anchor=(np.eye(4),'body') if record.get('body') else attachment_transform(body,models[gr],hand)
                    parts.append({'game_rel':gr,'name':os.path.basename(gr)+((' · '+hand) if len(hands)>1 else ''),
                                  **prepared[gr],'transform':transform.tolist(),'anchor':anchor})
            jobs.checkpoint()
            jobs.progress('Sending model to running Blender…')
            blender_bridge.receiver_status(root)
            receiver=blender_bridge.submit(root,job_id,parts)
            submitted=True
            ack=blender_bridge.await_receipt(root,job_id,receiver=receiver,checkpoint=jobs.checkpoint)
            warnings.extend(ack.get('warnings',[]))
            return {'ok':True,'meshes':ack.get('meshes',0),'live':True,
                    'warnings':list(dict.fromkeys(warnings)),
                    'seconds':round(time.perf_counter()-started,3),
                    'note':'Save your Blender file to keep these imported edits.'}
    finally:
        if submitted:(root/'requests'/(job_id+'.json')).unlink(missing_ok=True)
        # Once claimed, Blender owns staging until its import ends. Cancellation
        # must not remove files while the receiver is reading them.
        if not (root/'requests'/(job_id+'.processing')).exists():
            shutil.rmtree(stage,ignore_errors=True)
