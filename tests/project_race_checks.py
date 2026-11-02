"""Queued project reads and debounced build selections retain their originating project."""
from urllib.parse import parse_qs, unquote, urlparse


def run_project_race_checks(context, url, report, checks):
    _dock_project_switch(context, url, checks)
    _selection_rename(context, url, checks)


def _dock_project_switch(context, url, checks):
    page = context.new_page()
    errors, reads, held_read, held_delete = [], [], [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    items = {
        name: [dict(token=f'{name}-{i}', name=f'MI_Part{i}', game_rel=f'Fixture/Materials/MI_Part{i}',
                    file_type='material', selected=True, mtime=1) for i in numbers]
        for name, numbers in [('Smoke A', (1, 2)), ('Smoke B', (3,))]
    }
    page.route('**/api/imported', lambda route: route.fulfill(json=items.get(
        unquote(route.request.headers.get('x-atelier-project', '')), [])))

    def changes(route):
        project = unquote(route.request.headers.get('x-atelier-project', ''))
        path = parse_qs(urlparse(route.request.url).query)['game_rel'][0]
        reads.append((project, path))
        if len(reads) == 1:
            held_read.append(route)
        else:
            route.fulfill(json={'ok': True, 'changes': [{'name': 'Tint', 'before': '#000000', 'after': '#ffffff'}]})

    page.route('**/api/material_changes?*', changes)
    page.route('**/api/delete_imported', lambda route: held_delete.append(route))
    try:
        page.goto(url)
        page.wait_for_selector('#grid-area .card')
        original = page.evaluate('atelierProject()')
        if original != 'Smoke A':
            page.evaluate("_selectProject('Smoke A')")
        page.wait_for_selector('.workspace-slot[data-token="Smoke A-2"]', state='attached')
        page.wait_for_function('document.querySelectorAll(".sb-item").length===2')
        # The dock shares the same saved edits while Library is open; reveal its existing
        # Restore control without loading a game model for this race regression.
        page.evaluate("AtelierViewport.reloadMaterials=()=>{(window.__raceReloads||=[]).push(atelierProject());};window.__raceReloads=[]")
        page.locator('.workspace-slot[data-token="Smoke A-2"] .workspace-restore').evaluate('button=>button.click()')
        page.locator('#atelier-confirm-ok').click()
        page.locator('#project-chip').click()
        page.locator('#proj-grid [data-name="Smoke B"]').click()
        page.wait_for_function('atelierProject()==="Smoke B" && !_projectOpening')
        assert len(held_read) == len(held_delete) == 1
        held_read.pop().fulfill(json={'ok': True, 'changes': [{'name': 'Tint', 'before': '#000000', 'after': '#ff0000'}]})
        with page.expect_response('**/api/delete_imported'):
            held_delete.pop().fulfill(json={'ok': True, 'deleted': 1})
        page.wait_for_selector('.workspace-slot[data-token="Smoke B-3"][data-changes="1"]', state='attached')
        assert ('Smoke A', 'Fixture/Materials/MI_Part2') in reads, reads
        assert ('Smoke B', 'Fixture/Materials/MI_Part3') in reads, reads
        page.evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
        assert not page.evaluate('__raceReloads'), page.evaluate('__raceReloads')
        page.evaluate('name=>_selectProject(name)', original)
        assert not errors, errors
        checks.append('Queued dock comparisons keep their originating project; a Restore finishing after a project switch cannot reload the new project')
    finally:
        page.close()


def _selection_rename(context, url, checks):
    from pathlib import Path
    from atelier import config as C, project_meta

    page = context.new_page()
    errors, writes = [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    # Keep the debounce pending long enough to rename through the real UI. Flushing
    # before rename must not depend on the timer firing or on network request order.
    page.add_init_script("""(() => {const schedule=window.setTimeout;
      window.setTimeout=(callback,delay,...args)=>schedule(callback,delay===400?10000:delay,...args);
    })();""")
    page.on('request', lambda request: writes.append((urlparse(request.url).path,
        unquote(request.headers.get('x-atelier-project', ''))))
        if request.method == 'POST' and urlparse(request.url).path in
        ('/api/project/asset_selection', '/api/project/rename') else None)
    try:
        page.goto(url)
        page.wait_for_selector('#grid-area .card')
        original = page.evaluate('atelierProject()')
        page.evaluate("""() => {sidebarData={pending:{token:'pending',name:'T_Pending',file_type:'texture',
          game_rel:'Fixture/T_Pending',selected:false}};saveSelection();}""")
        page.locator('#project-chip').click()
        target = page.locator('#proj-grid [data-name]').filter(has=page.get_by_title(original, exact=True))
        target.hover()
        target.locator('[data-action=rename]').click()
        page.locator('#proj-name-input').fill('Selection rename fixture')
        page.route('**/api/project/asset_selection', lambda route: route.fulfill(json={'ok': False, 'error': 'Fixture write failure'}))
        page.locator('#proj-name-ok').click()
        page.wait_for_selector('#proj-name-error:not([hidden])')
        assert page.locator('#proj-name-input').input_value() == 'Selection rename fixture'
        assert not any(path=='/api/project/rename' for path, _ in writes), writes
        page.unroute('**/api/project/asset_selection')
        page.locator('#proj-name-ok').click()
        page.wait_for_function("!_projNameBusy")
        assert not page.locator('#proj-name-error').is_visible(), (page.locator('#proj-name-error').inner_text(), writes)
        page.locator('#proj-name-overlay').wait_for(state='hidden')
        page.wait_for_function('atelierProject()==="Selection rename fixture"')
        assert writes[:3] == [('/api/project/asset_selection', original),
                              ('/api/project/asset_selection', original), ('/api/project/rename', original)], writes
        assert project_meta.get_deselected(str(Path(C.PROJECTS_ROOT, 'Selection rename fixture'))) == {'Fixture/T_Pending'}
        target = page.locator('#proj-grid [data-name="Selection rename fixture"]')
        target.hover()
        target.locator('[data-action=rename]').click()
        page.locator('#proj-name-input').fill(original)
        page.locator('#proj-name-ok').click()
        page.locator('#proj-name-overlay').wait_for(state='hidden')
        page.wait_for_function('name=>atelierProject()===name', arg=original)
        page.evaluate("""() => {sidebarData={pending:{token:'pending',name:'T_Copy',file_type:'texture',
          game_rel:'Fixture/T_Copy',selected:false}};saveSelection();}""")
        target = page.locator('#proj-grid [data-name]').filter(has=page.get_by_title(original, exact=True))
        target.hover()
        target.locator('[data-action=duplicate]').click()
        page.locator('#proj-name-input').fill('Selection copy fixture')
        page.locator('#proj-name-ok').click()
        page.locator('#proj-name-overlay').wait_for(state='hidden')
        assert project_meta.get_deselected(str(Path(C.PROJECTS_ROOT, 'Selection copy fixture'))) == {'Fixture/T_Copy'}
        assert not errors, errors
        checks.append('Rename and Duplicate flush pending build selections first; failed saves keep the form retryable and copied/renamed projects retain inclusion state')
    finally:
        page.close()
