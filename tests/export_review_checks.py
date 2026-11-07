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
        overlay.wait_for(state='hidden')
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
        review.wait_for_function("document.querySelector('.export-review-modal').dataset.state === 'busy' && document.querySelector('.export-review-stage[data-glyph-state=busy]')")
        # The build request leaves in the same task as the busy render; allow its interception to arrive.
        for _ in range(50):
            if pending:
                break
            review.wait_for_timeout(20)
        assert len(pending) == 1
        assert review.locator('#install-btn').is_disabled()
        assert overlay.locator('progress').count() == 0  # A build can't be counted, so there's no bar.
        # The build runs in the glyph, at the Stage tier.
        stage = overlay.locator('.export-review-stage')
        assert stage.get_attribute('data-atelier-motion') == 'glyph'
        assert stage.get_attribute('data-glyph-state') == 'busy' and stage.get_attribute('data-glyph-tier') == 'stage'
        assert stage.get_attribute('data-glyph-asset') is None, 'A build handles several asset types, so it shows Working'
        assert stage.bounding_box()['height'] == 216
        review.wait_for_timeout(900)
        review.screenshot(path=str(report / 'working-export-busy.png'))
        review.set_viewport_size({'width': 1024, 'height': 640})
        assert stage.bounding_box()['height'] == 164
        assert stage.locator('svg').bounding_box()['height'] == 164
        action_box = overlay.locator('.export-review-actions').bounding_box()
        assert action_box['y'] >= 0 and action_box['y'] + action_box['height'] <= 640
        review.screenshot(path=str(report / 'working-export-compact.png'))
        review.set_viewport_size({'width': 1400, 'height': 900})
        review.keyboard.press('Escape')
        overlay.wait_for(state='hidden')
        assert not overlay.is_visible()
        review.locator('#export-last-result').click()
        assert overlay.locator('.export-review-stage[data-glyph-state=busy]').is_visible()
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
        review.wait_for_function("document.querySelector('.export-review-stage[data-glyph-state=busy]') !== null")
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
        review.wait_for_function("document.querySelector('.export-review-stage[data-glyph-state=busy]') !== null")
        pending.pop(0).abort('failed')
        review.wait_for_selector('#export-review-retry')
        assert 'Your project edits are preserved' in overlay.inner_text()
        assert review.locator('#install-btn').is_enabled()
        assert len(review.evaluate('Object.keys(sidebarData)')) == 4
        assert not errors, errors
        checks.append('Destination/network failures preserve edits and a persistent manual retry without submitting unreviewed or automatic builds')

        review.evaluate("document.querySelectorAll('#toast-area .toast').forEach(el => el.remove())")
        for theme in ('light', 'dark'):
            review.locator('#settings-theme').select_option(theme, force=True)
            review.locator('#export-review-refresh').click()
            review.screenshot(path=str(report / f'export-review-{theme}.png'), animations='disabled')
    finally:
        for route in pending + held_checks:
            try:
                route.abort('failed')
            except Exception:
                pass
        review.close()
    run_export_review_glyph_checks(context, url, report, checks)
    run_import_dialog_glyph_checks(context, url, report, checks)


