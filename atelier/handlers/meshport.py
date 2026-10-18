"""Portable Blender export with materials, packed textures and held weapons.

The standalone scene is a porting artifact. Ordinary Edit in Blender files retain
their per-mesh, linked-image round trip. Neither route needs a Blender addon.
RivalsPorting's typed parameters and material families informed the manifest and
shader mapping; all graph construction here uses Atelier's bundled Python.
"""
import json
import os
from pathlib import Path
import re
import tempfile

import numpy as np

from atelier import config, jobs
from atelier.storage import publish_files
from atelier.handlers import mesh, meshedit, meshstudio, meshreplace


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
    candidates=[name for name in weapon_bones if name in body_bones and re.search(r'weapon|sword|gun|blade|hammer|bow|staff|dagger|shield|pistol|spear|axe',name,re.I) and not re.search(r'^ik_|^weapon_[lr]$',name,re.I)]
    side='l' if hand=='left' or (hand=='auto' and re.search(r'(?:^|_)(?:l|left)(?:_|$)',os.path.basename(weapon.base),re.I)) else 'r'
    socket='weapon_'+side
    grip=next((name for name in weapon_bones if re.search(r'handle|grip',name,re.I)),None)
    grip=grip or (socket if socket in weapon_bones else None) or (candidates[0] if candidates else None)
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
