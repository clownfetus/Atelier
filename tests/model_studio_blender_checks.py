"""Generate and audit real portable Blender scenes through a private app only."""
import argparse
import json
import os
from pathlib import Path
import time
from urllib.request import Request,urlopen


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',required=True)
    parser.add_argument('--skin',action='append',required=True)
    parser.add_argument('--report-dir',type=Path,required=True)
    parser.add_argument('--project')
    parser.add_argument('--weapon',action='append',help='Choose specific weapons for a one-skin imported-model case')
    args=parser.parse_args();args.report_dir.mkdir(parents=True,exist_ok=True)
    def api(path,data=None):
        headers={'Content-Type':'application/json'}
        if args.project:headers['X-Atelier-Project']=args.project
        request=Request(args.url+path,data=json.dumps(data).encode() if data is not None else None,headers=headers)
        with urlopen(request,timeout=120) as response:return json.load(response)
    if not args.project:args.project=api('/api/projects')['active']
    results=[]
    for skin in args.skin:
        meshes=api('/api/skin_meshes?skin_id='+skin);body=next(row for row in meshes if row['kind']=='body')
        weapons=[row for row in meshes if row['kind']=='weapon']
        if args.weapon:
            weapons=[row for row in weapons if row['game_rel'] in args.weapon];assert len(weapons)==len(args.weapon),args.weapon
        # One ordinary held weapon per case; Magik also tests independent dual copies.
        selected=[{'game_rel':weapon['game_rel'],'hand':'both' if skin=='1029001' else 'auto'} for weapon in (weapons if args.weapon else weapons[:1])]
        print('Exporting real Blender scene '+skin,flush=True)
        response=api('/api/model_blender_export',{'game_rel':body['game_rel'],'weapons':selected})
        identifier=response['job']['id']
        for _ in range(2400):
            state=api('/api/jobs/'+identifier)['job']
            if state['state'] in ('succeeded','failed','cancelled'):break
            time.sleep(.5)
        result=state.get('result') or state
        folder=args.report_dir/skin;folder.mkdir(exist_ok=True)
        (folder/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        assert result.get('ok'),result
        destination=Path(result['blend']).resolve()
        assert destination.is_relative_to(Path(os.environ['ATELIER_DATA_DIR']).resolve()),destination
        assert destination.is_file() and destination.stat().st_size>10000
        audit=json.loads(destination.with_suffix('.materials.json').read_text(encoding='utf-8'))
        assert not audit['unconnected_textures'] and audit['images']
        assert all(image['packed'] and min(image['size'])>0 for image in audit['images'])
        assert audit['armatures'] and all(rig['bones']>0 for rig in audit['armatures'])
        assert any(rig['bones']>20 and rig['nonzero_bone_heads']>0 for rig in audit['armatures'])
        assert all(row['deformation_rig'] and row['rest_deformation_error']<1e-4 for row in audit['meshes'])
        assert not audit['game_physics_simulated']
        assert len(audit['parts'])==1+sum(2 if record['hand']=='both' else 1 for record in selected)
        material_rows=[row for part in audit['materials'] for row in part['materials']]
        assert material_rows and all(not row.get('missing') for row in material_rows)
        assert all(row['connected_textures']==row['textures'] for row in material_rows)
        results.append({'skin':skin,'blend':str(destination),'meshes':result['meshes'],'materials':result['materials'],
                        'packed_images':result['textures'],'deformation_rigs':audit['armatures'],'all_texture_nodes_connected':True,
                        'game_physics_simulated':False,'warnings':result['warnings']})
        (args.report_dir/'results.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
        print('PASS '+skin+' · '+str(result['meshes'])+' meshes · '+str(result['textures'])+' packed images',flush=True)


if __name__=='__main__':main()
