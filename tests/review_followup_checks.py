"""Failure-oriented browser regressions for the review follow-ups; all builds are intercepted."""
from urllib.parse import urlparse

MESH = 'Characters/1024/1024503/Meshes/SK_1024_1024503'


def run_review_followup_checks(context, url, report, checks):
    from idle_selection_checks import run_idle_selection_checks
    run_idle_selection_checks(context, url, report, checks)
    tab = context.new_page()
    errors, held = [], []
    tab.on('pageerror', lambda error: errors.append(str(error)))
    tab.route('**/api/import_texture', lambda route: held.append(route))
    tab.route('**/api/imported', lambda route: route.fulfill(json=[]))
    try:
        tab.goto(url)
        tab.wait_for_selector('#grid-area .card, #grid-area .folder-card')
        tab.evaluate("""() => {
            _openAfterImport = false;
            window.reviewItem = {game_rel:'Fixture/T_Shared',name:'T_Shared',file_type:'texture'};
            handleAssetClick(reviewItem); handleAssetClick(reviewItem);
        }""")
        tab.wait_for_function('_editsInFlight.size === 1')
        tab.wait_for_timeout(100)
        assert len(held) == 1
        assert tab.locator('#tray-progress .toast:visible').count() == 1
        assert 'Preparing T_Shared for editing' in tab.locator('#tray-progress').inner_text()
        assert tab.locator('#toast-area [data-operation-state=busy]').count() == 0
        tab.evaluate("_selectProject('Smoke B')")
        tab.wait_for_function("atelierProject() === 'Smoke B'")
        assert tab.locator('#tray-progress').is_hidden()
        tab.evaluate('handleAssetClick(reviewItem)')
        tab.wait_for_function('_editsInFlight.size === 2')
        assert [route.request.headers['x-atelier-project'] for route in held] == ['Smoke%20A', 'Smoke%20B']
        assert tab.locator('#tray-progress .toast:visible').count() == 1
        before = tab.locator('#status-msg').inner_text()
        held[0].fulfill(json={'ok': True})
        tab.wait_for_function('_editsInFlight.size === 1')
        assert tab.locator('#status-msg').inner_text() == before
        assert tab.evaluate("suppressedImportGameRels.size === 1 && suppressedImportGameRels.has(_assetOperationKey(reviewItem.game_rel, 'Smoke B'))")
        held[1].fulfill(json={'ok': True})
        tab.wait_for_function('_editsInFlight.size === 0 && suppressedImportGameRels.size === 0')
        tab.evaluate("_selectProject('Smoke A')")
        tab.wait_for_function("atelierProject() === 'Smoke A'")
        checks.append('Duplicate edit clicks deduplicate within a project; the same asset loads independently across projects and stale completion preserves current status')
        assert not errors, errors
    finally:
        tab.close()

    tab = context.new_page()
    errors, held, snapshots = [], [], []
    tab.on('pageerror', lambda error: errors.append(str(error)))
    tab.route('**/api/import_texture', lambda route: held.append(route))
    tab.route('**/api/imported', lambda route: route.fulfill(json=[]))
    try:
        tab.goto(url)
        tab.wait_for_selector('#grid-area .card, #grid-area .folder-card')
        tab.wait_for_function('_activeProjectName === "Smoke A"')
        tab.route('**/api/imported', lambda route: snapshots.append(route))
        tab.evaluate('void loadSidebar()')
        tab.wait_for_timeout(100)
        assert len(snapshots) == 1
        tab.evaluate("""() => {
            _openAfterImport = false;
            for (const name of ['T_First','T_Second','T_Third'])
                void editAsset({game_rel:'Fixture/'+name,name,file_type:'texture'});
        }""")
        tab.wait_for_function('_editsInFlight.size === 3')
        tab.wait_for_timeout(100)
        assert len(held) == 3
        def completed(index):
            name = ['T_First', 'T_Second', 'T_Third'][index]
            return {'ok': True, 'imported': {'token': name, 'name': name, 'game_rel': 'Fixture/'+name,
                    'file_type': 'texture', 'selected': True, 'skin_id': '', 'mtime': 1}}
        held[0].fulfill(json=completed(0))
        tab.wait_for_selector('#sidebar-list .sb-item[data-token="T_First"]')
        assert tab.evaluate('_editsInFlight.size') == 2
        assert 'Ready to edit: T_First' in tab.locator('#tray-progress').inner_text()
        assert tab.locator('#sidebar-list .sidebar-empty').count() == 0
        tab.wait_for_function('document.getElementById("sel-count").textContent === "1"')
        snapshots[0].fulfill(json=[])
        tab.wait_for_timeout(100)
        assert tab.locator('#sidebar-list .sb-item').count() == 1
        tab.evaluate("sidebarData.T_First.selected = false; renderSidebar()")
        held[2].fulfill(json=completed(2))
        tab.wait_for_selector('#sidebar-list .sb-item[data-token="T_Third"]')
        assert not tab.evaluate('sidebarData.T_First.selected')
        held[1].fulfill(json={'ok': False, 'error': 'Fixture decode failure'})
        tab.wait_for_function('_editsInFlight.size === 0')
        assert tab.locator('#sidebar-list .sb-item').count() == 2
        assert len(snapshots) == 1, 'Completed imports should not queue another full tray request'
        assert not errors, errors
        tab.screenshot(path=str(report / 'tray-progressive-imports.png'))
        checks.append('Completed textures enter the tray while other imports are pending; stale snapshots, failed imports and existing export selections stay correct')
    finally:
        tab.close()

    tab = context.new_page()
    errors, builds, conflicts = [], [], []
    status = {'available': True, 'template': True, 'enabled': True, 'reasons': []}
    tab.on('pageerror', lambda error: errors.append(str(error)))
    tab.route('**/api/skin_swapper/status', lambda route: route.fulfill(json=status))
    tab.route('**/api/skin_swapper/plan', lambda route: route.fulfill(json={
        'problems': [], 'status': status, 'entries': [{'game_rel': MESH, 'sculpt': 0}]}))
    def conflict(route):
        conflicts.append(route.request.url)
        route.fulfill(json={'default': len(conflicts) == 1, 'mods': False})
    def build(route):
        endpoint = urlparse(route.request.url).path
        builds.append((endpoint, route.request.post_data_json))
        attempts = sum(path == endpoint for path, _ in builds)
        route.fulfill(json={'ok': attempts > 1, 'error': 'Simulated first failure' if attempts == 1 else '',
                            'pak_path': 'D:/Fixture/Retry.pak', 'applied': [], 'skipped': []})
    tab.route('**/api/check_mod_conflict?**', conflict)
    tab.route('**/api/install_mod', build)
    tab.route('**/api/skin_swapper/build', build)
    try:
        tab.goto(url)
        tab.wait_for_selector('#grid-area .card, #grid-area .folder-card')
        tab.evaluate("""mesh => {
            _modsFolderSet=false; _protectionPassword='';
            sidebarData={mesh:{name:'SK_1024_1024503',game_rel:mesh,file_type:'mesh',selected:true},
                texture:{name:'T_Test',game_rel:'Fixture/T_Test',file_type:'texture',selected:true}};
            document.getElementById('mod-name-input').value='RetryRegression';
            updateInstallBtn(); doInstallMod();
        }""", MESH)
        tab.wait_for_selector('input[name="export-format"]')
        tab.locator('input[value="skin-swapper"]').check()
        tab.locator('#skin-swapper-author').fill('Regression author')
        tab.wait_for_function('!document.getElementById("export-review-confirm").disabled')
        tab.locator('#export-review-confirm').click()
        tab.wait_for_selector('#confirm-overwrite-overlay.active')
        tab.locator('#confirm-overwrite-cancel').click()
        tab.locator('input[value="standard"]').check()
        tab.locator('#export-review-confirm').click()
        tab.wait_for_selector('#export-review-retry')
        tab.locator('#export-review-retry').click()
        tab.wait_for_function('document.getElementById("export-review-title").textContent.startsWith("Mod exported")')
        assert len(builds) == 2 and all(path == '/api/install_mod' for path, _ in builds), builds
        assert builds[0][1] == builds[1][1] and len(builds[1][1]['items']) == 2, builds
        checks.append('Cancelling Skin Swapper overwrite then choosing Standard preserves the Standard endpoint and both selected assets on retry')

        tab.locator('#export-review-refresh').click()
        tab.wait_for_selector('input[name="export-format"]')
        tab.locator('input[value="skin-swapper"]').check()
        tab.locator('#skin-swapper-author').fill('Regression author')
        tab.wait_for_function('!document.getElementById("export-review-confirm").disabled')
        assert tab.locator('.skin-swapper-form').inner_text() == 'Form 0 (default)'
        tab.locator('#export-review-confirm').click()
        tab.wait_for_selector('#export-review-retry')
        tab.locator('#export-review-retry').click()
        tab.wait_for_function('document.getElementById("export-review-title").textContent.startsWith("Mod exported")')
        assert len(builds) == 4 and all(path == '/api/skin_swapper/build' for path, _ in builds[2:]), builds
        assert builds[2][1] == builds[3][1] and builds[3][1]['meshes'] == [{'game_rel': MESH}]
        checks.append('Skin Swapper retry retains its endpoint, author, skin name and mesh for automatic form detection')
        tab.screenshot(path=str(report / 'review-followup-retries.png'))
        assert not errors, errors
    finally:
        tab.close()
