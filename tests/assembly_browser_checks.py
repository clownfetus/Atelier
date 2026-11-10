"""Assembly interactions in Chromium, using clearly labelled synthetic geometry."""
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import json
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
MESH = 'Characters/1029/1029001/Meshes/SK_AssemblyFixture'
HOOK = r'''
window.__assembly = {
 refresh:()=>refreshAssemblyMeshes(new Set(meshMeta.map(meta=>meta.game_rel))),
 orbitAndOpen:()=>{controls.rotateLeft(.12);const before=window.__assembly.state();document.querySelector('#assembly-material-context .assembly-primary').click();return before;},
 state:()=>({camera:camera.position.toArray(),target:controls.target.toArray(),selected:selectedMaterial,raf,
   canvas:[renderer.domElement.width,renderer.domElement.height,renderer.domElement.clientWidth,renderer.domElement.clientHeight],
   surface:assembly.selectedSurface()?.object?.name,project:viewportProject,decodes:window.__assemblyDecodes||0}),
 point:()=>{const p=new THREE.Vector3(0,1.5,.3).project(camera),r=renderer.domElement.getBoundingClientRect();
   return {x:r.x+(p.x+1)*r.width/2,y:r.y+(1-p.y)*r.height/2};},
};
loader.loadAsync = async url=>{
 window.__assemblyDecodes=(window.__assemblyDecodes||0)+1;
 const root=new THREE.Group(),materials=[0,1,2,3].map(i=>{const m=new THREE.MeshStandardMaterial();m.name=['MI_Body','MI_Trim','MI_Same','MI_Unknown'][i];return m;});
 const add=(name,geometry,xyz,material)=>{const mesh=new THREE.Mesh(geometry,materials[material]);mesh.name=name;mesh.position.set(...xyz);root.add(mesh);return mesh;};
 add('Torso fixture',new THREE.BoxGeometry(.75,1.15,.45),[0,1.55,0],0);
 add('Head fixture',new THREE.SphereGeometry(.29,24,16),[0,2.43,0],1);
 for(const side of [-1,1]){
   add('Arm fixture '+side,new THREE.CapsuleGeometry(.13,.7,6,12),[side*.59,1.58,0],0);
   add('Leg fixture '+side,new THREE.CapsuleGeometry(.16,.72,6,12),[side*.23,.48,0],2);
 }
 add('Unverified fixture',new THREE.SphereGeometry(.1,12,8),[.5,2.3,0],3);
 if (url.includes('SK_StandaloneFixture')) return {scene:root,animations:[]};
 const associations=new Map(materials.map((m,i)=>[m,{materials:i}]));
 return {scene:root,animations:[],parser:{associations,json:{materials:materials.map(m=>({name:m.name}))}}};
};
'''


