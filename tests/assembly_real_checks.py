"""Opt-in Assembly validation against real game assets and an isolated project.

Native geometry, materials, texture previews and editor requests are unmocked.
Only read-only observation hooks are appended to the browser modules. Edits are
restricted to the supplied test data, whose mods folder must be test-mods.
"""
import argparse
import hashlib
from io import BytesIO
import json
from pathlib import Path
import time
from urllib.parse import quote

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
HOOK = r'''
const assemblyNativeLoad=loader.loadAsync.bind(loader);let assemblyNativeLoads=0;
loader.loadAsync=async(...args)=>{assemblyNativeLoads++;return assemblyNativeLoad(...args);};
window.__assemblyReal={
 ready:()=>!modelLoading&&!materialTask&&!animation.loading()&&!connectedEditorPending&&!!objects.length,
 rest(){const control=document.getElementById('viewport-animation');control.value='';control.dispatchEvent(new Event('change'));},
 state(){const hit=assembly?.selectedSurface();return {
  project:viewportProject,selected:selectedMaterial,info:matData[selectedMaterial],
  surface:hit?{object:hit.object.uuid,mesh:hit.object.name,faceIndex:hit.faceIndex,materialIndex:hit.face?.materialIndex}:null,
  camera:camera.position.toArray(),target:controls.target.toArray(),up:camera.up.toArray(),
  geometries:renderer.info.memory.geometries,textures:renderer.info.memory.textures,loads:assemblyNativeLoads,
  playing:document.getElementById('viewport-play').getAttribute('aria-pressed'),
  objects:objects.map((object,index)=>({game_rel:meshMeta[index].game_rel,visible:object.root.visible,loaded:object.loaded,kind:object.kind})),
  data:matData,drafts:edited,status:document.getElementById('viewport-status').textContent,
  related:window.__assemblyRealRelated?.(),selectedTextures:[...document.querySelectorAll('.assembly-texture-card[aria-pressed=true]')].map(card=>({slot:card.dataset.slot,path:card.dataset.asset}))};},
 candidates(){
  modelRoot.updateMatrixWorld(true);camera.updateMatrixWorld(true);
  modelRoot.traverseVisible(mesh=>{if(mesh.isSkinnedMesh){mesh.computeBoundingSphere();mesh.computeBoundingBox();}});
  const rect=renderer.domElement.getBoundingClientRect(),ray=new THREE.Raycaster(),results=[],seen=new Set();
  for(const y of [.25,.35,.45,.55,.65,.75,.85,.15])for(const x of [.5,.45,.55,.4,.6,.35,.65,.3,.7]){
   const clientX=Math.round(rect.x+x*rect.width),clientY=Math.round(rect.y+y*rect.height);
   ray.setFromCamera(new THREE.Vector2((clientX-rect.x)/rect.width*2-1,1-(clientY-rect.y)/rect.height*2),camera);
   const hit=ray.intersectObjects(modelRoot.children,true).find(hit=>{
    for(let node=hit.object;node&&node!==modelRoot;node=node.parent)if(!node.visible)return false;
    const material=Array.isArray(hit.object.material)?hit.object.material[hit.face.materialIndex]:hit.object.material;
    return material?.visible&&!material.userData.heldDuplicate;
   });
   if(!hit)continue;
   const material=Array.isArray(hit.object.material)?hit.object.material[hit.face.materialIndex]:hit.object.material;
   const info=matData[material.name];if(!verifiedBinding(info)||seen.has(material.name))continue;
   seen.add(material.name);results.push({x:clientX,y:clientY,key:material.name,
    material:info.game_rel,mesh:info.mesh_game_rel,slot:info.slot_index,object:hit.object.uuid,
    faceIndex:hit.faceIndex,materialIndex:hit.face.materialIndex,slots:info.texture_sources});
  }return results;
 }
};
'''


