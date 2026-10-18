"""Build the visible Dante/Ebony/Ivory mod and read its actual IoStore directory.

Native builds run only through an independently configured app. Package readback
uses the existing pure reader; no game installation or source-file changes.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time
from urllib.request import Request,urlopen

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',required=True)
    parser.add_argument('--project',default='Dante Hood Verification')
    parser.add_argument('--report-dir',type=Path,required=True)
    args=parser.parse_args();args.report_dir.mkdir(parents=True,exist_ok=True)
    from atelier import config
    from atelier.handlers import custom_texture,meshvisibility
    import io_lib
    project=Path(config.PROJECTS_ROOT)/args.project
    assert project.is_dir() and project.resolve().is_relative_to(Path(os.environ['ATELIER_DATA_DIR']).resolve()),project
    body='Characters/1066/1066001/Meshes/SK_1066_1066001'
    left='Characters/1066/1066001/Weapons/Gun_L/Meshes/SK_WP_1066001_Gun_L'
    right='Characters/1066/1066001/Weapons/Gun_R/Meshes/SK_WP_1066001_Gun_R'
    materials=['Characters/1066/1066001/Weapons/Gun_L/Materials/Lobby/MI_WP_1066001_Gun_01',
               'Characters/1066/1066001/Weapons/Gun_L/Materials/MI_WP_1066001_Gun_01']
    expected=[body,left,right,*materials];custom=[]
    for material in materials:
        maps=custom_texture.public(material,str(project));assert len(maps)==4,maps
        custom.extend(record['game_rel'] for record in maps.values())
    expected.extend(custom);assert len(set(custom))==8
    assert all(not meshvisibility.hidden_sections(gr,str(project)) for gr in (body,left,right))
    def api(path,data=None):
        request=Request(args.url+path,data=json.dumps(data).encode() if data is not None else None,
                        headers={'Content-Type':'application/json','X-Atelier-Project':args.project})
        with urlopen(request,timeout=180) as response:return json.load(response)
    result=api('/api/install_mod',{'mod_name':'Dante Hood Ebony and Ivory verification',
                                 'items':[body,left,right],'copy_to_mods':False,'background':True})
    identifier=result['job']['id'];print('Building the combined visible body and both guns',flush=True)
    for _ in range(2400):
        job=api('/api/jobs/'+identifier)['job']
        if job['state'] in ('succeeded','failed','cancelled'):break
        time.sleep(.5)
    result=job.get('result') or job
    report={'project':args.project,'export':result,'installed':False,'in_game_verified':False}
    try:
        assert result.get('ok') and not result.get('skipped'),result
        toc_path=next(path for path in result['artifacts'] if path.endswith('.utoc'))
        toc=io_lib.parse_toc(toc_path);directory=io_lib.parse_dir_index(toc)
        verified=[]
        for game_rel in expected:
            rows=[(path,index) for path,index in directory if path.lower().endswith('/'+game_rel.lower()+'.uasset')]
            assert len(rows)==1,(game_rel,rows)
            path,index=rows[0];payload=io_lib.read_chunk(toc,toc_path[:-5]+'.ucas',index)
            assert len(payload)>0,game_rel
            verified.append({'game_rel':game_rel,'packed_bytes':len(payload)})
        report.update(verified_packages=verified,all_sections_visible=True,
                      mesh_count=3,independent_gun_materials=2,custom_texture_packages=len(custom))
        print('PASS packed directory and readable packages: 3 meshes, 2 independent materials, 8 custom textures; no hidden sections',flush=True)
    finally:
        (args.report_dir/'results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')


if __name__=='__main__':main()
