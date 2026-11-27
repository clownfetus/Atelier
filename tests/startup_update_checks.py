"""Startup never waits for the GitHub release check, and its offer still appears once answered."""


def run_startup_update_checks(context, url, report, checks):
    tab = context.new_page()
    held, errors = [], []
    tab.on('pageerror', lambda error: errors.append(str(error)))
    # Hold the release check open: the library must not wait for it.
    tab.route('**/api/update_check', lambda route: held.append(route))
    try:
        tab.goto(url)
        tab.wait_for_selector('#grid-area .folder-card, #grid-area .card')
        assert held, 'the release check was never requested'
        assert tab.locator('#update-overlay.active').count() == 0
        held[0].fulfill(json={'available': True, 'tag': '9.9.9', 'manual': True})
        tab.wait_for_selector('#update-overlay.active')
        assert '9.9.9' in tab.locator('#update-tag').inner_text()
        assert tab.evaluate("getComputedStyle(document.getElementById('update-overlay')).zIndex") == '250'
        tab.screenshot(path=str(report / 'startup-update-offer.png'))
        tab.locator('#update-later').click()
        tab.wait_for_function("!document.getElementById('update-overlay').classList.contains('active')")
        assert not errors, errors
        checks.append('Startup shows the library while the release check is pending; the update offer appears once it answers')
    finally:
        tab.close()

    picker = context.new_page()
    picker.route('**/api/projects', lambda route: route.fulfill(json={'active': '', 'projects': []}))
    picker.route('**/api/update_check', lambda route: route.fulfill(json={
        'available': True, 'tag': '9.9.9', 'manual': True}))
    try:
        picker.goto(url)
        picker.wait_for_selector('#project-overlay.active')
        picker.wait_for_selector('#update-overlay.active')
        picker.locator('#update-later').click()
        assert picker.locator('#project-overlay.active').count() == 1
        checks.append('Update offer appears above an empty project picker without requiring project creation')
    finally:
        picker.close()


def run_mod_repair_checks(context, url, report, checks):
    page = context.new_page()
    held, saves = [], []
    page.route('**/api/mod_repair/installed', lambda route: held.append(route))
    row = {
        'status': 'repairable', 'name': 'Older outfit.utoc',
        'fixed': 1, 'token': 'scan-1', 'suggested_name': 'Older outfit-repaired.zip',
    }

    def save(route):
        saves.append(route.request.post_data_json)
        route.fulfill(json={'ok': True, 'status': 'repaired', 'name': row['suggested_name']})

    page.route('**/api/mod_repair/save', save)
    page.route('**/api/mod_repair/scan', lambda route: route.fulfill(json={
        'ok': True, 'status': 'review', 'name': 'Uncertain.zip', 'reason': 'Needs a closer look.',
    }))
    page.route('**/api/pick_mod_file', lambda route: route.fulfill(json={
        'ok': True, 'path': 'Uncertain.zip', 'locked': False,
    }))
    try:
        page.goto(url)
        page.wait_for_selector('#grid-area .folder-card, #grid-area .card')
        page.wait_for_function("Boolean(window.AtelierModRepair)", timeout=5000)
        assert len(held) == 1, held
        assert held[0].request.method == 'GET'
        assert page.locator('#mod-repair-notice').count() == 0
        held[0].fulfill(json={'ok': True, 'repairs': [
            row, {'status': 'review', 'name': 'Uncertain.zip'},
        ]})
        notice = page.locator('#mod-repair-notice')
        notice.wait_for()
        assert '1 mod needs repair' in notice.inner_text()
        notice.get_by_role('button', name='Review mods').click()
        panel = page.locator('#repatch-overlay')
        assert 'Older outfit.utoc' in panel.inner_text()
        assert 'Uncertain.zip' not in panel.inner_text()
        panel.get_by_role('button', name='Save repaired copy').click()
        panel.get_by_text('Saved Older outfit-repaired.zip', exact=True).wait_for()
        assert [r['token'] for r in saves] == ['scan-1']
        page.screenshot(path=str(report / 'installed-mod-repair.png'))
        panel.locator('#repatch-pick').click()
        panel.get_by_role('button', name='Check for material issues').click()
        panel.get_by_text('Needs review', exact=True).wait_for()
        assert panel.get_by_role('button', name='Save repaired copy').count() == 0
        checks.append('The startup scan runs in the background and offers only confirmed repairs')
        checks.append('Repatch shows uncertain material checks without offering repair')
    finally:
        page.close()
