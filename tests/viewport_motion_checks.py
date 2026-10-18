"""Viewport SVG lifecycle against the real module, with controlled local geometry only."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

# Appended only to the intercepted module in this isolated test page. Production has no hooks.
HOOK = r"""
(() => {
  const nativeFetch = window.atelierFetch;
  const modelRequests = [], skinRequests = [], materialRequests = [], scenes = [];
  let immediate = false, deferSkins = false;
  let skinList = [{name:'Fixture mesh', game_rel:'Characters/1029/1029001/Meshes/Fixture'}];
  const response = value => ({json:async()=>value});
  function sceneFor(name) {
    const group = new THREE.Group(); group.name = name;
    const geometry = new THREE.BoxGeometry(1, 2, 1);
    const material = new THREE.MeshStandardMaterial({color:0xaccbff});
    material.name = 'Fixture material';
    const record = {name, geometryDisposed:false, materialDisposed:false};
    geometry.addEventListener('dispose', () => record.geometryDisposed = true);
    material.addEventListener('dispose', () => record.materialDisposed = true);
    group.add(new THREE.Mesh(geometry, material)); scenes.push(record);
    return {scene:group};
  }
  loader.loadAsync = url => immediate ? Promise.resolve(sceneFor(url)) : new Promise((resolve, reject) => {
    modelRequests.push({url, resolve:()=>resolve(sceneFor(url)), reject:()=>reject(Error('Fixture decode failure'))});
  });
  window.atelierFetch = (url, options, project) => {
    if (String(url).startsWith('/api/skin_meshes')) {
      if (!deferSkins) return Promise.resolve(response(skinList));
      return new Promise((resolve, reject) => skinRequests.push({
        resolve:value=>resolve(response(value)), reject:()=>reject(Error('Fixture index failure'))
      }));
    }
    if (url === '/api/skin_materials') return new Promise(resolve => materialRequests.push(
      ()=>resolve(response({ok:true, materials:{}}))));
    if (String(url).startsWith('/api/browse_material_dirs')) return Promise.resolve(response({dirs:[]}));
    return nativeFetch(url, options, project);
  };
  window.__viewportMotion = {
    configure(options={}) {
      immediate = Boolean(options.immediate); deferSkins = Boolean(options.deferSkins);
      skinList = options.skinList ?? [{name:'Fixture mesh', game_rel:'Characters/1029/1029001/Meshes/Fixture'}];
    },
    model: (index, fail=false) => modelRequests[index][fail ? 'reject' : 'resolve'](),
    skin: (index, value, fail=false) => skinRequests[index][fail ? 'reject' : 'resolve'](value),
    settleMaterials: () => materialRequests.splice(0).forEach(resolve=>resolve()),
    guard(kind) { saving = kind === 'saving'; edited = kind === 'edited' ? {Fixture:{Tint:[1,0,0,1]}} : {}; refreshFoot(); },
    state: () => ({generation, animating:!!raf, children:modelRoot?.children.map(child=>child.name) || [],
      modelRequests:modelRequests.length, skinRequests:skinRequests.length,
      materialRequests:materialRequests.length, scenes})
  };
})();
"""


def run_viewport_motion_checks(page, context, url, report, checks):
    motion_page = context.new_page()
    errors = []
    motion_page.on('pageerror', lambda error: errors.append(str(error)))
    motion_page.route('**/static/viewport.js', lambda route: route.fulfill(
        body=(ROOT / 'gui/viewport.js').read_text(encoding='utf-8') + HOOK,
        content_type='text/javascript'))
    try:
        motion_page.goto(url)
        motion_page.wait_for_function('window.__viewportMotion && window.AtelierMotion?.viewportLoader && window.atelierProject?.()')
        motion_page.wait_for_selector('#grid-area .card')
        motion_page.emulate_media(reduced_motion='no-preference')
        motion_page.evaluate(r"""() => {
          window.viewportTestHost = document.createElement('span');
          document.body.append(viewportTestHost);
          window.viewportTestMotion = AtelierMotion.viewportLoader.mount(viewportTestHost, {state:'loading'});
          window.viewportOldAnimations = viewportTestHost.getAnimations({subtree:true});
          if (!viewportOldAnimations.length) throw Error('Loading assembly did not animate');
          viewportTestMotion.setState('loading');
          if (!viewportOldAnimations.every(a => viewportTestHost.getAnimations({subtree:true}).includes(a)))
            throw Error('Repeated loading restarted assembly');
          viewportTestMotion.setState('ready');
          if (viewportTestHost.getAnimations({subtree:true}).length || !viewportOldAnimations.every(a=>a.playState==='idle'))
            throw Error('Ready retained assembly effects');
          viewportTestMotion.replay();
          if (viewportTestHost.getAnimations({subtree:true}).length) throw Error('Ready replay started motion');
          viewportTestMotion.setState('empty');
        }""")
        motion_page.wait_for_function('!viewportTestHost.getAnimations({subtree:true}).length')
        assert motion_page.evaluate("getComputedStyle(viewportTestHost.querySelector('.am-viewport-loader-outcome-empty')).opacity") == '1'
        motion_page.evaluate("viewportTestMotion.setState('error')")
        motion_page.wait_for_function('!viewportTestHost.getAnimations({subtree:true}).length')
        assert motion_page.evaluate("getComputedStyle(viewportTestHost.querySelector('.am-viewport-loader-outcome-error')).opacity") == '1'
        motion_page.evaluate(r"""() => {
          viewportTestMotion.setState('loading');
          window.viewportOldAnimations = viewportTestHost.getAnimations({subtree:true});
          viewportTestMotion = AtelierMotion.viewportLoader.mount(viewportTestHost, {state:'loading'});
          if (!viewportOldAnimations.every(a=>a.playState==='idle')) throw Error('Remount orphaned effects');
          if (viewportTestHost.querySelectorAll('svg').length !== 1) throw Error('Remount duplicated SVG');
        }""")
        motion_page.wait_for_function("viewportTestHost.getAnimations({subtree:true}).some(a=>a.effect.getTiming().iterations===Infinity)")
        motion_page.evaluate(r"""() => {
          const before = viewportTestHost.getAnimations({subtree:true});
          viewportTestMotion.setState('loading');
          const after = viewportTestHost.getAnimations({subtree:true});
          if (after.length !== before.length || !before.every(a=>after.includes(a)))
            throw Error('Repeated loading duplicated steady loops');
        }""")
        checks.append('Viewport SVG settles ready/empty/error, cancels interrupted assembly, and avoids duplicate loops/remounts')

        motion_page.emulate_media(reduced_motion='reduce')
        motion_page.wait_for_function("viewportTestHost.dataset.amReduced === 'true' && !viewportTestHost.getAnimations({subtree:true}).length")
        motion_page.evaluate("viewportTestMotion.setState('error'); viewportTestMotion.replay()")
        assert motion_page.evaluate('viewportTestHost.getAnimations({subtree:true}).length') == 0
        motion_page.emulate_media(reduced_motion='no-preference')
        motion_page.evaluate("viewportTestMotion.setReducedMotion('reduce'); viewportTestMotion.setState('loading')")
        assert motion_page.evaluate('viewportTestHost.getAnimations({subtree:true}).length') == 0
        motion_page.evaluate(r"""() => {
          viewportTestMotion.setReducedMotion('system');
          Object.defineProperty(document, 'hidden', {configurable:true, get:()=>window.viewportTestHidden});
          window.viewportTestHidden = true; document.dispatchEvent(new Event('visibilitychange'));
          if (viewportTestHost.getAnimations({subtree:true}).length) throw Error('Hidden loader kept animating');
          viewportTestHidden = false; document.dispatchEvent(new Event('visibilitychange'));
          if (!viewportTestHost.getAnimations({subtree:true}).length) throw Error('Visible pending loader did not resume');
          viewportTestHidden = true; document.dispatchEvent(new Event('visibilitychange'));
          viewportTestMotion.setState('error');
          viewportTestHidden = false; document.dispatchEvent(new Event('visibilitychange'));
          if (viewportTestHost.getAnimations({subtree:true}).length) throw Error('Completed outcome replayed on return');
          delete document.hidden;
          viewportTestMotion.destroy(); viewportTestMotion.destroy(); viewportTestMotion.setState('loading');
          if (viewportTestHost.querySelector('svg')) throw Error('Destroy left owned SVG');
        }""")
        checks.append('Viewport loader respects OS/forced reduced motion and visibility, with idempotent explicit teardown')

        motion_page.evaluate(r"""() => {
          const original = Element.prototype.animate;
          try {
            for (const mode of ['missing', 'throwing', 'partial']) {
              let calls = 0;
              Element.prototype.animate = mode === 'missing' ? undefined : function(...args) {
                if (mode === 'throwing' || ++calls === 4) throw Error('Fixture WAAPI failure');
                return original.apply(this, args);
              };
              const instance = AtelierMotion.viewportLoader.mount(viewportTestHost, {state:'loading'});
              if (!viewportTestHost.querySelector('svg')) throw Error('Animation failure lost static loader');
              const animations = viewportTestHost.getAnimations({subtree:true});
              const targets = animations.filter(a=>a.effect.getTiming().iterations===Infinity).map(a=>a.effect.target);
              if (new Set(targets).size !== targets.length) throw Error('Partial WAAPI failure duplicated loops');
              instance.setState('ready');
              if (viewportTestHost.getAnimations({subtree:true}).length) throw Error('Animation failure prevented ready cleanup');
              instance.destroy();
            }
          } finally { Element.prototype.animate = original; }
          viewportTestHost.remove();
          window.originalViewportLoader = AtelierMotion.viewportLoader;
          window.viewportMotionEvents = [];
          AtelierMotion.viewportLoader = {mount(host, options) {
            viewportMotionEvents.push(options.state);
            const instance = originalViewportLoader.mount(host, options);
            return {
              setState(state) { viewportMotionEvents.push(state); instance.setState(state); },
              destroy() { viewportMotionEvents.push('destroy'); instance.destroy(); }
            };
          }};
        }""")
        checks.append('Absent, throwing and partially failing WAAPI keep static artwork and cannot leave duplicate loader loops')

        def start_mesh(name='Fixture', immediate=False):
            motion_page.evaluate("""args => {
              __viewportMotion.configure({immediate:args.immediate});
              window.viewportOpen = AtelierViewport.openMesh('Characters/1029/1029001/Meshes/' + args.name, args.name, '1029001');
            }""", {'name': name, 'immediate': immediate})

        def close_preview():
            motion_page.evaluate("__viewportMotion.guard(''); AtelierViewport.close(); __viewportMotion.settleMaterials()")
            assert not motion_page.evaluate("document.getElementById('viewport-overlay').classList.contains('active')")
            assert not motion_page.evaluate('__viewportMotion.state().animating')
            assert motion_page.locator('#viewport-loading-motion-host svg').count() == 0

        start_mesh('Slow materials')
        assert motion_page.locator('#viewport-loading-motion-host').get_attribute('data-am-state') == 'loading'
        motion_page.evaluate("document.getElementById('viewport-loading-motion-host').getAnimations({subtree:true}).forEach(a=>a.pause())")
        motion_page.evaluate('__viewportMotion.model(0); viewportOpen')
        assert motion_page.locator('#viewport-loading').is_hidden()
        assert motion_page.locator('#viewport-loading-motion-host svg').count() == 0
        assert motion_page.evaluate('__viewportMotion.state().materialRequests') == 1
        assert motion_page.evaluate('__viewportMotion.state().children.length') == 1
        assert motion_page.evaluate("viewportMotionEvents.slice(-3)") == ['loading', 'ready', 'destroy']
        close_preview()
        start_mesh('Immediate fixture', immediate=True)
        motion_page.evaluate('viewportOpen')
        assert motion_page.locator('#viewport-loading').is_hidden()
        assert motion_page.evaluate("viewportMotionEvents.slice(-3)") == ['loading', 'ready', 'destroy']
        close_preview()
        checks.append('Real viewport reveals fast geometry immediately, even with paused assembly or pending material responses')

        motion_page.evaluate("__viewportMotion.configure({skinList:[]}); AtelierViewport.open('1029001', 'Empty fixture')")
        assert motion_page.locator('#viewport-loading-motion-host').get_attribute('data-am-state') == 'empty'
        assert motion_page.locator('#viewport-loading-msg').inner_text() == 'No meshes found for this skin.'
        close_preview()
        before = motion_page.evaluate('__viewportMotion.state().modelRequests')
        motion_page.evaluate("() => { __viewportMotion.configure(); window.viewportOpen = AtelierViewport.open('1029001', 'Failed skin fixture'); }")
        motion_page.wait_for_function(f'__viewportMotion.state().modelRequests === {before + 1}')
        motion_page.evaluate(f'__viewportMotion.model({before}, true); viewportOpen')
        assert motion_page.locator('#viewport-loading-motion-host').get_attribute('data-am-state') == 'error'
        assert motion_page.locator('#viewport-loading-msg').inner_text() == 'Failed to load meshes. Fixture mesh: Fixture decode failure'
        close_preview()
        before = motion_page.evaluate('__viewportMotion.state().modelRequests')
        start_mesh('Failed mesh fixture')
        motion_page.evaluate(f'__viewportMotion.model({before}, true); viewportOpen')
        assert motion_page.locator('#viewport-loading-motion-host').get_attribute('data-am-state') == 'error'
        assert 'Fixture decode failure' in motion_page.locator('#viewport-loading-msg').inner_text()
        close_preview()
        before = motion_page.evaluate('__viewportMotion.state().skinRequests')
        motion_page.evaluate("() => { __viewportMotion.configure({deferSkins:true}); window.viewportOpen=AtelierViewport.open('1029001', 'Failed index fixture'); }")
        motion_page.evaluate(f'__viewportMotion.skin({before}, [], true); viewportOpen')
        assert motion_page.locator('#viewport-loading-motion-host').get_attribute('data-am-state') == 'error'
        assert 'Fixture index failure' in motion_page.locator('#viewport-loading-msg').inner_text()
        close_preview()
        checks.append('Real viewport maps no meshes, failed decoding and failed index requests to truthful static outcomes')

        before = motion_page.evaluate('__viewportMotion.state().modelRequests')
        start_mesh('Old fixture')
        motion_page.evaluate("window.oldViewportOpen=viewportOpen; window.oldViewportEffects=document.getElementById('viewport-loading-motion-host').getAnimations({subtree:true})")
        start_mesh('New fixture')
        assert motion_page.evaluate("oldViewportEffects.every(a=>a.playState==='idle')")
        motion_page.evaluate(f'__viewportMotion.model({before}); oldViewportOpen')
        assert motion_page.locator('#viewport-loading-motion-host').get_attribute('data-am-state') == 'loading'
        assert motion_page.evaluate('__viewportMotion.state().children.length') == 0
        assert motion_page.evaluate('__viewportMotion.state().scenes.at(-1).geometryDisposed')
        assert motion_page.evaluate('__viewportMotion.state().scenes.at(-1).materialDisposed')
        motion_page.evaluate(f'__viewportMotion.model({before + 1}); viewportOpen')
        assert 'New%20fixture' in motion_page.evaluate('__viewportMotion.state().children[0]')
        close_preview()
        before = motion_page.evaluate('__viewportMotion.state().modelRequests')
        start_mesh('Closed fixture')
        close_preview()
        motion_page.evaluate(f'__viewportMotion.model({before}); viewportOpen')
        assert motion_page.evaluate('__viewportMotion.state().children.length') == 0
        assert motion_page.evaluate('__viewportMotion.state().scenes.at(-1).geometryDisposed')
        assert motion_page.locator('#viewport-loading-motion-host svg').count() == 0
        # A stale rejected request must not replace the next loader with an error.
        before = motion_page.evaluate('__viewportMotion.state().modelRequests')
        start_mesh('Old rejected fixture')
        motion_page.evaluate('() => { window.oldViewportOpen=viewportOpen; }')
        start_mesh('Current fixture')
        motion_page.evaluate(f'__viewportMotion.model({before}, true); oldViewportOpen')
        assert motion_page.locator('#viewport-loading-motion-host').get_attribute('data-am-state') == 'loading'
        motion_page.evaluate(f'__viewportMotion.model({before + 1}); viewportOpen')
        close_preview()
        for fail in (False, True):
            old_skin = motion_page.evaluate('__viewportMotion.state().skinRequests')
            before = motion_page.evaluate('__viewportMotion.state().modelRequests')
            motion_page.evaluate("() => { __viewportMotion.configure({deferSkins:true}); window.oldViewportOpen=AtelierViewport.open('1029001', 'Old index'); }")
            start_mesh('New index fixture')
            motion_page.evaluate(f'__viewportMotion.skin({old_skin}, [], {str(fail).lower()}); oldViewportOpen')
            assert motion_page.locator('#viewport-loading-motion-host').get_attribute('data-am-state') == 'loading'
            motion_page.evaluate(f'__viewportMotion.model({before}); viewportOpen')
            close_preview()
        checks.append('Rapid reopen/close cancels old motion, disposes late geometry and ignores stale failures')

        before = motion_page.evaluate('__viewportMotion.state().modelRequests')
        start_mesh('Protected fixture')
        motion_page.evaluate("window.protectedLoader=document.querySelector('#viewport-loading-motion-host svg'); window.savedConfirm=window.confirm; window.confirm=()=>false")
        try:
            for guard in ('saving', 'edited'):
                motion_page.evaluate("""guard => {
                  __viewportMotion.guard(guard);
                  if (!AtelierViewport.hasPendingEdits()) throw Error('Missing public pending-edit guard');
                  const priorConfirm = window.confirm;
                  window.confirm = () => { throw Error('Export guard prompted to discard'); };
                  document.getElementById('viewport-materials').classList.remove('empty');
                  document.getElementById('viewport-mat-section').style.display = 'flex';
                  try { AtelierViewport.focusPendingEdits(); }
                  finally { window.confirm = priorConfirm; }
                  const expectedFocus = guard === 'saving' ? 'viewport-status' : 'viewport-mat-save';
                  if (document.activeElement.id !== expectedFocus) throw Error('Pending-edit focus: expected ' + expectedFocus + ', got ' + document.activeElement.id);
                  if (!AtelierViewport.hasPendingEdits()) throw Error('Pending-edit focus discarded the draft');
                  AtelierViewport.close();
                  AtelierViewport.open('1029002', 'Blocked skin');
                  AtelierViewport.openMesh('Characters/1029/1029002/Meshes/Blocked', 'Blocked mesh', '1029002');
                }""", guard)
                assert motion_page.evaluate('document.querySelector("#viewport-loading-motion-host svg") === protectedLoader')
                assert motion_page.evaluate('__viewportMotion.state().modelRequests') == before + 1
                assert motion_page.evaluate("document.getElementById('viewport-overlay').classList.contains('active')")
        finally:
            motion_page.evaluate("window.confirm=savedConfirm; __viewportMotion.guard('')")
        motion_page.evaluate(f'__viewportMotion.model({before}); viewportOpen')
        close_preview()
        assert not motion_page.evaluate('AtelierViewport.hasPendingEdits()')
        checks.append('Save/dirty guards protect close/reopen; public export guards retain drafts and focus Save/status without discard prompts')

        for failure in ('missing', 'mount', 'state'):
            motion_page.evaluate("""failure => {
              AtelierMotion.viewportLoader = failure === 'missing' ? undefined : failure === 'mount'
                ? {mount:()=>{throw Error('Fixture mount failure')}}
                : {mount(host, options) {
                    const instance=originalViewportLoader.mount(host, options);
                    return {setState:()=>{throw Error('Fixture state failure')}, destroy:()=>instance.destroy()};
                  }};
            }""", failure)
            before = motion_page.evaluate('__viewportMotion.state().modelRequests')
            start_mesh(f'{failure} presentation fixture')
            if failure != 'state':
                assert motion_page.locator('#viewport-loading-slot .am-viewport-loader-fallback').is_visible()
            motion_page.evaluate(f'__viewportMotion.model({before}); viewportOpen')
            assert motion_page.locator('#viewport-loading').is_hidden(), failure
            assert motion_page.evaluate('__viewportMotion.state().children.length') == 1
            assert motion_page.locator('#viewport-loading-motion-host svg').count() == 0
            close_preview()
        motion_page.evaluate('AtelierMotion.viewportLoader=originalViewportLoader')
        checks.append('Missing, throwing mount and throwing state presentation cannot prevent geometry loading or ready cleanup')

        before = motion_page.evaluate('__viewportMotion.state().modelRequests')
        start_mesh('Visible loader fixture')
        for width, height in ((1024, 768), (1400, 900)):
            motion_page.set_viewport_size({'width': width, 'height': height})
            for theme in ('light', 'dark'):
                motion_page.locator('#settings-theme').select_option(theme, force=True)
                dimensions = motion_page.locator('#viewport-loading-motion-host svg').evaluate("""svg => {
                  const rect=svg.getBoundingClientRect();
                  // Krackle has no strokes: the smallest charge dot must stay a readable comic dot.
                  const dots=[...svg.querySelectorAll('.am-viewport-loader-dot')].map(dot=>Number(dot.getAttribute('r')));
                  return {width:rect.width, height:rect.height, dot:Math.min(...dots), dots:dots.length,
                    viewBox:svg.viewBox.baseVal.width};
                }""")
                assert dimensions['width'] == 72 and dimensions['height'] == 72, dimensions
                assert dimensions['dots'] == 12 and dimensions['dot'] * dimensions['width'] / dimensions['viewBox'] >= 2.5, dimensions
                motion_page.screenshot(path=str(report / f'viewport-loader-{theme}-{width}.png'), animations='disabled')
                assert motion_page.locator('#viewport-inspect-tools').is_hidden()
                assert motion_page.locator('#viewport-tools').is_hidden()
        motion_page.evaluate(f'__viewportMotion.model({before}); viewportOpen')
        close_preview()
        checks.append('Viewport loader remains 72px with readable comic-sized dots in both themes at compact and standard desktop sizes')
        assert not errors, errors
    finally:
        motion_page.close()
