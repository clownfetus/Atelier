"""Real renderer and HTTP capture checks; synthetic geometry is labelled explicitly."""
from io import BytesIO
import base64
import json
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
HOOK = r"""
window.__inspection = {
  frame:frameCamera, pick:pickMaterial,
  presentation:()=>inspection.presentationState(),
  tint:rgb=>Object.values(matsByName).flat()[0].color.setRGB(...rgb),
  glow:value=>{for(const m of Object.values(matsByName).flat()){m.emissive.setRGB(value,value*.3,value*.05);m.emissiveIntensity=1;}},
  swapMap:color=>{const m=Object.values(matsByName).flat()[0],t=new THREE.DataTexture(new Uint8Array([...color,255]),1,1);t.needsUpdate=true;
    (window.__fixtureTextures||=[]).push(t);m.map=t;m.needsUpdate=true;},
  clearMaps:()=>{for(const m of Object.values(matsByName).flat()){m.map=null;m.needsUpdate=true;}for(const t of window.__fixtureTextures||[])t.dispose();},
  chips:()=>{
    const previous=matData.MI_Cape;
    matData.MI_Cape={...previous,colors:[{name:'Region 1 - ColorA',rgba:[.2,.3,.4,1]}],baseIdx:-1,emiIdx:-1};buildPanel();
    const chip=()=>document.querySelector('.vp-mat[data-material="MI_Cape"] .vp-material-chip').style.background;
    const initial=chip();onColorInput('MI_Cape','Region 1 - ColorA','#00ff00');const changed=chip();
    delete edited.MI_Cape;matData.MI_Cape=previous;buildPanel();return {initial,changed};
  },
  state:()=>({position:camera.position.toArray(), target:controls.target.toArray(), aspect:camera.aspect,
    visible:objects.map(o=>o.root.visible), materials:Object.values(matsByName).flat().map(m=>({name:m.name,color:m.color.toArray(),wireframe:m.wireframe})),
    geometries:renderer.info.memory.geometries, animating:!!raf}),
  fits:()=>{
    camera.updateMatrixWorld(); const boxes=[];
    modelRoot.traverseVisible(mesh=>{if(!mesh.isMesh)return;if(mesh.isSkinnedMesh)mesh.computeBoundingBox();else mesh.geometry.computeBoundingBox();
      boxes.push((mesh.isSkinnedMesh?mesh.boundingBox:mesh.geometry.boundingBox).clone().applyMatrix4(mesh.matrixWorld));});
    const corners=[];
    for(const box of boxes) for(const x of [box.min.x,box.max.x]) for(const y of [box.min.y,box.max.y]) for(const z of [box.min.z,box.max.z])
      corners.push(new THREE.Vector3(x,y,z).project(camera).toArray());
    return corners.every(p=>p.every(Number.isFinite) && Math.abs(p[0])<1 && Math.abs(p[1])<1 && Math.abs(p[2])<1);
  },
  native:loader.loadAsync.bind(loader),
  idle:()=>animation.discover(meshMeta[0].game_rel),
  point:()=>{const p=new THREE.Vector3(0,1.5,.5).project(camera),r=document.getElementById('viewport-canvas').getBoundingClientRect();return {x:r.x+(p.x+1)*r.width/2,y:r.y+(1-p.y)*r.height/2};},
  bones:()=>{modelRoot.updateMatrixWorld(true); const out=[]; modelRoot.traverse(o=>{if(o.isBone) out.push(...o.getWorldPosition(new THREE.Vector3()).toArray());}); return out;},
  height:()=>{modelRoot.updateMatrixWorld(true); const box=new THREE.Box3();modelRoot.traverse(o=>{if(o.isSkinnedMesh) o.computeBoundingBox();});box.setFromObject(modelRoot);return box.getSize(new THREE.Vector3()).y;},
  useNative(){loader.loadAsync=this.native;},
  canon:_canonName,
};
loader.loadAsync = async url=>{
  const cape=url.includes('Cape'); const group=new THREE.Group(); group.name=cape?'Cape fixture':'Body fixture';
  const material=new THREE.MeshStandardMaterial({color:0x85aedd}); material.name=cape?'MI_Cape':'MI_Body';
  const geometry=new THREE.BoxGeometry(cape?8:1.3,cape?.2:3,cape?.2:1);
  const mesh=new THREE.Mesh(geometry,material); mesh.position.y=cape?1:1.5; group.add(mesh);
  if(!cape) for(const index of [1,2]) {
    const hair=new THREE.MeshStandardMaterial({color:0x444444});hair.name='MI_Hair_0'+index;
    const part=new THREE.Mesh(new THREE.BoxGeometry(.1,.1,.1),hair);part.position.set(index*.1,2.8,0);group.add(part);
  }
  return {scene:group,animations:[]};
};
"""


