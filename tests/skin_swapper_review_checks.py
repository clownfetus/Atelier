"""Skin Swapper export review: read-only IDs, live rule checks and the build request.

Status, plan, conflict and build routes are intercepted; nothing is built or written."""

MESH = 'Characters/1024/1024503/Meshes/SK_1024_1024503'
CLOAK = 'Characters/1025/1025001/Meshes/10251/SK_10251_1025001'
DAGGER = 'Characters/1025/1025001/Meshes/10250/SK_10250_1025001'
FORMS = {MESH: 0, CLOAK: 1, DAGGER: 0}


def run_skin_swapper_review_checks(page, context, url, report, checks):
    tab = context.new_page()
    errors, builds, plans = [], [], []
    status = {'available': True, 'template': True, 'enabled': True, 'reasons': []}
    tab.on('pageerror', lambda error: errors.append(str(error)))

    def plan(route):
        body = route.request.post_data_json
        plans.append(body)
        problems = [] if (body.get('author') or '').strip() else ['Author is required.']
        entries = [{'game_rel': item['game_rel'], 'sculpt': FORMS[item['game_rel']]} for item in body['meshes']]
        route.fulfill(json={'ok': True, 'entries': entries, 'problems': problems, 'status': status})

    def build(route):
        builds.append(route.request.post_data_json)
        route.fulfill(json={'ok': True, 'pak_path': 'D:/Fixture/RedeemedRedux_9999999_P.pak', 'skipped': [],
                            'applied': ['mesh SK_1024_1024503 -> /Game/Marvel/ProjectGalacta/Meshes/1024/1024503/RedeemedRedux/',
                                        'config GAL_RedeemedRedux (hero 1024, skin 1024503, form 0)'],
                            'artifacts': [], 'galacta_folder': '/Game/Marvel/ProjectGalacta/Meshes/1024/1024503/RedeemedRedux'})

    tab.route('**/api/skin_swapper/status', lambda route: route.fulfill(json=status))
    tab.route('**/api/skin_swapper/plan', plan)
    tab.route('**/api/skin_swapper/build', build)
    tab.route('**/api/check_mod_conflict?**', lambda route: route.fulfill(json={'default': False, 'mods': False}))
    try:
        tab.goto(url)
        tab.wait_for_function('window.AtelierExportReview && window.atelierProject?.()')
        tab.wait_for_selector('#grid-area .card')
        tab.evaluate("""mesh => {
          try { localStorage.removeItem('atelier.skinSwapper.author'); } catch (_) {}
          _pathLabels['Characters/1024'] = 'Hela'; _pathLabels['Characters/1024/1024503'] = 'The Redeemed';
          _modsFolderSet = false; _protectionPassword = '';
          sidebarData = {
            mesh: {name: 'SK_1024_1024503', game_rel: mesh, file_type: 'mesh', selected: true},
            tex: {name: 'T_Body_D', game_rel: 'Characters/1024/1024503/Textures/T_Body_D', file_type: 'texture', selected: true},
          };
          document.getElementById('mod-name-input').value = 'RedeemedRedux';
          updateInstallBtn(); doInstallMod();
        }""", MESH)
        tab.wait_for_selector('#export-review-overlay.active input[name="export-format"]')
        assert tab.locator('input[name="export-format"][value="standard"]').is_checked()
        tab.locator('input[name="export-format"][value="skin-swapper"]').check()
        tab.wait_for_selector('#skin-swapper-author')
        text = tab.locator('#export-review-overlay').inner_text()
        assert 'Hela · 1024' in text and 'The Redeemed · 1024503' in text, text
        assert '/Game/Marvel/ProjectGalacta/Meshes/1024/1024503/RedeemedRedux/' in text
        assert 'Left out of this Skin Swapper mod · 1' in text
        # Hero and skin are shown, never offered as inputs.
        assert tab.evaluate("[...document.querySelectorAll('#export-review-overlay input')].every(i => !/^\\d{4,7}$/.test(i.value))")
        tab.wait_for_function("document.querySelector('.skin-swapper-problems')?.textContent.includes('Author is required.')")
        assert tab.locator('#export-review-confirm').is_disabled()
        tab.locator('#skin-swapper-author').fill('Tendo')
        tab.wait_for_function("!document.getElementById('export-review-confirm').disabled")
        assert tab.locator('.skin-swapper-mesh select').count() == 0
        assert tab.locator('.skin-swapper-form').inner_text() == 'Form 0 (default)'
        assert plans[-1]['meshes'] == [{'game_rel': MESH}], plans[-1]
        tab.locator('#export-review-confirm').click()
        tab.wait_for_function("document.getElementById('export-review-title').textContent.startsWith('Mod exported')")
        body = builds[0]
        assert (body['mod_name'], body['author'], body['skin_name']) == ('RedeemedRedux', 'Tendo', 'The Redeemed'), body
        assert body['meshes'] == [{'game_rel': MESH}] and 'hero_id' not in body and 'skin_id' not in body
        result = tab.locator('#export-review-overlay').inner_text()
        assert 'Galacta folder: /Game/Marvel/ProjectGalacta/Meshes/1024/1024503/RedeemedRedux' in result
        assert 'never edits skins.txt' in result
        assert tab.evaluate("localStorage.getItem('atelier.skinSwapper.author')") == 'Tendo'
        tab.screenshot(path=str(report / 'skin-swapper-result.png'))

        tab.evaluate("""meshes => {
          document.getElementById('export-review-overlay').classList.remove('active');
          sidebarData = Object.fromEntries(meshes.map((game_rel, i) => [i, {
            game_rel, name: game_rel.split('/').pop(), file_type:'mesh', selected:true,
          }]));
          _pathLabels['Characters/1025'] = 'Cloak & Dagger';
          _pathLabels['Characters/1025/1025001'] = 'Default';
          document.getElementById('mod-name-input').value = 'CloakEdit';
          updateInstallBtn(); doInstallMod();
        }""", [CLOAK, DAGGER])
        tab.wait_for_function("document.querySelector('.skin-swapper-form')?.textContent === 'Form 1'")
        assert tab.locator('.skin-swapper-form').all_text_contents() == ['Form 1', 'Form 0 (default)']
        assert tab.locator('.skin-swapper-mesh select').count() == 0
        assert plans[-1]['meshes'] == [{'game_rel': CLOAK}, {'game_rel': DAGGER}]
        assert 'Cloak & Dagger · 1025' in tab.locator('#export-review-overlay').inner_text()
        tab.screenshot(path=str(report / 'skin-swapper-detected-forms.png'))

        status.update(available=False, enabled=False, reasons=['Project Galacta has switched Skin Swapper export off.'])
        tab.evaluate("document.getElementById('export-review-overlay').classList.remove('active'); doInstallMod()")
        tab.wait_for_selector('#export-review-overlay.active input[name="export-format"][value="skin-swapper"]:disabled')
        assert 'switched Skin Swapper export off' in tab.locator('.export-format').inner_text()
        assert tab.locator('input[name="export-format"][value="standard"]').is_checked()
        tab.screenshot(path=str(report / 'skin-swapper-unavailable.png'))
        assert len(builds) == 1 and not errors, (builds, errors)
        checks.append('Skin Swapper review shows hero/skin read-only from the mesh, gates Build on live rule checks, '
                      'reads Cloak form 1 and Dagger form 0 from the server without a dropdown or caller-supplied IDs/forms, and explains a revoked switch')
    finally:
        tab.close()
