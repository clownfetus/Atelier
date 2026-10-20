"""Reproduce an actual replacement file against a skin in a private app.

All native work goes through the app. The source file is read only, the project
is isolated, and the built mod is exported without installing it into the game.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import time
from urllib.parse import urlencode
from urllib.request import Request,urlopen
import uuid


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',required=True)
    parser.add_argument('--skin',required=True)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--companion',type=Path,action='append',default=[])
    parser.add_argument('--target')
    parser.add_argument('--project',default='Dante Hood Verification')
    parser.add_argument('--expected-units',choices=['metres','centimetres'],default='metres')
    parser.add_argument('--mod-name')
    parser.add_argument('--report-dir',type=Path,required=True)
    args=parser.parse_args();args.report_dir.mkdir(parents=True,exist_ok=True)
    name=args.project;headers={}
    def request(path,data=None,content_type='application/json',raw=False):
        body=json.dumps(data).encode() if data is not None and content_type=='application/json' else data
        with urlopen(Request(args.url+path,data=body,headers={**headers,'Content-Type':content_type}),timeout=180) as response:
            return response.read() if raw else json.load(response)
    projects=request('/api/projects');active=projects['active']
    if not any(row['name']==name for row in projects['projects']):
        assert request('/api/project/create',{'name':name})['ok']
        assert request('/api/project/select',{'name':active})['ok']
    headers['X-Atelier-Project']=name
    target=args.target or next(row['game_rel'] for row in request('/api/skin_meshes?skin_id='+args.skin) if row['kind']=='body')
    stages=[]
    def finish(response):
        if not response.get('job'):return response
        identifier=response['job']['id']
        for _ in range(3600):
            job=request('/api/jobs/'+identifier)['job']
            if not stages or stages[-1]!=job['stage']:
                stages.append(job['stage']);print(job['stage'],flush=True)
            if job['state'] in ('succeeded','failed','cancelled'):return job.get('result') or job
            time.sleep(.5)
        raise TimeoutError('Replacement verification did not finish')
    source=args.source.read_bytes();boundary=uuid.uuid4().hex
    fields={'game_rel':target,'options':json.dumps({'keep_skeleton':True,'keep_weights':True,'keep_morphs':True,'keep_parts':True,'source_units':'auto'})}
    data=b''
    for key,value in fields.items():data+=f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
    source_hashes={}
    for file in [args.source,*args.companion]:
        payload=file.read_bytes();source_hashes[str(file)]=hashlib.sha256(payload).hexdigest()
        data+=f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="{file.name}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode()+payload+b'\r\n'
    data+=f'--{boundary}--\r\n'.encode()
    report={'source':str(args.source),'source_sha256':hashlib.sha256(source).hexdigest(),'target':target,'project':name}
    try:
        imported=finish(request('/api/mesh_replace',data,'multipart/form-data; boundary='+boundary))
        report['import']=imported
        (args.report_dir/'import.json').write_text(json.dumps(imported,indent=2),encoding='utf-8')
        assert imported.get('ok'),imported
        info=imported['validation'];assert info['skeleton_preserved'] and info['rig_bones']>0 and info['lods']>=3,info
        if args.source.suffix.lower()=='.psk':assert info['source_scale']['units']==args.expected_units and info['source_scale']['matching_bones']>=4,info
        if args.companion or args.source.suffix.lower()=='.zip':
            assert info['material_bundle']['textures']==4 and info['alignment']['fitted'],info
            assert info['material_bundle']['normal_encoding']=='unity_ag',info
        preview=request('/api/model_gltf?'+urlencode({'game_rel':target}),raw=True)
        (args.report_dir/'replacement-preview.glb').write_bytes(preview)
        size=struct.unpack_from('<I',preview,12)[0];gltf=json.loads(preview[20:20+size])
        positions=[gltf['accessors'][prim['attributes']['POSITION']] for mesh in gltf['meshes'] for prim in mesh['primitives']]
        spans=[max(p['max'][axis] for p in positions)-min(p['min'][axis] for p in positions) for axis in range(3)]
        assert (.03<max(spans)<2 if '/Weapons/' in target else .7<max(spans)<4),spans
        report['preview_bounds_metres']=spans
        exported=finish(request('/api/install_mod',{'mod_name':args.mod_name or args.source.stem+' verification','items':[target],'copy_to_mods':False,'background':True}))
        report['export']=exported
        (args.report_dir/'export.json').write_text(json.dumps(exported,indent=2),encoding='utf-8')
        assert exported.get('ok') and not exported.get('skipped'),exported
        if args.companion or args.source.suffix.lower()=='.zip':assert any('custom textures' in row for row in exported['applied']),exported
        assert all(hashlib.sha256(Path(file).read_bytes()).hexdigest()==sha for file,sha in source_hashes.items())
        report['source_files_unchanged']=source_hashes
        print('PASS actual replacement · original skeleton · correct dimensions · all LODs · mod exported without installation',flush=True)
    finally:
        report['stages']=stages
        (args.report_dir/'results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')


if __name__=='__main__':main()
