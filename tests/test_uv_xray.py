"""UV X-Ray uses real Three geometry and existing project texture identities, read-only."""
import atexit
import copy
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
from wsgiref.simple_server import make_server, WSGIRequestHandler

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
environment = tempfile.TemporaryDirectory(prefix='atelier-uv-xray-')
os.environ['ATELIER_DATA_DIR'] = environment.name
from atelier.web import routes as R


def cleanup():
    R.shutdown(5)
    environment.cleanup()


atexit.register(cleanup)


class SourceIdentity(unittest.TestCase):
    def test_sources_keep_full_paths_custom_package_identity_and_all_slots(self):
        params = {'textures': {'BaseColor':'Body/Textures/T_Same', 'Diffuse':'Weapon/Textures/T_Same',
                               'Normal':'Body/Textures/T_Normal', 'Environment':'Shared/T_Cube'},
                  'texture_classes': {'BaseColor':'Texture2D','Diffuse':'Texture2D','Normal':'Texture2D','Environment':'TextureCube'},
                  'colors':[], 'scalars':[]}
        before = copy.deepcopy(params)
        custom = {'Normal':{'name':'T_Painted_Normal','file':'a'*20+'.png','folder':'MyMod/Normals'}}
        with patch.object(R, '_preview_surface', side_effect=lambda value:value), \
             patch.object(R._custom_tex, 'assignments', return_value=custom), \
             patch.object(R, '_tex_version', return_value='version'):
            result = R._viewport_material_payload('Body/Materials/MI_Body', params)
        sources = {source['slot']:source for source in result['texture_sources']}
        self.assertEqual(params,before)
        self.assertEqual(sources['BaseColor']['game_rel'],'Body/Textures/T_Same')
        self.assertEqual(sources['Diffuse']['game_rel'],'Weapon/Textures/T_Same')
        self.assertEqual(sources['BaseColor']['preview_role'],'basecolor')
        self.assertIsNone(sources['Diffuse']['preview_role'])
        self.assertEqual(sources['Normal']['game_rel'],'MyMod/Normals/T_Painted_Normal')
        self.assertEqual(sources['Normal']['texture_class'],'Texture2D')
        query = parse_qs(urlparse(sources['Normal']['url']).query)
        self.assertEqual(query,{'game_rel':['Body/Materials/MI_Body'],'slot':['Normal'],'v':['a'*20+'.png']})
        self.assertEqual(sources['Environment']['texture_class'],'TextureCube')
        self.assertEqual(parse_qs(urlparse(sources['Diffuse']['url']).query)['game_rel'],['Weapon/Textures/T_Same'])


