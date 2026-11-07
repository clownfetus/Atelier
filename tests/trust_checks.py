"""Wave 2 workflows against real disposable project files and controlled setup services."""
from pathlib import Path
import shutil


def run_trust_checks(page, context, url, report, checks):
    from atelier import config as C
    from atelier.web import browse
    from PIL import Image
    root=Path(C.PROJECTS_ROOT,'Smoke A')
    grs=['Fixture/T_UndoOne','Fixture/T_UndoTwo']
    files=[]
    for gr in grs:
        path=Path(C.project_base(gr,root)+'.png');path.parent.mkdir(parents=True,exist_ok=True)
        Image.new('RGBA',(4,4),(64,128,240,255)).save(path);files.append(path)
    originals=[p.read_bytes() for p in files]
    tab=context.new_page();errors=[];tab.on('pageerror',lambda error:errors.append(str(error)))
    module=(Path(__file__).resolve().parents[1]/'gui/viewport.js').read_text(encoding='utf-8')
    tab.route('**/static/viewport.js',lambda route:route.fulfill(content_type='text/javascript',body=module+"""
window.__trustViewport={seed(){generation++;viewportProject=atelierProject();edited={Body:{Tint:[1,0,0,1]}};},clear(){edited={};},dirty:()=>Object.keys(edited).length,canLeave};
"""))
    try:
        tab.goto(url);tab.wait_for_function("atelierProject()==='Smoke A' && document.querySelectorAll('.sb-item').length===2")
        tab.locator('.sb-item .sb-clear').first.click()
        tab.locator('#atelier-confirm-ok').click()
        undo=tab.locator('#toast-area .toast-undo');undo.wait_for()
        tab.wait_for_function("document.querySelectorAll('.sb-item').length===1")
        undo.click();tab.wait_for_function("document.querySelectorAll('.sb-item').length===2")
        assert [p.read_bytes() for p in files]==originals
        tab.evaluate("() => {_sbMarked=new Set(Object.keys(sidebarData));window.batch=sbDeleteMarked();}")
        tab.locator('#atelier-confirm-ok').click();tab.evaluate('batch')
        tab.wait_for_function("document.querySelectorAll('.sb-item').length===0")
        tab.locator('#toast-area .toast-undo').click();tab.wait_for_function("document.querySelectorAll('.sb-item').length===2")
        checks.append('Deleting an edit offers Undo and restores the byte-identical file through the real project routes')
        tab.locator('#clear-all-btn').click();tab.locator('#atelier-confirm-ok').click()
        tab.wait_for_function("document.querySelectorAll('.sb-item').length===0")
        undo=tab.locator('#toast-area .toast-undo');undo.wait_for();undo.hover()
        assert undo.locator('..').evaluate("el=>el.style.getPropertyValue('--toast-duration')")=='10000ms'
        tab.wait_for_timeout(400)
        assert undo.is_visible()
        undo.click();tab.wait_for_function("document.querySelectorAll('.sb-item').length===2")
        assert [p.read_bytes() for p in files]==originals
        tab.emulate_media(reduced_motion='reduce')
        tab.locator('.sb-item .sb-clear').first.click(modifiers=['Shift'])
        tab.wait_for_function("document.querySelectorAll('.sb-item').length===1")
        assert tab.locator('.trash-drain').count()==0
        tab.locator('#toast-area .toast-undo').click();tab.wait_for_function("document.querySelectorAll('.sb-item').length===2")
        checks.append('Clear All uses one Undo batch, hover pauses its ten-second toast and reduced motion omits the row dissolve')

        tab.locator('#menu-btn').focus()
        tab.evaluate("() => {window.answer=AtelierDialog.confirm({title:'<img src=x>',body:'<script>unsafe</script>',tone:'danger'});}")
        assert tab.locator('#atelier-confirm-cancel').evaluate('el=>el===document.activeElement')
        assert tab.locator('#atelier-confirm img, #atelier-confirm script').count()==0
        tab.keyboard.press('Shift+Tab');assert tab.locator('#atelier-confirm-ok').evaluate('el=>el===document.activeElement')
        tab.keyboard.press('Tab');assert tab.locator('#atelier-confirm-cancel').evaluate('el=>el===document.activeElement')
        tab.keyboard.press('Escape');assert tab.evaluate('answer') is False
        assert tab.locator('#menu-btn').evaluate('el=>el===document.activeElement')
        tab.evaluate("() => {window.answer=AtelierDialog.confirm({body:'Backdrop cancellation'});}")
        tab.locator('#atelier-confirm').click(position={'x':2,'y':2});assert tab.evaluate('answer') is False
        for theme in ('dark','light'):
            tab.locator('#settings-theme').select_option(theme,force=True)
            tab.evaluate("() => {window.answer=AtelierDialog.confirm({title:'Restore game values?',body:'Your saved draft stays until you choose Restore.',confirmLabel:'Restore',tone:'danger'});}")
            tab.screenshot(path=str(report/f'trust-confirm-{theme}.png'))
            tab.locator('#atelier-confirm-cancel').click()
        checks.append('Themed confirmations render literal text, trap Tab, focus Cancel for danger, cancel on Escape/backdrop and restore focus')
        _confirm_paths(tab,checks)
        tab.evaluate('__trustViewport.seed()')
        for answer in (False,True):
            tab.evaluate('() => {window.leave=__trustViewport.canLeave();}')
            assert tab.evaluate('__trustViewport.dirty()')==1
            tab.locator('#atelier-confirm-'+('ok' if answer else 'cancel')).click()
            assert tab.evaluate('leave') is answer
            assert tab.evaluate('__trustViewport.dirty()')==1
        tab.evaluate('__trustViewport.clear()')
        checks.append('Viewport leave waits for the themed answer and cancelled navigation retains its recolour draft')
        assert not errors,errors
    finally:
        tab.close()
        for path in files:path.unlink(missing_ok=True)
        shutil.rmtree(root/'.atelier-trash',ignore_errors=True)
    _setup(context,url,report,checks)
    _launch_check(context,url,report,checks)


