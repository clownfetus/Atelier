"""Material save feedback and originating-draft safety, with intercepted save requests only."""
from pathlib import Path
from time import monotonic
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
VIEWPORT_HOOK = r"""
window.__materialSaveViewport = {
  seed(names=['Body','Hair'], project=window.atelierProject()) {
    generation++; materialGeneration++; saving=false; viewportProject=project;
    matsByName={}; edited=Object.fromEntries(names.map(name=>[name,{Tint:[1,0,0,1]}]));
    matData=Object.fromEntries(names.map(name=>[name,{
      game_rel:'Fixture/MI_'+name, colors:[{name:'Tint',rgba:[1,1,1,1]}]
    }]));
    document.getElementById('viewport-status').textContent=''; refreshFoot();
  },
  state:()=>({edited,saving,project:viewportProject}),
  edit:(name,rgba)=>{(edited[name] ||= {}).Tint=rgba;},
  save:saveEdits,
  replace() {
    generation++; materialGeneration++; edited={New:{Tint:[0,0,1,1]}};
    viewportProject='Other project';
    document.getElementById('viewport-status').textContent='New viewport status';
  }
};
"""


def run_material_save_motion_checks(page, context, url, report, checks):
    material_page = context.new_page()
    errors, requests, pending = [], [], []
    material_page.on('pageerror', lambda error: errors.append(str(error)))
    material_page.route('**/static/viewport.js', lambda route: route.fulfill(
        body=(ROOT / 'gui/viewport.js').read_text(encoding='utf-8') + VIEWPORT_HOOK,
        content_type='text/javascript'))
    material_page.route('**/api/material_params?*', lambda route: route.fulfill(json={
        'ok': True, 'colors': [{'name': 'Tint', 'rgba': [.25, .5, .75, 1]}],
        'scalars': [{'name': 'Roughness', 'value': .35}]}))
    material_page.route('**/api/dye_info?*', lambda route: route.fulfill(json={'dyeable': False}))
    material_page.route('**/api/imported', lambda route: route.fulfill(json=[]))
    response = {'payload': {'ok': True, 'inten_saved': True}, 'defer': False, 'abort': False}

    def save_fixture(route):
        requests.append({'body': route.request.post_data_json,
                         'project': route.request.headers.get('x-atelier-project')})
        if response['defer']:
            pending.append(route)
        elif response['abort']:
            route.abort('failed')
        else:
            route.fulfill(json=response['payload'])

    material_page.route('**/api/material_save', save_fixture)

    def clear_toasts():
        material_page.evaluate("document.querySelectorAll('#toast-area .toast').forEach(el=>el.remove())")

    def open_editor(name='MI_Fixture'):
        material_page.evaluate("name=>openMaterialEditor({name,game_rel:'Fixture/'+name})", name)
        material_page.wait_for_selector('#mathx0')

    def wait_editor_closed():
        # Editor transitions may commit their class change after saveMaterial resolves.
        material_page.locator('#material-overlay.active').wait_for(state='detached')

    def state_toasts(state):
        return material_page.locator(f'#toast-area [data-atelier-motion="material-save"][data-am-state="{state}"]')

    def wait_pending(count):
        deadline = monotonic() + 5
        while len(pending) < count and monotonic() < deadline:
            material_page.wait_for_timeout(10)
        assert len(pending) >= count, (len(pending), count)

    def start_save(expression='saveMaterial()', promise='materialSavePending'):
        count = len(pending)
        material_page.evaluate(f'() => {{ window.{promise}={expression}; }}')
        wait_pending(count + 1)
        return pending[count]

    try:
        material_page.goto(url)
        material_page.wait_for_function('window.__materialSaveViewport && window.AtelierMotion?.materialSave && window.AtelierMaterialSaveFeedback && window.atelierProject?.()')
        material_page.wait_for_selector('#grid-area .card')
        material_page.emulate_media(reduced_motion='no-preference')
        material_page.evaluate(r"""() => {
          window.materialMotionHost=document.createElement('span'); document.body.append(materialMotionHost);
          window.materialMotion=AtelierMotion.materialSave.mount(materialMotionHost,{state:'saving'});
          window.materialEffects=materialMotionHost.getAnimations({subtree:true});
          if (!materialEffects.length) throw Error('Saving did not animate');
          materialMotion.setState('saving');
          if (!materialEffects.every(a=>materialMotionHost.getAnimations({subtree:true}).includes(a)))
            throw Error('Repeated saving restarted the loop');
          materialMotion.setState('success');
          if (!materialEffects.every(a=>a.playState==='idle')) throw Error('Saving survived success');
        }""")
        for state in ('success', 'warning', 'error'):
            material_page.evaluate('state=>materialMotion.setState(state)', state)
            material_page.wait_for_function('!materialMotionHost.getAnimations({subtree:true}).length')
            assert material_page.evaluate(f'getComputedStyle(materialMotionHost.querySelector(".am-material-save-outcome-{state}")).opacity') == '1'
        material_page.evaluate(r"""() => {
          materialMotion.setState('saving');
          const previous=materialMotion, effects=materialMotionHost.getAnimations({subtree:true});
          materialMotion=AtelierMotion.materialSave.mount(materialMotionHost,{state:'saving'});
          previous.destroy(); previous.setState('error');
          if (!effects.every(a=>a.playState==='idle') || materialMotionHost.querySelectorAll('svg').length!==1)
            throw Error('Duplicate mount retained old effects/artwork');
          if (materialMotionHost.dataset.amState!=='saving') throw Error('Old handle modified replacement');
        }""")
        material_page.emulate_media(reduced_motion='reduce')
        material_page.wait_for_function("materialMotionHost.dataset.amReduced==='true' && !materialMotionHost.getAnimations({subtree:true}).length")
        material_page.evaluate("materialMotion.setState('success'); materialMotion.replay()")
        assert material_page.evaluate('materialMotionHost.getAnimations({subtree:true}).length') == 0
        material_page.emulate_media(reduced_motion='no-preference')
        material_page.evaluate("materialMotion.setReducedMotion('reduce'); materialMotion.setState('saving')")
        assert material_page.evaluate('materialMotionHost.getAnimations({subtree:true}).length') == 0
        material_page.evaluate(r"""() => {
          materialMotion.setReducedMotion('system');
          Object.defineProperty(document,'hidden',{configurable:true,get:()=>window.materialHidden});
          window.materialHidden=true; document.dispatchEvent(new Event('visibilitychange'));
          if (materialMotionHost.getAnimations({subtree:true}).length) throw Error('Hidden save still animates');
          materialHidden=false; document.dispatchEvent(new Event('visibilitychange'));
          if (!materialMotionHost.getAnimations({subtree:true}).length) throw Error('Pending save did not resume');
          materialHidden=true; document.dispatchEvent(new Event('visibilitychange'));
          materialMotion.setState('success');
          materialHidden=false; document.dispatchEvent(new Event('visibilitychange'));
          if (materialMotionHost.getAnimations({subtree:true}).length) throw Error('Hidden completion replayed');
          delete document.hidden;
          materialMotion.destroy(); materialMotion.destroy(); materialMotion.setState('saving');
          if (materialMotionHost.querySelector('svg')) throw Error('Destroy left save SVG');
          const original=Element.prototype.animate;
          try {
            for (const mode of ['missing','throwing','partial']) {
              let calls=0;
              Element.prototype.animate=mode==='missing' ? undefined : function(...args) {
                if (mode==='throwing' || ++calls===2) throw Error('Fixture WAAPI failure');
                return original.apply(this,args);
              };
              const instance=AtelierMotion.materialSave.mount(materialMotionHost,{state:'saving'});
              instance.setState('success');
              if (!materialMotionHost.querySelector('svg')) throw Error('WAAPI failure lost static result');
              instance.destroy();
              if (materialMotionHost.getAnimations({subtree:true}).length) throw Error('WAAPI failure leaked effects');
            }
          } finally { Element.prototype.animate=original; }
          materialMotionHost.remove();
          window.materialOriginalProject=_activeProjectName; _activeProjectName='Save Ω';
        }""")
        checks.append('Material-save SVG settles outcomes, handles remounts/reduced motion/visibility and survives absent or partially failing WAAPI')

        clear_toasts()
        open_editor()
        material_page.evaluate('saveMaterial()')
        wait_editor_closed()
        assert state_toasts('success').count() == 1
        assert requests[-1] == {'project': quote('Save Ω', safe=''), 'body': {
            'game_rel': 'Fixture/MI_Fixture', 'colors': {'Tint': [.25, .5, .75, 1]},
            'scalars': {'Roughness': .35}, 'inten': {}}}, requests[-1]
        clear_toasts()
        open_editor('MI_Intensity')
        material_page.evaluate('matEditor.colors[0].inten=4')
        response['payload'] = {'ok': True, 'inten_saved': False}
        material_page.evaluate('saveMaterial()')
        assert requests[-1]['body']['inten'] == {'Tint': 4}
        assert state_toasts('warning').count() >= 1 and state_toasts('success').count() == 0
        assert 'intensit' in material_page.locator('#toast-area').inner_text().lower()
        checks.append('Dialog saves preserve project header and material payload; failed intensity persistence reports warning instead of full success')

        for abort in (False, True):
            clear_toasts()
            open_editor('MI_Retry')
            material_page.evaluate('matEditor.colors[0].rgba=[.8,.2,.1,1]')
            submitted = material_page.evaluate('JSON.stringify(matEditor)')
            response.update(payload={'ok': False, 'error': 'Fixture save failure'}, abort=abort)
            material_page.evaluate('saveMaterial()')
            assert material_page.locator('#material-overlay').evaluate('el=>el.classList.contains("active")')
            assert material_page.evaluate('JSON.stringify(matEditor)') == submitted
            assert state_toasts('error').count() >= 1
            response.update(payload={'ok': True, 'inten_saved': True}, abort=False)
            material_page.evaluate('saveMaterial()')
            assert requests[-1]['body']['colors']['Tint'] == [.8, .2, .1, 1]
            wait_editor_closed()
        checks.append('Failed and rejected saves retain dialog drafts and allow retry without replaying stale outcome state')

        clear_toasts()
        response['defer'] = True
        open_editor('MI_Changing')
        first = start_save()
        before = len(requests)
        material_page.evaluate('() => { window.duplicateMaterialDone=false; saveMaterial().then(()=>duplicateMaterialDone=true); }')
        material_page.wait_for_function('duplicateMaterialDone', timeout=2000)
        assert len(requests) == before, 'Duplicate click issued a second request for the same draft'
        material_page.evaluate('matEditor.colors[0].rgba=[0,0,1,1]')
        first.fulfill(json={'ok': True, 'inten_saved': True})
        material_page.evaluate('materialSavePending')
        assert material_page.evaluate('matEditor.colors[0].rgba') == [0, 0, 1, 1]
        assert material_page.locator('#material-overlay').evaluate('el=>el.classList.contains("active")')
        assert state_toasts('warning').count() >= 1
        second = start_save()
        assert requests[-1]['body']['colors']['Tint'] == [0, 0, 1, 1]
        second.fulfill(json={'ok': True, 'inten_saved': True})
        material_page.evaluate('materialSavePending')
        wait_editor_closed()
        for stale_case in ('closed', 'reopened', 'project'):
            open_editor('MI_Origin')
            old = start_save()
            if stale_case in ('closed', 'reopened'):
                material_page.evaluate('closeMaterialEditor(true)')
            if stale_case == 'reopened':
                open_editor('MI_Newer')
                material_page.locator('#mat-status').evaluate("el=>el.textContent='New draft status'")
            if stale_case == 'project':
                material_page.evaluate("_activeProjectName='Other project'; document.getElementById('mat-status').textContent='Other project status'")
            old.fulfill(json={'ok': True, 'inten_saved': True})
            material_page.evaluate('materialSavePending')
            assert requests[-1]['project'] == quote('Save Ω', safe='')
            if stale_case == 'closed':
                assert material_page.evaluate('matEditor') is None
            elif stale_case == 'reopened':
                assert material_page.evaluate('matEditor.name') == 'MI_Newer'
                assert material_page.locator('#mat-status').inner_text() == 'New draft status'
            else:
                assert material_page.locator('#mat-status').inner_text() == 'Other project status'
            material_page.evaluate("closeMaterialEditor(true); _activeProjectName='Save Ω'")
        checks.append('In-flight dialog saves deduplicate, retain newer edits and cannot close or overwrite a later dialog/project')

        clear_toasts()
        material_page.evaluate('__materialSaveViewport.seed()')
        body = start_save('__materialSaveViewport.save()', 'viewportSavePending')
        count = len(pending)
        body.fulfill(json={'ok': True})
        wait_pending(count + 1)
        pending[count].fulfill(json={'ok': False, 'error': 'Fixture Hair failure'})
        material_page.evaluate('viewportSavePending')
        state = material_page.evaluate('__materialSaveViewport.state()')
        assert list(state['edited']) == ['Hair'] and not state['saving'], state
        assert state_toasts('warning').count() >= 1 and state_toasts('success').count() == 0
        response['defer'] = False
        response['payload'] = {'ok': True}
        material_page.evaluate('__materialSaveViewport.save()')
        assert not material_page.evaluate('__materialSaveViewport.state().edited')
        assert requests[-1]['body'] == {'game_rel': 'Fixture/MI_Hair', 'colors': {'Tint': [1, 0, 0, 1]}, 'scalars': {}}
        assert requests[-1]['project'] == quote('Save Ω', safe='')
        clear_toasts()
        response['defer'] = True
        material_page.evaluate("__materialSaveViewport.seed(['Body'])")
        old = start_save('__materialSaveViewport.save()', 'viewportSavePending')
        material_page.evaluate("__materialSaveViewport.edit('Body',[0,0,1,1])")
        old.fulfill(json={'ok': True})
        material_page.evaluate('viewportSavePending')
        assert material_page.evaluate('__materialSaveViewport.state().edited.Body.Tint') == [0, 0, 1, 1]
        assert state_toasts('warning').count() >= 1 and state_toasts('success').count() == 0
        material_page.evaluate("__materialSaveViewport.seed(['Body'])")
        old = start_save('__materialSaveViewport.save()', 'viewportSavePending')
        material_page.evaluate('__materialSaveViewport.replace()')
        old.fulfill(json={'ok': True})
        material_page.evaluate('viewportSavePending')
        assert material_page.locator('#viewport-status').inner_text() == 'New viewport status'
        assert material_page.evaluate('__materialSaveViewport.state().edited.New.Tint') == [0, 0, 1, 1]
        assert not material_page.evaluate('__materialSaveViewport.state().saving')
        clear_toasts()
        material_page.evaluate("__materialSaveViewport.seed(['Body'])")
        old = start_save('__materialSaveViewport.save()', 'viewportSavePending')
        material_page.evaluate("_activeProjectName='Other project'; document.getElementById('viewport-status').textContent='Other project status'")
        old.fulfill(json={'ok': True})
        material_page.evaluate('viewportSavePending')
        assert not material_page.evaluate('__materialSaveViewport.state().saving')
        assert material_page.locator('#viewport-status').inner_text() == 'Other project status'
        assert 'Save Ω:' in material_page.locator('#toast-area').inner_text()
        material_page.evaluate("_activeProjectName='Save Ω'")
        checks.append('Viewport saves retain failed/newer recolors, retry the correct payload and leave replacement viewport status untouched')

        response.update(defer=False, payload={'ok': True, 'inten_saved': True})
        material_page.evaluate('window.originalMaterialPresentation=AtelierMaterialSaveFeedback')
        for failure in ('missing', 'throwing'):
            clear_toasts()
            material_page.evaluate("failure=>{window.AtelierMaterialSaveFeedback=failure==='missing' ? undefined : {toast:()=>{throw Error('Fixture presentation failure')}}; window.materialInjected=false;}", failure)
            name = f'MI_{failure} <img src=x onerror="window.materialInjected=true"> & Ω'
            open_editor(name)
            before = len(requests)
            material_page.evaluate('saveMaterial()')
            assert len(requests) == before + 1
            assert name in material_page.locator('#toast-area').inner_text()
            assert material_page.locator('#toast-area img').count() == 0
            assert not material_page.evaluate('materialInjected')
            wait_editor_closed()
            open_editor(name)
            message = '<img src=x onerror="window.materialInjected=true"> fixture error & Ω'
            response['payload'] = {'ok': False, 'error': message}
            material_page.evaluate('saveMaterial()')
            assert message in material_page.locator('#toast-area').inner_text()
            assert material_page.locator('#toast-area img').count() == 0
            assert not material_page.evaluate('materialInjected')
            material_page.evaluate('closeMaterialEditor(true)')
            response['payload'] = {'ok': True, 'inten_saved': True}
        material_page.evaluate('window.AtelierMaterialSaveFeedback=originalMaterialPresentation')
        clear_toasts()
        material_page.evaluate(r"""() => {
          const original=AtelierMotion.materialSave;
          try {
            for (const failure of ['missing','mount']) {
              AtelierMotion.materialSave=failure==='missing' ? undefined : {mount:()=>{throw Error('Fixture mount failure')}};
              const el=toastMaterialSave('Static save fallback','error',5000);
              if (!el?.isConnected || !el.textContent.includes('Static save fallback')) throw Error('Lost static save message');
              el.remove();
            }
          } finally { AtelierMotion.materialSave=original; }
        }""")
        checks.append('Missing or throwing save presentation preserves successful requests and renders filenames/errors as text with static fallback')

        material_page.evaluate(r"""() => {
          window.materialToast=AtelierMaterialSaveFeedback.toast('Saving fixture','saving',0);
          window.materialToastEffects=materialToast.getAnimations({subtree:true});
          if (!materialToastEffects.length) throw Error('Saving toast did not animate');
          materialToast.remove(); materialToast.remove();
          if (!materialToastEffects.every(a=>a.playState==='idle')) throw Error('Toast removal leaked motion');
          window.clickedMaterialToast=AtelierMaterialSaveFeedback.toast('Saved fixture','success',5000);
          clickedMaterialToast.click();
          window.timedMaterialToast=AtelierMaterialSaveFeedback.toast('Saved fixture','success',60);
        }""")
        material_page.wait_for_function('!materialToast.isConnected && !clickedMaterialToast.isConnected && !timedMaterialToast.isConnected')
        clear_toasts()
        response['defer'] = True
        open_editor('MI_Save_feedback')
        save = start_save()
        for theme in ('light', 'dark'):
            material_page.locator('#settings-theme').evaluate('(el,value)=>{el.value=value;el.dispatchEvent(new Event("change"));}', theme)
            # Production keeps pending feedback in the existing footer; only completed
            # saves use the new notification artwork. Do not invent a busy toast here.
            assert material_page.locator('#mat-status').inner_text() == 'Saving…'
            assert material_page.locator('#material-overlay').evaluate('el=>el.classList.contains("active")')
            material_page.screenshot(path=str(report / f'material-save-saving-{theme}.png'), animations='disabled')
        save.fulfill(json={'ok': True, 'inten_saved': True})
        material_page.evaluate('materialSavePending')
        for theme in ('light', 'dark'):
            material_page.locator('#settings-theme').evaluate('(el,value)=>{el.value=value;el.dispatchEvent(new Event("change"));}', theme)
            svg = state_toasts('success').locator('svg')
            box = svg.bounding_box()
            assert box['width'] == 24 and box['height'] == 24, box
            material_page.screenshot(path=str(report / f'material-save-success-{theme}.png'), animations='disabled')
        checks.append('Save toasts clean up on removal/click/timeout and retain a readable 24px footprint in both themes during real fixture saves')
        assert not errors, errors
    finally:
        material_page.unroute_all(behavior='ignoreErrors')
        material_page.close()
