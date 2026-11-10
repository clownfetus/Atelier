"""The five extra motion placements: real controls with held, explicitly simulated job results."""
from io import BytesIO

from PIL import Image, ImageDraw


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
            if(this.matches('#library-preview img,.workspace-slot,.workspace-slot *, .library-pin-chip,.library-pin-chip *'))
              __effects.push({el:this,animation:result,frames:result.effect.getKeyframes(),duration:result.effect.getTiming().duration});
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
            tab.wait_for_function("!document.querySelector('#library-preview').open")
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