def _confirm_paths(tab,checks):
    calls=[]
    def write(route):
        calls.append(route.request.url.split('/api/')[1])
        route.fulfill(json={'ok':False,'error':'Fixture stop after confirmation'})
    for endpoint in ('material_reset','material_custom_texture/clear','curve_reset','vfx_reset','world_reset','text_reset'):
        tab.route('**/api/'+endpoint,write)
    tab.route('**/api/material_params?*',lambda route:route.fulfill(json={'ok':True,'colors':[{'name':'Tint','rgba':[1,1,1,1]}],'scalars':[]}))
    tab.route('**/api/dye_info?*',lambda route:route.fulfill(json={'dyeable':False}))
    tab.evaluate("openMaterialEditor({name:'MI_Trust',game_rel:'Fixture/MI_Trust'})")
    tab.evaluate("matEditor.textures={Diffuse:'T_Original'};matEditor.custom={Diffuse:{source:'My image.png'}}")
    for expression,endpoint in [('resetMaterial()','material_reset'),('matCustomTextureClear(0)','material_custom_texture/clear')]:
        for accepted in (False,True):
            before=len(calls)
            tab.evaluate('expression=>{window.action=eval(expression)}',expression)
            tab.locator('#atelier-confirm-'+('ok' if accepted else 'cancel')).click()
            tab.evaluate('action');assert len(calls)==before+int(accepted)
            if accepted:assert calls[-1]==endpoint
    tab.evaluate("matEditor.colors[0].rgba=[.2,.3,.4,1];_matRefreshDirty()")
    for action in ('closeMaterialEditor()','openMaterialEditor({name:"Other",game_rel:"Fixture/MI_Other"})'):
        tab.evaluate('expression=>{window.action=eval(expression)}',action)
        assert tab.evaluate("matEditor.name")=='MI_Trust'
        tab.locator('#atelier-confirm-cancel').click();tab.evaluate('action')
        assert tab.evaluate('materialDirtyCount()')==1
    tab.evaluate('closeMaterialEditor(true)')
    cases=[('curveEditor',"{name:'Curve',game_rel:'Fixture/C_Test',dirty:{0:true}}",'resetCurve()','closeCurveEditor()','curve_reset'),
           ('vfxEditor',"{name:'Effect',game_rel:'Fixture/NS_Test',groups:[],scalars:[],vectors:[],baseline:'dirty'}",'resetVfx()','closeVfxEditor()','vfx_reset'),
           ('worldEditor',"{name:'Level',game_rel:'Fixture/Map.umap',edits:{lights:{}},baseline:'dirty'}","document.getElementById('world-reset').click()",'closeWorldEditor()','world_reset'),
           ('textEditor',"{name:'Text',game_rel:'Fixture/Strings_ST',edits:{Hello:'Hi'},baseline:'dirty'}","document.getElementById('text-reset').click()",'closeTextEditor()','text_reset')]
    for variable,seed,reset,close,endpoint in cases:
        tab.evaluate(f'{variable}={seed}')
        for accepted in (False,True):
            before=len(calls);tab.evaluate('expression=>{window.action=eval(expression)}',reset)
            tab.locator('#atelier-confirm-'+('ok' if accepted else 'cancel')).click();tab.evaluate('action')
            if accepted:tab.wait_for_function("document.querySelectorAll('#atelier-confirm').length===0");tab.wait_for_timeout(50)
            assert len(calls)==before+int(accepted),(variable,calls)
            if accepted:assert calls[-1]==endpoint
        tab.evaluate('expression=>{window.action=eval(expression)}',close)
        tab.locator('#atelier-confirm-cancel').click();assert tab.evaluate('action') is False
        assert tab.evaluate(f'{variable}!==null')
        tab.evaluate('expression=>{window.action=eval(expression)}',close)
        tab.locator('#atelier-confirm-ok').click();assert tab.evaluate('action') is True
        tab.evaluate(f'{variable}=null')
    checks.append('Material, custom-texture, curve, effect, level and text reset/leave paths await themed answers and cancelled leave retains drafts')
    tab.route('**/api/blender_status',lambda route:route.fulfill(json={'ok':True}))
    extra=[]
    def extraction(route):
        body=route.request.post_data_json;extra.append(body)
        route.fulfill(json={'ok':False,'can_force':not body.get('force'),'error':'Fixture inspection warning'})
    tab.route('**/api/mesh_blend_extract',extraction)
    tab.evaluate("() => {window.action=meshBlendExtract('Fixture/SK_Test','Fixture mesh');}")
    tab.locator('#atelier-confirm-cancel').click();tab.evaluate('action');assert not extra
    for accept in (False,True):
        before=len(extra)
        tab.evaluate("() => {window.action=meshBlendExtract('Fixture/SK_Test','Fixture mesh');}")
        tab.locator('#atelier-confirm-ok').click()
        tab.locator('#atelier-confirm-title').filter(has_text='Extract for inspection').wait_for()
        tab.locator('#atelier-confirm-'+('ok' if accept else 'cancel')).click();tab.evaluate('action')
        assert len(extra)==before+1+int(accept)
        if accept:assert extra[-1]['force']==1
    tab.route('**/api/revert_imported',write)
    for accept in (False,True):
        before=len(calls)
        tab.evaluate("() => {window.action=revertImported({name:'Painted',game_rel:'Fixture/T_Test',file_type:'texture'});}")
        tab.locator('#atelier-confirm-'+('ok' if accept else 'cancel')).click();tab.evaluate('action')
        assert len(calls)==before+int(accept)
    checks.append('Blender extraction, inspection override and asset Revert require their themed answers before sending work')


