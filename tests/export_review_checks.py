"""Export review/recovery contracts; all builds and file-manager actions are intercepted."""
from urllib.parse import quote


def run_export_review_checks(page, context, url, report, checks):
    review = context.new_page()
    errors, installs, pending, conflicts, reveals = [], [], [], [], []
    held_checks = []
    hold_check = {'value': False}
    conflict_response = {'default': False, 'mods': False}
    review.on('pageerror', lambda error: errors.append(str(error)))

    def conflict(route):
        conflicts.append(route.request.headers)
        if hold_check['value']:
            held_checks.append(route)
        else:
            route.fulfill(json=conflict_response)

    def install(route):
        installs.append({'body': route.request.post_data_json, 'headers': route.request.headers})
        pending.append(route)

    review.route('**/api/check_mod_conflict?**', conflict)
    review.route('**/api/install_mod', install)
    review.route('**/api/open_export_folder', lambda route: (reveals.append(route.request.url), route.fulfill(json={'ok': True})))
    try:
        review.goto(url)
        review.wait_for_function('window.AtelierExportReview && window.atelierProject?.()')
        review.wait_for_selector('#grid-area .card')
        review.evaluate("""() => {
          _activeProjectName = 'Review Ω';
          _modsFolderSet = true; _modsFolderPath = 'D:/Fixture/mods'; _protectionPassword = 'secret-review-password';
          sidebarData = {
            material: {name:'Body <img src=x>', game_rel:'Characters/Fixture/MI_Body', file_type:'material', selected:true},
            texture: {name:'Body texture', game_rel:'Characters/Fixture/T_Body', file_type:'texture', selected:true},
            audio: {name:'Sound', game_rel:'Audio/Sound', file_type:'audio', selected:true},
            mesh: {name:'Mesh', game_rel:'Characters/Fixture/SK_Body', file_type:'mesh', selected:false}
          };
          document.getElementById('mod-name-input').value = 'Review fixture';
          document.getElementById('toggle-copy').checked = true;
          document.getElementById('toggle-password').checked = true;
          updateInstallBtn();
        }""")
        overlay = review.locator('#export-review-overlay')
        review.evaluate("""() => {
          window.seedExportDraft = () => {
            matEditor = {name:'Review material', game_rel:'Characters/Fixture/MI_Body', project:'Review Ω',
              colors:[], scalars:[{name:'Roughness', value:0.4}], compareMode:'saved'};
            _matRemember(matEditor); matEditor.scalars[0].value = 0.8;
            _matRefreshDirty();
          };
          window.clearExportDraft = () => {
            _materialSaving.delete(matEditor); matEditor = null;
            document.getElementById('material-overlay').classList.remove('active');
          };
          seedExportDraft(); doInstallMod();
        }""")
        assert not installs and not conflicts
        assert 'Save or discard' in review.locator('#mat-status').inner_text()
        assert review.locator('#mat-save').evaluate('el => el === document.activeElement')
        assert review.evaluate('matEditor.scalars[0].value') == 0.8
        review.evaluate("matEditor.scalars[0].value = 0.4; _materialSaving.add(matEditor); _matRefreshDirty(); doInstallMod()")
        assert 'save in progress' in review.locator('#mat-status').inner_text()
        assert review.locator('#mat-status').evaluate('el => el === document.activeElement')
        assert not installs and not conflicts
        review.evaluate('clearExportDraft()')
        review.wait_for_function("typeof window.AtelierViewport?.hasPendingEdits === 'function'")
        review.evaluate("""() => {
          window.savedExportViewport = AtelierViewport;
          window.AtelierViewport = {...AtelierViewport, hasPendingEdits: () => true,
            focusPendingEdits: () => {
              window.exportViewportFocused = true;
              document.getElementById('viewport-overlay').classList.add('active');
              document.getElementById('viewport-materials').classList.remove('empty');
              const save = document.getElementById('viewport-mat-save'); save.disabled = false; save.focus();
            }};
          doInstallMod();
        }""")
        assert not installs and not conflicts
        assert review.evaluate('exportViewportFocused')
        assert review.locator('#viewport-mat-save').evaluate('el => el === document.activeElement')
        review.evaluate("window.AtelierViewport = savedExportViewport; document.getElementById('viewport-overlay').classList.remove('active')")
        review.locator('#install-btn').click()
        assert overlay.is_visible()
        assert 'Included changes · 2' in overlay.inner_text()
        assert 'Excluded changes · 2' in overlay.inner_text()
        assert 'Unsupported export type: audio' in overlay.inner_text()
        assert 'Not selected' in overlay.inner_text()
        assert 'Characters/Fixture/MI_Body' in overlay.inner_text()
        assert 'secret-review-password' not in overlay.inner_text()
        assert overlay.locator('img').count() == 0
        assert not installs and not conflicts
        review.keyboard.press('Shift+Tab')
        assert review.locator('#export-review-confirm').evaluate('el => el === document.activeElement')
        review.keyboard.press('Escape')
        assert not overlay.is_visible()
        assert review.locator('#install-btn').evaluate('el => el === document.activeElement')
        checks.append('Export review lists included/excluded types and paths, keeps credentials private and supports keyboard cancellation')

        # A draft created after reviewing, or while the conflict request is in flight,
        # must not silently export the last saved material values.
        review.locator('#install-btn').click()
        review.evaluate('seedExportDraft()')
        review.locator('#export-review-confirm').click()
        assert not installs and not conflicts
        assert review.evaluate('matEditor.scalars[0].value') == 0.8
        assert review.locator('#mat-save').evaluate('el => el === document.activeElement')
        review.evaluate('clearExportDraft()')
        review.locator('#install-btn').click()
        hold_check['value'] = True
        review.locator('#export-review-confirm').click()
        review.wait_for_function("document.getElementById('export-review-title').textContent.startsWith('Checking')")
        review.evaluate('seedExportDraft()')
        held_checks.pop(0).fulfill(json={'default': False, 'mods': False})
        review.wait_for_function("document.activeElement.id === 'mat-save'")
        assert not installs
        assert review.evaluate('materialDirtyCount()') == 1
        hold_check['value'] = False
        conflicts.clear()
        review.evaluate('clearExportDraft()')
        checks.append('Material/viewport drafts and saves block export; material guards recheck confirmation/dispatch, retaining drafts and editor focus')

        review.locator('#install-btn').click()
        review.evaluate("_activeProjectName = 'Other project'")
        review.locator('#export-review-confirm').click()
        assert 'changed. Refresh the review' in overlay.inner_text()
        assert not installs and not conflicts
        review.evaluate("_activeProjectName = 'Review Ω'; sidebarData.texture.selected = false")
        review.locator('#export-review-confirm').click()
        assert not installs
        review.locator('#export-review-refresh').click()
        assert 'Included changes · 1' in overlay.inner_text()
        review.locator('#export-review-confirm').click()
        review.wait_for_function("document.querySelector('.export-review-modal').dataset.state === 'busy' && document.querySelector('progress')")
        assert len(pending) == 1
        assert review.locator('#install-btn').is_disabled()
        assert overlay.locator('progress').get_attribute('value') is None
        review.keyboard.press('Escape')
        assert not overlay.is_visible()
        review.locator('#export-last-result').click()
        assert overlay.locator('progress').is_visible()
        review.evaluate('doInstallMod()')
        assert len(installs) == 1
        request = installs[-1]
        assert request['headers']['x-atelier-project'] == quote('Review Ω', safe='')
        assert conflicts[-1]['x-atelier-project'] == quote('Review Ω', safe='')
        assert request['body'] == {
            'mod_name': 'Review fixture', 'items': ['Characters/Fixture/MI_Body'],
            'password': 'secret-review-password', 'copy_to_mods': True, 'background': True,
        }
        pending.pop(0).fulfill(json={'ok': True, 'pak_path': 'D:/Fixture/exported/Review.pak',
                                   'installed_dir': 'D:/Fixture/mods', 'applied': ['mat MI_Body'],
                                   'skipped': ['Missing optional texture']})
        review.wait_for_function("document.querySelector('.export-review-modal').dataset.state === 'warning'")
        assert 'Missing optional texture' in overlay.inner_text()
        assert 'mat MI_Body' in overlay.inner_text()
        assert 'D:/Fixture/exported/Review.pak' in overlay.inner_text()
        review.keyboard.press('Escape')
        review.locator('#export-last-result').click()
        assert 'Missing optional texture' in overlay.inner_text()
        review.locator('#export-review-reveal').click()
        review.wait_for_timeout(30)
        assert len(reveals) == 1
        checks.append('Export uses reviewed project headers/payload, blocks stale reviews and duplicate clicks, and retains full warning results')

        # A successful build with failed installation must remain distinguishable and recoverable.
        review.locator('#export-review-refresh').click()
        review.locator('#export-review-confirm').click()
        review.wait_for_function("document.querySelector('progress') !== null")
        pending.pop(0).fulfill(json={'ok': False, 'built': True, 'pak_path': 'D:/Fixture/exported/Review.pak',
                                   'applied': ['mat MI_Body'], 'error': 'Fixture copy denied'})
        review.wait_for_selector('#export-review-retry')
        assert 'Export built; copy failed' in overlay.inner_text()
        assert 'Fixture copy denied' in overlay.inner_text()
        assert review.locator('#export-review-reveal').is_visible()
        before = len(installs)
        review.evaluate("_activeProjectName = 'Other project'")
        review.locator('#export-review-retry').click()
        assert len(installs) == before
        assert 'changed. Refresh the review' in overlay.inner_text()
        review.evaluate("_activeProjectName = 'Review Ω'")
        conflict_response.update(default=True)
        review.locator('#export-review-retry').click()
        review.wait_for_selector('#confirm-overwrite-overlay.active')
        review.evaluate("document.getElementById('mod-name-input').value = 'Changed after review'")
        review.locator('#confirm-overwrite-ok').click()
        assert len(installs) == before
        assert 'changed. Refresh the review' in overlay.inner_text()
        review.locator('#export-review-refresh').click()
        review.locator('#export-review-confirm').click()
        review.wait_for_selector('#confirm-overwrite-overlay.active')
        review.locator('#confirm-overwrite-cancel').click()
        assert overlay.is_visible()
        assert review.locator('#export-review-confirm').is_enabled()
        checks.append('Partial installation exposes built files; retry and overwrite revalidate the original project/settings and cancellation restores review')

        # Failing destination checks never silently overwrite existing output.
        conflict_response.clear()
        conflict_response.update(ok=False, error='Fixture destination check failed')
        review.locator('#export-review-confirm').click()
        review.wait_for_selector('#export-review-retry')
        assert 'Fixture destination check failed' in overlay.inner_text()
        assert len(installs) == before
        conflict_response.clear()
        conflict_response.update(default=False, mods=False)
        review.locator('#export-review-retry').click()
        review.wait_for_function("document.querySelector('progress') !== null")
        pending.pop(0).abort('failed')
        review.wait_for_selector('#export-review-retry')
        assert 'Your project edits are preserved' in overlay.inner_text()
        assert review.locator('#install-btn').is_enabled()
        assert len(review.evaluate('Object.keys(sidebarData)')) == 4
        assert not errors, errors
        checks.append('Destination/network failures preserve edits and a persistent manual retry without submitting unreviewed or automatic builds')

        review.evaluate("document.querySelectorAll('#toast-area .toast').forEach(el => el.remove())")
        for theme in ('light', 'dark'):
            review.locator('#topbar [data-theme-picker]').select_option(theme)
            review.locator('#export-review-refresh').click()
            review.screenshot(path=str(report / f'export-review-{theme}.png'), animations='disabled')
    finally:
        for route in pending + held_checks:
            try:
                route.abort('failed')
            except Exception:
                pass
        review.close()
