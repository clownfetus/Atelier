"""Opt-in UV X-Ray check using native game decoding and an existing isolated project PNG.

No geometry, material, texture or native API is mocked. Outputs remain in --report-dir.
The only intercepted app module appends read-only observation helpers for browser checks.
"""
import argparse
import base64
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import struct
import sys
import threading
from urllib.parse import quote
from wsgiref.simple_server import make_server, WSGIRequestHandler

import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]

HOOK = r'''
const uvNativeLoad=loader.loadAsync.bind(loader),uvNativeParsers=new WeakMap();
loader.loadAsync=async(...args)=>{const result=await uvNativeLoad(...args);result.scene.traverse(mesh=>uvNativeParsers.set(mesh,result.parser));return result;};
const uvBytes=array=>new Uint8Array(array.buffer,array.byteOffset,array.byteLength);
const uvBase64=array=>{const bytes=uvBytes(array);let text='';for(let i=0;i<bytes.length;i+=8192)text+=String.fromCharCode(...bytes.subarray(i,i+8192));return btoa(text);};
window.__uvReal={
  ready:()=>!modelLoading&&!materialTask&&!animation.loading()&&objects.some(o=>o.loaded),
  state:()=>({project:viewportProject,status:document.getElementById('viewport-status').textContent,
    textures:renderer.info.memory.textures,materials:Object.entries(matData).map(([key,info])=>({key,...info}))}),
  rest(){const e=document.getElementById('viewport-animation');e.value='';e.dispatchEvent(new Event('change'));},
  candidates(targetSource){
    modelRoot.updateMatrixWorld(true);camera.updateMatrixWorld(true);
    const results=[],rect=renderer.domElement.getBoundingClientRect(),ray=new THREE.Raycaster(),box=new THREE.Box3();
    modelRoot.traverseVisible(mesh=>{if(mesh.isSkinnedMesh){mesh.computeBoundingSphere();mesh.computeBoundingBox();}});
    box.setFromObject(modelRoot);
    const projected=[];
    for(const x of [box.min.x,box.max.x])for(const y of [box.min.y,box.max.y])for(const z of [box.min.z,box.max.z])projected.push(new THREE.Vector3(x,y,z).project(camera));
    const bounds={left:Math.max(-.95,Math.min(...projected.map(p=>p.x))),right:Math.min(.95,Math.max(...projected.map(p=>p.x))),
      bottom:Math.max(-.9,Math.min(...projected.map(p=>p.y))),top:Math.min(.7,Math.max(...projected.map(p=>p.y)))};
    for(const fy of [.5,.25,.75,.15,.85,.35,.65,.05,.95])for(const fx of [.5,.38,.62,.25,.75]){
      const x=Math.round(rect.x+(bounds.left+(bounds.right-bounds.left)*fx+1)*rect.width/2),
        y=Math.round(rect.y+(1-bounds.bottom-(bounds.top-bounds.bottom)*fy)*rect.height/2);
      ray.setFromCamera(new THREE.Vector2((x-rect.x)/rect.width*2-1,-(y-rect.y)/rect.height*2+1),camera);
      const hit=ray.intersectObjects(modelRoot.children,true).find(hit=>{
        for(let node=hit.object;node&&node!==modelRoot;node=node.parent)if(!node.visible)return false;
        const material=Array.isArray(hit.object.material)?hit.object.material[hit.face.materialIndex]:hit.object.material;
        return material?.visible&&!material.userData.heldDuplicate;
      });
      if(!hit)continue;
      const mesh=hit.object,geometry=mesh.geometry,uv=geometry.getAttribute('uv');
      const material=Array.isArray(mesh.material)?mesh.material[hit.face.materialIndex]:mesh.material,info=matData[material.name];
      if(!uv||!info?.texture_roles?.basecolor||info.eye_preview||results.some(item=>item.key===material.name))continue;
      const group=Array.isArray(mesh.material)?geometry.groups.find(g=>g.materialIndex===hit.face.materialIndex&&hit.faceIndex*3>=g.start&&hit.faceIndex*3<g.start+g.count):
        {start:0,count:geometry.index?.count||geometry.attributes.position.count};
      if(!group)continue;
        let minU=Infinity,minV=Infinity,maxU=-Infinity,maxV=-Infinity;
        for(let i=group.start;i<group.start+group.count;i++){
          const vertex=geometry.index?geometry.index.getX(i):i;
          minU=Math.min(minU,uv.getX(vertex));maxU=Math.max(maxU,uv.getX(vertex));
          minV=Math.min(minV,uv.getY(vertex));maxV=Math.max(maxV,uv.getY(vertex));
        }
          const ids=[hit.face.a,hit.face.b,hit.face.c],weights=hit.barycoord.toArray();
          const point={u:ids.reduce((sum,v,k)=>sum+uv.getX(v)*weights[k],0),v:ids.reduce((sum,v,k)=>sum+uv.getY(v)*weights[k],0)};
          const association=uvNativeParsers.get(mesh)?.associations.get(mesh);
          const uvValues=new Float32Array(uv.count*2);
          for(let i=0;i<uv.count;i++){uvValues[i*2]=uv.getX(i);uvValues[i*2+1]=uv.getY(i);}
          results.push({x,y,key:material.name,material:info.game_rel,slot:info.slot_index,source:info.texture_roles.basecolor,
            faceIndex:hit.faceIndex,ids,point,association,uv_range:[minU,minV,maxU,maxV],
            uv:uvBase64(uvValues),index:geometry.index?uvBase64(geometry.index.array):null,index_type:geometry.index?.array.constructor.name,
            start:group.start,count:group.count,flipY:material.map?.flipY??false});
      if(results.some(c=>c.source===targetSource&&minSupported(c))&&results.filter(minSupported).length>=2)return results;
    }
    return results;
    function minSupported(c){return Math.min(...c.uv_range.slice(0,2))>=0&&Math.max(...c.uv_range.slice(2))<=1;}
  },
  async snapshot(){
    const cache=new WeakMap(),list=[];
    const hash=array=>{if(!array)return null;if(!cache.has(array))cache.set(array,crypto.subtle.digest('SHA-256',uvBytes(array)).then(buffer=>Array.from(new Uint8Array(buffer),b=>b.toString(16).padStart(2,'0')).join('')));return cache.get(array);};
    modelRoot.traverse(o=>{if(o.isMesh)list.push({id:o.uuid,uv:hash(o.geometry.getAttribute('uv')?.array),index:hash(o.geometry.index?.array)});});
    return JSON.stringify({edited,meshes:await Promise.all(list.map(async o=>({id:o.id,uv:await o.uv,index:await o.index})))});
  },
};
'''