def same_context(before, after, *, texture=True):
    for field in ('project', 'selected', 'surface', 'objects', 'loads'):
        assert before[field] == after[field], (field, before[field], after[field])
    for field in ('camera', 'target', 'up'):
        assert all(abs(a-b) < 1e-6 for a,b in zip(before[field], after[field])), (field, before[field], after[field])
    if texture:
        assert before['selectedTextures'] == after['selectedTextures'], ('texture selection', before['selectedTextures'], after['selectedTextures'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--data-dir', required=True, type=Path)
    parser.add_argument('--report-dir', required=True, type=Path)
    parser.add_argument('--skin', default='1029304')
    args = parser.parse_args()
    data = args.data_dir.resolve(strict=True)
    config = json.loads((data/'mr_config.json').read_text(encoding='utf-8'))
    assert data != ROOT and Path(config['mods_folder']).resolve() == data/'test-mods', 'Use isolated test data'
    report = args.report_dir.resolve(); report.mkdir(parents=True,exist_ok=True)
    paks = Path(config['paks'])
    game_before = {p.name:(p.stat().st_size,p.stat().st_mtime_ns) for p in paks.iterdir() if p.is_file()}
    result = {'ok':False,'skin':args.skin,'checks':[],'surfaces':[],'page_errors':[],'asset_errors':[]}
    def passed(message):
        result['checks'].append(message)
        (report/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print('PASS '+message,flush=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={'width':1680,'height':1100},reduced_motion='reduce',accept_downloads=True)
        page = context.new_page()
        page.on('pageerror',lambda error:result['page_errors'].append(str(error)))
        def response_received(response):
            if response.status>=400 and any('/api/'+name in response.url for name in ('model_gltf','skin_materials','texture_png','assembly_thumbnail','material_save')):
                result['asset_errors'].append({'url':response.url,'status':response.status})
        page.on('response',response_received)
        page.route('**/static/viewport.js',lambda route:route.fulfill(body=(ROOT/'gui/viewport.js').read_text(encoding='utf-8')+HOOK,content_type='text/javascript'))
        def inspect_hook(route):
            source=(ROOT/'gui/viewport-inspection.js').read_text(encoding='utf-8')
            source=source.replace('let related = null;', 'let related = null;window.__assemblyRealRelated=()=>related?{keys:[...related.names],section:related.section?.id}:null;')
            route.fulfill(body=source,content_type='text/javascript')
        page.route('**/static/viewport-inspection.js',inspect_hook)
        try:
            page.goto(args.url,wait_until='domcontentloaded')
            page.wait_for_function('window.AtelierViewport && window.atelierProject?.()',timeout=90000)
            assert page.evaluate('atelierProject()') == config['active_project']
            if page.locator('#changelog-done').is_visible():page.locator('#changelog-done').click()
            page.wait_for_function('!document.querySelector(".overlay.active")',timeout=30000)
            print('Loading real Magik geometry, materials and standing idle...',flush=True)
            page.evaluate('skin=>{void AtelierViewport.open(skin,"Magik · Assembly native verification")}',args.skin)
            deadline=time.monotonic()+420
            while not page.evaluate('window.__assemblyReal?.ready() || false'):
                assert not result['page_errors'],result['page_errors']
                if time.monotonic()>deadline:raise TimeoutError('Real character did not finish loading')
                page.wait_for_timeout(500)
            page.evaluate('__assemblyReal.rest()')
            page.locator('#viewport-assembly').click()
            page.wait_for_selector('.assembly-section')
            page.evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
            state=page.evaluate('__assemblyReal.state()')
            (report/'loaded-materials.json').write_text(json.dumps(state,indent=2),encoding='utf-8')
            assert not any(info.get('mapping_error') or info.get('material_error') for info in state['data'].values()), state['status']
            candidates=page.evaluate('__assemblyReal.candidates()')
            (report/'click-candidates.json').write_text(json.dumps(candidates,indent=2),encoding='utf-8')
            candidates=[candidate for candidate in candidates if candidate['slots']]
            assert len(candidates)>=2,'At least two visible material sections are required'
            chosen=next((c for c in candidates if 'body' in c['material'].lower() and any(s.get('role')=='normal' for s in c['slots'])),candidates[0])
            others=[c for c in candidates if c['key']!=chosen['key']][:2]
            for candidate in [*others,chosen]:
                # Selecting another resource can resize the texture shelf. Raycast
                # the current canvas before each click, as a user sees it now.
                page.evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
                candidate=next(c for c in page.evaluate('__assemblyReal.candidates()') if c['key']==candidate['key'])
                page.mouse.click(candidate['x'],candidate['y'])
                page.wait_for_function('key=>__assemblyReal.state().selected===key',arg=candidate['key'])
                page.wait_for_function('path=>document.getElementById("assembly-material-context").textContent.includes(path)',arg=candidate['material'])
                selected=page.evaluate('__assemblyReal.state()')
                assert selected['surface']['object']==candidate['object']
                assert selected['surface']['faceIndex']==candidate['faceIndex']
                assert selected['surface']['materialIndex']==candidate['materialIndex']
                manifest=next((data/'_cache/imports').rglob(Path(candidate['mesh']).name+'.json'))
                native=json.loads(manifest.read_text(encoding='utf-8'))
                slot=next(slot for slot in native['slots'] if slot['index']==candidate['slot'])
                assert slot['mi']==candidate['material'],(slot,candidate)
                expected={source['slot']:source['game_rel'] for source in candidate['slots'] if not source.get('inferred')}
                actual=page.locator('.assembly-texture-card').evaluate_all('(cards)=>Object.fromEntries(cards.map(card=>[card.dataset.slot,card.dataset.asset]))')
                assert actual==expected,(actual,expected)
                result['surfaces'].append({'material':candidate['material'],'mesh':candidate['mesh'],'cooked_slot':candidate['slot'],
                    'face_index':candidate['faceIndex'],'texture_slots':expected})
            passed(f'Real mouse clicks select {len(result["surfaces"])} exact Magik sections; material paths match native cooked-slot metadata and all texture cards match their bindings')
            base=next(source for source in chosen['slots'] if source.get('role')=='basecolor' and not source.get('inferred'))
            card=page.locator('.assembly-texture-card').filter(has_text='Diffuse').first
            if not card.count():card=page.locator('.assembly-texture-card').first
            card.click()
            current=page.evaluate('__assemblyReal.state()')
            selected_path=current['selectedTextures'][0]['path']
            expected_keys={key for key,info in current['data'].items() if info.get('mapping_via')=='imports' and not info.get('mapping_error') and not info.get('material_set_override')
                and any(source['game_rel'].lower()==selected_path.lower() and not source.get('inferred') for source in info.get('texture_sources',[]))}
            assert set(current['related']['keys'])==expected_keys
            assert set(page.locator('.assembly-section.is-related').evaluate_all('rows=>rows.map(row=>row.dataset.material)'))<=expected_keys
            page.wait_for_function("[...document.querySelectorAll('.assembly-texture-preview img')].filter(img=>img.getBoundingClientRect().width&&img.getBoundingClientRect().right<innerWidth).every(img=>img.complete&&img.naturalWidth)",timeout=120000)
            page.mouse.move(10,10)
            page.screenshot(path=str(report/'magik-assembly-connected.png'))
            passed('Texture selection highlights only materials with the same complete package reference; native thumbnails load successfully')
            before=page.evaluate('__assemblyReal.state()')
            page.get_by_role('button',name='Preview',exact=True).click()
            page.wait_for_selector('#library-preview[open] img:not([hidden])')
            preview=page.locator('#library-preview img').get_attribute('src')
            assert quote(selected_path,safe='') in preview or selected_path in preview
            page.locator('#library-preview-close').click()
            same_context(before,page.evaluate('__assemblyReal.state()'))
            passed('Full native texture preview closes back to the same selected surface, texture and camera')
            # Give the camera an actual orbit gesture before editor round trips.
            rect=page.locator('#viewport-canvas').bounding_box()
            page.mouse.move(rect['x']+rect['width']*.7,rect['y']+rect['height']*.5)
            page.mouse.down();page.mouse.move(rect['x']+rect['width']*.7+28,rect['y']+rect['height']*.5+12,steps=8);page.mouse.up()
            page.wait_for_timeout(850)
            before=page.evaluate('__assemblyReal.state()')
            page.locator('#assembly-material-context .assembly-primary').click()
            page.wait_for_selector('#material-overlay.active')
            # Observe the exact handoff pose after the real pointer click; any
            # remaining orbit inertia must stay stopped throughout the return.
            handoff=page.evaluate('__assemblyReal.state()')
            for field in ('selected','surface','objects','loads','selectedTextures'):
                assert before[field]==handoff[field],field
            before=handoff
            page.wait_for_selector('#matsw0',timeout=120000)
            page.locator('#mat-close').click()
            page.wait_for_selector('#viewport-overlay.active')
            page.wait_for_function('__assemblyReal.ready()',timeout=180000)
            page.evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
            same_context(before,page.evaluate('__assemblyReal.state()'))
            passed('Material editor inspection preserves the orbited camera, exact clicked triangle, texture selection and loaded geometry')
            before=page.evaluate('__assemblyReal.state()')
            page.locator('#assembly-material-context .assembly-primary').click()
            page.wait_for_selector('#matsw0',timeout=120000)
            parameter=page.locator('#matrow0 label').inner_text()
            page.locator('#matsw0').evaluate("input=>{input.value='#496faa';input.dispatchEvent(new Event('input',{bubbles:true}));}")
            page.locator('#mat-save').click()
            page.wait_for_selector('#viewport-overlay.active',timeout=120000)
            page.wait_for_function('__assemblyReal.ready()',timeout=180000)
            page.evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
            after=page.evaluate('__assemblyReal.state()');same_context(before,after)
            assert before['info']['colors']!=after['info']['colors'],'Saved material colours did not refresh'
            passed('Saving a real material through the established editor updates Assembly and retains the complete editing context')
            # Assign an authored test image through the real slot editor; never overwrite game content.
            source=next((s for s in chosen['slots'] if s.get('role')=='normal' and s.get('texture_class')=='Texture2D'),base)
            page.locator('.assembly-texture-card').evaluate_all('(cards,slot)=>cards.find(card=>card.dataset.slot===slot).click()',source['slot'])
            before=page.evaluate('__assemblyReal.state()')
            page.get_by_role('button',name='Edit material slot',exact=True).click()
            page.wait_for_selector('#material-overlay.active')
            page.wait_for_function('slot=>[...document.querySelectorAll(".mat-texture")].some(row=>row.querySelector("label")?.textContent===slot)',arg=source['slot'],timeout=120000)
            row=page.locator('.mat-texture').filter(has=page.locator('label',has_text=source['slot'])).first
            output=BytesIO();Image.new('RGB',(64,64),(127,127,255)).save(output,'PNG')
            with page.expect_file_chooser() as picker:row.get_by_role('button',name='Use my own image…',exact=True).click()
            picker.value.set_files({'name':'Assembly-native-normal.png','mimeType':'image/png','buffer':output.getvalue()})
            page.wait_for_function("document.getElementById('mat-status').textContent.includes('now uses')",timeout=120000)
            page.locator('#mat-close').click();page.wait_for_selector('#viewport-overlay.active')
            page.wait_for_function('__assemblyReal.ready()',timeout=180000)
            page.evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
            after=page.evaluate('__assemblyReal.state()');same_context(before,after,texture=False)
            custom=next(s for s in after['info']['texture_sources'] if s['slot']==source['slot'])
            assert custom['custom'] and custom['game_rel']!=source['game_rel']
            assert after['selectedTextures']==[{'slot':custom['slot'],'path':custom['game_rel']}]
            response=context.request.get(args.url+custom['url'],headers={'X-Atelier-Project':quote(config['active_project'],safe='')})
            assert response.ok
            with Image.open(BytesIO(response.body())) as actual:
                assert actual.size==(64,64) and actual.convert('RGB').getpixel((10,10))==(127,127,255)
            page.mouse.move(10,10);page.screenshot(path=str(report/'magik-assembly-project-texture.png'))
            passed('The real material slot editor publishes a custom texture only to the isolated project; Assembly follows its new package and retains the selected slot')
            before=page.evaluate('__assemblyReal.state()')
            page.get_by_role('button',name='Inspect UVs',exact=True).click()
            page.wait_for_selector('#viewport-uv-content:not([hidden])')
            assert chosen['material'] in page.locator('#viewport-uv-material').inner_text()
            page.locator('#viewport-uv-toggle').click();same_context(before,page.evaluate('__assemblyReal.state()'))
            passed('UV inspection identifies the same real selected material and returns without resetting camera or resource selection')
            page.set_viewport_size({'width':1024,'height':768})
            page.evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
            assert page.locator('.assembly-section').count()>=10
            assert page.locator('#assembly-sections').evaluate('list=>list.scrollHeight>list.clientHeight')
            assert page.locator('.assembly-geometry-actions button').evaluate_all('buttons=>buttons.every(button=>{const r=button.getBoundingClientRect(),parent=button.closest("#assembly-geometry-selection").getBoundingClientRect();return r.top>=parent.top&&r.bottom<=parent.bottom&&r.bottom<innerHeight;})')
            page.screenshot(path=str(report/'magik-assembly-compact.png'))
            passed('With twelve real surfaces, geometry actions remain visible at 1024×768 while the surface list scrolls independently')
            assert not result['page_errors'],result['page_errors']
            assert not result['asset_errors'],result['asset_errors']
            assert {p.name:(p.stat().st_size,p.stat().st_mtime_ns) for p in paks.iterdir() if p.is_file()}==game_before
            assert not any((data/'test-mods').iterdir()),'A test installed a game mod'
            result['final']={'selected':after['selected'],'surface':after['surface'],'loads':after['loads'],'camera':after['camera'],
                'custom_slot':source['slot'],'custom_path':custom['game_rel'],'saved_parameter':parameter,
                'project_files':len(list((data/'assets/projects'/config['active_project']).rglob('*')))}
            passed('No browser errors, failed core asset requests, game container changes or installed mods')
            result['ok']=True
        except Exception:
            page.screenshot(path=str(report/'failure.png'))
            try:(report/'failure-state.json').write_text(json.dumps(page.evaluate('__assemblyReal.state()'),indent=2),encoding='utf-8')
            except Exception:pass
            raise
        finally:
            (report/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
            browser.close()


if __name__=='__main__':main()