def run_assembly_checks(context, url, report, checks):
    tab = context.new_page()
    tab.set_viewport_size({'width':1600, 'height':1000})
    errors, thumbnails, effects_reads, material_saves = [], [], [], []
    tab.on('pageerror', lambda error: errors.append(str(error)))
    tab.on('console', lambda message: errors.append(message.text) if message.type == 'error' and 'Shader Error' in message.text else None)
    tab.route('**/static/viewport.js', lambda route: route.fulfill(body=(ROOT/'gui/viewport.js').read_text(encoding='utf-8') + HOOK, content_type='text/javascript'))
    tab.route('**/api/skin_meshes?*', lambda route: route.fulfill(json=[{'game_rel': MESH, 'name': 'Synthetic Assembly mannequin', 'kind': 'body'}]))
    tab.route('**/api/browse_material_dirs?*', lambda route: route.fulfill(json={'dirs': []}))
    tab.route('**/api/idle_animations?*', lambda route: route.fulfill(json={'ok': True, 'animations': []}))
    texture = 'Characters/1029/1029001/Textures/T_Shared'
    maps = [dict(slot=slot, game_rel=path, role=role, url='/api/texture_png?game_rel='+path,
                 texture_class='Texture2D', custom=False) for slot, path, role in [
        ('BaseColor', texture, 'basecolor'), ('SpecularTexture', 'Textures/T_Specular', 'specular'),
        ('Normal', 'MyMod/T_PaintedNormal', 'normal'), ('DyeingTexture', 'Textures/T_ColorID', 'dye')]]
    maps[2].update(custom=True, url='/api/material_custom_texture/preview?game_rel=Materials/MI_Body&slot=Normal&v=custom')
    def materials(route):
        result = {}
        for model in route.request.post_data_json['meshes']:
            for slot in model['slots']:
                index = slot['material_index']
                result[slot['key']] = dict(game_rel=('Weapon/Materials/MI_Same' if index == 2 else 'Materials/'+slot['name']),
                    mesh_game_rel=model['game_rel'], slot_name=slot['name'], slot_index=index,
                    mapping_via='name' if index == 3 else 'imports', colors=[{'name':'BaseTint','rgba':[.1,.3,.65,1]}],
                    scalars=[], surface={'parent':'M_Character','blend':'BLEND_Opaque'},
                    textures={'BaseColor':texture}, texture_sources=maps if index == 0 else [dict(maps[0],game_rel='Other/Textures/T_Shared')] if index == 2 else [],
                    texture_roles={'basecolor':texture}, tex_ver={texture:'0'})
        route.fulfill(json={'ok':True,'materials':result})
    tab.route('**/api/skin_materials', materials)
    image_actions = []
    def import_texture(route):
        path = route.request.post_data_json['game_rel']
        image_actions.append(('prepare', path))
        route.fulfill(json={'ok':True, 'imported':{'game_rel':path, 'token':'assembly-texture',
                      'name':'T_Shared', 'file_type':'texture', 'selected':True}})
    def open_texture(route):
        path = parse_qs(urlsplit(route.request.url).query)['game_rel'][0]
        image_actions.append(('open', path))
        route.fulfill(json={'ok':True})
    tab.route('**/api/import_texture', import_texture)
    tab.route('**/api/open_with?*', open_texture)
    def save_material(route):
        material_saves.append(route.request.post_data_json)
        route.fulfill(json={'ok':True})
    tab.route('**/api/material_save', save_material)
    tab.route('**/api/material_params?*', lambda route: route.fulfill(json={'ok':True,'colors':[{'name':'BaseTint','rgba':[.1,.3,.65,1]}],'scalars':[],'textures':{'Normal':'Textures/T_Normal'},'texture_classes':{'Normal':'Texture2D'}}))
    tab.route('**/api/dye_info?*', lambda route: route.fulfill(json={'dyeable':False}))
    tab.route('**/api/mesh_add', lambda route: route.fulfill(json={'ok':True,'game_rel':MESH,'state':'original'}))
    def png(color):
        output = BytesIO(); Image.new('RGBA', (80,80),color).save(output,'PNG'); return output.getvalue()
    diffuse = png((45,103,163,255))
    tab.route('**/api/texture_png?*', lambda route: route.fulfill(body=diffuse,content_type='image/png'))
    tab.route('**/api/assembly_thumbnail?*', lambda route: (thumbnails.append(route.request.url),route.fulfill(body=png((132,115,207,255)) if 'slot=Normal' in route.request.url else diffuse,content_type='image/png')))
    tab.route('**/api/assembly_references', lambda route: (effects_reads.append(route.request.post_data_json),route.fulfill(json={'ok':True,'effects':[],'warnings':[],'scope':'Direct outgoing package references only; reverse VFX references are not indexed.'})))
    try:
        tab.goto(url); tab.wait_for_function('window.__assembly && window.atelierProject?.()')
        tab.wait_for_selector('#grid-area .card')
        tab.evaluate("localStorage.setItem('atelier.assembly','0')")
        open_mesh = "mesh=>AtelierViewport.openMesh(mesh,'Assembly verification · synthetic mannequin')"
        tab.evaluate(open_mesh, 'Meshes/SK_StandaloneFixture')
        tab.wait_for_selector('.assembly-section')
        assert tab.locator('#viewport-workspace-label').text_content() == 'Assembly View'
        tab.locator('#viewport-close').click()
        tab.evaluate(open_mesh, MESH)
        tab.wait_for_selector('.assembly-section')
        tab.wait_for_function("document.getElementById('viewport-canvas').getAttribute('aria-busy')==='false'")
        assert not thumbnails and not effects_reads, 'Opening Assembly must not extract every texture or effect'
        search = tab.get_by_role('searchbox', name='Find a surface or material')
        search.fill('Torso fixture')
        assert tab.locator('.assembly-section').count() == 1
        search.fill('')
        browse = tab.get_by_role('button', name='Browse materials')
        browse.click()
        tab.locator('#viewport-material-search').fill('Trim')
        assert tab.locator('.vp-material-select:visible').count() == 1
        tab.locator('#viewport-material-search').fill('')
        browse.click()
        checks.append('Standalone and costume meshes open directly in Assembly, with surface search and the grouped material browser')
        point = tab.evaluate('__assembly.point()'); tab.mouse.click(point['x'],point['y'])
        tab.wait_for_selector('.assembly-texture-card')
        assert tab.locator('.assembly-texture-card').count() == 4
        assert tab.evaluate('__assembly.state().surface') == 'Torso fixture'
        assert tab.locator('#assembly-material-context').inner_text().count('Materials/MI_Body') >= 1
        before = tab.evaluate('__assembly.state()')
        tab.get_by_role('button', name='Hide panels').click()
        assert tab.locator('#assembly-geometry').is_hidden() and tab.locator('#viewport-materials').is_hidden()
        assert tab.locator('#assembly-textures').is_hidden()
        tab.wait_for_function('width=>__assembly.state().canvas[2]>width',arg=before['canvas'][2])
        tab.get_by_role('button', name='Show panels').click()
        tab.wait_for_selector('.assembly-texture-card')
        after = tab.evaluate('__assembly.state()')
        assert before['surface'] == after['surface'] and before['decodes'] == after['decodes']
        assert all(abs(a-b)<1e-9 for a,b in zip(before['camera'],after['camera']))
        checks.append('Hiding and restoring panels gives the model more room and preserves the selected surface and camera')
        tab.locator('.assembly-texture-card').first.click()
        assert not image_actions
        assert tab.locator('.assembly-section.is-related').count() == 3, 'Torso and two arms share the exact material texture'
        assert not tab.locator('.assembly-section.is-related').filter(has_text='Same').count(), 'Same texture filename in another folder is unrelated'
        tab.wait_for_function("[...document.querySelectorAll('.assembly-texture-preview img')].some(img=>img.complete&&img.naturalWidth)")
        checks.append('Assembly raycasting selects the actual surface, exact material and four bound texture slots; same-named assets stay separate')
        assert not effects_reads
        tab.locator('#assembly-effects > summary').click(); tab.get_by_role('button', name='Inspect references', exact=True).click()
        tab.wait_for_selector('#assembly-effect-content p',state='visible')
        assert len(effects_reads) == 1
        tab.wait_for_function("document.getElementById('assembly-effect-content').textContent.includes('No direct VFX')")
        checks.append('Effects inspect references on demand and explain missing reverse references')
        before = tab.evaluate('__assembly.orbitAndOpen()')
        tab.wait_for_selector('#material-overlay.active')
        tab.locator('#mat-close').click()
        tab.wait_for_selector('#viewport-overlay.active')
        tab.wait_for_function("document.getElementById('viewport-canvas').getAttribute('aria-busy')==='false'")
        after = tab.evaluate('__assembly.state()')
        assert before['selected'] == after['selected'] and before['surface'] == after['surface']
        assert before['decodes'] == after['decodes']
        assert all(abs(a-b)<1e-9 for a,b in zip(before['camera'],after['camera'])), (before,after)
        checks.append('Full material editor round trip clears orbit inertia and preserves the selected mesh, camera and loaded geometry')
        # Custom resources route to their owning material slot in the same editor.
        tab.locator('.assembly-texture-card[data-slot="Normal"]').click()
        tab.get_by_role('button', name='Edit texture slot',exact=True).click()
        tab.wait_for_selector('#material-overlay.active'); tab.wait_for_selector('#mattex0')
        tab.locator('#mat-close').click(); tab.wait_for_selector('#viewport-overlay.active')
        tab.wait_for_function("document.getElementById('viewport-canvas').getAttribute('aria-busy')==='false'")
        tab.locator('.assembly-section').filter(has_text='Unknown').click()
        tab.wait_for_function("document.getElementById('assembly-material-context').textContent.includes('Reference unverified')")
        assert 'Reference unverified' in tab.locator('#assembly-material-context').inner_text()
        assert not tab.locator('.assembly-texture-card').count()
        assert tab.locator('#viewport-material-editor').is_hidden()
        assert 'Materials/MI_Unknown' in tab.locator('#assembly-material-context').inner_text()
        tab.get_by_role('button', name='Show colour controls').click()
        hex_colour = tab.locator('#viewport-material-editor .vp-hex').first
        hex_colour.fill('#2E69A4')
        hex_colour.press('Tab')
        tab.locator('#viewport-mat-save').click()
        tab.wait_for_function("document.getElementById('viewport-mat-save').disabled")
        assert [save['game_rel'] for save in material_saves] == ['Materials/MI_Unknown']
        assert not tab.locator('.assembly-texture-card').count()
        checks.append('Unverified references show the save target before exposing colour controls. Connected texture slots still require verified references')
        tab.locator('.assembly-section').filter(has_text='Body').first.click()
        tab.wait_for_selector('.assembly-texture-card')
        tab.get_by_role('button',name='Inspect UVs',exact=True).click()
        tab.wait_for_selector('#viewport-uv-content:not([hidden])')
        assert 'Torso fixture' in tab.locator('#viewport-uv-mesh').inner_text()
        tab.locator('#viewport-uv-toggle').click()
        before = tab.evaluate('__assembly.state()')
        tab.get_by_role('button',name='Replace model',exact=True).click()
        tab.wait_for_selector('#mesh-edit-overlay.active')
        tab.locator('#mesh-edit-overlay').get_by_role('button',name='Close',exact=True).click()
        tab.wait_for_selector('#viewport-overlay.active')
        after = tab.evaluate('__assembly.state()')
        assert before['camera'] == after['camera'] and before['decodes'] == after['decodes']
        tab.evaluate('__assembly.refresh()')
        tab.wait_for_function("document.getElementById('viewport-canvas').getAttribute('aria-busy')==='false'")
        after = tab.evaluate('__assembly.state()')
        assert before['selected'] == after['selected'] and after['decodes'] == before['decodes']+1
        assert all(abs(a-b)<1e-9 for a,b in zip(before['camera'],after['camera']))
        checks.append('UV inspection uses the selected primitive; replacement handoff retains the scene and changed geometry refreshes without moving the camera')
        tab.locator('#assembly-geometry-collapse').click()
        tab.set_viewport_size({'width':800,'height':768})
        tab.wait_for_function("document.getElementById('viewport-canvas').clientWidth > 300")
        assert tab.locator('#assembly-geometry-reopen').is_hidden()
        tab.set_viewport_size({'width':1600,'height':1000})
        assert tab.locator('#assembly-geometry-reopen').is_visible()
        tab.locator('#assembly-geometry-reopen').click()
        tab.locator('#assembly-textures-collapse').click(); assert tab.locator('#assembly-texture-cards').is_hidden()
        tab.locator('#assembly-textures-collapse').click()
        handle = tab.get_by_role('separator',name='Resize material panel'); handle.focus(); handle.press('ArrowLeft')
        assert int(handle.get_attribute('aria-valuenow')) > 292
        checks.append('Collapsed Geometry leaves the model visible when the window narrows, and panels resize from the keyboard')
        texture_card = tab.locator('.assembly-texture-card[data-slot="BaseColor"]')
        texture_card.click(button='right')
        with tab.expect_response('**/api/open_with?*'):
            tab.get_by_role('button',name='Open in default image app').click()
        assert image_actions == [('prepare',texture), ('open',texture)]
        tab.wait_for_function("document.querySelector('.assembly-texture-card[data-slot=BaseColor]').textContent.includes('In project')")
        checks.append('Assembly texture clicks select a slot. The context menu prepares the project image before opening it')
        tab.emulate_media(reduced_motion='reduce'); tab.locator('.assembly-section').first.click()
        assert not tab.locator('#assembly-links').is_visible()
        for theme in ('dark','light'):
            tab.evaluate('(theme)=>{localStorage.setItem("atelier.theme",theme);location.reload()}',theme)
            tab.wait_for_function('window.__assembly && window.atelierProject?.()')
            tab.evaluate("AtelierViewport.open('1029001','Assembly verification · synthetic mannequin')")
            tab.wait_for_selector('.assembly-section')
            tab.wait_for_function("document.getElementById('viewport-canvas').getAttribute('aria-busy')==='false'")
            assert tab.locator('#viewport-workspace-label').text_content() == 'Assembly View'
            tab.locator('.assembly-section').first.click(); tab.wait_for_selector('.assembly-texture-card')
            tab.screenshot(path=str(report/f'assembly-{theme}-1600.png'))
        tab.set_viewport_size({'width':1024,'height':768})
        tab.screenshot(path=str(report/'assembly-light-1024.png'))
        assert tab.locator('#viewport-box').evaluate('el=>el.scrollWidth<=el.clientWidth+2')
        assert tab.locator('#viewport-body').evaluate('el=>el.scrollWidth<=el.clientWidth+2')
        assert tab.locator('.assembly-geometry-actions button').evaluate_all('buttons=>buttons.every(button=>{const r=button.getBoundingClientRect(),panel=button.closest("#assembly-geometry-selection").getBoundingClientRect();return r.top>=panel.top&&r.bottom<=panel.bottom;})'), 'Compact geometry actions must remain visible'
        assert tab.locator('#assembly-geometry').evaluate('el=>el.getBoundingClientRect().width<190'), 'Compact panel widths must override theme defaults'
        tab.locator('#viewport-showcase').click()
        assert tab.locator('#viewport-stage').evaluate('el=>el.classList.contains("vp-showcase")')
        assert tab.locator('#viewport-uv-toggle').is_disabled()
        tab.locator('#viewport-showcase').click()
        assert tab.locator('#viewport-uv-toggle').is_enabled() and tab.locator('.assembly-section').first.is_visible()
        checks.append('Assembly supports light/dark and reduced motion, fits 1024px, and keeps the editing layout when toggling Showcase')
        assert not errors,errors
    except Exception:
        (report/'assembly-failure.json').write_text(json.dumps({'state':tab.evaluate('__assembly.state()'),'errors':errors},indent=2))
        tab.screenshot(path=str(report/'assembly-failure.png')); raise
    finally:
        tab.close()
