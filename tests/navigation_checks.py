"""Recoverable project forms, keyboard selection and interruptible Workspace loading."""


def run_navigation_checks(context, url, report, checks):
    from project_race_checks import run_project_race_checks
    run_project_race_checks(context, url, report, checks)
    run_home_folder_checks(context, url, report, checks)
    page = context.new_page()
    errors, workspace_writes = [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('request', lambda request: workspace_writes.append(request.url)
            if request.method == 'POST' and request.url.endswith('/api/project/workspace') else None)
    page.route('**/api/catalogue/library', lambda route: route.fulfill(json={'heroes': [
        {'name': 'Magik', 'path': 'Characters/1029', 'skins': [
            {'name': 'Original costume', 'path': 'Characters/1029/1029001'}]}]}))
    page.route('**/api/catalogue/hero/**', lambda route: route.fulfill(status=404, body='No artwork in this fixture'))

    def picker():
        page.locator('#project-chip').click()
        page.wait_for_selector('#project-overlay.active .proj-card')

    def card(name):
        return page.locator('#proj-grid [data-name]').filter(has=page.get_by_title(name, exact=True))

    def action(name, action):
        target = card(name)
        target.hover()
        target.locator(f'[data-action={action}]').click()
        page.wait_for_selector('#proj-name-overlay.active')

    try:
        page.goto(url)
        page.wait_for_selector('#grid-area .card')
        original = page.evaluate('atelierProject()')
        page.screenshot(path=str(report / '01-library-after.png'), animations='disabled')
        picker()
        page.locator('#proj-new-btn').click()
        page.locator('#proj-name-input').press('Enter')
        assert page.locator('#proj-name-error').inner_text() == 'Enter a project name.'
        assert page.locator('#proj-name-input').get_attribute('aria-invalid') == 'true'

        held = []
        page.route('**/api/project/create', lambda route: held.append(route))
        page.locator('#proj-name-input').fill('Retry UI project')
        page.locator('#proj-name-ok').click()
        assert page.locator('#proj-name-ok').is_disabled()
        assert page.locator('#proj-name-cancel').is_disabled()
        assert page.locator('#proj-name-input').get_attribute('readonly') is not None
        assert page.locator('.at-proj-name').get_attribute('aria-busy') == 'true'
        page.locator('#proj-name-input').press('Enter')
        assert len(held) == 1
        held.pop().fulfill(json={'ok': False, 'error': 'A project with this name already exists.'})
        page.wait_for_selector('#proj-name-error:not([hidden])')
        assert page.locator('#proj-name-overlay').is_visible()
        assert page.locator('#proj-name-input').input_value() == 'Retry UI project'
        assert page.locator('#proj-name-ok').is_enabled()
        page.locator('#proj-name-input').focus()
        page.keyboard.press('Shift+Tab')
        assert page.locator('#proj-name-ok').evaluate('el=>el===document.activeElement')
        page.keyboard.press('Tab')
        assert page.locator('#proj-name-input').evaluate('el=>el===document.activeElement')
        page.screenshot(path=str(report / '02-project-error-after.png'), animations='disabled')
        page.unroute('**/api/project/create')
        page.locator('#proj-name-ok').click()
        page.wait_for_function('atelierProject()==="Retry UI project" && !_projectOpening')
        page.locator('#proj-name-overlay').wait_for(state='hidden')
        page.locator('#project-overlay').wait_for(state='hidden')
        assert page.locator('#page-library').get_attribute('aria-current') == 'page'
        checks.append('Project naming keeps errors and typed names in the form, blocks duplicate submissions, traps Tab and retries without reopening')

        picker()
        action('Retry UI project', 'rename')
        page.locator('#proj-name-input').fill(original)
        page.locator('#proj-name-ok').click()
        page.wait_for_selector('#proj-name-error:not([hidden])')
        assert page.locator('#proj-name-input').input_value() == original
        page.locator('#proj-name-input').fill('UI renamed project')
        page.locator('#proj-name-ok').click()
        page.wait_for_function('atelierProject()==="UI renamed project"')
        page.locator('#proj-name-overlay').wait_for(state='hidden')
        assert page.locator('#project-chip-name').inner_text() == 'UI renamed project'
        assert page.locator('#mod-name-input').input_value() == 'UI renamed project'
        assert page.locator('#proj-close').is_visible()
        assert card('UI renamed project').evaluate('el=>el===document.activeElement')
        page.screenshot(path=str(report / '03-active-rename-after.png'), animations='disabled')
        page.locator('#proj-close').click()
        page.locator('#project-overlay').wait_for(state='hidden')
        page.locator('#mod-name-input').fill('MyCustomMod')
        picker()
        action('UI renamed project', 'rename')
        page.locator('#proj-name-input').fill('UI temporary name')
        page.locator('#proj-name-ok').click()
        page.locator('#proj-name-overlay').wait_for(state='hidden')
        assert page.evaluate('atelierProject()') == 'UI temporary name'
        assert page.locator('#mod-name-input').input_value() == 'MyCustomMod'
        action('UI temporary name', 'rename')
        page.locator('#proj-name-input').fill('UI renamed project')
        page.locator('#proj-name-ok').click()
        page.locator('#proj-name-overlay').wait_for(state='hidden')
        assert page.locator('#mod-name-input').input_value() == 'MyCustomMod'
        checks.append('Renaming updates the active project and default mod filename, preserves custom filenames, and keeps the picker closable with focus on the renamed card')

        action('UI renamed project', 'duplicate')
        page.route('**/api/project/duplicate', lambda route: route.abort())
        page.locator('#proj-name-input').fill('Network retry copy')
        page.locator('#proj-name-ok').click()
        page.wait_for_selector('#proj-name-error:not([hidden])')
        assert page.locator('#proj-name-input').input_value() == 'Network retry copy'
        assert page.locator('#proj-name-ok').is_enabled()
        page.unroute('**/api/project/duplicate')
        page.keyboard.press('Escape')
        page.locator('#proj-name-overlay').wait_for(state='hidden')
        assert card('UI renamed project').evaluate('el=>el===document.activeElement')
        checks.append('Rename validation and duplicate network failures retain the form; Escape cancels and restores focus to the original project')

        target = card('UI renamed project')
        target.hover()
        target.locator('.proj-check input').focus()
        page.keyboard.press('Space')
        assert target.locator('.proj-check input').is_checked()
        assert target.locator('.proj-check input').evaluate('el=>el===document.activeElement'), page.evaluate('({tag:document.activeElement.tagName,id:document.activeElement.id})')
        page.keyboard.press('Space')
        assert not target.locator('.proj-check input').is_checked()
        assert target.locator('.proj-check input').evaluate('el=>el===document.activeElement'), page.evaluate('({tag:document.activeElement.tagName,id:document.activeElement.id})')
        page.screenshot(path=str(report / '04-project-keyboard-after.png'), animations='disabled')
        page.locator('#proj-search').fill('renamed')
        assert page.locator('#proj-search').evaluate('el=>el===document.activeElement')
        page.locator('#proj-search').fill('')
        page.keyboard.press('Escape')
        page.locator('#project-overlay').wait_for(state='hidden')
        checks.append('Project checkbox selection keeps keyboard focus after redraws; repeated Space and search work without falling into the background')

        held = []
        page.route('**/api/project/workspace', lambda route: held.append(route))
        page.locator('#page-workspace').click()
        page.wait_for_selector('#workspace-opening:not([hidden])')
        assert page.locator('#page-workspace').get_attribute('aria-current') == 'page'
        assert page.locator('#workspace').get_attribute('aria-busy') == 'true'
        assert 'Opening' in page.locator('#workspace-opening-status').inner_text()
        page.screenshot(path=str(report / '05-workspace-loading-after.png'), animations='disabled')
        picker()
        held.pop().fulfill(json={'ok': True, 'workspace': {}})
        page.wait_for_function('document.body.dataset.page==="library"')
        # Let the delayed response finish its continuation before checking the modal.
        page.evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
        assert page.locator('#project-overlay').is_visible()
        assert page.locator('#workspace').is_hidden()
        page.screenshot(path=str(report / '06-late-workspace-after.png'), animations='disabled')
        page.unroute('**/api/project/workspace')
        page.locator('#proj-close').click()
        page.locator('#project-overlay').wait_for(state='hidden')
        checks.append('Workspace shows immediate loading feedback; leaving during a delayed request keeps Library and the project picker in control')

        page.route('**/api/project/workspace', lambda route: route.fulfill(status=503, json={'error': 'fixture unavailable'}))
        page.locator('#page-workspace').click()
        page.wait_for_selector('#workspace-retry:not([hidden])')
        assert 'Could not open your saved workspace' in page.locator('#workspace-opening-status').inner_text()
        assert page.locator('#workspace-choice').is_hidden()
        assert page.locator('#workspace').get_attribute('aria-busy') is None
        for width, height in [(1400, 900), (900, 600)]:
            page.set_viewport_size({'width': width, 'height': height})
            for theme in ('light', 'dark'):
                page.evaluate('theme=>document.documentElement.dataset.theme=theme', theme)
                page.screenshot(path=str(report / f'07-workspace-error-{theme}-{width}.png'), animations='disabled')
                assert page.locator('#workspace-retry').is_visible()
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.unroute('**/api/project/workspace')
        page.route('**/api/project/workspace', lambda route: route.fulfill(json={'ok': True, 'workspace': {}}))
        page.locator('#workspace-retry').click()
        page.wait_for_selector('.workspace-costume')
        page.wait_for_function('document.querySelector(".workspace-hero img")?.hidden')
        assert page.locator('.workspace-hero img').is_hidden()
        assert page.locator('#workspace-opening').is_hidden()
        page.set_viewport_size({'width': 1400, 'height': 900})
        page.evaluate('document.documentElement.dataset.theme="light"')
        page.screenshot(path=str(report / '08-workspace-recovered-after.png'), animations='disabled')
        assert not workspace_writes, workspace_writes
        checks.append('Failed Workspace loads explain the error and offer Retry or Library; successful retry recovers without overwriting saved costume state')
        page.unroute('**/api/project/workspace')
        page.locator('#page-library').click()
        picker()
        card(original).click()
        page.wait_for_function('name=>atelierProject()===name && !_projectOpening', arg=original)
        assert not errors, errors
    finally:
        page.close()


def run_home_folder_checks(context, url, report, checks):
    from contextlib import ExitStack
    from urllib.parse import parse_qs, urlparse
    from unittest.mock import patch
    from atelier.web import browse as B

    entries = [
        ('UI/Textures/T_Icon.uasset', 'fixture.utoc', 'Marvel/Content/Marvel/'),
        ('Audio/SC_Unlisted.uasset', 'fixture.utoc', 'Marvel/Content/Marvel/'),
        ('Helpers/BP_Unlisted.uasset', 'fixture.utoc', 'Marvel/Content/Marvel/'),
    ]
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    with ExitStack() as stack:
        stack.enter_context(patch.object(B, 'ensure_index', return_value=entries))
        stack.enter_context(patch('atelier.index.ensure_index', return_value=entries))
        stack.enter_context(patch('atelier.handlers.world.list_maps', return_value=[]))
        stack.enter_context(patch('atelier.added_assets.library_items', side_effect=lambda path: [
            {'type': 'folder', 'name': 'My assets', 'label': 'My assets', 'rel_path': 'My assets'}] if not path else []))
        page.route('**/api/browse?*', lambda route: route.fulfill(json=B.browse_dispatch(
            parse_qs(urlparse(route.request.url).query).get('path', [''])[0])))
        try:
            page.goto(url)
            page.wait_for_selector('#grid-area .card')
            assert set(page.locator('#grid-area .card-name').all_text_contents()) == {'UI', 'My assets'}
            for theme in ('light', 'dark'):
                page.evaluate('theme=>document.documentElement.dataset.theme=theme', theme)
                page.screenshot(path=str(report / f'00-home-folders-{theme}.png'), animations='disabled')
            page.locator('#grid-area .card').filter(has=page.get_by_text('UI', exact=True)).click()
            page.wait_for_function('nav.path==="UI" && _gridStatus==="ready"')
            assert page.locator('#grid-area .card-name').all_text_contents() == ['Textures']
            # A pin made before its folder was hidden still opens, and can still be removed.
            page.evaluate("AtelierLibraryPins.toggle({type:'folder',rel_path:'Helpers',label:'Helpers'})")
            page.evaluate("pushNav({path:''})")
            page.wait_for_function('nav.path==="" && _gridStatus==="ready"')
            assert 'Helpers' not in page.locator('#grid-area .card-name').all_text_contents()
            page.locator('.library-pin-open[title="Helpers"]').click()
            page.wait_for_function('nav.path==="Helpers" && _gridStatus==="ready"')
            assert 'Empty folder' in page.locator('#empty-state').inner_text()
            page.evaluate("pushNav({path:''})")
            page.wait_for_function('nav.path==="" && _gridStatus==="ready"')
            page.locator('.library-pin-remove[aria-label*="Helpers"]').click()
            assert page.evaluate("!AtelierLibraryPins.isPinned('Helpers')")
            assert not errors, errors
            checks.append('Library Home hides empty and unsupported-only folders and absent curated sections; populated folders and project-added folders remain browsable, and a pin to a hidden folder still opens and can be removed')
        finally:
            page.close()
