"""Upgrade popup checks using bundled notes and real config persistence."""
from pathlib import Path
from atelier import config as C


def run_changelog_checks(context, url, report, checks):
    original = C._load_config()
    current = Path(C.VERSION_FILE).read_text(encoding='utf-8').strip()
    tab = context.new_page()
    errors = []
    tab.on('pageerror', lambda error: errors.append(str(error)))

    def upgraded(previous='0.4.0'):
        C._save_config(paks='fixture/Paks', changelog_version=previous)

    def dismiss(action):
        with tab.expect_response('**/api/changelog/acknowledge') as response:
            action()
        assert response.value.ok
        tab.wait_for_function("!document.getElementById('changelog-overlay').classList.contains('active')")

    try:
        upgraded()
        held = []
        tab.route('**/api/changelog', lambda route: held.append(route))
        tab.goto(url)
        tab.wait_for_selector('#grid-area .folder-card, #grid-area .card')
        assert held, 'Local release notes were not requested'
        assert tab.locator('#changelog-overlay.active').count() == 0
        held[0].continue_()
        tab.wait_for_selector('#changelog-overlay.active')
        tab.unroute('**/api/changelog')
        assert tab.locator('#changelog-version').inner_text() == 'Atelier ' + current
        versions = tab.locator('.changelog-release h3').all_text_contents()
        assert versions[0] == current and versions[-1] == '0.4.1'
        assert '0.4.0' not in versions and 'Unreleased' not in versions
        assert tab.locator('#changelog-body strong').count() > 0
        assert tab.locator('#changelog-done').evaluate('el => el === document.activeElement')
        tab.keyboard.press('Tab')
        assert tab.locator('#changelog-close').evaluate('el => el === document.activeElement')
        tab.keyboard.press('Shift+Tab')
        assert tab.locator('#changelog-done').evaluate('el => el === document.activeElement')
        tab.locator('#menu-btn').evaluate('el => el.focus()')
        assert tab.locator('#changelog-done').evaluate('el => el === document.activeElement')
        checks.append('Local changelog loading does not delay the library; skipped releases and safe formatting appear with trapped keyboard focus')

        for theme in ('light', 'dark'):
            tab.locator('#settings-theme').select_option(theme, force=True)
            for width, height in ((1400, 900), (1024, 768), (540, 600)):
                tab.set_viewport_size({'width': width, 'height': height})
                assert tab.locator('#changelog-done').is_visible()
                assert tab.locator('#changelog-done').evaluate('el => {const r=el.getBoundingClientRect(); return el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));}')
                assert tab.locator('#changelog-body').evaluate('el => el.scrollHeight > el.clientHeight')
                assert tab.locator('.changelog-modal').evaluate('el => {const r=el.getBoundingClientRect(); return r.top>=0 && r.bottom<=innerHeight && r.left>=0 && r.right<=innerWidth;}')
                tab.screenshot(path=str(report / f'changelog-{theme}-{width}x{height}.png'))
        checks.append('Scrollable release notes fit both themes at desktop, small-window and narrow-window sizes')
        dismiss(lambda: tab.locator('#changelog-done').click())
        assert C._load_config()['changelog_version'] == current
        with tab.expect_response('**/api/changelog') as response:
            tab.reload()
        assert response.value.json()['available'] is False
        tab.wait_for_selector('#grid-area .folder-card, #grid-area .card')
        assert tab.locator('#changelog-overlay.active').count() == 0
        tab.set_viewport_size({'width': 1400, 'height': 900})
        tab.locator('#menu-btn').click()
        tab.get_by_text('What’s new…', exact=True).click()
        tab.wait_for_selector('#changelog-overlay.active')
        dismiss(lambda: tab.keyboard.press('Escape'))
        assert tab.locator('#menu-btn').evaluate('el => el === document.activeElement')
        checks.append('Dismissal is saved to app settings, survives reload, and the app menu reopens the changelog with Escape restoring focus')

        # The update service can answer while the user is reading the installed release.
        upgraded('0.4.1')
        offers = []
        tab.route('**/api/update_check', lambda route: offers.append(route))
        tab.reload()
        tab.wait_for_selector('#changelog-overlay.active')
        offers[0].fulfill(json={'available': True, 'tag': '9.9.9', 'manual': True})
        assert tab.locator('#update-overlay.active').count() == 0
        dismiss(lambda: tab.locator('#changelog-close').click())
        tab.wait_for_selector('#update-overlay.active')
        tab.locator('#update-later').click()
        tab.unroute('**/api/update_check')
        checks.append('A delayed update offer waits for the changelog to close, keeping a single focused dialog')

        upgraded('0.4.1')
        tab.route('**/api/update_check', lambda route: route.fulfill(json={
            'available': True, 'tag': '9.9.9', 'manual': True}))
        tab.reload()
        tab.wait_for_selector('#update-overlay.active')
        tab.wait_for_selector('#grid-area .folder-card, #grid-area .card')
        assert tab.locator('#changelog-overlay.active').count() == 0
        tab.locator('#update-later').click()
        tab.wait_for_selector('#changelog-overlay.active')
        dismiss(lambda: tab.locator('#changelog-overlay').click(position={'x': 2, 'y': 2}))
        tab.unroute('**/api/update_check')
        checks.append('The changelog waits for an existing update dialog and backdrop dismissal acknowledges the installed version')

        upgraded('0.4.1')
        tab.route('**/api/setup_status', lambda route: route.fulfill(json={'configured': False}))
        tab.reload()
        tab.wait_for_selector('#setup-step-1')
        assert tab.locator('#changelog-overlay.active').count() == 0
        assert C._load_config()['changelog_version'] == '0.4.1'
        checks.append('First-run setup keeps priority and does not acknowledge notes the user has not seen')
        tab.unroute('**/api/setup_status')

        tab.route('**/api/changelog', lambda route: route.abort())
        tab.reload()
        tab.wait_for_selector('#grid-area .folder-card, #grid-area .card')
        assert tab.locator('#changelog-overlay.active').count() == 0
        checks.append('A failed local notes request leaves the library usable without an unhandled error')
        assert not errors, errors
    finally:
        tab.close()
        C._save_config(paks=original.get('paks'), changelog_version=original.get('changelog_version'))
