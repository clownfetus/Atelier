"""Presentation checks against real Chromium; artwork and game operations are explicit fixtures."""
from io import BytesIO
from PIL import Image, ImageDraw
from pathlib import Path
from design_checks import measure_contrast


def run_polish_checks(page, context, url, report, checks):
    tab = context.new_page()
    errors = []
    tab.on('pageerror', lambda error: errors.append(str(error)))
    viewport = (Path(__file__).resolve().parents[1] / 'gui/viewport.js').read_text(encoding='utf-8')
    viewport += """
window.__polishViewport={reveal:()=>inspection.materialize(),state:()=>({filmic:renderer.toneMapping===THREE.ACESFilmicToneMapping,
  environment:!!scene.environment?.isTexture,materials:Object.values(matsByName).flat().map(m=>({opacity:m.opacity,wireframe:m.wireframe,color:m.color.toArray()}))})};
loader.loadAsync=async()=>{const root=new THREE.Group(),material=new THREE.MeshStandardMaterial({color:0x85aedd});material.name='MI_Fixture';
  const mesh=new THREE.Mesh(new THREE.SphereGeometry(1,24,16),material);mesh.position.y=1;root.add(mesh);
  const bone=new THREE.Bone();bone.name='IdleBone';root.add(bone);return {scene:root,animations:[]};};
"""
    tab.route('**/static/viewport.js', lambda route: route.fulfill(body=viewport,content_type='text/javascript'))
    tab.route('**/api/skin_materials', lambda route: route.fulfill(json={'ok':True,'materials':{'MI_Fixture':{
        'game_rel':'Fixture/MI_Fixture','colors':[{'name':'Tint','rgba':[.3,.5,.8,1]}],'scalars':[],'textures':{}}}}))
    tab.route('**/api/browse_material_dirs?*', lambda route: route.fulfill(json={'dirs':[]}))
    tab.route('**/api/idle_animations?*', lambda route: route.fulfill(json={'ok':True,'animations':[{'label':'Fixture idle','game_rel':'Fixture/Idle'}]}))
    tab.route('**/api/idle_animation',lambda route:route.fulfill(json={'ok':True,'version':2,'space':'atelier-gltf-local',
        'name':'Fixture idle','duration':1,'tracks':[{'bone':'IdleBone','times':[0,1],'positions':[0,0,0,0,1,0]}]}))
    art = Image.new('RGB', (320, 240), '#203952')
    draw = ImageDraw.Draw(art); draw.polygon([(200, 5), (300, 60), (280, 240), (120, 240)], fill='#bc6639')
    output = BytesIO(); art.save(output, 'PNG')
    image = output.getvalue()
    stored = None
    tab.route('**/api/catalogue/thumbnail/*', lambda route: route.fulfill(body=image, content_type='image/png'))
    tab.route('**/api/catalogue/hero/*/story', lambda route: route.fulfill(body=image, content_type='image/png'))
    tab.route('**/api/catalogue/library', lambda route: route.fulfill(json={'heroes': [
        {'name': 'Fixture hero', 'path': 'Characters/1029', 'thumbnail': '/api/catalogue/thumbnail/1029',
         'skins': [{'name': 'Fixture skin', 'path': 'Characters/1029/1029001', 'thumbnail': '/api/catalogue/thumbnail/1029001'}]}]}))
    folders = {
        '': [dict(type='folder',name='Characters',label='Characters',rel_path='Characters')],
        'Characters': [dict(type='folder', name='1029', label='1029 — Fixture hero', rel_path='Characters/1029', thumbnail='/api/catalogue/thumbnail/1029')],
        'Characters/1029': [dict(type='folder', name='1029001', label='1029001 — Fixture skin', rel_path='Characters/1029/1029001', thumbnail='/api/catalogue/thumbnail/1029001')],
        'Characters/1029/1029001': [dict(type='file', file_type='material', name='MI_Fixture', game_rel='Fixture/MI_Fixture', rel_path='Fixture/MI_Fixture', imported=True)],
    }
    def browse(route):
        from urllib.parse import parse_qs, urlparse
        path = parse_qs(urlparse(route.request.url).query).get('path', [''])[0]
        route.fulfill(json=folders.get(path, []))
    tab.route('**/api/browse?*', browse)
    tab.route('**/api/material_params?*', lambda route: route.fulfill(json={'ok':True,
        'colors':[{'name':'Tint','rgba':[9,9,9,.5]}], 'scalars':[], 'original':{'colors':[{'name':'Tint','rgba':[.1,.3,.5,1]}],'scalars':[]}}))
    tab.route('**/api/dye_info?*', lambda route: route.fulfill(json={'dyeable':False}))
    tab.route('**/api/imported', lambda route: route.fulfill(json=[]))
    tab.route('**/api/jobs', lambda route: route.fulfill(json={'jobs':[]}))
    try:
        tab.goto(url); tab.wait_for_selector('#grid-area .card'); tab.wait_for_function('window.AtelierPolish && window.AtelierContinuity')
        stored=tab.evaluate("Object.fromEntries(['motion','density','adaptiveAccent','theme','appearance','firstExportCelebrated'].map(key=>['atelier.'+key,localStorage.getItem('atelier.'+key)]))")
        assert not tab.locator('#startup-splash').count()
        tab.wait_for_selector('.roster-portrait'); tab.locator('.roster-portrait').click()
        assert tab.locator('.roster-skin').get_attribute('aria-label') == 'Fixture skin'
        checks.append('Home roster exposes catalogue heroes and their costumes without importing assets')
        tab.evaluate("pushNav({path:'Characters'})"); tab.wait_for_selector('.hero-portrait.loaded')
        tab.locator('#grid-area .card').click(); tab.wait_for_selector('#library-hero.has-art')
        assert 'Fixture hero' in tab.locator('#library-hero h2').inner_text()
        assert tab.locator('html').get_attribute('data-library-direction') == 'forward'
        tab.wait_for_timeout(300)
        assert tab.evaluate("[...document.querySelectorAll('[style]')].every(n=>!n.style.viewTransitionName)")
        tab.locator('#btn-back').click(); tab.wait_for_selector('.hero-portrait.loaded')
        tab.wait_for_function("document.getElementById('grid-area').getAttribute('aria-busy')==='false' && nav.path==='Characters'")
        assert tab.locator('html').get_attribute('data-library-direction') == 'back'
        tab.wait_for_timeout(250)
        tab.evaluate("pushNav({path:'Characters/1029/1029001'})"); tab.wait_for_selector('#grid-area .card.imported')
        tab.wait_for_selector('#library-hero.has-art')
        assert tab.locator('.card-type-badge').count() == 1
        assert tab.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--skin-loader-accent').trim()!=='#accbff'")
        tab.locator('.studio-brand').click(); tab.wait_for_timeout(360)
        assert tab.locator('.studio-brand > [data-atelier-motion=logo-entrance]').count() <= 1
        tab.evaluate("openMaterialEditor({name:'Fixture material',game_rel:'Fixture/MI_Fixture'})")
        tab.wait_for_selector('#matsw0'); tab.wait_for_timeout(250)
        assert tab.locator('.library-heading h1,#material-overlay h2').evaluate_all("(nodes)=>nodes.every(node=>getComputedStyle(node).fontVariationSettings.includes('80') && getComputedStyle(node).fontWeight==='650')")
        assert tab.locator('#matsw0').evaluate("el=>el.style.boxShadow.includes('px') && el.style.opacity==='0.5'")
        tab.evaluate('matCompare("original"); matRestoreParameter("colors",0)')
        tab.wait_for_timeout(180)
        tab.evaluate('closeMaterialEditor(true)'); tab.wait_for_timeout(250)
        assert not tab.locator('#material-overlay').evaluate("el=>el.classList.contains('active')")
        assert not tab.locator('.polish-ghost').count()
        checks.append('Folder direction, portrait/banner and breadcrumb transitions clean up; editors return to their card; HDR/alpha swatches keep real values')
        tab.evaluate("AtelierViewport.openMesh('Fixture/Body','Synthetic sphere')")
        tab.wait_for_function("document.getElementById('viewport-loading').style.display==='none' && document.getElementById('viewport-animation').options.length===2")
        tab.wait_for_timeout(600)
        state=tab.evaluate('__polishViewport.state()'); assert state['filmic'] and state['environment'],state
        tab.wait_for_function("document.getElementById('viewport-animation').value!=='' && document.getElementById('viewport-play').getAttribute('aria-pressed')==='true'")
        tab.evaluate('__polishViewport.reveal()'); tab.wait_for_timeout(80)
        wire=tab.locator('#viewport-canvas').screenshot()
        tab.wait_for_timeout(550)
        shaded=tab.locator('#viewport-canvas').screenshot()
        assert wire!=shaded
        assert tab.evaluate('__polishViewport.state().materials')==state['materials']
        tab.evaluate('AtelierViewport.close()')
        checks.append('Filmic studio environment and wireframe-to-shaded reveal render real Three.js geometry without changing editable materials; discovered idle starts automatically')

        tab.evaluate("""() => {
          document.getElementById('toast-area').replaceChildren();
          window.operation=toastSpinner('Replacing…'); window.operationOriginal=operation;
          operation.resolve('<literal file>', 'success', 1200);
        }""")
        assert tab.evaluate('operation===operationOriginal && operation.isConnected')
        assert tab.locator('[data-operation-state=success]').inner_text() == '<literal file>'
        tab.evaluate("toast('Repeat fixture','info',1000);toast('Repeat fixture','info',1000);toast('Repeat fixture','info',1000)")
        assert tab.locator('.toast-repeat').inner_text() == '×3'
        assert tab.locator('.toast-timed').count() == 2
        tab.locator('.toast-repeat').hover(); tab.wait_for_timeout(1100)
        assert tab.locator('.toast-repeat').count() == 1
        assert tab.locator('.toast-repeat').evaluate("el=>getComputedStyle(el.parentElement,'::after').animationPlayState==='paused'")
        tab.mouse.move(0,0); tab.wait_for_timeout(1050)
        assert not tab.locator('.toast-repeat').count()
        checks.append('Operation resolves on the same mount with literal text; repeats merge, bump and reset their paused countdown line')

        tab.evaluate("""() => {
          sidebarData={m:{token:'m',game_rel:'Fixture/MI_Fixture',name:'Material fixture',file_type:'material',selected:true,ui_preview:{colors:[[.8,.1,.2,1],[.2,.4,.7,1]]}},
            c:{token:'c',game_rel:'Fixture/Curve',name:'Curve fixture',file_type:'curve',selected:true,ui_preview:{points:[[2,20],[20,5],[38,15]]}}}; renderSidebar();
          AtelierPolish.fly('Fixture/MI_Fixture');
        }""")
        assert tab.locator('.sb-color-mosaic').count() == 1
        assert tab.locator('.sb-sparkline').count() == 1
        assert tab.locator('#sel-count').inner_text() == '2'
        tab.evaluate("delete sidebarData.c;renderSidebar()")
        tab.wait_for_timeout(400)
        assert tab.locator('.sb-item').count() == 1 and not tab.locator('.polish-ghost').count()
        tab.evaluate("AtelierPolish.importStart([{name:'A',game_rel:'A'},{name:'B',game_rel:'B'}]);AtelierPolish.importProgress({game_rel:'A',ok:true});AtelierPolish.importProgress({game_rel:'B',ok:false})")
        assert tab.locator('#import-segments [data-state=done]').count() == 1
        assert tab.locator('#import-segments [data-state=failed]').count() == 1
        tab.evaluate("AtelierPolish.importProgress({done:true,results:[],error:'Cancelled after A'})")
        assert tab.locator('#import-segments [data-state=done]').count() == 1
        tab.evaluate("AtelierPolish.packing(); localStorage.removeItem('atelier.firstExportCelebrated'); AtelierPolish.exported()")
        assert tab.locator('.export-color-moment').count() > 0
        tab.wait_for_timeout(550)
        tab.evaluate('AtelierPolish.exported()'); assert not tab.locator('.export-color-moment').count()
        checks.append('Saved sidebar colors/curves, fly/packing snapshots, row removal, rolling counts, real import outcomes and one-time mod-color celebration clean up')
        jobs=[{'id':'polish-job','project':'Smoke A','kind':'fixture','label':'Fixture job','state':'running','stage':'Working','current':2,'total':4,'can_cancel':True}]
        tab.route('**/api/jobs',lambda route:route.fulfill(json={'jobs':jobs}))
        tab.evaluate('AtelierJobs.refresh()')
        assert tab.locator('.activity-ring').evaluate("el=>el.style.getPropertyValue('--job-progress')==='50%'")
        jobs[0]['total']=0;tab.evaluate('AtelierJobs.refresh()');assert tab.locator('.activity-ring.indeterminate').count()==1
        jobs[0]['state']='succeeded';tab.evaluate('AtelierJobs.refresh()');assert not tab.locator('.activity-ring').count()
        tab.locator('#grid-area .card').click(button='right')
        assert tab.locator('#ctx-menu').evaluate("el=>getComputedStyle(el).transformOrigin!=='50% 50%'")
        tab.keyboard.press('Escape')
        checks.append('Activity ring uses reported progress or an indeterminate running state and clears at completion; menu motion starts at its anchor')

        tab.evaluate("""() => {
          document.getElementById('settings-density').value='compact';document.getElementById('settings-density').dispatchEvent(new Event('change'));
          document.getElementById('settings-adaptive-accent').click();
        }""")
        tab.wait_for_timeout(50)
        assert tab.locator('html').get_attribute('data-density') == 'compact'
        for preset in ('contrast','blueprint','comic'):
            tab.evaluate('(preset)=>document.querySelector(`[data-theme-preset="${preset}"]`).click()',preset)
            assert tab.locator('html').get_attribute('data-palette') == preset
            assert all(pair['ratio']>=4.5 for pair in measure_contrast(tab)),preset
        tab.evaluate("""() => {
          const picker=document.getElementById('settings-motion');picker.value='off';picker.dispatchEvent(new Event('change'));
          AtelierPolish.play(document.getElementById('library-count'),[{opacity:0},{opacity:1}],160);
        }""")
        assert tab.evaluate("AtelierMotionPolicy.query().matches && document.getElementById('library-count').getAnimations().length===0")
        tab.reload();tab.wait_for_selector('#grid-area .card')
        assert tab.locator('html').get_attribute('data-density')=='compact'
        assert tab.evaluate('AtelierMotionPolicy.query().matches')
        assert tab.locator('html').get_attribute('data-palette')=='comic'
        tab.evaluate("document.startViewTransition=undefined;pushNav({path:'Characters'})")
        tab.wait_for_selector('.hero-portrait.loaded')
        tab.locator('#grid-area .card').click(); tab.wait_for_selector('#library-hero.has-art')
        checks.append('Compact density and extra palettes persist; forced reduced motion is static and navigation works without View Transitions')
        for theme in ('dark','light'):
            tab.evaluate("(theme)=>{const picker=document.getElementById('settings-theme');picker.value=theme;picker.dispatchEvent(new Event('change'));}",theme)
            for width,height in ((1024,768),(1400,900)):
                tab.set_viewport_size({'width':width,'height':height})
                tab.wait_for_timeout(80)
                assert tab.evaluate('document.documentElement.scrollWidth===innerWidth')
                tab.screenshot(path=str(report/f'polish-{theme}-{width}.png'))
        assert not errors, errors
        checks.append('Polished character library fits dark/light at 1024×768 and 1400×900 without horizontal overflow')
    finally:
        if stored is not None:
            tab.evaluate("saved=>{for(const [key,value] of Object.entries(saved)){if(value===null)localStorage.removeItem(key);else localStorage.setItem(key,value);}}",stored)
        tab.close()
