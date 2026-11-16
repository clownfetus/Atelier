"""The extra motion placements: real controls with held, explicitly simulated job results."""
from io import BytesIO
from time import monotonic
from urllib.parse import urlsplit

from PIL import Image, ImageDraw

# Requests the editor checks hold open, so the glyph beside each control can be seen while it runs.
EDITOR_HOLDS = ('material_custom_texture', 'material_replace', 'material_reset', 'dye_download',
                'mat_textures_download', 'curve_reset', 'vfx_reset', 'world_reset', 'text_reset', 'asset_opts')


def run_motion_placements_checks(context, url, report, checks):
    tab = context.new_page()
    errors = []
    tab.on('pageerror', lambda error: errors.append(str(error)))
    image = Image.new('RGB', (320, 240), '#172331')
    draw = ImageDraw.Draw(image)
    draw.rectangle((36, 36, 144, 144), fill='#4F80CC')
    draw.rectangle((168, 72, 276, 180), fill='#45AB91')
    draw.ellipse((88, 140, 164, 216), fill='#EB9A72')
    output = BytesIO(); image.save(output, format='PNG')
    tab.route('**/motion-image.png*', lambda route: route.fulfill(body=output.getvalue(), content_type='image/png'))
    tab.route('**/api/imported', lambda route: route.fulfill(json=[]))
    tab.route('**/api/jobs', lambda route: route.fulfill(json={'jobs': []}))
    stored = None
    try:
        tab.goto(url)
        tab.wait_for_function("window.AtelierAddAsset && window.AtelierLibraryPins && window.atelierProject?.() && !document.querySelector('.overlay.active')")
        tab.bring_to_front()
        stored = tab.evaluate("Object.fromEntries(['atelier.motion','atelier.homePins.v1'].map(key=>[key,localStorage.getItem(key)]))")
        tab.evaluate("""() => {
          window.__effects=[];
          const animate=Element.prototype.animate;
          Element.prototype.animate=function(...args){
            const result=animate.apply(this,args);
            if(this.matches('#library-preview img,.workspace-slot,.workspace-slot *, .library-pin-chip,.library-pin-chip *, #library-hero .image-swap, #viewport-skin-card .image-swap'))
              __effects.push({el:this,animation:result,frames:result.effect.getKeyframes(),duration:result.effect.getTiming().duration,src:this.getAttribute('src'),
                box:this.matches('.image-swap')?[this,this.parentElement.querySelector(':scope > img:not(.image-swap)')].map(node=>{const r=node.getBoundingClientRect();return [r.left,r.top,r.width,r.height];}):null});
            if(window.__holdSwap&&this.matches('.image-swap')){result.pause();result.currentTime=__holdSwap;}
            return result;
          };
          AtelierJobs.run=(path,options)=>new Promise(resolve=>window.__job={path,options,resolve});
          window.__mode=value=>{const control=document.getElementById('settings-motion');control.value=value;control.dispatchEvent(new Event('change'));};
          window.__finish=async result=>{__job.resolve(result);await new Promise(resolve=>setTimeout(resolve,0));};
          window.__settle=async()=>{
            const animations=document.getAnimations();animations.forEach(a=>{if(a.effect.getTiming().iterations!==Infinity)a.finish();});
            await Promise.allSettled(animations.filter(a=>a.effect.getTiming().iterations!==Infinity).map(a=>a.finished));
          };
        }""")

        for mode in ('full', 'calm', 'off'):
            tab.evaluate('__mode', mode)
            for kind in ('texture', 'mesh', 'material'):
                tab.evaluate("""kind=>{
                  AtelierAddAsset.open();
                  const type=document.getElementById('add-asset-type');type.value=kind;type.dispatchEvent(new Event('change'));
                  const source=document.getElementById('add-asset-mode');source.value='game';source.dispatchEvent(new Event('change'));
                  document.getElementById('add-asset-name').value='MotionProbe';
                  document.getElementById('add-asset-source').value='Fixture/Source';
                  document.getElementById('add-asset-name').dispatchEvent(new Event('input'));
                  document.querySelector('.add-asset-form').requestSubmit();
                }""", kind)
                badge = tab.locator('#add-asset-overlay .material-save-badge')
                assert badge.get_attribute('data-glyph-state') == 'busy'
                assert badge.get_attribute('data-glyph-asset') == kind
                assert tab.locator('#add-asset-status').inner_text() == 'Preparing your asset…'
                if mode == 'full' and kind == 'texture':
                    tab.keyboard.press('Escape')
                    assert badge.count() == 0
                    tab.evaluate('AtelierAddAsset.open()')
                    assert badge.count() == 1
                    tab.evaluate("__job.options.onUpdate({stage:'Reading the selected texture'})")
                    assert 'Reading the selected texture' in tab.locator('#add-asset-status').inner_text()
                    tab.locator('.add-asset-modal').screenshot(path=str(report / 'motion-add-texture.png'))
                    tab.evaluate("_activeProjectName='Smoke B';window.dispatchEvent(new Event('atelier:project-assets'))")
                    assert badge.count() == 0
                    tab.evaluate("_activeProjectName='Smoke A'")
                tab.evaluate("__finish({ok:false,error:'Fixture asset could not be read.'})")
                assert badge.count() == 0
                assert tab.locator('#add-asset-submit').is_enabled()
                tab.keyboard.press('Escape')
        checks.append('Add custom asset uses the selected texture/mesh/material loader in Full, Calm and Off; hide, reopen, project changes and failed results clean it up')

        for mode in ('full', 'calm', 'off'):
            tab.evaluate('__mode', mode)
            for kind in ('material', 'curve'):
                tab.evaluate("""kind=>{
                  const items=[{game_rel:'Fixture/Asset',name:'Fixture asset'}];
                  AtelierBulkEdit.open({folder:items,edited:[]},atelierProject(),{kind,source:'folder'});
                  document.getElementById('bulk-preview').click();
                }""", kind)
                assert tab.locator('#bulk-overlay .material-save-badge[data-glyph-state=busy]').count() == 1
                assert tab.locator('.bulk-review-progress').count() == 0
                tab.evaluate("__job.options.onUpdate({stage:'Reviewing the second asset',state:'running',current:1,total:4})")
                bar = tab.locator('.bulk-review-progress progress')
                assert bar.evaluate('bar=>[bar.value,bar.max]') == [1, 4]
                assert bar.get_attribute('aria-valuetext') == '1 of 4 assets reviewed'
                assert tab.locator('.bulk-review-progress .progress-disc').count() == 1
                tab.evaluate("window.dispatchEvent(new CustomEvent('atelier-job',{detail:{kind:'bulk-preview',project:'Other',current:99,total:100,stage:'Other job'}}))")
                assert bar.evaluate('bar=>bar.value') == 1
                tab.keyboard.press('Escape')
                assert bar.count() == 0
                tab.evaluate('AtelierBulkEdit.open({},atelierProject())')
                assert bar.evaluate('bar=>[bar.value,bar.max]') == [1, 4]
                tab.evaluate("__job.options.onUpdate({stage:'Finishing review',state:'running',current:0,total:0})")
                assert bar.count() == 0
                assert tab.locator('#bulk-overlay .material-save-badge').count() == 1
                tab.evaluate("__job.options.onUpdate({stage:'Reviewing assets',state:'running',current:2,total:4})")
                if mode == 'full' and kind == 'material':
                    for theme in ('dark', 'light'):
                        tab.evaluate('theme=>document.documentElement.dataset.theme=theme', theme)
                        tab.locator('.bulk-modal').screenshot(path=str(report / f'motion-bulk-review-{theme}.png'))
                    for width, height in ((1024, 768), (800, 600), (560, 768)):
                        tab.set_viewport_size({'width': width, 'height': height})
                        assert tab.locator('.bulk-modal').evaluate('panel=>panel.scrollWidth<=panel.clientWidth')
                    tab.set_viewport_size({'width': 1400, 'height': 900})
                tab.evaluate("__finish({ok:true,preview_id:'fixture-review',changed_assets:1,changed_values:1,assets:[{game_rel:'Fixture/Asset',changes:1}]})")
                assert bar.count() == 0
                assert tab.locator('#bulk-apply').is_enabled()
                tab.locator('#bulk-apply').click()
                badge = tab.locator('#bulk-overlay .material-save-badge')
                assert badge.get_attribute('data-glyph-state') == 'busy'
                assert badge.get_attribute('data-glyph-asset') == ('material' if kind == 'material' else None)
                tab.keyboard.press('Escape')
                assert badge.count() == 0
                tab.evaluate('AtelierBulkEdit.open({},atelierProject())')
                assert badge.count() == 1
                if mode == 'full' and kind == 'material':
                    tab.locator('.bulk-modal').screenshot(path=str(report / 'motion-bulk-save.png'))
                tab.evaluate("__finish({ok:false,error:'Fixture batch could not be saved.'})")
                assert badge.count() == 0 and bar.count() == 0
                assert 'could not be saved' in tab.locator('#bulk-status').inner_text()
                tab.keyboard.press('Escape')
        checks.append('Bulk review rolls only to its own real counts, drops uncounted bars and resumes after hiding; material/mixed saves use the correct busy glyph and clean up on failure in all modes')

        for mode in ('full', 'calm', 'off'):
            tab.evaluate('__mode', mode)
            tab.evaluate("""() => {
              AtelierLibraryPins.list().forEach(pin=>AtelierLibraryPins.remove(pin.path));
              AtelierLibraryPins.render(document.getElementById('home-pins'),{isHome:true});
              __effects=[];AtelierLibraryPins.toggle({path:'Maps',label:'Maps'});
            }""")
            effects = tab.evaluate('__effects.map(effect=>({frames:effect.frames,duration:effect.duration}))')
            assert bool(effects) == (mode != 'off'), (mode, effects)
            assert all('opacity' not in frame for effect in effects for frame in effect['frames'])
            if mode == 'calm':
                assert not any('scale(' in frame.get('transform', '') for effect in effects for frame in effect['frames'])
            tab.evaluate('__settle()')
            tab.evaluate("""() => {
              document.querySelector('#home-pins .library-pin-open').focus();
              __effects=[];AtelierLibraryPins.render(document.getElementById('home-pins'),{isHome:true});
              AtelierLibraryPins.updateLabels({Maps:'Maps'});
            }""")
            assert tab.evaluate('__effects.length') == 0
            assert tab.evaluate('document.activeElement.matches("#home-pins .library-pin-open") && document.activeElement.closest("[data-pin-path]").dataset.pinPath==="Maps"'), mode
            tab.evaluate("AtelierLibraryPins.remove('Maps')")
            ghost = tab.locator('.polish-ghost.library-pin-chip')
            assert bool(ghost.count()) == (mode != 'off')
            assert tab.locator('#home-pins .library-pin-open').count() == 0
            if mode != 'off':
                assert ghost.get_attribute('aria-hidden') == 'true' and ghost.evaluate('node=>node.inert')
            tab.evaluate("AtelierLibraryPins.toggle({path:'Maps',label:'Maps'})")
            assert ghost.count() == 0
            assert tab.locator('#home-pins .library-pin-open').count() == 1
            tab.evaluate('__settle()')
            tab.evaluate("__effects=[];AtelierLibraryPins.render(document.getElementById('home-pins'),{isHome:true,filter:'zzz'});AtelierLibraryPins.render(document.getElementById('home-pins'),{isHome:true})")
            assert tab.evaluate('__effects.length') == 0
        checks.append('Pins settle only when added, fold as inert copies when removed and cancel stale folds on rapid repinning; filtering, labels and repaints preserve focus without replaying motion')

        for mode in ('full', 'calm', 'off'):
            tab.evaluate('__mode', mode)
            tab.evaluate("""() => {
              __effects=[];
              AtelierLibraryTools.previewImage({label:'Motion preview',path:'Fixture/Preview',src:'/motion-image.png',caption:'Loaded image'},document.getElementById('add-asset-open'));
            }""")
            tab.wait_for_function("document.querySelector('#library-preview img').complete && !document.querySelector('#library-preview img').hidden")
            effects = tab.evaluate('__effects.map(effect=>({frames:effect.frames,duration:effect.duration}))')
            assert bool(effects) == (mode != 'off'), (mode, effects)
            if effects:
                assert effects[0]['frames'][0]['clipPath'] == 'inset(0px 0px 100%)'
                assert not any('opacity' in frame for frame in effects[0]['frames'])
            tab.evaluate('AtelierLibraryTools.closePreview()')
            tab.wait_for_selector('#library-preview:not([open]) img:not([src])', state='attached')
            assert tab.locator('#library-preview img').evaluate('image=>image.getAnimations().length') == 0
        tab.emulate_media(reduced_motion='reduce')
        tab.evaluate("__mode('full');__effects=[];AtelierLibraryTools.previewImage({label:'Reduced preview',path:'Fixture',src:'/motion-image.png',caption:''})")
        tab.wait_for_function("!document.querySelector('#library-preview img').hidden")
        assert tab.evaluate('__effects.length') == 0
        tab.evaluate('AtelierLibraryTools.closePreview()')
        tab.emulate_media(reduced_motion='no-preference')
        tab.evaluate("__mode('full');AtelierLibraryTools.previewImage({label:'Interrupted preview',path:'Fixture',src:'/motion-image.png',caption:''})")
        tab.wait_for_function("!document.querySelector('#library-preview img').hidden")
        tab.evaluate("__mode('off')")
        assert tab.locator('#library-preview img').evaluate('image=>image.getAnimations().length') == 0
        tab.evaluate('AtelierLibraryTools.closePreview()')
        checks.append('Quick Preview reveals the loaded image from the top without a fade, cancels on close and stays still in Off and OS reduced motion')

        # Catalogue art's sharper copy: the first check finds it still being made, a later one finds it ready. The
        # sharper copy is blue, so a held swap shows which picture is where.
        def png(size, colour):
            data = BytesIO(); Image.new('RGB', size, colour).save(data, 'PNG')
            return data.getvalue()
        old_colour, new_colour = (182, 64, 80), (64, 100, 182)
        pictures = {path: (png(size, old_colour), png(tuple(n * 4 for n in size), new_colour)) for path, size in
                    (('/api/catalogue/hero/1029/story', (344, 120)), ('/api/catalogue/banner/1029100', (848, 192)))}
        upscale = {'ready': False, 'heads': 0}
        def catalogue(route):
            parts = urlsplit(route.request.url)
            if parts.path not in pictures:
                route.fulfill(status=404)
                return
            if route.request.method == 'HEAD':
                upscale['heads'] += 1
            route.fulfill(body=pictures[parts.path]['upscale=4' in parts.query], content_type='image/png',
                          headers={'X-Atelier-Upscale': 'ready' if upscale['ready'] else 'pending', 'Cache-Control': 'no-cache'})
        def becomes_ready():
            deadline = monotonic() + 10
            while not upscale['heads'] and monotonic() < deadline:
                tab.wait_for_timeout(50)
            assert upscale['heads'], 'Visible catalogue art must be checked for a sharper copy'
            upscale['ready'] = True
        def swaps():
            return tab.evaluate('__effects.filter(effect=>effect.box).map(effect=>({frames:effect.frames,box:effect.box,src:effect.src}))')
        def assert_swap(found, where):
            assert len(found) == 1, (where, found)
            frames = found[0]['frames']
            assert [frame['clipPath'] for frame in frames] == ['inset(0px)', 'inset(100% 0px 0px)'], (where, frames)
            assert not any('opacity' in frame for frame in frames), (where, frames)
            assert 'upscale' not in found[0]['src'], ('The outgoing copy must show the original art', where, found[0])
            outgoing, incoming = found[0]['box']
            assert all(abs(a - b) < 1 for a, b in zip(outgoing, incoming)), ('The outgoing copy must sit exactly over the art', where, found[0]['box'])
        near = lambda pixel, colour: sum(abs(a - b) for a, b in zip(pixel, colour)) < 30
        tab.route('**/api/catalogue/**', catalogue)
        art = "document.querySelector('#library-hero .library-hero-art:not(.image-swap)')"
        for mode, ready_first in (('full', False), ('calm', False), ('off', False), ('full', True)):
            tab.evaluate('__mode', mode)
            upscale.update(ready=ready_first, heads=0)
            hold = mode == 'full' and not ready_first
            tab.evaluate("hold=>{__effects=[];window.__holdSwap=hold?60:0;AtelierContinuity.banner('Characters/1029');}", hold)
            if not ready_first:
                tab.wait_for_function(art + '?.naturalWidth===344')
                becomes_ready()
            if hold:
                # Held part-way: the sharper art shows above the cut and the original below it, under the banner's copy.
                tab.wait_for_function("document.querySelector('#library-hero .image-swap')?.getAnimations()[0]?.playState==='paused'", timeout=15000)
                held = tab.evaluate("""() => {
                  const copy=document.querySelector('#library-hero .image-swap'),rect=copy.getBoundingClientRect(),host=document.getElementById('library-hero').getBoundingClientRect();
                  return {cut:parseFloat(getComputedStyle(copy).clipPath.slice(6))/100,top:rect.top,height:rect.height,x:host.left+host.width*.8};
                }""")
                assert .1 < held['cut'] < .9, held
                shot = Image.open(BytesIO(tab.screenshot(scale='css'))).convert('RGB')
                tab.locator('#library-hero').screenshot(path=str(report / 'motion-upscale-swap-held.png'))
                above = shot.getpixel((round(held['x']), round(held['top'] + held['height'] * held['cut'] / 2)))
                below = shot.getpixel((round(held['x']), round(held['top'] + held['height'] * (1 + held['cut']) / 2)))
                assert near(above, new_colour) and near(below, old_colour), (held, above, below)
                tab.evaluate("window.__holdSwap=0;document.querySelector('#library-hero .image-swap').getAnimations()[0].play()")
            tab.wait_for_function(art + "?.naturalWidth===1376 && !document.querySelector('#library-hero .image-swap')", timeout=15000)
            if mode == 'off' or ready_first:
                assert not swaps(), ('A sharper copy already waiting, or arriving in Off, replaces the art at once', mode, swaps())
            else:
                assert_swap(swaps(), mode)
        # Model Studio's skin card takes the same swap, with its sharpened nameplate as the source.
        assert tab.evaluate("!document.getElementById('viewport-skin-card')")
        tab.evaluate('__mode', 'full')
        upscale.update(ready=False, heads=0)
        tab.evaluate("""() => {
          __effects=[];window.__holdSwap=0;
          const card=document.createElement('figure');card.id='viewport-skin-card';
          Object.assign(card.style,{position:'fixed',left:'16px',top:'16px',width:'320px',margin:'0',zIndex:'9999'});
          const image=document.createElement('img');image.alt='';card.append(image);document.body.append(card);
          image.src='/api/catalogue/banner/1029100?sharp=1';
        }""")
        card = "document.querySelector('#viewport-skin-card img:not(.image-swap)')"
        tab.wait_for_function(card + '?.naturalWidth===848')
        becomes_ready()
        tab.wait_for_function(card + "?.naturalWidth===3392 && !document.querySelector('#viewport-skin-card .image-swap')", timeout=15000)
        assert_swap(swaps(), 'skin card')
        tab.evaluate("document.getElementById('viewport-skin-card').remove()")
        tab.unroute('**/api/catalogue/**')
        checks.append('Sharper catalogue art (the library banner and the skin card) that arrives while it is on screen opens down over the original from its top edge in Full and Calm, new art above the cut and the original below; in Off, or when it was already waiting, it replaces the art at once and leaves no copy behind')

        tab.evaluate("""() => {
          document.getElementById('body').hidden=true;document.getElementById('workspace').hidden=false;
          document.getElementById('workspace-stage').hidden=false;
          window.__saved=[];
          window.__edit={token:'motion-edit',game_rel:'Fixture/Texture',name:'Saved texture',file_type:'texture',mtime:1,selected:true};
          window.__refresh=()=>window.dispatchEvent(new Event('atelier:project-assets'));
          window.AtelierViewport={hasPendingEdits:()=>false,reloadMaterials:()=>{}};
          window.AtelierModTray={items:()=>__saved,preview:()=>'/motion-image.png',restore:async()=>{__saved=[];__refresh();return true;}};
        }""")
        for mode in ('full', 'calm', 'off'):
            tab.evaluate('__mode', mode)
            tab.evaluate('__saved=[];__refresh();__effects=[];__saved=[{...__edit}];__refresh()')
            assert bool(tab.evaluate('__effects.length')) == (mode != 'off')
            tab.evaluate('__settle()')
            assert tab.locator('#workspace-dock-list .workspace-slot').bounding_box()['width'] == 260
            tab.evaluate('window.__slot=document.querySelector("#workspace-dock-list .workspace-slot");__effects=[];__refresh()')
            assert tab.evaluate('__effects.length===0 && __slot===document.querySelector("#workspace-dock-list .workspace-slot")')
            tab.evaluate('__saved[0].selected=false;__refresh()')
            assert tab.evaluate('__effects.length') == 0
            tab.evaluate('__saved[0].mtime++;__refresh()')
            assert bool(tab.evaluate('__effects.length')) == (mode != 'off')
            tab.evaluate('__settle()')
            tab.locator('#workspace-dock-list .workspace-restore').click()
            tab.wait_for_function('!document.querySelector("#workspace-dock-list .workspace-slot")')
            assert tab.locator('#workspace-review').is_disabled()
            if mode != 'off':
                tab.evaluate("document.getElementById('workspace').hidden=true")
                tab.wait_for_function('!document.querySelector(".polish-ghost.workspace-slot")')
                tab.evaluate("document.getElementById('workspace').hidden=false")
            tab.evaluate('__effects=[];__saved=[{...__edit}];__refresh()')
            assert bool(tab.evaluate('__effects.length')) == (mode != 'off')
            assert tab.locator('.polish-ghost.workspace-slot').count() == 0
            tab.evaluate('__settle()')
            tab.evaluate("__effects=[];_activeProjectName='Smoke B';__refresh()")
            assert tab.evaluate('__effects.length') == 0
            tab.evaluate("_activeProjectName='Smoke A';__refresh();document.getElementById('workspace').hidden=true;__effects=[];__saved[0].mtime++;__refresh()")
            assert tab.evaluate('__effects.length') == 0
            tab.evaluate("document.getElementById('workspace').hidden=false")
        checks.append('Your mod seats new saves and Undo, reseats changed saves, folds Restore and keeps unchanged/selection-only/project-switch/hidden refreshes still in Full, Calm and Off')
        assert not errors, errors
    finally:
        if stored:
            tab.evaluate("saved=>{for(const [key,value] of Object.entries(saved)){if(value===null)localStorage.removeItem(key);else localStorage.setItem(key,value);}}", stored)
        tab.close()
    run_editor_motion_placements_checks(context, url, report, checks)