def run_import_dialog_glyph_checks(context, url, report, checks):
    """Edit All: the glyph reports the real job, and the count stays in the text."""
    tab = context.new_page()
    errors = []
    tab.on('pageerror', lambda error: errors.append(str(error)))
    host = '#import-stage > [data-atelier-motion="glyph"]'
    items = "[{game_rel:'A'},{game_rel:'B'}]"
    try:
        tab.goto(url)
        tab.wait_for_function('window.AtelierImportDialog && window.AtelierMotion?.glyph && window.atelierProject?.()')
        tab.evaluate(f"document.getElementById('prog-overlay').classList.add('active'); AtelierImportDialog.begin({items})")
        glyph = tab.locator(host)
        assert glyph.count() == 1 and glyph.get_attribute('data-glyph-state') == 'busy' and glyph.get_attribute('data-glyph-tier') == 'stage'
        assert glyph.get_attribute('data-glyph-asset') in (None, ''), 'A batch names no one asset'
        box = glyph.bounding_box()
        assert box['width'] == 211 and box['height'] == 176, box
        assert glyph.locator('.glyph-piece').first.evaluate('el=>getComputedStyle(el).stroke') != 'none', 'The halo has no colour'
        tab.evaluate("AtelierImportDialog.progress({game_rel:'A', ok:true, name:'A'})")
        assert glyph.get_attribute('data-glyph-state') == 'busy', 'An item finishing is not a result'
        assert tab.locator('.am-import-ink-flight').count() == 0
        cases = (({'results': [1, 2], 'total': 2}, 'success', 'Imported 2 textures'),
                 ({'results': [1], 'total': 2, 'error': 'Fixture failure'}, 'warning', 'Imported with warnings'),
                 ({'results': [], 'total': 2, 'error': 'Fixture failure'}, 'error', 'Import failed'),
                 ({'results': [], 'total': 2, 'error': 'Cancelled'}, 'info', 'Import cancelled'))
        for data, state, title in cases:
            tab.evaluate(f"AtelierImportDialog.begin({items})")
            assert glyph.get_attribute('data-glyph-state') == 'busy'
            tab.evaluate('data=>AtelierImportDialog.finish(data)', data)
            assert glyph.get_attribute('data-glyph-state') == state, state
            assert tab.locator('#import-status-title').inner_text() == title
            assert tab.locator(host).count() == 1
            tab.wait_for_timeout(1900)
            tab.screenshot(path=str(report / f'import-glyph-{state}.png'))
        tab.evaluate('AtelierImportDialog.abandon()')
        assert tab.locator('#import-stage').evaluate('el=>el.childElementCount') == 0
        tab.evaluate("""items => {
          const original = AtelierMotion.glyph;
          try {
            for (const failure of ['missing', 'mount']) {
              AtelierMotion.glyph = failure === 'missing' ? undefined : {mount: () => { throw Error('Fixture mount failure'); }};
              AtelierImportDialog.begin(items);
              if (document.getElementById('import-stage').childElementCount) throw Error('Failed glyph left its host');
              AtelierImportDialog.finish({results: [1, 2], total: 2});
              if (document.getElementById('import-status-title').textContent !== 'Imported 2 textures') throw Error('Lost the result text');
            }
          } finally { AtelierMotion.glyph = original; }
        }""", [{'game_rel': 'A'}, {'game_rel': 'B'}])
        assert not errors, errors
        checks.append('Edit All import shows the glyph at Stage size, forms each real result with the count in text, and works without the glyph')
    finally:
        tab.close()


SNAPSHOT = """{project:'Smoke A', modName:'Glyph fixture', copyToMods:false, modsPath:'', protected:false, skipped:0, excluded:[],
  included:[{name:'Body', game_rel:'Characters/1015/1015101/Materials/MI_1015101_Body', file_type:'material'},
            {name:'Equip', game_rel:'Characters/1015/1015101/Texture/T_1015101_Equip_01_D', file_type:'texture'}]}"""


