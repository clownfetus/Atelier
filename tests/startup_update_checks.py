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