@unittest.skipUnless(shutil.which('node'), 'Node is unavailable')
class UVGeometry(unittest.TestCase):
    def test_section_channels_coordinates_orientation_and_unsupported_layouts(self):
        with tempfile.TemporaryDirectory(prefix='atelier-uv-three-') as folder:
            folder = Path(folder)
            vendor = (ROOT/'gui/vendor/three/three.module.min.js').as_uri()
            loader = folder/'loader.mjs'
            loader.write_text("export async function resolve(name,context,next){if(name==='three')return {url:"+json.dumps(vendor)+",shortCircuit:true};return next(name,context);}",encoding='utf-8')
            script = folder/'checks.mjs'
            script.write_text(r'''
import assert from 'node:assert/strict';
import * as THREE from 'three';
const {uvChannels,uvSection,uvPoint,buildUVLayout,drawUVLayout,mappingIssue,textureSources} = await import(process.argv[2]);
const geometry = new THREE.BufferGeometry();
geometry.setAttribute('position',new THREE.Float32BufferAttribute(new Array(18).fill(0),3));
geometry.setAttribute('uv',new THREE.Float32BufferAttribute([.1,.1,.4,.1,.1,.8,.6,.2,.9,.2,.9,.7],2));
geometry.setAttribute('uv1',new THREE.InterleavedBufferAttribute(new THREE.InterleavedBuffer(new Float32Array([0,.2,.3,0,.6,.3,0,.2,.9,0,.6,.3,0,.9,.3,0,.9,.8]),3),2,1));
geometry.setIndex([0,1,2,3,4,5]);geometry.addGroup(0,3,0);geometry.addGroup(3,3,0);
const material = new THREE.MeshStandardMaterial(), mesh = new THREE.Mesh(geometry,[material]);
const hit = {object:mesh,material,faceIndex:0,face:{a:0,b:1,c:2,materialIndex:0},barycoord:new THREE.Vector3(1/3,1/3,1/3)};
const original = Array.from(geometry.getAttribute('uv').array), indices = Array.from(geometry.index.array);
assert.deepEqual(uvChannels(geometry),[0,1]);
assert.deepEqual(uvSection(hit),{start:0,end:3,section:0});
assert.ok(Math.abs(uvPoint(hit,0).u-.2)<1e-6);assert.ok(Math.abs(uvPoint(hit,0).v-1/3)<1e-6);
assert.ok(Math.abs(uvPoint(hit,1).u-1/3)<1e-6);assert.ok(Math.abs(uvPoint(hit,1).v-.5)<1e-6);
const layout = buildUVLayout(hit,0), commands = [];
const context = {beginPath(){},stroke(){},moveTo(x,y){commands.push([x,y])},lineTo(x,y){commands.push([x,y])}};
drawUVLayout(context,layout,100,50);
assert.equal(commands.length,4,'Only the clicked section is exported, even when both groups share the same material');
assert.ok(Math.abs(commands[0][0]-10)<1e-5 && Math.abs(commands[0][1]-5)<1e-5,'flipY=false uses source image top-left orientation');
commands.length=0;drawUVLayout(context,buildUVLayout(hit,0,true),100,50);
assert.ok(Math.abs(commands[0][1]-45)<1e-5,'flipY=true uses the opposite image orientation');
const other = {...hit,faceIndex:1,face:{a:3,b:4,c:5,materialIndex:0}};
assert.deepEqual(uvSection(other),{start:3,end:6,section:1});
assert.equal(buildUVLayout(other,1).triangles,1);
geometry.setAttribute('uv2',new THREE.Uint16BufferAttribute([0,0,65535,0,0,65535,0,0,65535,0,0,65535],2,true));
assert.deepEqual(uvChannels(geometry),[0,1,2]);assert.ok(Math.abs(uvPoint(hit,2).u-1/3)<1e-6);geometry.deleteAttribute('uv2');
mesh.material=material;assert.equal(buildUVLayout(hit,0).triangles,2,'A single material follows Three and ignores groups');mesh.material=[material];
geometry.setIndex(null);assert.equal(buildUVLayout(hit,0).triangles,1,'Non-indexed triangle sections are supported');geometry.setIndex(indices);
geometry.setDrawRange(3,3);assert.throws(()=>buildUVLayout(hit,0),/triangle layout/);geometry.setDrawRange(0,Infinity);
assert.throws(()=>buildUVLayout(hit,2),/no supported/);
geometry.getAttribute('uv').setX(0,1.2);assert.throws(()=>buildUVLayout(hit,0),/outside the 0–1/);
geometry.getAttribute('uv').setX(0,NaN);assert.throws(()=>buildUVLayout(hit,0),/invalid coordinates/);
geometry.getAttribute('uv').setX(0,original[0]);geometry.index.setX(0,99);assert.throws(()=>buildUVLayout(hit,0),/incomplete/);geometry.index.setX(0,0);
assert.deepEqual(Array.from(geometry.getAttribute('uv').array),original);assert.deepEqual(Array.from(geometry.index.array),indices);
const tex = new THREE.Texture(), source = {texture_class:'Texture2D'};
assert.equal(mappingIssue(source,{},tex),'');tex.repeat.x=2;assert.match(mappingIssue(source,{},tex),/Transformed/);tex.repeat.x=1;
assert.match(mappingIssue({texture_class:'TextureCube'},{},tex),/TextureCube/);
assert.match(mappingIssue(source,{eye_preview:true},tex),/Layered eye/);
assert.match(mappingIssue(source,{surface:{parent:'M_WorldAligned'}},tex),/World-projected/);
tex.matrixAutoUpdate=false;tex.matrix.elements[6]=.2;assert.match(mappingIssue(source,{},tex),/Transformed/);
const metadata=[{slot:'Normal',game_rel:'Custom/T_Normal',url:'/api/material_custom_texture/preview?slot=Normal'}];
assert.equal(textureSources({texture_sources:metadata},material),metadata,'Use the backend asset identity and project URL unchanged');
geometry.dispose();material.dispose();tex.dispose();
console.log('PASS indexed sections, shared materials, draw ranges, normalized channels, barycentric coordinates, image orientation, source identity and unsupported mappings');
''',encoding='utf-8')
            result = subprocess.run([shutil.which('node'),'--no-warnings','--experimental-loader',loader.as_uri(),str(script),(ROOT/'gui/viewport-uv.js').as_uri()],capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)