def _setup(context,url,report,checks):
    rows="['game','key','map'].map(n=>document.querySelector(`#setup-rows [data-row=${n}]`).dataset.state).join()"
    well="document.querySelector('#setup-well [data-atelier-motion=setup-drop]')?.dataset"
    ink="document.querySelector('#setup-well [data-atelier-motion=ink-well]')?.dataset"
    for automatic in (True,False):
        tab=context.new_page();writes=[];errors=[];tab.on('pageerror',lambda e:errors.append(str(e)))
        try:
            tab.add_init_script("""const previous=window.fetch;window.fetch=(url,opts)=>String(url).startsWith('https://')?Promise.resolve({ok:true,json:async()=>({mainKey:'a'.repeat(64)})}):previous(url,opts);""" if automatic else """const previous=window.fetch;window.fetch=(url,opts)=>String(url).startsWith('https://')?Promise.reject(Error('Offline')):previous(url,opts);""")
            tab.route('**/api/setup_status',lambda route:route.fulfill(json={'configured':False,'paks_prefill':'D:/Steam/MarvelRivals'}))
            tab.route('**/api/validate_paks?*',lambda route:route.fulfill(json={'status':'ok'}))
            tab.route('**/api/validate_usmap?*',lambda route:route.fulfill(json={'status':'empty' if route.request.url.endswith('path=') else 'ok'}))
            tab.route('**/api/download_usmap',lambda route:route.fulfill(json={'ok':automatic,'path':'Fixture.usmap' if automatic else None}))
            def save(route):writes.append(route.request.post_data_json);route.fulfill(json={'ok':True})
            tab.route('**/api/save_paks',save)
            tab.goto(url);tab.wait_for_selector('#setup-overlay.active[data-setup-page=first-run]')
            # One page: what the check found, and only what is missing asks for input.
            assert tab.locator('#settings-theme').is_hidden() and tab.locator('#setup-title').is_hidden()
            assert tab.locator('#setup-save').inner_text().strip()=='Open Atelier'
            if automatic:
                tab.wait_for_function(rows+"==='done,done,done'")
                # One drop runs down past every valid row and falls into the well Open Atelier labels.
                tab.wait_for_function(well+".amFull==='true'",timeout=5000)
                # Landing is the export review's ink-well performing its success.
                assert tab.evaluate(ink+".amState")=='success'
                assert tab.locator('#setup-rows > li').evaluate_all('rows=>rows.map(r=>r.dataset.row).join()')=='key,map,game'
                assert tab.locator('#setup-well .at-setup-save-slot #setup-save').count()==1
                # One block to a stage, in the mark's order and exact colours, on one column with the well.
                blocks=tab.evaluate("""()=>[...document.querySelectorAll('#setup-rows > li')].map(row=>{
                  const block=row.querySelector('.at-setup-block'),box=block.getBoundingClientRect(),css=getComputedStyle(row);
                  return {piece:block.dataset.piece,color:getComputedStyle(block.querySelector('svg').firstElementChild).fill,x:box.left+box.width/2,rule:css.borderBottomWidth};})""")
                assert [b['piece'] for b in blocks]==['texture','mesh','material'],blocks
                assert [b['color'] for b in blocks]==['rgb(108, 152, 202)','rgb(90, 170, 154)','rgb(223, 143, 107)'],blocks
                assert all(b['rule']=='0px' for b in blocks),blocks
                centre=tab.evaluate("()=>{const box=document.getElementById('setup-well').getBoundingClientRect();return box.left+box.width/2}")
                assert all(abs(b['x']-centre)<1 for b in blocks),(blocks,centre)
                assert tab.locator('[data-row=game] .at-setup-what').inner_text()=='Found on this PC'
                assert tab.locator('[data-row=key] .at-setup-what').inner_text()=='Current key retrieved'
                # Each row's found glyph: the ink key, the code file, the folder; the well's lid is open.
                for row,found in (('key','key'),('map','file'),('game','folder')):
                    assert tab.locator(f'[data-row={row}] [data-atelier-motion=krackle-glyph][data-am-found={found}][data-am-state=success]').count()==1
                assert tab.evaluate(well+".amLid")=='open'
                assert tab.locator('#setup-page-title').inner_text()=='Ready to open Atelier'
                assert tab.locator('#setup-path').is_hidden() and tab.locator('#setup-save').is_enabled()
                tab.locator('[data-row=game] .at-setup-change').click()
                assert tab.locator('#setup-path').is_visible()
                for theme in ('dark','light'):
                    tab.evaluate("theme=>{const s=document.getElementById('settings-theme');s.value=theme;s.dispatchEvent(new Event('change',{bubbles:true}))}",theme)
                    tab.screenshot(path=str(report/f'trust-setup-{theme}.png'),animations='disabled')
            else:
                tab.wait_for_function(rows+"==='done,missing,missing'")
                # The key comes first, so the drop waits above it although the game was found.
                tab.wait_for_function(well+".amReached==='0' && "+well+".amFull==='false' && "+well+".amMoving==='false'",timeout=5000)
                # Waiting on the person, the well is alive: it cooks as it does in the export review,
                # and its lid is shut.
                tab.wait_for_function(ink+".amState==='busy' && "+ink+".amSleeping==='false'",timeout=3000)
                assert tab.evaluate(well+".amLid")=='shut'
                assert "couldn't be reached" in tab.locator('[data-row=key] .at-setup-what').inner_text()
                assert tab.locator('#setup-page-title').inner_text()=='Atelier needs two things from you'
                assert tab.locator('#setup-save').is_disabled() and tab.locator('#setup-aes').is_visible()
                tab.locator('#setup-aes').fill('0x'+'a'*64);tab.locator('#setup-usmap').fill('Fixture.usmap')
                tab.wait_for_function(rows+"==='done,done,done'")
                tab.wait_for_function(well+".amFull==='true'",timeout=5000)
                assert tab.locator('[data-row=key] .at-setup-what').inner_text()=='Key entered'
            tab.wait_for_function("document.querySelector('#setup-save:not(:disabled)')")
            tab.locator('#setup-save').click();tab.wait_for_function("!document.getElementById('setup-overlay').classList.contains('active')")
            assert writes==[{'path':'D:/Steam/MarvelRivals','aes_key':'a'*64,'usmap_path':'Fixture.usmap'}]
            # Settings keeps its full form with every control back in place.
            tab.evaluate('openPaths()')
            tab.wait_for_function("!document.getElementById('setup-loading').classList.contains('active')",timeout=20000)
            assert tab.locator('#setup-path').is_visible();assert tab.locator('#settings-theme').is_visible()
            assert tab.locator('#setup-page').is_hidden();assert tab.locator('#setup-save-label').inner_text()=='Save'
            assert tab.locator('#setup-overlay[data-setup-page]').count()==0
            assert tab.locator('#setup-well [data-atelier-motion], .am-setup-drop-flight').count()==0
            assert not errors,errors
        finally:tab.close()
    checks.append('First-run setup is one page that fills from the check and its ink-well, asks only for what is missing, supports offline fallback, preserves the save payload and keeps Settings as a full form')


