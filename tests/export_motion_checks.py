"""The real frontend export hooks and their feedback, using local API fixtures."""
from urllib.parse import quote


def run_export_motion_checks(page, context, url, report, checks):
    # A separate page keeps test projects, pending exports and settings out of viewport checks.
    motion_page = context.new_page()
    errors = []
    motion_page.on('pageerror', lambda error: errors.append(str(error)))
    try:
        motion_page.goto(url)
        motion_page.wait_for_function("window.AtelierMotion?.glyph && window.AtelierExportFeedback && window.atelierProject?.()")
        motion_page.wait_for_selector('#grid-area .card')
        motion_page.emulate_media(reduced_motion='no-preference')
        response = {'value': {'ok': True, 'pak_path': 'fixture/Mod_P.pak', 'skipped': []}}
        requests = []

        def install_fixture(route):
            requests.append({'headers': route.request.headers, 'body': route.request.post_data_json})
            if response.get('abort'):
                route.abort('failed')
            else:
                route.fulfill(json=response['value'])

        motion_page.route('**/api/install_mod', install_fixture)
        motion_page.evaluate("""() => {
          window.originalMotionProject = _activeProjectName;
          _activeProjectName = 'Motion Ω';
          sidebarData = {motion: {selected:true, game_rel:'Characters/Fixture/MI_Body', file_type:'material'}};
          updateInstallBtn();
        }""")
        args = {'name': 'Motion fixture', 'items': [{'game_rel': 'Characters/Fixture/MI_Body'}],
                'skipped': 0, 'copy': True, 'password': 'test-password', 'project': 'Motion Ω'}

        def run_export(payload, expected, client_skipped=0, abort=False):
            response.update(value=payload, abort=abort)
            motion_page.evaluate("document.querySelectorAll('#toast-area .toast').forEach(el=>el.remove())")
            motion_page.evaluate("""args => _runInstall(args.name, args.items, args.skipped,
              args.copy, args.password, args.project)""", dict(args, skipped=client_skipped))
            assert motion_page.locator('#install-btn-motion-host').get_attribute('data-glyph-state') == expected
            assert motion_page.locator(f'#toast-area [data-glyph-state="{expected}"]').count() > 0
            assert motion_page.locator('#install-btn').is_enabled()

        run_export({'ok': True, 'pak_path': 'fixture/Mod_P.pak', 'skipped': []}, 'success')
        assert requests[-1]['headers']['x-atelier-project'] == quote(args['project'], safe='')
        assert requests[-1]['body'] == {'mod_name': args['name'], 'items': ['Characters/Fixture/MI_Body'],
                                        'password': 'test-password', 'copy_to_mods': True, 'background': True}
        run_export({'ok': True, 'pak_path': 'fixture/Mod_P.pak', 'skipped': []}, 'warning', client_skipped=1)
        run_export({'ok': True, 'installed_dir': 'fixture/mods', 'skipped': ['A', 'B', 'C', 'D', 'E']}, 'warning')
        assert '+1 more' in motion_page.locator('#toast-area').inner_text()
        run_export({'ok': False, 'built': True, 'pak_path': 'fixture/Mod_P.pak', 'error': 'fixture copy failure'}, 'warning')
        assert 'Export succeeded; installation failed' in motion_page.locator('#toast-area').inner_text()
        run_export({'ok': False, 'error': 'fixture build failure'}, 'error')
        run_export({'ok': False}, 'error', abort=True)
        run_export({'ok': False, 'need_mods_folder': True}, 'warning')
        assert motion_page.locator('#setup-overlay').evaluate("el=>el.classList.contains('active')")
        motion_page.evaluate("document.getElementById('setup-overlay').classList.remove('active')")
        checks.append('Real export hook preserves project headers/payload and distinguishes success, skipped work, partial install, settings and request errors')

        # Optional presentation must never suppress a request or turn a successful export into failure.
        response.update(value={'ok': True, 'pak_path': 'fixture/Mod_P.pak', 'skipped': []}, abort=False)
        motion_page.evaluate('window.originalExportPresentation = window.AtelierExportFeedback')
        try:
            for failure in ('missing', 'begin', 'toast', 'finish'):
                motion_page.evaluate("""failure => {
                  document.querySelectorAll('#toast-area .toast').forEach(el=>el.remove());
                  const original = originalExportPresentation;
                  window.presentationInjected = false;
                  if (failure === 'missing') window.AtelierExportFeedback = undefined;
                  else window.AtelierExportFeedback = {
                    ...original,
                    ...(failure === 'begin' ? {begin:()=>{throw Error('fixture begin')}} : {}),
                    ...(failure === 'toast' ? {toast:()=>{throw Error('fixture toast')}} : {}),
                    ...(failure === 'finish' ? {begin:()=>()=>{throw Error('fixture finish')}} : {})
                  };
                }""", failure)
                name = f'Motion {failure} <img src=x onerror="window.presentationInjected=true"> & Ω'
                before = len(requests)
                motion_page.evaluate("""args => _runInstall(args.name, args.items, args.skipped,
                  args.copy, args.password, args.project)""", dict(args, name=name))
                assert len(requests) == before + 1, failure
                assert requests[-1]['body']['mod_name'] == name
                assert motion_page.locator('#install-btn').is_enabled(), failure
                text = motion_page.locator('#toast-area').inner_text()
                assert f'Exported: {name}' in text, (failure, text)
                assert 'Error:' not in text and 'Export failed' not in text, (failure, text)
                assert motion_page.locator('#toast-area .toast.success').count() == 1
                assert motion_page.locator('#toast-area img').count() == 0
                assert not motion_page.evaluate('presentationInjected')
        finally:
            motion_page.evaluate('window.AtelierExportFeedback = originalExportPresentation')
        checks.append('Missing or throwing export presentation cannot block successful requests; fallback messages escape asset text')

        # Keep two actual fetch requests pending to test out-of-order visual completions.
        motion_page.unroute('**/api/install_mod', install_fixture)
        pending = []
        motion_page.route('**/api/install_mod', lambda route: pending.append(route))
        motion_page.evaluate("""() => { window.firstMotionExport = _runInstall('First',
          [{game_rel:'Characters/Fixture/First'}], 0, false, '', 'Motion Ω'); }""")
        motion_page.wait_for_function("document.getElementById('install-btn-motion-host').dataset.glyphState === 'busy'")
        motion_page.evaluate("""() => { window.secondMotionExport = _runInstall('Second',
          [{game_rel:'Characters/Fixture/Second'}], 0, false, '', 'Motion Ω'); }""")
        motion_page.wait_for_timeout(50)
        assert len(pending) == 2, len(pending)
        pending[1].fulfill(json={'ok': True, 'skipped': ['Fixture skipped']})
        motion_page.evaluate('secondMotionExport')
        assert motion_page.locator('#install-btn-motion-host').get_attribute('data-glyph-state') == 'warning'
        pending[0].fulfill(json={'ok': True, 'skipped': []})
        motion_page.evaluate('firstMotionExport')
        assert motion_page.locator('#install-btn-motion-host').get_attribute('data-glyph-state') == 'warning'
        motion_page.wait_for_function("!document.getElementById('install-btn-motion-host').dataset.glyphState", timeout=4000)
        # A completion from an old project must not turn the new project's button into success.
        motion_page.evaluate("""() => { window.oldProjectExport = _runInstall('Old project',
          [{game_rel:'Characters/Fixture/Old'}], 0, false, '', 'Motion Ω'); }""")
        motion_page.wait_for_timeout(50)
        assert len(pending) == 3
        motion_page.evaluate("_activeProjectName = 'Smoke B'; updateInstallBtn()")
        pending[2].fulfill(json={'ok': True, 'skipped': []})
        motion_page.evaluate('oldProjectExport')
        assert motion_page.locator('#install-btn-motion-host').get_attribute('data-glyph-state') != 'success'
        motion_page.evaluate('_activeProjectName = originalMotionProject; updateInstallBtn()')
        checks.append('Overlapping exports keep independent feedback; old operations/projects cannot overwrite current button results')

        motion_page.evaluate(r"""() => {
          window.fadeButton = document.getElementById('install-btn');
          window.fadeSlot = fadeButton.querySelector('.export-feedback-slot');
          window.fadeHost = document.getElementById('install-btn-motion-host');
          window.fadeDone = AtelierExportFeedback.begin(fadeButton); fadeDone('success');
        }""")
        assert motion_page.locator('#install-btn-motion-host').get_attribute('data-glyph-tier') == 'micro'
        motion_page.wait_for_function('!fadeHost.dataset.glyphState', polling=5, timeout=4000)
        motion_page.evaluate(r"""() => {
          const fallback = fadeSlot.firstElementChild;
          if (fadeHost.querySelector('svg') || fadeHost.getAnimations().length) throw Error('The glyph should go without a fade');
          if (getComputedStyle(fallback).display === 'none') throw Error('The icon did not come back');
          if (fadeSlot.getBoundingClientRect().width !== 28) throw Error('The result changed the icon slot');
          fadeDone = AtelierExportFeedback.begin(fadeButton);
          if (fadeHost.dataset.glyphState !== 'busy' || getComputedStyle(fallback).display !== 'none')
            throw Error('A new export did not bring the glyph back');
        }""")
        motion_page.wait_for_timeout(250)
        assert motion_page.locator('#install-btn-motion-host').get_attribute('data-glyph-state') == 'busy'
        motion_page.evaluate("fadeDone('warning')")
        motion_page.wait_for_function('!fadeHost.dataset.glyphState', polling=5, timeout=4000)
        checks.append('Export results hand back to the static icon in a fixed 28px slot, with no fade in the glyph, and a new export brings the glyph back')

        # While the review's stage draws the job, the button holds still, and it follows the dialog.
        moved = motion_page.evaluate("""async () => {
          window.reviewShown = true;
          window.quietDone = AtelierExportFeedback.begin(fadeButton, atelierProject(), {quiet: () => reviewShown});
          const frames = async () => { const a = fadeHost.innerHTML; await new Promise(r => setTimeout(r, 500)); return a !== fadeHost.innerHTML; };
          const shown = await frames();
          reviewShown = false; document.dispatchEvent(new Event('atelier:export-review'));
          const hidden = await frames();
          reviewShown = true; document.dispatchEvent(new Event('atelier:export-review'));
          const again = await frames();
          quietDone('success');
          const state = fadeHost.dataset.glyphState, done = await frames();
          return {shown, hidden, again, state, done};
        }""")
        assert moved == {'shown': False, 'hidden': True, 'again': False, 'state': 'success', 'done': False}, moved
        motion_page.wait_for_function('!fadeHost.dataset.glyphState', timeout=4000)
        checks.append('The button holds still while the review stage draws the job and follows the dialog as it hides and shows')

        motion_page.evaluate("""() => {
          document.querySelectorAll('#toast-area .toast').forEach(el=>el.remove());
          window.dismissedToast = AtelierExportFeedback.toast('Dismiss fixture', 'info', 0, 'busy');
          window.dismissedHost = dismissedToast.querySelector('[data-atelier-motion=glyph]');
          if (dismissedHost?.dataset.glyphState !== 'busy') throw Error('Toast did not mount the glyph');
          dismissedToast.remove(); dismissedToast.remove();
        }""")
        motion_page.wait_for_function("!dismissedToast.isConnected && !dismissedHost.querySelector('svg')")
        motion_page.evaluate("""() => {
          window.clickedToast = AtelierExportFeedback.toast('Click fixture', 'success', 5000, 'success');
          clickedToast.click();
          window.timedToast = AtelierExportFeedback.toast('Timeout fixture', 'success', 60, 'success');
        }""")
        motion_page.wait_for_function('!clickedToast.isConnected && !timedToast.isConnected')
        motion_page.evaluate("""() => {
          window.visibleToast = AtelierExportFeedback.toast('Exported: motion fixture', 'success', 5000, 'success');
        }""")
        for theme in ('light', 'dark'):
            motion_page.locator('#settings-theme').select_option(theme, force=True)
            motion_page.evaluate("AtelierExportFeedback.begin(document.getElementById('install-btn'))('success')")
            assert motion_page.locator('#install-btn-motion-host').evaluate('(el)=>el.getBoundingClientRect().width') == 44
            assert motion_page.locator('#toast-area [data-atelier-motion="glyph"]').evaluate('(el)=>[el.getBoundingClientRect().width,el.getBoundingClientRect().height]') == [59, 40]
            motion_page.screenshot(path=str(report / f'export-motion-{theme}.png'), animations='disabled')
        motion_page.evaluate('visibleToast.remove()')
        checks.append('Export toasts dispose on explicit removal, click and timeout; light/dark feedback captured')
        assert not errors, errors
    finally:
        motion_page.close()