def run_editor_motion_placements_checks(context, url, report, checks):
    """Loaders beside editor, recolour, mesh and S-map work; images opening on their plates; Activity rows; no fades."""
    tab = context.new_page()
    errors, held = [], []
    tab.on('pageerror', lambda error: errors.append(str(error)))
    picture = BytesIO(); Image.new('RGB', (64, 64), '#4F80CC').save(picture, format='PNG')
    jobs = {'jobs': []}
    tab.route('**/api/imported', lambda route: route.fulfill(json=[]))
    tab.route('**/api/jobs', lambda route: route.fulfill(json=jobs))
    tab.route('**/api/material_params?*', lambda route: route.fulfill(json={
        'ok': True, 'colors': [{'name': 'Region 1 - ColorA', 'rgba': [.25, .5, .75, 1]}], 'scalars': []}))
    tab.route('**/api/dye_info?*', lambda route: route.fulfill(json={
        'dyeable': True, 'used': {'1': 1}, 'coverage': {'1': 100}, 'overlay': {'1': '#4F80CC'}, 'regions': {}}))
    tab.route('**/api/asset_opts?*', lambda route: route.fulfill(json={'ok': True, 'opts': {}}))
    tab.route('**/api/dye_preview', lambda route: route.fulfill(body=picture.getvalue(), content_type='image/png'))
    tab.route('**/api/dye_overlay?*', lambda route: route.fulfill(body=picture.getvalue(), content_type='image/png'))
    for path in EDITOR_HOLDS:
        tab.route(f'**/api/{path}', lambda route: held.append(route))

    def wait_held(count):
        deadline = monotonic() + 5
        while len(held) < count and monotonic() < deadline:
            tab.wait_for_timeout(10)
        assert len(held) >= count, (len(held), count)

    def badge(overlay):
        return tab.locator(f'#{overlay} .material-save-badge')

    def gone(selector):
        tab.wait_for_function('selector=>!document.querySelector(selector)', arg=selector)

    def busy_while(start, overlay, asset, download=False):
        count = len(held)
        tab.evaluate(f'() => {{ window.__pending = {start}; }}')
        wait_held(count + 1)
        shown = badge(overlay)
        assert shown.count() == 1, (start, shown.count())
        assert shown.get_attribute('data-glyph-state') == 'busy', start
        assert shown.get_attribute('data-glyph-asset') == asset, (start, shown.get_attribute('data-glyph-asset'))
        route = held.pop()
        if download: route.fulfill(status=500, body='')
        else: route.fulfill(json={'ok': False, 'error': 'Fixture request failed.'})
        gone(f'#{overlay} .material-save-badge')

    def effects():
        return tab.evaluate('__effects.map(effect=>({frames:effect.frames,selector:effect.selector}))')

    stored = None
    try:
        tab.goto(url)
        tab.wait_for_function("window.AtelierMaterialSaveFeedback && window.AtelierMeshEdit && window.AtelierSMapsUI && window.atelierProject?.() && !document.querySelector('.overlay.active')")
        tab.bring_to_front()
        stored = tab.evaluate("Object.fromEntries(['atelier.motion'].map(key=>[key,localStorage.getItem(key)]))")
        tab.evaluate("""() => {
          window.__effects=[];
          const animate=Element.prototype.animate;
          Element.prototype.animate=function(...args){
            const result=animate.apply(this,args);
            const selector=['#dye-prev','.job-row','.job-row *'].find(selector=>this.matches(selector));
            if(selector)__effects.push({selector,frames:result.effect.getKeyframes()});
            return result;
          };
          AtelierJobs.run=(path,options)=>new Promise(resolve=>window.__job={path,options,resolve});
          window.AtelierDialog={confirm:async()=>true};
          window.__mode=value=>{const control=document.getElementById('settings-motion');control.value=value;control.dispatchEvent(new Event('change'));};
          window.__finish=async result=>{__job.resolve(result);await new Promise(resolve=>setTimeout(resolve,0));};
          window.__settle=async()=>{
            const animations=document.getAnimations().filter(a=>a.effect.getTiming().iterations!==Infinity);
            animations.forEach(a=>a.finish());await Promise.allSettled(animations.map(a=>a.finished));
          };
          window.__dyeLoaded=()=>{const img=document.getElementById('dye-prev');return !!img&&img.complete&&img.naturalWidth>0;};
        }""")

        for mode in ('full', 'calm', 'off'):
            tab.evaluate('__mode', mode)
            tab.evaluate("__effects=[];openMaterialEditor({name:'MI_Fixture',game_rel:'Fixture/MI_Fixture'})")
            tab.wait_for_function("document.getElementById('dye-prev')?.dataset.url && __dyeLoaded()")
            tab.wait_for_timeout(50)
            opened = [effect for effect in effects() if effect['selector'] == '#dye-prev']
            assert bool(opened) == (mode != 'off'), (mode, opened)
            if opened:
                assert opened[0]['frames'][0]['clipPath'] == 'inset(0px 0px 100%)'
                assert not any('opacity' in frame for frame in opened[0]['frames'])
            tab.evaluate("__effects=[];dyeView('regions')")
            tab.wait_for_function("document.getElementById('dye-prev')?.src.includes('dye_overlay') && __dyeLoaded()")
            tab.wait_for_timeout(50)
            assert bool(effects()) == (mode != 'off'), mode
            tab.evaluate("__effects=[];dyeView('preview')")
            tab.wait_for_function("document.getElementById('dye-prev')?.dataset.url && __dyeLoaded()")
            tab.wait_for_timeout(50)
            assert bool(effects()) == (mode != 'off'), mode
            # A live colour change swaps the picture in place; a repaint of the same picture stays still.
            tab.evaluate("__effects=[];window.__before=document.getElementById('dye-prev').dataset.url;dyeRefresh(0)")
            tab.wait_for_function("document.getElementById('dye-prev').dataset.url!==__before && __dyeLoaded()")
            tab.evaluate("window.__plate=document.getElementById('dye-prev');renderMatEditor();dyeRefresh(0)")
            tab.wait_for_function("document.getElementById('dye-prev')!==__plate && document.getElementById('dye-prev').dataset.url && __dyeLoaded()")
            tab.wait_for_timeout(50)
            assert not effects(), (mode, effects())

            busy_while("matCustomTextureUpload({editor:matEditor,slot:'Diffuse',project:_activeProjectName},new File(['x'],'fixture.png',{type:'image/png'}))",
                       'material-overlay', 'texture')
            assert tab.locator('#mat-status').inner_text() == 'Error: Fixture request failed.'
            busy_while('dyeDownload()', 'material-overlay', 'texture', download=True)
            assert tab.locator('#mat-status').inner_text() == 'Download failed'
            busy_while('matTexturesDownload()', 'material-overlay', 'texture', download=True)
            busy_while("(document.getElementById('mat-source-path').value='Fixture/MI_Source',replaceMaterialFromSource())", 'material-overlay', 'material')
            assert not tab.evaluate("document.getElementById('mat-body').inert")
            busy_while('resetMaterial()', 'material-overlay', 'material')
            if mode == 'full':
                # Requests that overlap in one editor share its glyph until the last one ends.
                count = len(held)
                tab.evaluate("() => { window.__a=dyeDownload(); window.__b=matTexturesDownload(); }")
                wait_held(count + 2)
                assert badge('material-overlay').count() == 1
                assert badge('material-overlay').get_attribute('data-glyph-asset') == 'texture'
                held.pop().fulfill(status=500, body='')
                tab.wait_for_timeout(50)
                assert badge('material-overlay').count() == 1
                held.pop().fulfill(status=500, body='')
                gone('#material-overlay .material-save-badge')
            tab.evaluate('closeMaterialEditor(true)')
            tab.locator('#material-overlay.active').wait_for(state='detached')

            tab.evaluate("""() => {
              curveEditor={game_rel:'Fixture/Curve',name:'Fixture curve',channels:{},stops:[],dirty:{}};
              document.getElementById('curve-overlay').classList.add('active');
            }""")
            busy_while('resetCurve()', 'curve-overlay', None)
            assert tab.locator('#curve-status').inner_text() == 'Error: Fixture request failed.'
            tab.evaluate("curveEditor=null;document.getElementById('curve-overlay').classList.remove('active')")
            tab.evaluate("""() => {
              vfxEditor={game_rel:'Fixture/NS_Fixture',name:'Fixture effect',groups:[],scalars:[],vectors:[]};
              document.getElementById('vfx-overlay').classList.add('active');
            }""")
            busy_while('resetVfx()', 'vfx-overlay', None)
            assert not tab.evaluate("document.getElementById('vfx-body').inert || document.getElementById('vfx-save').disabled")
            tab.evaluate("vfxEditor=null;document.getElementById('vfx-overlay').classList.remove('active')")
            for editor, overlay in (('worldEditor', 'world'), ('textEditor', 'text')):
                tab.evaluate(f"{editor}={{game_rel:'Fixture/{overlay}',name:'Fixture {overlay}'}};document.getElementById('{overlay}-overlay').classList.add('active')")
                busy_while(f"document.getElementById('{overlay}-reset').click()", f'{overlay}-overlay', None)
                assert tab.locator(f'#{overlay}-status').inner_text() == 'Fixture request failed.'
                tab.evaluate(f"{editor}=null;document.getElementById('{overlay}-overlay').classList.remove('active')")
            tab.evaluate("texOpts={game_rel:'Fixture/T_Fixture',name:'T_Fixture',opts:{}};document.getElementById('texopt-overlay').classList.add('active')")
            row = tab.locator('#texopt-overlay .modal-row')
            still_height = row.bounding_box()['height']
            count = len(held)
            tab.evaluate('() => { window.__pending = saveTexOpts(); }')
            wait_held(count + 1)
            assert badge('texopt-overlay').get_attribute('data-glyph-asset') == 'texture'
            # Sub-pixel rounding from the dialog's unfold can differ by a fraction of a pixel.
            saving_height = row.bounding_box()['height']
            assert abs(saving_height - still_height) < 0.5, ('The export options footer must not jump while it saves', mode, still_height, saving_height)
            if mode == 'full':
                tab.locator('#texopt-overlay .modal').screenshot(path=str(report / 'motion-texture-options.png'))
            held.pop().fulfill(json={'ok': False, 'error': 'Fixture request failed.'})
            gone('#texopt-overlay .material-save-badge')
            tab.evaluate("texOpts=null;document.getElementById('texopt-overlay').classList.remove('active')")
        checks.append('Material editor uploads, bakes and packs use the texture loader, and replace and reset the material loader. Other editors reset with the working glyph, export options save with the texture loader, and overlapping requests share one glyph in Full, Calm and Off')
        checks.append('The dye preview opens from the top of its plate when the editor opens or its view changes, and stays still for live colour changes, repaints of the same picture and Off')

        tab.evaluate("window.AtelierViewport={hasPendingEdits:()=>false,close:async()=>{},focusPendingEdits(){},openMesh(){}}")
        target = "{game_rel:'Fixture/Meshes/SK_Fixture',name:'SK_Fixture'}"
        for mode in ('full', 'calm', 'off'):
            tab.evaluate('__mode', mode)
            tab.evaluate(f'AtelierMeshEdit.open({target})')
            tab.wait_for_selector('#mesh-edit-overlay.active')
            tab.evaluate("() => { window.__pending = AtelierMeshEdit.replace([new File(['x'],'fixture.fbx')]); }")
            shown = badge('mesh-edit-overlay')
            assert shown.get_attribute('data-glyph-state') == 'busy' and shown.get_attribute('data-glyph-asset') == 'mesh'
            assert tab.evaluate("__job.path") == '/api/mesh_replace'
            if mode == 'full':
                tab.locator('#mesh-edit-overlay .modal').screenshot(path=str(report / 'motion-mesh-replace.png'))
            tab.keyboard.press('Escape')
            assert shown.count() == 0
            tab.evaluate(f'AtelierMeshEdit.open({target})')
            assert shown.count() == 1
            tab.evaluate("_activeProjectName='Smoke B';window.dispatchEvent(new Event('atelier:project-assets'))")
            assert shown.count() == 0
            tab.evaluate("_activeProjectName='Smoke A'")
            tab.evaluate("__finish({ok:false,error:'Fixture model could not be read.'})")
            assert shown.count() == 0
            assert 'could not be read' in tab.locator('#mesh-edit-status').inner_text()
            assert tab.locator('#mesh-replace-choose').is_enabled()
            tab.keyboard.press('Escape')
        checks.append('Replacing a mesh shows the mesh loader beside its status; hiding, reopening, project changes and failures clean it up in Full, Calm and Off')

        for mode in ('full', 'calm', 'off'):
            tab.evaluate('__mode', mode)
            tab.evaluate("""async () => {
              const {createViewportRecolour} = await import('/static/viewport-recolour.js');
              const state = window.__recolour = {posts: []};
              const reply = body => ({ok: true, json: async () => body});
              const api = {
                fetch(path, options = {}) {
                  if (path.startsWith('/api/texture_recolour/preview')) return Promise.resolve({ok: false, json: async () => ({error: 'Preview held for the check.'})});
                  if (options.method === 'POST') return new Promise(resolve => state.posts.push(body => resolve(reply(body))));
                  return Promise.resolve(reply({ok: false}));
                },
                materials: () => [], retint() {}, applied: async () => {}, note() {}, rebuild() {}, reload() {},
              };
              const box = createViewportRecolour(api).section('Body', {texture_roles: {basecolor: 'Fixture/T_Body_D'}});
              box.id = 'motion-recolour';
              Object.assign(box.style, {position: 'fixed', left: '16px', top: '16px', width: '320px', zIndex: 9999, padding: '16px', background: 'var(--bg2)'});
              document.body.append(box);
              const picker = box.querySelector('input[type=color]'); picker.value = '#c04020'; picker.dispatchEvent(new Event('input'));
            }""")
            tab.wait_for_function("document.querySelector('#motion-recolour .vp-recolour-status').textContent==='Preview held for the check.'")
            tab.evaluate("document.querySelector('#motion-recolour .vp-recolour-apply').click()")
            shown = tab.locator('#motion-recolour .vp-recolour-feedback .material-save-badge')
            assert shown.get_attribute('data-glyph-state') == 'busy' and shown.get_attribute('data-glyph-asset') == 'texture'
            assert shown.get_attribute('data-glyph-tier') == 'inline'
            assert tab.locator('#motion-recolour .vp-recolour-status').inner_text() == 'Saving recolour…'
            if mode == 'full':
                tab.locator('#motion-recolour').screenshot(path=str(report / 'motion-recolour-save.png'))
            tab.evaluate("__recolour.posts.shift()({ok:false,error:'Fixture recolour failed.'})")
            gone('#motion-recolour .material-save-badge')
            assert tab.locator('#motion-recolour .vp-recolour-status').inner_text() == 'Fixture recolour failed.'
            # Asking to replace other edits ends this wait; the replacing save is its own.
            tab.evaluate("""() => {
              window.AtelierDialog={confirm:()=>new Promise(resolve=>window.__confirm=resolve)};
              const apply=document.querySelector('#motion-recolour .vp-recolour-apply'); apply.disabled=false; apply.click();
            }""")
            assert shown.count() == 1
            tab.evaluate("window.__confirm=null;__recolour.posts.shift()({needs_replace:true})")
            tab.wait_for_function('!!window.__confirm')
            assert shown.count() == 0
            tab.evaluate('__confirm(true)')
            tab.wait_for_function("__recolour.posts.length===1")
            assert shown.count() == 1
            tab.evaluate("__recolour.posts.shift()({ok:false,error:'Fixture recolour failed.'})")
            gone('#motion-recolour .material-save-badge')
            tab.evaluate("window.AtelierDialog={confirm:async()=>true};document.getElementById('motion-recolour').remove()")
        checks.append('Saving a recolour shows the texture loader beside its status, ends it for the replace question and on failure, in Full, Calm and Off')

        tray = '#tray-progress .export-feedback-toast'
        for mode in ('full', 'calm', 'off'):
            tab.evaluate('__mode', mode)
            tab.evaluate("() => { AtelierSMapsUI.update([{file_type:'texture',game_rel:'Fixture/T_Fixture_D'}]); window.__pending=AtelierSMapsUI.process(); }")
            glyph = tab.locator(f'{tray} [data-atelier-motion="glyph"]')
            assert glyph.get_attribute('data-glyph-state') == 'busy' and glyph.get_attribute('data-glyph-asset') == 'texture'
            assert tab.locator(f'{tray} .export-feedback-message').inner_text() == 'Processing S maps…'
            assert tab.evaluate('__job.path') == '/api/s_maps/plan'
            tab.evaluate(f"window.__trayRow=document.querySelector('{tray}')")
            tab.evaluate("__finish({ok:true,plan_id:'fixture-plan',pairs:[],skipped:[]})")
            tab.wait_for_timeout(20)
            assert tab.evaluate('__job.path') == '/api/s_maps/process'
            assert tab.evaluate(f"document.querySelector('{tray}')===__trayRow"), 'Planning hands to processing without restarting the loader'
            tab.evaluate("__finish({ok:false,error:'Fixture S maps could not be processed.'})")
            gone(tray)
            tab.evaluate("document.querySelectorAll('#toast-area .toast').forEach(toast=>toast.remove())")
        checks.append('Processing S maps shows the texture loader in the Mod tray from planning to the result, without restarting between them, in Full, Calm and Off')

        def job(name, stage='Working'):
            return {'id': name, 'kind': 'fixture', 'label': 'Fixture ' + name, 'state': 'running', 'stage': stage,
                    'project': tab.evaluate('atelierProject()')}

        def open_activity():
            # The panel takes its baseline from the refresh its own button starts.
            with tab.expect_response('**/api/jobs'):
                tab.locator('#job-activity').click()
            tab.wait_for_selector('#job-overlay.active .job-row')
            tab.wait_for_timeout(100)

        for mode in ('full', 'calm', 'off'):
            tab.evaluate('__mode', mode)
            jobs['jobs'] = [job(f'{mode}-a')]
            tab.evaluate('__effects=[];AtelierJobs.refresh()')
            open_activity()
            assert not effects(), 'Opening Activity shows its rows as they are'
            jobs['jobs'] = [job(f'{mode}-b'), job(f'{mode}-a')]
            tab.evaluate('AtelierJobs.refresh()')
            seated = effects()
            assert bool(seated) == (mode != 'off'), (mode, seated)
            assert not any('opacity' in frame for effect in seated for frame in effect['frames'])
            assert any('scale(' in frame.get('transform', '') for effect in seated for frame in effect['frames']) == (mode == 'full')
            if mode == 'full':
                tab.locator('#job-overlay .modal').screenshot(path=str(report / 'motion-activity-seat.png'))
            tab.evaluate('__settle()')
            jobs['jobs'] = [job(f'{mode}-b', 'Still working'), job(f'{mode}-a')]
            tab.evaluate('__effects=[];AtelierJobs.refresh()')
            assert not effects(), 'A progress repaint keeps rows still'
            tab.keyboard.press('Escape')
            jobs['jobs'] = [job(f'{mode}-c'), job(f'{mode}-b'), job(f'{mode}-a')]
            tab.evaluate('AtelierJobs.refresh()')
            open_activity()
            tab.evaluate('AtelierJobs.refresh()')
            assert not effects(), 'Jobs that arrived while Activity was closed are shown still'
            tab.keyboard.press('Escape')
        jobs['jobs'] = []
        checks.append('A job that starts while Activity is open seats into the list (squash in Full only, still in Off); opening, progress repaints and closed refreshes stay still')

        for mode in ('full', 'off'):
            tab.evaluate('__mode', mode)
            result = tab.evaluate("""() => {
              const row=document.createElement('div');row.className='mat-row flash';row.textContent='Region 1';document.body.append(row);
              const running=row.getAnimations({subtree:true}), flash=running.map(animation=>animation.effect.getKeyframes());
              running.forEach(animation=>animation.cancel());
              const hidden=getComputedStyle(row,'::before').clipPath;row.remove();
              const wrap=document.createElement('div');wrap.className='folder-card-wrap';
              const pin=document.createElement('button');pin.className='library-pin-toggle';wrap.append(pin);document.body.append(wrap);
              const style=getComputedStyle(pin),rest={opacity:style.opacity,clip:style.clipPath,transition:style.transitionProperty};
              pin.focus();const focused=getComputedStyle(pin).clipPath;wrap.remove();
              const rules=[...document.styleSheets].flatMap(sheet=>{try{return [...sheet.cssRules];}catch(_){return [];}});
              const rule=selector=>rules.find(item=>item.selectorText===selector)?.style;
              const glow=rule('#viewport-skin-card::before'),shown=rule('#viewport-box.has-skin-colour #viewport-skin-card::before');
              return {flash,hidden,rest,focused,glow:{opacity:glow.opacity,clip:glow.clipPath,transition:glow.transitionProperty},
                shown:{opacity:shown.opacity,clip:shown.clipPath,transition:shown.transitionProperty}};
            }""")
            assert result['hidden'] == 'inset(0px 100% 0px 0px)', result
            assert bool(result['flash']) == (mode == 'full'), result
            for frames in result['flash']:
                assert any('clipPath' in frame for frame in frames) and not any('opacity' in frame or 'backgroundColor' in frame for frame in frames), frames
            assert result['rest']['opacity'] == '1' and 'opacity' not in result['rest']['transition'], result
            assert result['rest']['clip'] == 'inset(0px -8px 100%)', result
            if mode == 'off':
                assert result['focused'] == 'inset(-8px)', result
            for side in ('glow', 'shown'):
                assert not result[side]['opacity'] and 'opacity' not in result[side]['transition'] and result[side]['clip'], result
        checks.append('Finding a region folds its highlight away, and the costume glow and folder pin unfold, all without fading')
        assert not errors, errors
    finally:
        if stored:
            tab.evaluate("saved=>{for(const [key,value] of Object.entries(saved)){if(value===null)localStorage.removeItem(key);else localStorage.setItem(key,value);}}", stored)
        tab.close()