def _launch_check(context,url,report,checks):
    watch = """document.addEventListener('DOMContentLoaded', () => {
      const overlay = document.getElementById('setup-overlay');
      window.__setupShown = overlay.classList.contains('active');
      new MutationObserver(() => {
        if (overlay.classList.contains('active')) window.__setupShown = true;
      }).observe(overlay, {attributes: true, attributeFilter: ['class']});
    });"""
    for fails in (False, True):
        tab = context.new_page()
        errors = []
        tab.on('pageerror', lambda error: errors.append(str(error)))
        try:
            tab.add_init_script(watch)
            held = []
            tab.route('**/api/setup_status', lambda route: held.append(route))
            with tab.expect_request('**/api/setup_status'):
                tab.goto(url)
            # Hold the answer beyond the former 400 ms cover delay.
            tab.wait_for_timeout(700)
            shown_while_pending = tab.evaluate('window.__setupShown')

            if fails:
                held.pop().fulfill(status=500, body='Traceback: boom')
                tab.wait_for_selector('#setup-overlay.active[data-setup-page=failed]')
                assert tab.locator('#setup-page-error').inner_text() == 'server error (500)'
                assert tab.locator('#setup-hero [data-atelier-motion=setup-check][data-am-state=error]').count() == 1
                tab.screenshot(path=str(report / 'trust-launch-failed.png'), animations='disabled')
                tab.unroute('**/api/setup_status')
                tab.route('**/api/setup_status', lambda route: route.fulfill(json={'configured': True}))
                tab.locator('#setup-retry').click()
            else:
                held.pop().fulfill(json={'configured': True})

            assert shown_while_pending is False, 'Setup opened while its status was still pending'
            tab.wait_for_selector('#grid-area .card')
            assert tab.locator('#setup-overlay.active').count() == 0
            assert tab.locator('#setup-hero [data-atelier-motion=setup-check]').count() == 0
            if not fails:
                assert tab.evaluate('window.__setupShown') is False
            assert not errors, errors
        finally:
            tab.close()
    checks.append('Slow configured launches open the Library without showing setup. Failed checks show a retry that can recover')