def run_export_review_glyph_checks(context, url, report, checks):
    """The stage through a build: carries on, forms the real result, and a reopened result is still."""
    tab = context.new_page()
    errors = []
    tab.on('pageerror', lambda error: errors.append(str(error)))
    stage = "document.querySelector('.export-review-stage')"
    settled = """async () => {
      const svg = document.querySelector('.export-review-stage svg'), a = svg.innerHTML;
      await new Promise(r => setTimeout(r, 250));
      return svg.innerHTML === a;
    }"""
    try:
        tab.goto(url)
        tab.wait_for_function('window.AtelierExportReview && window.AtelierMotion?.glyph && window.atelierProject?.()')
        tab.emulate_media(reduced_motion='no-preference')
        tab.evaluate(f"""() => {{
          window.reviewSnapshot = Object.freeze({SNAPSHOT});
          document.getElementById('update-overlay')?.remove();
          AtelierExportReview.open(reviewSnapshot, {{confirm(){{}}, refresh(){{}}, settings(){{}}, reveal(){{}}}});
        }}""")
        assert tab.evaluate(f"{stage}.childNodes.length") == 0, 'The review itself shows no glyph'

        # Busy after busy carries on in the same glyph, and only a real result changes it.
        tab.evaluate(f"AtelierExportReview.checking(reviewSnapshot); window.reviewSvg = {stage}.querySelector('svg')")
        tab.evaluate("AtelierExportReview.start(reviewSnapshot)")
        tab.wait_for_timeout(1500)
        busy = tab.evaluate(f"({{same: {stage}.querySelector('svg') === reviewSvg, state: {stage}.dataset.glyphState, tier: {stage}.dataset.glyphTier, staging: AtelierExportReview.staging('busy')}})")
        assert busy == {'same': True, 'state': 'busy', 'tier': 'stage', 'staging': True}, busy
        assert not tab.evaluate(settled), 'Working should keep moving'
        tab.evaluate("AtelierExportReview.finish(reviewSnapshot, {ok:true, pak_path:'D:/Fixture/Glyph.pak', applied:[], skipped:[]})")
        done = tab.evaluate(f"({{same: {stage}.querySelector('svg') === reviewSvg, state: {stage}.dataset.glyphState, staging: AtelierExportReview.staging('success')}})")
        assert done == {'same': True, 'state': 'success', 'staging': True}, done
        # Complete has short holds of its own, so wait until nothing has changed for longer than any of them.
        for _ in range(12):
            if tab.evaluate(settled.replace('250', '800')):
                break
        else:
            raise AssertionError('The result never settled')
        halo = tab.evaluate(f"(()=>{{const p={stage}.querySelector('.glyph-piece'),m=document.querySelector('.export-review-modal');return [getComputedStyle(p).stroke,getComputedStyle(m).backgroundColor]}})()")
        probe = tab.evaluate("(c)=>{const d=document.createElement('div');d.style.color=c;document.body.append(d);const v=getComputedStyle(d).color;d.remove();return v}", halo[0])
        assert probe == tab.evaluate("(c)=>{const d=document.createElement('div');d.style.color=c;document.body.append(d);const v=getComputedStyle(d).color;d.remove();return v}", halo[1]), halo
        tab.locator('.export-review-modal').screenshot(path=str(report / 'export-review-glyph-success.png'))
        checks.append('Export review: busy carries on through checking and building, and the same glyph forms the real result on the dialog\'s own surface')

        # A reopened result is still.
        tab.keyboard.press('Escape')
        tab.locator('#export-review-overlay').wait_for(state='hidden')
        tab.locator('#export-last-result').click(force=True)
        assert tab.evaluate(f"{stage}.dataset.glyphState") == 'success'
        assert tab.evaluate(settled)
        # From the review, which has no glyph, the result mounts already finished.
        tab.evaluate("""() => {
          document.querySelector('#export-review-overlay').classList.remove('active');
          AtelierExportReview.open(reviewSnapshot, {confirm(){}, refresh(){}, settings(){}, reveal(){}});
        }""")
        assert tab.evaluate(f"{stage}.childNodes.length") == 0
        tab.evaluate("document.getElementById('export-last-result').click()")
        assert tab.evaluate(f"{stage}.dataset.glyphState") == 'success'
        assert tab.evaluate(settled), 'A reopened result should not play again'

        # Each outcome maps as SPEC section 7 says.
        for result, want, title in (
            ("{ok:true, pak_path:'D:/F.pak', applied:[], skipped:['Missing optional texture']}", 'warning', 'Mod exported with warnings'),
            ("{ok:false, built:true, pak_path:'D:/F.pak', error:'Copy failed', applied:[], skipped:[]}", 'warning', 'Export built; copy failed'),
            ("{ok:false, error:'The build failed. Check the export folder is writable.', applied:[], skipped:[]}", 'error', 'Export failed'),
            ("{ok:false, cancelled:true, error:'Export cancelled.', applied:[], skipped:[]}", 'info', 'Export cancelled'),
        ):
            tab.evaluate("AtelierExportReview.start(reviewSnapshot)")
            assert tab.evaluate(f"{stage}.dataset.glyphState") == 'busy'
            assert not tab.evaluate(settled), 'A new build after a still result moves again'
            tab.evaluate(f"AtelierExportReview.finish(reviewSnapshot, {result})")
            got = tab.evaluate(f"({{state: {stage}.dataset.glyphState, title: document.getElementById('export-review-title').textContent}})")
            assert got == {'state': want, 'title': title}, got
            tab.wait_for_timeout(1500)
            tab.locator('.export-review-modal').screenshot(path=str(report / f'export-review-glyph-{want}-{title.split()[1].strip(";")}.png'))
        checks.append('Export review: a reopened result is still; warnings, a failed copy, failure and cancelling each draw their own state, and a new build moves again')
        assert not errors, errors
    finally:
        tab.close()