def glb_accessors(payload):
    assert payload[:4] == b'glTF' and struct.unpack_from('<I',payload,4)[0] == 2
    offset=12; document=None; binary=None
    while offset<len(payload):
        size,kind=struct.unpack_from('<II',payload,offset);data=payload[offset+8:offset+8+size];offset+=8+size
        if kind==0x4e4f534a:document=json.loads(data)
        elif kind==0x004e4942:binary=data
    def read(index):
        accessor=document['accessors'][index];view=document['bufferViews'][accessor['bufferView']]
        dtype={5121:'u1',5123:'<u2',5125:'<u4',5126:'<f4'}[accessor['componentType']]
        components={'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4}[accessor['type']]
        return np.ndarray((accessor['count'],components),dtype=dtype,buffer=binary,
            offset=view.get('byteOffset',0)+accessor.get('byteOffset',0),
            strides=(view.get('byteStride',np.dtype(dtype).itemsize*components),np.dtype(dtype).itemsize))
    return document,read


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',type=Path,required=True)
    parser.add_argument('--report-dir',type=Path,required=True)
    parser.add_argument('--project',required=True)
    parser.add_argument('--mesh',required=True)
    parser.add_argument('--texture',required=True)
    args=parser.parse_args()
    os.environ['ATELIER_DATA_DIR']=str(args.data_dir.resolve())
    sys.path.insert(0,str(ROOT))
    from atelier.web import routes as R
    from atelier.web.app import _ThreadingWSGIServer
    from atelier import config as C
    assert Path(C.DATA_ROOT).resolve()!=ROOT.resolve(),'Use isolated application data'
    report=args.report_dir.resolve();report.mkdir(parents=True,exist_ok=True)
    assert not report.is_relative_to(Path(C.PAKS).resolve())
    project=Path(C.project_dir(args.project));project_texture=Path(C.project_base(args.texture,str(project))+'.png')
    assert project_texture.is_file(),'An existing project PNG is required'
    hashes=lambda:{str(p.relative_to(project)):hashlib.sha256(p.read_bytes()).hexdigest() for p in project.rglob('*') if p.is_file()}
    before=hashes();game_before={p.name:(p.stat().st_size,p.stat().st_mtime_ns) for p in Path(C.PAKS).iterdir() if p.is_file()}
    R.set_active_project(args.project)
    class Quiet(WSGIRequestHandler):
        def log_message(self,*_args):pass
    server=make_server('127.0.0.1',0,R.app,_ThreadingWSGIServer,Quiet)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    url=f'http://127.0.0.1:{server.server_port}'
    result={'ok':False,'mesh':args.mesh,'project_texture':args.texture,'checks':[],'sections':[],'page_errors':[]}
    try:
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch()
            context=browser.new_context(viewport={'width':1500,'height':1100},reduced_motion='reduce',accept_downloads=True)
            page=context.new_page();page.on('pageerror',lambda error:result['page_errors'].append(str(error)))
            page.route('**/static/viewport.js',lambda route:route.fulfill(body=(ROOT/'gui/viewport.js').read_text(encoding='utf-8')+HOOK,content_type='text/javascript'))
            page.goto(url,wait_until='domcontentloaded')
            page.wait_for_function('window.AtelierViewport&&window.atelierProject?.()',timeout=60000)
            if page.locator('#changelog-overlay.active').count():page.locator('#changelog-done').click()
            print('Opening native game model and project texture...',flush=True)
            page.evaluate('mesh=>{void AtelierViewport.openMesh(mesh);}',args.mesh)
            page.wait_for_function('__uvReal.ready()',timeout=240000)
            page.evaluate('__uvReal.rest()')
            page.evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
            state=page.evaluate('__uvReal.state()');(report/'materials.json').write_text(json.dumps(state,indent=2),encoding='utf-8')
            print('Native model ready; locating visible material sections...',flush=True)
            candidates=page.evaluate('(texture)=>__uvReal.candidates(texture)',args.texture)
            (report/'candidates.json').write_text(json.dumps(candidates,indent=2),encoding='utf-8')
            supported=[c for c in candidates if min(c['uv_range'][:2])>=0 and max(c['uv_range'][2:])<=1]
            chosen=next(c for c in supported if c['source']==args.texture)
            other=next(c for c in supported if c['slot']!=chosen['slot'])
            headers={'X-Atelier-Project':quote(args.project,safe='')}
            source_response=context.request.get(url+'/api/texture_png?game_rel='+quote(args.texture,safe=''),headers=headers)
            assert source_response.ok
            assert hashlib.sha256(source_response.body()).hexdigest()==before[str(project_texture.relative_to(project))]
            with Image.open(project_texture) as source:expected_size=source.size
            model_response=context.request.get(url+'/api/model_gltf?game_rel='+quote(args.mesh,safe=''),headers=headers)
            assert model_response.ok
            document,read=glb_accessors(model_response.body())
            snapshot=page.evaluate('__uvReal.snapshot()');gpu=page.evaluate('__uvReal.state().textures')
            page.click('#viewport-uv-toggle')
            page.wait_for_selector('#viewport-uv-empty')
            for number,candidate in enumerate([chosen,other]):
                page.mouse.click(candidate['x'],candidate['y'])
                page.wait_for_function("!document.getElementById('viewport-uv-export').disabled",timeout=30000)
                assert candidate['material'] in page.inner_text('#viewport-uv-material')
                assert candidate['source'] in page.inner_text('#viewport-uv-source-path')
                assert f"Cooked slot {candidate['slot']}" in page.inner_text('#viewport-uv-mesh')
                readout=page.inner_text('#viewport-uv-point')
                for label,key in [('U','u'),('V','v')]:
                    import re
                    actual=float(re.search(label+r' ([0-9.-]+)',readout).group(1))
                    assert abs(actual-candidate['point'][key])<2e-6,(readout,candidate['point'])
                association=candidate['association'];primitive=document['meshes'][association['meshes']]['primitives'][association['primitives']]
                raw_uv=read(primitive['attributes']['TEXCOORD_0'])
                assert np.allclose(raw_uv,np.frombuffer(base64.b64decode(candidate['uv']),dtype='<f4').reshape(-1,2),atol=1e-7)
                raw_index=read(primitive['indices']).reshape(-1) if 'indices' in primitive else np.arange(len(raw_uv))
                if candidate['index']:
                    assert np.array_equal(raw_index,np.frombuffer(base64.b64decode(candidate['index']),dtype={'Uint32Array':'<u4','Uint16Array':'<u2'}[candidate['index_type']]))
                page.locator('#viewport-uv-panel').screenshot(path=str(report/f'section-{number}-panel.png'))
                page.screenshot(path=str(report/f'section-{number}-model.png'))
                with page.expect_download() as download:page.click('#viewport-uv-export')
                output=report/f'section-{number}-uv.png';download.value.save_as(output)
                with Image.open(output) as exported:
                    exported=exported.convert('RGBA');alpha=np.asarray(exported)[:,:,3];width,height=exported.size
                    if number==0:assert exported.size==expected_size
                    assert np.count_nonzero(alpha)>100 and np.count_nonzero(alpha==0)>alpha.size*.1
                    assert np.all(np.asarray(exported)[:,:,:3][alpha>0]==255),'Export must contain only white UV lines'
                    triangles=raw_index[candidate['start']:candidate['start']+candidate['count']].reshape(-1,3)
                    coords=raw_uv[triangles]
                    edges=np.concatenate([(coords[:,0]+coords[:,1])*.5,(coords[:,1]+coords[:,2])*.5,(coords[:,2]+coords[:,0])*.5])
                    def coverage(flip):
                        hits=[]
                        for u,v in edges[::max(1,len(edges)//2000)]:
                            x=int(round(float(u)*width));y=int(round((1-float(v) if flip else float(v))*height))
                            hits.append(bool(alpha[max(0,y-2):min(height,y+3),max(0,x-2):min(width,x+3)].any()))
                        return sum(hits)/len(hits)
                    aligned=coverage(candidate['flipY']);mirrored=coverage(not candidate['flipY'])
                    assert aligned>.99,aligned
                    result['sections'].append({'material':candidate['material'],'slot':candidate['slot'],'texture':candidate['source'],
                        'triangles':len(triangles),'clicked_uv':candidate['point'],'export_size':[width,height],
                        'edge_alignment_fraction':aligned,'incorrect_vertical_mirror_fraction':mirrored,
                        'export_sha256':hashlib.sha256(output.read_bytes()).hexdigest()})
                assert page.evaluate('__uvReal.state().textures')==gpu
            assert page.evaluate('__uvReal.snapshot()')==snapshot
            page.screenshot(path=str(report/'real-model-uv-xray.png'))
            page.click('#viewport-showcase');assert page.is_hidden('#viewport-uv-panel') and page.is_disabled('#viewport-uv-toggle')
            page.click('#viewport-inspect');assert not page.is_disabled('#viewport-uv-toggle')
            assert not result['page_errors'],result['page_errors']
            page.evaluate('AtelierViewport.close()');browser.close()
            assert hashes()==before,'Project files changed during inspection'
            assert {p.name:(p.stat().st_size,p.stat().st_mtime_ns) for p in Path(C.PAKS).iterdir() if p.is_file()}==game_before
            result['checks']=['Native real-game GLB and material identity; two visible cooked material slots picked by real mouse clicks',
                'Project texture API bytes match the existing project PNG SHA-256',
                'All Three UV/index data match independently parsed native GLB accessors',
                'Exported PNG edge alignment checked against raw GLB UVs; exact project-image resolution and transparent white-line pixels',
                'No extra Three GPU textures; UVs, indices, drafts, project files and game containers unchanged',
                'Showcase closes and disables UV inspection; Inspect restores availability; no page errors']
            result['ok']=True
    finally:
        (report/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        server.shutdown();server.server_close();R.shutdown(5)
    print(json.dumps(result,indent=2),flush=True)


if __name__=='__main__':main()
