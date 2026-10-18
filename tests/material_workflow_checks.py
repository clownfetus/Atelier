"""Material grouping, comparison and draft safety; all writes are intercepted."""
from pathlib import Path
from time import monotonic

ROOT = Path(__file__).resolve().parents[1]
VIEWPORT_HOOK = r"""
window.__materialWorkflowViewport = {
  seed() {
    generation++; materialGeneration++; saving=false; viewportProject=window.atelierProject();
    matsByName={}; edited={}; matData={Body:{game_rel:'Fixture/MI_Body', baseIdx:0, emiIdx:-1,
      colors:[{name:'Tint',rgba:[.2,.3,.4,1]}],scalars:[]}}; selectedMaterial='Body'; buildPanel();
  }, edit:()=>onColorInput('Body','Tint','#ff0000'),
  state:()=>({edited,colors:matData.Body.colors,hex:linToHex(matData.Body.colors[0].rgba)}), save:saveEdits
};
"""


def run_material_workflow_checks(page, context, url, report, checks):
    tab = context.new_page()
    errors, writes, delayed_params, delayed_original, delayed_saves = [], [], [], [], []
    tab.on('pageerror', lambda error: errors.append(str(error)))
    fixture = {'ok': True, 'colors': [
        {'name': 'Tint', 'rgba': [.25, .5, .75, 1]},
        {'name': 'Region 2 - ColorA', 'rgba': [.8, .2, .1, 1]},
        {'name': 'Region 2 - ColorB', 'rgba': [.4, .2, .1, 1]}],
        'scalars': [{'name': 'Roughness', 'value': .35}]}
    original = {'ok': True, 'colors': [
        {'name': 'Tint', 'rgba': [1, 1, 1, 1]},
        {'name': 'Region 2 - ColorA', 'rgba': [.2, .8, .1, 1]},
        {'name': 'Region 2 - ColorB', 'rgba': [.1, .8, .4, 1]}],
        'scalars': [{'name': 'Roughness', 'value': .8}]}
    behavior = {'original': 'ok', 'save': 'ok'}
    tab.route('**/static/viewport.js', lambda route: route.fulfill(
        body=(ROOT / 'gui/viewport.js').read_text(encoding='utf-8') + VIEWPORT_HOOK,
        content_type='text/javascript'))

    def params(route):
        if 'Delayed' in route.request.url:
            delayed_params.append(route)
        else:
            route.fulfill(json=fixture)

    def comparison(route):
        if behavior['original'] == 'delay':
            delayed_original.append(route)
        else:
            route.fulfill(json=original if behavior['original'] == 'ok' else {'ok': False, 'error': 'Fixture source unavailable'})

    def save(route):
        writes.append(route.request.post_data_json)
        if behavior['save'] == 'delay':
            delayed_saves.append(route)
        else:
            route.fulfill(json={'ok': True, 'inten_saved': True})

    tab.route('**/api/material_params?*', params)
    tab.route('**/api/material_original?*', comparison)
    tab.route('**/api/material_save', save)
    tab.route('**/api/dye_info?*', lambda route: route.fulfill(json={'dyeable': False}))
    tab.route('**/api/imported', lambda route: route.fulfill(json=[]))

    def open_editor(name='MI_Workflow'):
        tab.evaluate("name=>openMaterialEditor({name,game_rel:'Fixture/'+name})", name)
        tab.wait_for_selector('#mathx0')

    def pending(routes):
        deadline = monotonic() + 5
        while not routes and monotonic() < deadline:
            tab.wait_for_timeout(10)
        assert routes, 'Expected intercepted request'
        return routes.pop(0)

    try:
        tab.goto(url)
        tab.wait_for_function('window.atelierProject?.() && window.__materialWorkflowViewport')
        open_editor()
        assert tab.locator('.mat-parameter-group summary').all_text_contents() == ['Surface colors1', 'Dye region 22', 'Scalar parameters1']
        assert tab.evaluate('materialDirtyCount()') == 0
        assert 'Saved:' in tab.locator('#matrow0 .mat-reference').inner_text()
        tab.locator('#msn0').fill('.6')
        tab.locator('#msn0').dispatch_event('input')
        assert tab.evaluate('materialDirtyCount()') == 1
        assert tab.locator('#matscalar0').evaluate("el=>el.classList.contains('is-modified')")
        assert '1 unsaved' in tab.locator('#mat-dirty').inner_text()
        tab.locator('#matscalar0 .mat-restore').click()
        assert tab.evaluate('materialDirtyCount()') == 0
        assert tab.evaluate('matEditor.scalars[0].value') == .35
        tab.evaluate("matColor(0, '#ff0000')")
        before = tab.evaluate('JSON.stringify(materialSaveSnapshot(matEditor))')
        tab.get_by_role('button', name='Game original', exact=True).click()
        tab.wait_for_function("matEditor.compareMode==='original'")
        assert before == tab.evaluate('JSON.stringify(materialSaveSnapshot(matEditor))')
        assert not writes, 'Comparison modified the project'
        assert 'Game original:' in tab.locator('#matrow0 .mat-reference').inner_text()
        tab.locator('#matrow0 .mat-restore').click()
        assert tab.evaluate('matEditor.colors[0].rgba') == [1, 1, 1, 1]
        assert tab.evaluate('materialDirtyCount()') == 1
        tab.locator('#mat-revert').click()
        assert tab.evaluate('matEditor.colors[0].rgba') == [.25, .5, .75, 1]
        assert tab.evaluate('materialDirtyCount()') == 0
        checks.append('Material colors, dye regions and scalars are grouped; saved/game-original comparisons are read-only and per-row restore changes only the draft')

        tab.evaluate("matScalar(0, '.6', false)")
        tab.locator('#mat-close').click()
        tab.locator('#atelier-confirm-cancel').click()
        assert tab.locator('#material-overlay').evaluate("el=>el.classList.contains('active')")
        assert tab.evaluate("() => {const e=new Event('beforeunload',{cancelable:true}); window.dispatchEvent(e); return e.defaultPrevented;}")
        tab.locator('#mat-close').click()
        tab.locator('#atelier-confirm-ok').click()
        assert tab.evaluate('matEditor') is None
        open_editor('MI_Unavailable')
        behavior['original'] = 'fail'
        tab.get_by_role('button', name='Game original', exact=True).click()
        tab.wait_for_function("document.getElementById('mat-status').textContent.includes('unavailable')")
        assert tab.evaluate('matEditor.compareMode') == 'saved'
        assert not writes
        behavior['original'] = 'delay'
        tab.evaluate("() => {window.pendingOriginal=matCompare('original');}")
        old = pending(delayed_original)
        tab.evaluate('closeMaterialEditor()')
        open_editor('MI_New')
        old.fulfill(json=original)
        tab.evaluate('pendingOriginal')
        assert tab.evaluate('matEditor.name') == 'MI_New'
        assert tab.evaluate('matEditor.compareMode') == 'saved'
        tab.evaluate('closeMaterialEditor()')
        tab.evaluate("() => {window.pendingOpen=openMaterialEditor({name:'Delayed',game_rel:'Fixture/Delayed'});}")
        old = pending(delayed_params)
        tab.evaluate('closeMaterialEditor()')
        open_editor('MI_Replacement')
        old.fulfill(json=fixture)
        tab.evaluate('pendingOpen')
        assert tab.evaluate('matEditor.name') == 'MI_Replacement'
        checks.append('Material dirty drafts guard close/reload; original-read errors stay explicit and stale comparison/open responses cannot replace a newer editor')

        behavior['save'] = 'delay'
        tab.evaluate("() => {matScalar(0,'.5',false); window.workflowSave=saveMaterial();}")
        old = pending(delayed_saves)
        tab.evaluate("matScalar(0,'.7',false)")
        old.fulfill(json={'ok': True, 'inten_saved': True})
        tab.evaluate('workflowSave')
        assert tab.evaluate('matEditor.scalars[0].value') == .7
        assert tab.evaluate("_matReference('scalars',0,'saved').value") == .5
        assert tab.evaluate('materialDirtyCount()') == 1
        assert '1 unsaved' in tab.locator('#mat-dirty').inner_text()
        for theme in ('light', 'dark'):
            tab.locator('#settings-theme').evaluate('(el,value)=>{el.value=value;el.dispatchEvent(new Event("change"));}', theme)
            tab.wait_for_timeout(250)
            tab.screenshot(path=str(report / f'material-workflow-{theme}.png'))
            assert tab.locator('#material-overlay .mat-modal').evaluate('el=>el.scrollWidth<=el.clientWidth')
        tab.evaluate('closeMaterialEditor(true); __materialWorkflowViewport.seed()')
        tab.evaluate('__materialWorkflowViewport.edit()')
        assert tab.evaluate('Object.keys(__materialWorkflowViewport.state().edited).length') == 1
        tab.locator('.vp-saved-swatch').evaluate('el=>el.click()')
        assert tab.evaluate('Object.keys(__materialWorkflowViewport.state().edited).length') == 0
        assert tab.locator('#viewport-mat-reset').is_disabled()
        tab.evaluate('() => {__materialWorkflowViewport.edit(); window.workflowViewportSave=__materialWorkflowViewport.save();}')
        old = pending(delayed_saves)
        old.fulfill(json={'ok': True})
        tab.evaluate('workflowViewportSave')
        saved=tab.evaluate('__materialWorkflowViewport.state()')
        assert saved['colors'][0]['rgba']==writes[-1]['colors']['Tint']
        assert saved['hex']=='#ff0000' and saved['colors'][0]['rgba'][0]>1
        assert saved['colors'][0]['rgba'][1:]==[0,0,1]
        assert tab.evaluate('Object.keys(__materialWorkflowViewport.state().edited).length') == 0
        checks.append('Save completion advances only the submitted baseline; newer drafts remain dirty and viewport saved swatches revert exactly to the last successful save')
        assert not errors, errors
    finally:
        tab.close()
