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
window.__polishViewport={
  revealFrames(){
    const original=performance.now,base=performance.now();
    try {
      // Capture real renders at fixed reveal positions; screenshot scheduling on
      // a software GPU can otherwise miss the entire 420ms transition.
      performance.now=()=>base;inspection.materialize();
      performance.now=()=>base+84;inspection.render();
      const wire=renderer.domElement.toDataURL('image/png');
      performance.now=()=>base+600;inspection.render();
      return {wire,shaded:renderer.domElement.toDataURL('image/png')};
    } finally {performance.now=original;}
  },
  state:()=>({filmic:renderer.toneMapping===THREE.ACESFilmicToneMapping,
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
        tab.emulate_media(reduced_motion='no-preference')
        tab.goto(url); tab.wait_for_selector('#grid-area .card'); tab.wait_for_function('window.AtelierPolish && window.AtelierContinuity')
        tab.bring_to_front()
        stored=tab.evaluate("Object.fromEntries(['motion','density','adaptiveAccent','theme','appearance','firstExportCelebrated'].map(key=>['atelier.'+key,localStorage.getItem('atelier.'+key)]))")
        assert not tab.locator('#startup-splash').count()
        tab.wait_for_selector('.roster-portrait'); tab.locator('.roster-portrait').click()
        assert tab.locator('.roster-skin').get_attribute('aria-label') == 'Fixture skin'
        checks.append('Home roster exposes catalogue heroes and their costumes without importing assets')
        tab.evaluate("pushNav({path:'Characters'})"); tab.wait_for_selector('.hero-portrait.loaded')
        assert tab.locator('.artwork-card').evaluate("""card=>{
          const art=card.querySelector('.card-thumb').getBoundingClientRect(), name=card.querySelector('.card-name').getBoundingClientRect();
          const style=getComputedStyle(card.querySelector('.card-name'));
          return art.height>art.width && name.top>=art.bottom && name.top-art.bottom<=8 &&
            name.height<=2*parseFloat(style.lineHeight)+1 && style.paddingTop==='0px' &&
            style.webkitLineClamp==='2' && getComputedStyle(card).padding==='0px';
        }""")
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
        assert tab.locator('#matsw0').evaluate("el=>el.style.boxShadow==='none' && el.style.opacity==='0.5' && el.parentElement.querySelector('.hdr-ring i')")
        tab.evaluate('matCompare("original"); matRestoreParameter("colors",0)')
        tab.wait_for_timeout(180)
        tab.evaluate('closeMaterialEditor(true)'); tab.wait_for_timeout(250)
        assert not tab.locator('#material-overlay').evaluate("el=>el.classList.contains('active')")
        assert not tab.locator('.polish-ghost').count()
        checks.append('Folder direction, portrait/banner and breadcrumb transitions clean up; editors return to their card; HDR/alpha swatches keep real values')
        tab.locator('#settings-motion').select_option('full',force=True)
        tab.evaluate("AtelierViewport.openMesh('Fixture/Body','Synthetic sphere')")
        tab.wait_for_function("document.getElementById('viewport-loading').style.display==='none' && document.getElementById('viewport-animation').options.length===2")
        tab.wait_for_timeout(600)
        state=tab.evaluate('__polishViewport.state()'); assert state['filmic'] and state['environment'],state
        tab.wait_for_function("document.getElementById('viewport-animation').value!=='' && document.getElementById('viewport-play').getAttribute('aria-pressed')==='true'")
        frames=tab.evaluate('__polishViewport.revealFrames()')
        assert frames['wire'].startswith('data:image/png;base64,')
        assert frames['wire']!=frames['shaded']
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
        # The toast leaves its slot on time; its 120 ms exit fade then removes the faded copy.
        assert not tab.locator('#toast-area .toast-repeat').count()
        tab.wait_for_function("!document.querySelector('.toast-repeat')", timeout=1000)
        checks.append('Operation resolves on the same mount with literal text; repeats merge, bump and reset their paused countdown line')

        full = tab.evaluate('!AtelierMotionPolicy.query().matches && !document.hidden')
        tab.evaluate("""() => { document.getElementById('toast-area').replaceChildren();
          window.leavingToast=toast('Exit fixture','info',5000); leavingToast.remove(); }""")
        assert not tab.locator('#toast-area .toast').count()
        if full:
            assert tab.evaluate("(layer=>layer.inert && layer.contains(leavingToast) && !leavingToast.hasAttribute('role'))(document.getElementById('toast-exit-layer'))")
        tab.wait_for_function('!leavingToast.isConnected', timeout=1000)
        # Typing that keeps a folder empty rebuilds the empty state without replaying its entrance.
        tab.locator('#search-scope').click()
        assert tab.evaluate('AtelierSearch.scope()') == 'folder'

        def empty_effects(text):
            tab.locator('#search-input').fill(text)
            tab.wait_for_selector('#empty-state [data-atelier-motion=empty-state][data-am-kind=none]')
            return tab.evaluate("document.querySelector('#empty-state [data-atelier-motion=empty-state]').getAnimations({subtree:true}).length")
        first, repeat = empty_effects('zzqx'), empty_effects('zzqxy')
        tab.locator('#search-input').fill('')
        tab.wait_for_function("!document.querySelector('#empty-state [data-am-kind=none]')")
        again = empty_effects('zzqx')
        assert repeat == 0 and (not full or (first > 0 and again > 0)), (first, repeat, again)
        tab.locator('#search-input').fill('')
        tab.locator('#search-scope').click()
        checks.append('A dismissed toast leaves its slot at once and fades from an inert layer; typing that keeps a folder empty does not replay its empty-state entrance')

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
        tab.evaluate('AtelierPolish.packing()')
        tab.wait_for_function("!document.querySelector('.k-workflow-link,.k-workflow-svg')")
        tab.evaluate("localStorage.removeItem('atelier.firstExportCelebrated'); AtelierPolish.exported()")
        assert tab.locator('svg.export-color-moment').count() == 1
        assert tab.evaluate("""() => {
          const button=document.getElementById('install-btn'),bounds=button.getBoundingClientRect(),svg=document.querySelector('svg.export-color-moment');
          const box=svg.getBoundingClientRect(),flow=svg.querySelector('.export-receipt-flow'),seal=svg.querySelector('.export-receipt-seal');
          if(Math.abs(box.left-bounds.left)>.1||Math.abs(box.top-bounds.top)>.1||box.width!==bounds.width||box.height!==bounds.height)return false;
          if(getComputedStyle(svg).overflow!=='hidden'||getComputedStyle(svg).pointerEvents!=='none')return false;
          const length=flow.getTotalLength(),start=flow.getPointAtLength(0),end=flow.getPointAtLength(length),receiver=seal.getBBox();
          const slot=button.querySelector('.am-export-feedback-slot').getBoundingClientRect();
          if(start.x<slot.left-bounds.left||start.x>slot.right-bounds.left||start.y<slot.top-bounds.top||start.y>slot.bottom-bounds.top)return false;
          if(end.x<receiver.x||end.x>receiver.x+receiver.width||end.y<receiver.y||end.y>receiver.y+receiver.height)return false;
          // The measured route remains inside the receiver, never a detached particle trip.
          for(let i=0;i<=80;i++){const point=flow.getPointAtLength(length*i/80);if(point.x<0||point.x>bounds.width||point.y<0||point.y>bounds.height)return false;}
          const mask=svg.querySelector('mask'),cutouts=[...mask.querySelectorAll('.export-receipt-content-cutout')];
          if(!cutouts.length||flow.parentElement.getAttribute('mask')!==`url(#${mask.id})`)return false;
          const walker=document.createTreeWalker(button,NodeFilter.SHOW_TEXT);
          while(walker.nextNode()){
            const text=walker.currentNode;if(!text.textContent.trim()||text.parentElement?.closest('.am-export-feedback-slot'))continue;
            const range=document.createRange();range.selectNodeContents(text);
            for(const label of range.getClientRects())if(!cutouts.some(cutout=>{const cut=cutout.getBBox();return cut.x<=label.left-bounds.left&&cut.y<=label.top-bounds.top&&cut.x+cut.width>=label.right-bounds.left&&cut.y+cut.height>=label.bottom-bounds.top;}))return false;
          }
          const stops=[...svg.querySelectorAll('linearGradient stop')];
          return stops.length>=2&&stops.length%2===0&&stops.every((stop,i)=>
            AtelierKrackleInks.contrast(stop.getAttribute('stop-color'),getComputedStyle(button).backgroundColor)>=3
            &&(i%2===0||stop.getAttribute('stop-color')===stops[i-1].getAttribute('stop-color')));
        }"""), 'Export flow must connect the glyph to its seal inside the button, mask the real label and preserve flat sampled inks'
        tab.wait_for_function("Number(document.querySelector('.export-receipt-seal')?.getAttribute('opacity'))>=.8")
        tab.locator('#install-btn').screenshot(path=str(report/'polish-export-ink-catch.png'))
        tab.wait_for_function("!document.querySelector('.export-color-moment')", timeout=2000)
        tab.evaluate('AtelierPolish.exported()'); assert not tab.locator('.export-color-moment').count()
        checks.append('Saved sidebar colors/curves, connected asset handoffs, row removal, rolling counts, real import outcomes and one-time mod-color export seal clean up')
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
        }""")
        tab.wait_for_timeout(50)
        assert tab.locator('html').get_attribute('data-density') == 'compact'
        theme_before = tab.evaluate("[getComputedStyle(document.documentElement).getPropertyValue('--acc'),getComputedStyle(document.querySelector('.btn.primary')).backgroundColor]")
        tab.evaluate("window.dispatchEvent(new StorageEvent('storage',{key:'atelier.adaptiveAccent',newValue:'1'}));window.dispatchEvent(new CustomEvent('atelier:artwork',{detail:{accent:'#ff0000',colors:['#ff0000']}}))")
        assert tab.evaluate("[getComputedStyle(document.documentElement).getPropertyValue('--acc'),getComputedStyle(document.querySelector('.btn.primary')).backgroundColor]") == theme_before
        checks.append('Artwork and legacy adaptive-accent preferences preserve theme colours on controls')
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
        tab.evaluate("pushNav({path:'Characters/1029/1029001/Textures'})")
        tab.wait_for_function("document.querySelector('#breadcrumbs .active')?.textContent==='Textures'")
        labels = tab.locator('#breadcrumbs .crumb-label').all_text_contents()
        assert labels == ['Characters', 'Fixture hero', 'Fixture skin', 'Textures'], labels
        assert tab.locator('#breadcrumbs .crumb-label').evaluate_all('(labels)=>labels.every(label=>label.scrollWidth<=label.clientWidth)'), labels
        assert tab.locator('#breadcrumbs').evaluate("el=>el.closest('.library-location') && !el.closest('#topbar')")
        checks.append('Breadcrumbs retain complete hero, costume and folder names in their own row at compact width')
        # Keyboard focus on the first folder must not capture another folder's hover popup.
        tab.evaluate("pushNav({path:''})")
        tab.wait_for_selector('#grid-area .card')
        tab.evaluate("""() => {
          const grid=document.querySelector('#grid-area .grid');
          const first=grid.querySelector('.card');first.title='First folder';
          const second=first.cloneNode(true);second.title='Second folder';second.querySelector('.card-name').textContent='Second folder';grid.append(second);
        }""")
        first, second = tab.locator('#grid-area .card').nth(0), tab.locator('#grid-area .card').nth(1)
        tab.mouse.move(1, 1)
        first.focus()
        tab.wait_for_timeout(450)
        assert tab.locator('#atelier-tooltip').is_hidden()
        tab.keyboard.press('Tab')
        first.focus()
        tab.wait_for_selector('#atelier-tooltip:visible')
        second.hover()
        tab.wait_for_function("document.querySelector('#atelier-tooltip:not([hidden])')?.textContent==='Second folder'")
        assert second.get_attribute('aria-describedby') == 'atelier-tooltip'
        assert 'atelier-tooltip' not in (first.get_attribute('aria-describedby') or '')
        bounds, popup = second.bounding_box(), tab.locator('#atelier-tooltip').bounding_box()
        assert abs(bounds['x']-popup['x']) < 2, (bounds,popup)
        tab.keyboard.press('Escape')
        assert second.get_attribute('title') == 'Second folder'
        checks.append('Folder hover popups follow the pointer even while the first card retains keyboard focus; titles and descriptions restore on dismissal')
        checks.append('Polished character library fits dark/light at 1024×768 and 1400×900 without horizontal overflow')
    finally:
        if stored is not None:
            tab.evaluate("saved=>{for(const [key,value] of Object.entries(saved)){if(value===null)localStorage.removeItem(key);else localStorage.setItem(key,value);}}",stored)
        tab.close()
