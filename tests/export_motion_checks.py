"""Export SVG/controller and real frontend export hooks, using local API fixtures."""
from urllib.parse import quote


def run_export_motion_checks(page, context, url, report, checks):
    # A separate page keeps test projects, pending exports and settings out of viewport checks.
    motion_page = context.new_page()
    errors = []
    motion_page.on('pageerror', lambda error: errors.append(str(error)))
    try:
        motion_page.goto(url)
        motion_page.wait_for_function("window.AtelierMotion?.exportFeedback && window.AtelierExportFeedback && window.atelierProject?.()")
        motion_page.wait_for_selector('#grid-area .card')
        motion_page.emulate_media(reduced_motion='no-preference')
        motion_page.evaluate("""() => {
          window.motionHost = document.createElement('span');
          document.body.append(motionHost);
          window.motionInstance = AtelierMotion.exportFeedback.mount(motionHost, {state:'busy'});
          window.motionAnimations = motionHost.getAnimations({subtree:true});
          if (!motionAnimations.length) throw Error('Busy state did not animate');
          motionInstance.setState('busy');
          const repeated = motionHost.getAnimations({subtree:true});
          if (!motionAnimations.every(a => repeated.includes(a))) throw Error('Repeated busy restarted motion');
          motionInstance.setState('success');
          if (!motionAnimations.every(a => a.playState === 'idle')) throw Error('Old busy loop survived success');
        }""")
        motion_page.wait_for_function('motionHost.getAnimations({subtree:true}).length === 0')
        assert motion_page.evaluate("getComputedStyle(motionHost.querySelector('.am-export-feedback-outcome-success')).opacity") == '1'
        motion_page.evaluate("""() => {
          motionInstance.destroy();
          motionInstance.destroy();
          motionInstance.setState('busy');
          if (motionHost.querySelector('svg')) throw Error('Destroy left owned SVG');
          motionInstance = AtelierMotion.exportFeedback.mount(motionHost, {state:'success'});
          if (!motionHost.getAnimations({subtree:true}).length) throw Error('Fresh success toast did not animate');
          motionInstance.setState('busy');
        }""")
        checks.append('Export motion handles repeated states, terminal mounting, interruption and finished-effect cleanup')

        motion_page.emulate_media(reduced_motion='reduce')
        motion_page.wait_for_function("motionHost.dataset.amReduced === 'true' && !motionHost.getAnimations({subtree:true}).length")
        motion_page.evaluate("motionInstance.setReducedMotion('system'); motionInstance.setState('success')")
        assert motion_page.evaluate('motionHost.getAnimations({subtree:true}).length') == 0
        motion_page.emulate_media(reduced_motion='no-preference')
        motion_page.evaluate("motionInstance.setReducedMotion('reduce'); motionInstance.setState('warning')")
        assert motion_page.evaluate('motionHost.getAnimations({subtree:true}).length') == 0
        assert motion_page.evaluate("getComputedStyle(motionHost.querySelector('.am-export-feedback-well')).transitionDuration") == '0s'
        motion_page.evaluate("""() => {
          motionInstance.setReducedMotion('system'); motionInstance.setState('busy');
          Object.defineProperty(document, 'hidden', {configurable:true, get:()=>window.motionHidden});
          window.motionHidden = true;
          document.dispatchEvent(new Event('visibilitychange'));
          const runningMotion = () => motionHost.getAnimations({subtree:true}).filter(a=>a.constructor.name === 'Animation');
          if (runningMotion().length) throw Error('Hidden document kept animating');
          motionInstance.setState('success');
          window.motionHidden = false;
          document.dispatchEvent(new Event('visibilitychange'));
          if (runningMotion().length) throw Error('Hidden one-shot replayed on return');
          motionInstance.setState('busy');
          motionHidden = true; document.dispatchEvent(new Event('visibilitychange'));
          motionHidden = false; document.dispatchEvent(new Event('visibilitychange'));
          if (!motionHost.getAnimations({subtree:true}).length) throw Error('Busy motion did not resume');
          delete document.hidden;
          motionInstance.destroy();
        }""")
        checks.append('OS/forced reduced motion stop CSS and WAAPI; hidden work pauses and completed one-shots stay settled')

        motion_page.evaluate("""() => {
          const original = Element.prototype.animate;
          try {
            for (const unavailable of [undefined, () => {throw Error('WAAPI unavailable')}]) {
              Element.prototype.animate = unavailable;
              const instance = AtelierMotion.exportFeedback.mount(motionHost, {state:'busy'});
              instance.setState('success');
              if (!motionHost.querySelector('svg') || motionHost.dataset.amState !== 'success')
                throw Error('Missing animation support lost static feedback');
              instance.destroy();
            }
          } finally { Element.prototype.animate = original; }
          motionInstance = AtelierMotion.exportFeedback.mount(motionHost, {state:'busy'});
          window.detachedAnimations = motionHost.getAnimations({subtree:true});
          motionHost.remove();
        }""")
        motion_page.wait_for_function("detachedAnimations.every(a => a.playState === 'idle') && !motionHost.querySelector('svg')")
        motion_page.evaluate("""() => {
          motionInstance.setState('success'); motionInstance.destroy();
          document.body.append(motionHost);
          motionInstance = AtelierMotion.exportFeedback.mount(motionHost, {state:'idle'});
          if (motionHost.querySelectorAll('svg').length !== 1) throw Error('Remount duplicated artwork');
          motionInstance.setState('busy');
          const old = motionInstance, oldSvg = motionHost.querySelector('svg');
          const oldAnimations = motionHost.getAnimations({subtree:true});
          motionInstance = AtelierMotion.exportFeedback.mount(motionHost, {state:'busy'});
          old.setState('error'); old.destroy();
          if (oldSvg.isConnected || !oldAnimations.every(a=>a.playState === 'idle'))
            throw Error('Duplicate mount kept old artwork or animation');
          if (motionHost.dataset.amState !== 'busy' || motionHost.querySelectorAll('svg').length !== 1)
            throw Error('Old controller interfered with replacement mount');
          window.removedSvgAnimations = motionHost.getAnimations({subtree:true});
          motionHost.querySelector('svg').remove();
        }""")
        motion_page.wait_for_function("removedSvgAnimations.every(a=>a.playState === 'idle') && !motionHost.dataset.amState")
        motion_page.evaluate("""() => {
          motionInstance.setState('success');
          if (motionHost.dataset.amState) throw Error('Removed SVG controller still changed host');
          motionInstance.destroy(); motionHost.remove();
        }""")
        checks.append('Missing/throwing WAAPI preserves feedback; host/SVG removal and duplicate mounting clean up motion')

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
            assert motion_page.locator('#install-btn-motion-host').get_attribute('data-am-state') == expected
            assert motion_page.locator(f'#toast-area [data-am-state="{expected}"]').count() > 0
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
        motion_page.wait_for_function("document.getElementById('install-btn-motion-host').dataset.amState === 'busy'")
        motion_page.evaluate("""() => { window.secondMotionExport = _runInstall('Second',
          [{game_rel:'Characters/Fixture/Second'}], 0, false, '', 'Motion Ω'); }""")
        motion_page.wait_for_timeout(50)
        assert len(pending) == 2, len(pending)
        pending[1].fulfill(json={'ok': True, 'skipped': ['Fixture skipped']})
        motion_page.evaluate('secondMotionExport')
        assert motion_page.locator('#install-btn-motion-host').get_attribute('data-am-state') == 'warning'
        pending[0].fulfill(json={'ok': True, 'skipped': []})
        motion_page.evaluate('firstMotionExport')
        assert motion_page.locator('#install-btn-motion-host').get_attribute('data-am-state') == 'warning'
        motion_page.wait_for_function("!document.getElementById('install-btn-motion-host').dataset.amState || document.getElementById('install-btn-motion-host').dataset.amState === 'idle'", timeout=4000)
        # A completion from an old project must not turn the new project's button into success.
        motion_page.evaluate("""() => { window.oldProjectExport = _runInstall('Old project',
          [{game_rel:'Characters/Fixture/Old'}], 0, false, '', 'Motion Ω'); }""")
        motion_page.wait_for_timeout(50)
        assert len(pending) == 3
        motion_page.evaluate("_activeProjectName = 'Smoke B'; updateInstallBtn()")
        pending[2].fulfill(json={'ok': True, 'skipped': []})
        motion_page.evaluate('oldProjectExport')
        assert motion_page.locator('#install-btn-motion-host').get_attribute('data-am-state') != 'success'
        motion_page.evaluate('_activeProjectName = originalMotionProject; updateInstallBtn()')
        checks.append('Overlapping exports keep independent feedback; old operations/projects cannot overwrite current button results')

        motion_page.evaluate("""() => {
          document.querySelectorAll('#toast-area .toast').forEach(el=>el.remove());
          window.dismissedToast = AtelierExportFeedback.toast('Dismiss fixture', 'info', 0, 'busy');
          window.dismissedAnimations = dismissedToast.getAnimations({subtree:true});
          if (!dismissedAnimations.length) throw Error('Toast did not mount motion');
          dismissedToast.remove(); dismissedToast.remove();
        }""")
        motion_page.wait_for_function("!dismissedToast.isConnected && dismissedAnimations.every(a=>a.playState === 'idle')")
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
            assert motion_page.locator('#install-btn-motion-host').evaluate('(el)=>el.getBoundingClientRect().width') == 20
            assert motion_page.locator('#toast-area [data-atelier-motion="export-feedback"]').evaluate('(el)=>el.getBoundingClientRect().width') == 24
            motion_page.screenshot(path=str(report / f'export-motion-{theme}.png'), animations='disabled')
        motion_page.evaluate('visibleToast.remove()')
        checks.append('Export toasts dispose on explicit removal, click and timeout; light/dark feedback captured')
        assert not errors, errors
    finally:
        motion_page.close()