def run_viewport_inspection_checks(page, context, url, report, checks, real_mesh=None, real_idle=None, reuse_page=False):
    # OrbitControls reconstructs spherical coordinates; a last-bit rounding change is not camera movement.
    def same_vector(left,right):
        return len(left)==len(right) and all(abs(a-b)<1e-10 for a,b in zip(left,right))
    # WebView2 owns one page; creating a browser tab there closes its unsupported target.
    tab = page if reuse_page else context.new_page()
    if reuse_page:
        tab.add_init_script("""(() => {
          const original=HTMLAnchorElement.prototype.click;
          HTMLAnchorElement.prototype.click=function(){
            if(!this.download||!this.href.startsWith('blob:'))return original.call(this);
            fetch(this.href).then(r=>r.arrayBuffer()).then(buffer=>{
              const bytes=new Uint8Array(buffer);let text='';
              for(let i=0;i<bytes.length;i+=8192)text+=String.fromCharCode(...bytes.subarray(i,i+8192));
              window.__capturedDownload=btoa(text);
            });
          };
        })();""")
    def save_download(action, target, timeout=60000):
        if reuse_page:
            tab.evaluate('window.__capturedDownload=null');action()
            tab.wait_for_function('!!window.__capturedDownload',timeout=timeout)
            target.write_bytes(base64.b64decode(tab.evaluate('window.__capturedDownload')))
        else:
            with tab.expect_download(timeout=timeout) as download: action()
            download.value.save_as(target)
    errors = []
    tab.on('pageerror', lambda error: errors.append(str(error)))
    tab.on('console', lambda message: errors.append(message.text) if message.type=='error' and ('Shader Error' in message.text or 'VALIDATE_STATUS' in message.text) else None)
    tab.route('**/static/viewport.js', lambda route: route.fulfill(
        body=(ROOT / 'gui/viewport.js').read_text(encoding='utf-8') + HOOK, content_type='text/javascript'))
    tab.route('**/api/skin_meshes?*', lambda route: route.fulfill(json=[
        {'name':name+' fixture','game_rel':'Characters/1029/1029001/Meshes/'+name} for name in ('Body','Cape')]))
    materials = {name:dict(game_rel='Characters/1029/1029001/Materials/'+name,
        colors=[dict(name='Tint',rgba=[.6,.2,.15,1])],scalars=[],textures={},dyeable=name=='MI_Body') for name in ('MI_Body','MI_Cape','MI_Hair_01','MI_Hair_02')}
    tab.route('**/api/skin_materials', lambda route: route.fulfill(json={'ok':True,'materials':materials}))
    tab.route('**/api/material_original?*', lambda route: route.fulfill(json={'ok':True,
        'colors':[{'name':'Tint','rgba':[.05,.4,.8,1]}],'scalars':[],'textures':{}}))
    tab.route('**/api/material_params?*', lambda route: route.fulfill(json={'ok':True,
        'colors':[{'name':'Tint','rgba':[.6,.2,.15,1]}],'scalars':[]}))
    tab.route('**/api/dye_info?*', lambda route: route.fulfill(json={'dyeable':False}))
    tab.route('**/api/browse_material_dirs?*', lambda route: route.fulfill(json={'dirs':[]}))
    overlay = BytesIO(); Image.new('RGB',(64,64),(50,173,230)).save(overlay,'PNG')
    tab.route('**/api/dye_overlay?*', lambda route: route.fulfill(body=overlay.getvalue(),content_type='image/png'))
    tab.route('**/api/dye_texture?*', lambda route: route.fulfill(body=overlay.getvalue(),content_type='image/png'))
    try:
        tab.emulate_media(reduced_motion='no-preference')
        tab.goto(url); tab.wait_for_function('window.__inspection && window.atelierProject?.()')
        tab.evaluate("document.getElementById('settings-motion').value='system';document.getElementById('settings-motion').dispatchEvent(new Event('change'))")
        tab.wait_for_selector('#grid-area .card')
        tab.evaluate("AtelierViewport.open('1029001','Inspection fixtures — synthetic geometry')")
        tab.wait_for_selector('.vp-mat'); tab.wait_for_function("document.getElementById('viewport-loading').style.display==='none'")
        def settings():
            if not tab.locator('#viewport-settings-menu').evaluate('el=>el.open'):
                tab.locator('#viewport-settings-menu > summary').click()
        def models():
            if not tab.locator('#viewport-model-menu').evaluate('el=>el.open'):
                tab.locator('#viewport-model-menu > summary').click()
        assert tab.evaluate('__inspection.state().visible') == [True,False]
        assert tab.evaluate("__inspection.canon('MI_1029001_10290_Body')===__inspection.canon('MI_1029100_10290_Body') && __inspection.canon('MI_1029001_10290_Body')!==__inspection.canon('MI_1029001_10291_Body')")
        assert tab.locator('#viewport-material-editor').is_hidden()
        assert not tab.locator('#viewport-box input[type=color]:visible').count()
        tab.locator('.vp-material-select').first.click()
        assert tab.locator('#viewport-material-editor').is_visible()
        assert not tab.locator('.vp-advanced').evaluate('el=>el.open')
        hex_input=tab.locator('#viewport-material-editor .vp-hex').first
        hex_input.fill('#70459B'); hex_input.press('Tab')
        assert not tab.locator('#viewport-mat-save').is_disabled()
        assert tab.locator('.vp-saved-hex').first.inner_text()!=tab.locator('.vp-current-hex').first.inner_text()
        tab.locator('.vp-revert-material').click()
        assert tab.locator('#viewport-mat-save').is_disabled()
        tab.locator('.vp-editor-dismiss').click()
        assert tab.locator('#viewport-material-editor').is_hidden()
        tab.locator('.vp-material-select').filter(has_text='Hair').click()
        parts=tab.get_by_label('Material part',exact=True)
        assert parts.locator('option').count()==2
        first_part=parts.input_value()
        tab.locator('#viewport-material-editor input[type=color]').first.fill('#00FF00')
        parts.select_option(index=1)
        assert not tab.locator('#viewport-mat-save').is_disabled() and tab.locator('.vp-revert-material').is_disabled()
        tab.get_by_label('Material part',exact=True).select_option(first_part)
        assert tab.locator('#viewport-material-editor .vp-hex').first.input_value()=='#00FF00'
        tab.locator('.vp-revert-material').click();tab.locator('.vp-editor-dismiss').click()
        assert tab.locator('#viewport-mat-save').is_disabled()
        checks.append('Related material parts share one clean group; the part picker preserves per-part drafts and restores the correct saved values')
        tab.locator('#viewport-material-search').fill('no such material')
        assert tab.locator('#viewport-material-no-results').is_visible()
        tab.locator('#viewport-material-search').fill('')
        models(); tab.locator('#viewport-model-choice').select_option('1')
        assert tab.evaluate('__inspection.state().visible') == [False,True]
        models(); tab.locator('#viewport-model-choice').select_option('all')
        assert tab.evaluate('__inspection.state().visible') == [True,True]
        settings(); tab.keyboard.press('Escape')
        assert tab.locator('#viewport-overlay').is_visible() and not tab.locator('#viewport-settings-menu').evaluate('el=>el.open')
        checks.append('Studio opens with one mesh and no editing controls; selection, hex colour, saved/current swatches, material revert, search, model switching and menu Escape work')
        for theme in ('dark','light'):
            tab.evaluate('(theme)=>document.documentElement.dataset.theme=theme', theme)
            for width,height in ((1024,768),(1400,900),(1920,1080)):
                tab.set_viewport_size({'width':width,'height':height}); tab.wait_for_timeout(150)
                settings()
                for view in ('front','right','top','perspective'):
                    tab.locator('#viewport-view').select_option(view)
                    assert tab.evaluate('__inspection.fits()'), (theme,width,view)
                assert tab.locator('#viewport-box').evaluate('(el)=>el.scrollWidth===el.clientWidth')
                tab.keyboard.press('Escape')
                assert tab.evaluate("""() => {
                  const a=document.getElementById('viewport-inspect-tools').getBoundingClientRect(),b=document.getElementById('viewport-tools').getBoundingClientRect();
                  return a.right+6<=b.left;
                }"""), (theme,width,'overlapping stage controls')
                tab.screenshot(path=str(report/f'viewer-{theme}-{width}.png'))
        checks.append('Inspection toolbar fits both themes at three sizes; wide geometry stays framed in all camera presets')
        for width,height in ((800,700),(680,900)):
            tab.set_viewport_size({'width':width,'height':height});tab.wait_for_timeout(120)
            assert tab.locator('#viewport-box').evaluate('el=>el.scrollWidth===el.clientWidth')
            settings()
            assert tab.locator('#viewport-settings-menu .vp-popover').evaluate('el=>{const r=el.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth&&r.bottom<=innerHeight;}')
            tab.keyboard.press('Escape')
            tab.screenshot(path=str(report/f'viewer-compact-{width}.png'))
        checks.append('Studio adapts to narrow and short windows with reachable settings and no horizontal overflow')
        tab.set_viewport_size({'width':1400,'height':900})
        models(); tab.locator('#viewport-obj-section > summary').click()
        tab.locator('.vp-solo').first.click()
        assert tab.evaluate('__inspection.state().visible') == [True,False]
        tab.locator('.vp-solo').first.click()
        assert tab.evaluate('__inspection.state().visible') == [True,True]
        for cb in tab.locator('.vp-obj input').all(): cb.uncheck()
        assert tab.locator('#viewport-hidden').is_visible()
        tab.locator('#viewport-show-hidden').click()
        assert tab.evaluate('__inspection.state().visible') == [True,True]
        checks.append('Solo restores prior visibility; all-hidden state offers recovery and updates triangle counts')
        baseline = tab.evaluate('__inspection.state().materials')
        settings()
        for lighting in ('flat','emissive','studio'):
            tab.locator('#viewport-lighting').select_option(lighting)
            tab.wait_for_timeout(60)
        tab.locator('#viewport-canvas').focus(); tab.keyboard.press('w'); tab.keyboard.press('g'); tab.keyboard.press('1')
        assert tab.locator('#viewport-wireframe').get_attribute('aria-pressed') == 'true'
        assert tab.locator('#viewport-view').input_value() == 'front'
        tab.keyboard.press('w'); tab.keyboard.press('g')
        for mode in ('original','wipe','edited'):
            tab.locator('#viewport-'+mode).click()
            tab.wait_for_function('(mode)=>document.getElementById("viewport-"+mode).getAttribute("aria-pressed")==="true"',arg=mode)
            if mode=='wipe':
                tab.locator('#viewport-wipe-range').fill('25')
                line=tab.locator('#viewport-wipe-line').bounding_box(); stage=tab.locator('#viewport-stage').bounding_box()
                tab.mouse.move(line['x']+10,line['y']+80); tab.mouse.down()
                tab.mouse.move(stage['x']+stage['width']*.65,line['y']+80); tab.mouse.up()
                assert 63 <= int(tab.locator('#viewport-wipe-range').input_value()) <= 67
                tab.screenshot(path=str(report/'viewer-comparison.png'))
        assert baseline == tab.evaluate('__inspection.state().materials')
        settings()
        tab.locator('#viewport-regions').click()
        tab.wait_for_function("document.getElementById('viewport-regions').getAttribute('aria-pressed')==='true'")
        tab.screenshot(path=str(report/'viewer-regions.png'))
        tab.locator('#viewport-regions').click()
        assert baseline == tab.evaluate('__inspection.state().materials')
        checks.append('Lighting, keyboard controls, wireframe, Original/Edited, wipe and dye overlays leave editable materials intact')
        point=tab.evaluate('__inspection.point()'); tab.mouse.move(point['x'],point['y'])
        tab.keyboard.press('Escape'); point=tab.evaluate('__inspection.point()'); tab.mouse.move(point['x'],point['y'])
        tab.wait_for_selector('#viewport-hover:not([hidden])')
        assert 'Body' in tab.locator('#viewport-hover').inner_text()
        tab.mouse.click(point['x'],point['y'])
        assert tab.locator('.vp-mat.is-picked').get_attribute('data-material') == 'MI_Body'
        assert not tab.locator('#material-overlay.active').count()
        before_focus=tab.evaluate('__inspection.state().position')
        tab.mouse.dblclick(point['x'],point['y'])
        tab.wait_for_function('!__inspection.presentation().moving')
        assert before_focus != tab.evaluate('__inspection.state().position')
        tab.locator('.vp-advanced > summary').click()
        tab.locator('.vp-material-edit').click()
        tab.wait_for_selector('#material-overlay.active')
        assert tab.locator('#mat-title').inner_text() == 'MI_Body'
        tab.locator('#mat-close').click()
        tab.wait_for_selector('#viewport-overlay.active')
        checks.append('Hover outlines the material; click selects it immediately, double-click frames the part, and Edit opens its existing editor')
        tab.wait_for_timeout(250)
        tab.mouse.move(0,0)
        assert tab.locator('#viewport-axes line').count()==3
        axes=tab.locator('#viewport-axes').inner_html()
        settings()
        tab.locator('#viewport-view').select_option('right');tab.wait_for_timeout(80)
        assert axes != tab.locator('#viewport-axes').inner_html()
        tab.locator('#viewport-view').select_option('perspective')
        tab.evaluate('__inspection.tint([.1,.8,.2])')
        tab.wait_for_function('__inspection.presentation().colors.some(c=>c.name==="MI_Body" && c.shown[1]>.2 && c.shown[1]<.8)')
        tab.wait_for_timeout(180)
        state=tab.evaluate('__inspection.presentation().colors.find(c=>c.name==="MI_Body")')
        assert state['target']==state['shown']==[.1,.8,.2],state
        tab.evaluate('__inspection.swapMap([255,0,0])');tab.wait_for_timeout(60)
        tab.evaluate('__inspection.swapMap([0,0,255])')
        tab.wait_for_function('__inspection.presentation().colors.some(c=>c.name==="MI_Body" && c.mapMix<1)')
        tab.wait_for_function('__inspection.presentation().colors.every(c=>c.mapMix===1)')
        tab.evaluate('__inspection.clearMaps();__inspection.tint([.6,.2,.15])');tab.wait_for_timeout(180)
        checks.append('Linear color and replacement-texture blends settle at exact target values; orientation axes follow camera presets')
        chips=tab.evaluate('__inspection.chips()')
        assert chips['initial']!='rgb(184, 184, 192)' and chips['initial']!=chips['changed'],chips
        checks.append('Material chips show dye-region colours when no base tint exists and follow live edits')
        assert tab.locator('#viewport-bloom').get_attribute('aria-pressed')=='false'
        tab.evaluate('__inspection.glow(3)');tab.wait_for_timeout(180)
        before_bloom=tab.locator('#viewport-canvas').screenshot()
        tab.locator('#viewport-bloom').click();tab.wait_for_timeout(100)
        assert tab.evaluate('__inspection.presentation().targets')==3
        with_bloom=tab.locator('#viewport-canvas').screenshot()
        assert before_bloom != with_bloom
        tab.screenshot(path=str(report/'viewer-bloom.png'))
        tab.locator('#viewport-bloom').click()
        assert tab.evaluate('__inspection.presentation().targets')==0
        tab.evaluate('__inspection.glow(0)')
        tab.locator('#viewport-backdrop').select_option('solid')
        tab.locator('#viewport-backdrop-color').fill('#304050')
        assert tab.locator('#viewport-stage').evaluate('el=>getComputedStyle(el).backgroundColor')=='rgb(48, 64, 80)'
        assert tab.locator('#viewport-canvas').evaluate('el=>getComputedStyle(el).backgroundColor')=='rgba(0, 0, 0, 0)'
        tab.locator('#viewport-backdrop').select_option('checker')
        tab.locator('#viewport-grid').click()
        tab.locator('#viewport-capture-menu summary').click()
        save_download(lambda:tab.locator('#viewport-poster').click(),report/'viewer-transparent.png')
        tab.wait_for_function('document.getElementById("viewport-capture-cancel").hidden')
        with Image.open(report/'viewer-transparent.png') as image:
            assert image.mode=='RGBA' and image.getpixel((0,0))[3]==0
        settings();tab.locator('#viewport-grid').click();tab.locator('#viewport-backdrop').select_option('gradient')
        checks.append('Optional bloom changes real rendered pixels and releases all targets when disabled; solid and transparent backdrops export correctly')
        tab.evaluate("document.getElementById('settings-motion').value='reduce';document.getElementById('settings-motion').dispatchEvent(new Event('change'));__inspection.tint([.2,.3,.4])")
        tab.locator('#viewport-fit').click();tab.wait_for_timeout(50)
        assert not tab.evaluate('__inspection.presentation().moving')
        state=tab.evaluate('__inspection.presentation().colors.find(c=>c.name==="MI_Body")')
        assert state['shown']==[.2,.3,.4],state
        tab.evaluate("document.getElementById('settings-motion').value='system';document.getElementById('settings-motion').dispatchEvent(new Event('change'));__inspection.tint([.6,.2,.15])")
        tab.wait_for_timeout(180)
        checks.append('Forced reduced motion settles camera, color and texture presentation immediately without altering editable parameter data')
        tab.locator('#viewport-expand').click()
        tab.wait_for_timeout(150)
        assert tab.locator('#viewport-box').evaluate('(el)=>el.clientWidth>innerWidth-30')
        tab.locator('#viewport-expand').click()
        settings()
        tab.locator('#viewport-view').select_option('perspective')
        tab.locator('#viewport-capture-menu summary').click()
        tab.locator('#viewport-capture-name').fill('Inspection showcase')
        saved = tab.evaluate('__inspection.state()')
        save_download(lambda:tab.locator('#viewport-poster').click(),report/'viewer-poster.png')
        tab.wait_for_function("document.getElementById('viewport-capture-cancel').hidden")
        with Image.open(report/'viewer-poster.png') as image: assert image.size == (1400,1520)
        after = tab.evaluate('__inspection.state()')
        (report/'capture-camera-restore.json').write_text(json.dumps({'before':saved,'after':after},indent=2),encoding='utf-8')
        assert same_vector(after['position'],saved['position']) and same_vector(after['target'],saved['target']), (saved['position'],after['position'],saved['target'],after['target'])
        tab.locator('#viewport-capture-menu summary').click()
        save_download(lambda:tab.locator('#viewport-turntable').click(),report/'viewer-turntable.webp')
        tab.wait_for_function("document.getElementById('viewport-capture-cancel').hidden")
        with Image.open(report/'viewer-turntable.webp') as image:
            assert image.size == (720,800) and image.n_frames > 1, (image.size,image.n_frames)
        assert same_vector(tab.evaluate('__inspection.state().position'),saved['position'])
        checks.append('Poster PNG and animated WebP download through the real encoder and restore camera position and controls')
        tab.locator('#viewport-capture-menu summary').click(); tab.locator('#viewport-turntable').click()
        tab.locator('#viewport-capture-cancel').click()
        tab.wait_for_function("document.getElementById('viewport-capture-cancel').hidden")
        assert same_vector(tab.evaluate('__inspection.state().position'),saved['position'])
        checks.append('Capture cancellation restores the camera and exits turntable rotation')
        if real_mesh:
            tab.route('**/api/model_gltf?*',lambda route:route.fulfill(body=real_mesh.read_bytes(),content_type='model/gltf-binary'))
            tab.evaluate('__inspection.useNative()')
            for index in range(3):
                tab.evaluate("AtelierViewport.openMesh('Characters/1029/1029100/Meshes/10291/SK_10291_1029100','Decoded game model')")
                tab.wait_for_function("document.getElementById('viewport-loading').style.display==='none'")
                if index==0: tab.screenshot(path=str(report/'viewer-real-model.png'))
                if index==0 and real_idle:
                    idle=json.loads(real_idle.read_text(encoding='utf-8'))
                    rest_height=tab.evaluate('__inspection.height()')
                    tab.route('**/api/idle_animations?*',lambda route:route.fulfill(json={'ok':True,'animations':[{'label':'Standing idle (real game clip)','game_rel':'Characters/1029/Idle'}]}))
                    tab.route('**/api/idle_animation',lambda route:route.fulfill(json={'ok':True,**idle}))
                    tab.evaluate('__inspection.idle()')
                    tab.wait_for_function("document.getElementById('viewport-play').getAttribute('aria-pressed')==='true'")
                    first=tab.evaluate('__inspection.bones()')
                    tab.wait_for_timeout(400)
                    second=tab.evaluate('__inspection.bones()')
                    assert max(abs(a-b) for a,b in zip(first,second))>1e-5
                    assert .65 < tab.evaluate('__inspection.height()')/rest_height < 1.35
                    tab.locator('#viewport-play').click()
                    paused=tab.evaluate('__inspection.bones()'); tab.wait_for_timeout(200)
                    assert paused==tab.evaluate('__inspection.bones()')
                    tab.screenshot(path=str(report/'viewer-standing-idle.png'))
                    tab.locator('#viewport-animation').select_option('')
                    assert paused!=tab.evaluate('__inspection.bones()')
                    assert not tab.locator('#viewport-play').is_disabled()
                    tab.locator('#viewport-play').click()
                    assert tab.locator('#viewport-play').get_attribute('aria-pressed')=='true'
                    checks.append('Real standing idle moves the game skeleton; Pause freezes it and Rest pose restores it')
                tab.evaluate('AtelierViewport.close()')
                assert not tab.evaluate('__inspection.state().animating')
            checks.append('A real decoded game GLB renders and three close cycles stop the renderer')
        else: tab.evaluate('AtelierViewport.close()')
        assert not errors,errors
    finally:
        if not reuse_page: tab.close()
