"""Exercise the actual update UI using explicit network/process fixtures."""


def run_update_browser_checks(context, url, report, checks):
    tab = context.new_page()
    downloads, restarts = [], []
    tab.route('**/api/update_check', lambda route: route.fulfill(json={'available': True, 'tag': '9.9.9', 'patch': True}))
    tab.route('**/api/update_download', lambda route: (downloads.append(True), route.fulfill(json={'ok': True})))
    tab.route('**/api/update_status', lambda route: route.fulfill(json={'state': 'ready'}))
    tab.route('**/api/update_progress', lambda route: route.fulfill(json={'pct': 100, 'bytes': 1024, 'total': 1024}))
    tab.route('**/api/update_apply', lambda route: (restarts.append(True), route.fulfill(json={'ok': False, 'error': 'The update could not restart. Try again.'})))
    try:
        tab.goto(url)
        tab.wait_for_selector('#update-overlay.active')
        tab.locator('#update-now').click()
        tab.wait_for_selector('#update-ready', state='visible')
        assert downloads == [True] and not restarts, 'Downloading must not restart the application.'
        tab.screenshot(path=str(report / 'update-ready.png'))
        tab.locator('#update-restart-later').click()
        tab.wait_for_function("!document.getElementById('update-overlay').classList.contains('active')")
        checks.append('Downloaded update waits for explicit restart; Restart Later keeps the workspace open')
        tab.evaluate("document.getElementById('update-overlay').classList.add('active')")
        tab.locator('#update-restart').click()
        tab.wait_for_selector('#update-error', state='visible')
        assert restarts == [True]
        assert tab.locator('#update-error-message').inner_text() == 'The update could not restart. Try again.'
        assert not tab.locator('#update-restart').is_disabled()
        tab.locator('#update-error-ok').click()
        checks.append('A failed restart displays its error and returns control to the workspace')
    finally:
        tab.close()

    saved = context.new_page()
    saved.route('**/api/update_check', lambda route: route.fulfill(json={'available': True, 'tag': '9.9.9', 'ready': True}))
    saved.route('**/api/update_download', lambda route: (_ for _ in ()).throw(AssertionError('A ready update must not download again.')))
    try:
        saved.goto(url)
        saved.wait_for_selector('#update-ready', state='visible')
        saved.locator('#update-restart-later').click()
        checks.append('A previously verified download is offered for restart without downloading again')
    finally:
        saved.close()

    failed = context.new_page()
    failed.route('**/api/update_check', lambda route: route.fulfill(json={'available': True, 'tag': '9.9.9'}))
    failed.route('**/api/update_download', lambda route: route.fulfill(json={'ok': False, 'error': 'Could not verify this download.'}))
    try:
        failed.goto(url)
        failed.wait_for_selector('#update-overlay.active')
        failed.locator('#update-now').click()
        failed.wait_for_selector('#update-error', state='visible')
        assert failed.locator('#update-error-message').inner_text() == 'Could not verify this download.'
        failed.locator('#update-error-ok').click()
        checks.append('Rejected downloads show a recoverable error without starting an update')
    finally:
        failed.close()