class Browser(unittest.TestCase):
    def test_surface_inspection_and_exact_transparent_export(self):
        from atelier.web.app import _ThreadingWSGIServer
        from playwright.sync_api import sync_playwright

        class Quiet(WSGIRequestHandler):
            def log_message(self, *_args):
                pass

        Path(R.PROJECTS_ROOT,'UV Fixture').mkdir(parents=True,exist_ok=True)
        R.set_active_project('UV Fixture')
        server = make_server('127.0.0.1',0,R.app,_ThreadingWSGIServer,Quiet)
        thread = threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f'http://127.0.0.1:{server.server_port}'
        source = BytesIO(); Image.new('RGBA',(96,48),(12,85,150,255)).save(source,'PNG')
        normal = BytesIO(); Image.new('RGBA',(48,96),(128,128,255,255)).save(normal,'PNG')
        material = {'game_rel':'Fixture/Materials/MI_Body','mesh_game_rel':'Fixture/Meshes/SK_Body','slot_index':0,
                    'colors':[],'scalars':[],'textures':{'BaseColor':'Fixture/T_Color','Normal':'Fixture/T_Normal'},
                    'texture_roles':{'basecolor':'Fixture/T_Color'},'texture_classes':{'BaseColor':'Texture2D','Normal':'Texture2D'},
                    'texture_sources':[
                        {'slot':'BaseColor','game_rel':'Fixture/T_Color','role':'basecolor','preview_role':'basecolor','texture_class':'Texture2D','url':'/api/texture_png?game_rel=Fixture/T_Color'},
                        {'slot':'Normal','game_rel':'Fixture/T_Normal','role':'normal','preview_role':'normal','texture_class':'Texture2D','url':'/api/texture_png?game_rel=Fixture/T_Normal'},
                        {'slot':'Environment','game_rel':'Fixture/T_Cube','texture_class':'TextureCube','url':'/api/texture_png?game_rel=Fixture/T_Cube'}]}
        requests, modules, errors, writes = [], [], [], []

        def fixtures(route):
            request = route.request; path = urlparse(request.url).path
            if request.method != 'GET' and path not in ('/api/skin_materials','/api/viewport_cancel'):
                writes.append(path)
            payload = {
                '/api/setup_status':{'configured':True}, '/api/prereqs':{'issues':[]},
                '/api/update_check':{'available':False}, '/api/usmap_update_check':{'ok':True},
                '/api/index_warnings':{'failed':[]}, '/api/stale_mips':{'ok':True,'count':0},
                '/api/catalogue/status':{'updating':False,'portraits':0}, '/api/catalogue/library':{'heroes':[]},
                '/api/browse':[], '/api/browse_material_dirs':{'dirs':[]},
                '/api/skin_meshes':[{'name':'UV fixture','game_rel':'Fixture/Meshes/SK_Body'}],
                '/api/skin_materials':{'ok':True,'materials':{'MI_Body':material}},
                '/api/idle_animations':{'ok':True,'animations':[]},
            }.get(path)
            if payload is not None:
                return route.fulfill(json=payload)
            if path == '/api/texture_png':
                requests.append(request.url)
                return route.fulfill(body=normal.getvalue() if 'T_Normal' in request.url else source.getvalue(),content_type='image/png')
            if path.startswith('/api/catalogue/'):
                return route.fulfill(status=404,body='No fixture artwork')
            route.continue_()

        hook = r'''
loader.loadAsync = async () => {
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position',new THREE.Float32BufferAttribute([-1,-1,0,0,-1,0,-1,1,0,0,-1,0,1,-1,0,1,1,0],3));
  geometry.setAttribute('uv',new THREE.Float32BufferAttribute([.1,.1,.4,.1,.1,.8,.6,.2,.9,.2,.9,.7],2));
  geometry.setAttribute('uv1',new THREE.Float32BufferAttribute([.2,.3,.6,.3,.2,.9,.6,.3,.9,.3,.9,.8],2));
  geometry.setIndex([0,1,2,3,4,5]);geometry.addGroup(0,3,0);geometry.addGroup(3,3,0);geometry.computeVertexNormals();
  const material=new THREE.MeshStandardMaterial();material.name='MI_Body';
  const oldNormal=document.createElement('canvas');oldNormal.width=oldNormal.height=4;material.normalMap=new THREE.CanvasTexture(oldNormal);
  const mesh=new THREE.Mesh(geometry,[material]);mesh.name='Two sections sharing one material';
  const group=new THREE.Group();group.add(mesh);window.__uvMesh=mesh;
  return {scene:group,animations:[]};
};
window.__uvTest = {
  ready:()=>!modelLoading && !materialTask && !!window.__uvMesh?.material[0].map,
  point(section=0){
    const mesh=window.__uvMesh,position=mesh.geometry.getAttribute('position'),p=new THREE.Vector3();
    for(let i=section*3;i<section*3+3;i++)p.add(new THREE.Vector3().fromBufferAttribute(position,i));
    p.divideScalar(3).applyMatrix4(mesh.matrixWorld).project(camera);
    const r=document.getElementById('viewport-canvas').getBoundingClientRect();return {x:r.x+(p.x+1)*r.width/2,y:r.y+(1-p.y)*r.height/2};
  },
  snapshot:()=>JSON.stringify({uv:Array.from(__uvMesh.geometry.getAttribute('uv').array),index:Array.from(__uvMesh.geometry.index.array),edited}),
  gpu:()=>renderer.info.memory.textures,
  transformed:value=>{__uvMesh.material[0].map.repeat.x=value?2:1;},
  delaySource(){const native=materialFetch;materialFetch=async(url,options)=>{
    const response=await native(url,options);if(url.includes('T_Normal'))await new Promise(resolve=>window.__releaseUVSource=resolve);return response;};},
};
'''
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            context = browser.new_context(viewport={'width':1400,'height':1000},reduced_motion='reduce',accept_downloads=True)
            context.route('**/api/**',fixtures)
            context.route('https://**',lambda route:route.fulfill(json={}))
            page = context.new_page()
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.on('request',lambda request:modules.append(request.url) if '/static/viewport-uv.js' in request.url else None)
            page.route('**/static/viewport.js',lambda route:route.fulfill(body=(ROOT/'gui/viewport.js').read_text(encoding='utf-8')+hook,content_type='text/javascript'))
            page.goto(url); page.wait_for_function('window.__uvTest && window.atelierProject?.()')
            page.evaluate("AtelierViewport.open('1029001','UV X-Ray — synthetic geometry')")
            page.wait_for_function('__uvTest.ready()')
            page.evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
            self.assertFalse(modules,'The UV module must stay unloaded until requested')
            before = page.evaluate('__uvTest.snapshot()'); gpu = page.evaluate('__uvTest.gpu()'); loaded = len(requests)
            page.click('#viewport-uv-toggle')
            page.wait_for_selector('#viewport-uv-empty')
            self.assertEqual(len(requests),loaded,'Opening without a surface must not load a source image')

            def pick(section=0):
                point = page.evaluate('(section)=>__uvTest.point(section)',section)
                page.mouse.click(point['x'],point['y'])

            pick(); page.wait_for_function("!document.getElementById('viewport-uv-export').disabled")
            self.assertIn('Geometry section 0',page.inner_text('#viewport-uv-mesh'))
            self.assertIn('U 0.200000',page.inner_text('#viewport-uv-point'))
            self.assertIn('Fixture/T_Color',page.inner_text('#viewport-uv-source-path'))
            self.assertEqual(len(requests),loaded,'The already loaded source image is reused without a second decode')
            self.assertEqual(page.evaluate('__uvTest.gpu()'),gpu,'UV inspection must not allocate GPU textures')
            if os.environ.get('ATELIER_UV_REPORT_DIR'):
                report = Path(os.environ['ATELIER_UV_REPORT_DIR']); report.mkdir(parents=True,exist_ok=True)
                page.screenshot(path=str(report/'uv-xray.png'))
            page.select_option('#viewport-uv-zoom','4')
            page.locator('#viewport-uv-opacity').fill('0')
            with page.expect_download() as download:
                page.click('#viewport-uv-export')
            with Image.open(download.value.path()) as downloaded:
                image = downloaded.convert('RGBA')
            self.assertEqual(image.size,(96,48))
            self.assertEqual(image.getpixel((0,0))[3],0)
            self.assertGreater(image.getpixel((20,5))[3],0,'Source image orientation must match the overlay')
            self.assertEqual(image.getpixel((20,43))[3],0,'The export must not vertically mirror a glTF UV layout')
            self.assertEqual(image.getpixel((19,16))[3],0,'The clicked-point marker and source pixels are excluded')
            self.assertIsNone(image.getchannel('A').crop((49,0,96,48)).getbbox(),'A shared material must not include the other geometry section')
            page.select_option('#viewport-uv-channel','1')
            self.assertIn('V 0.500000',page.inner_text('#viewport-uv-point'))
            self.assertIn('viewport texture uses UV0',page.inner_text('#viewport-uv-mapping-note'))
            page.select_option('#viewport-uv-source','1')
            page.wait_for_function("document.getElementById('viewport-uv-resolution').textContent.includes('48 × 96')")
            with page.expect_download() as download:
                page.click('#viewport-uv-export')
            with Image.open(download.value.path()) as downloaded:
                self.assertEqual(downloaded.size,(48,96),'Every source exports at its own exact non-square dimensions')
            pick(1); page.wait_for_function("!document.getElementById('viewport-uv-export').disabled")
            self.assertIn('Geometry section 1',page.inner_text('#viewport-uv-mesh'))
            page.evaluate('__uvTest.transformed(true)');pick(0)
            page.wait_for_function("document.getElementById('viewport-uv-status').textContent.includes('Transformed')")
            self.assertTrue(page.is_disabled('#viewport-uv-export'))
            page.evaluate('__uvTest.transformed(false)');pick()
            page.select_option('#viewport-uv-source','2')
            self.assertIn('TextureCube',page.inner_text('#viewport-uv-status'))
            self.assertTrue(page.is_disabled('#viewport-uv-export'))
            self.assertFalse(any('T_Cube' in request for request in requests))
            page.select_option('#viewport-uv-source','0')
            page.wait_for_function("!document.getElementById('viewport-uv-export').disabled")
            page.evaluate('__uvTest.delaySource()'); page.select_option('#viewport-uv-source','1')
            page.wait_for_function("typeof window.__releaseUVSource==='function'")
            page.click('#viewport-uv-toggle');page.evaluate('__releaseUVSource()')
            self.assertTrue(page.is_hidden('#viewport-uv-panel'))
            self.assertEqual(page.evaluate("document.getElementById('viewport-uv-image').width"),1,'Closing releases preview backing stores')
            page.click('#viewport-uv-toggle');pick()
            page.wait_for_function("!document.getElementById('viewport-uv-export').disabled")
            page.click('#viewport-showcase')
            self.assertTrue(page.is_hidden('#viewport-uv-panel'))
            self.assertTrue(page.is_disabled('#viewport-uv-toggle'))
            page.click('#viewport-inspect')
            self.assertFalse(page.is_disabled('#viewport-uv-toggle'))
            self.assertEqual(page.evaluate('__uvTest.snapshot()'),before,'Inspection must not mutate UVs, indices or recolour drafts')
            self.assertFalse(writes,'UV inspection must not write project assets')
            self.assertFalse(errors,errors)
            browser.close()


if __name__ == '__main__':
    unittest.main()
