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
        motion_page.wait_for_function('window.__viewportMotion && window.AtelierMotion?.glyph && window.atelierProject?.()')
        motion_page.wait_for_selector('#grid-area .card')
        motion_page.emulate_media(reduced_motion='no-preference')
        motion_page.evaluate("""() => {
          window.originalGlyph = AtelierMotion.glyph;
          window.viewportMotionEvents = [];
          // Only the mesh loader's glyph is recorded; the appearance loader in the corner has its own checks.
          AtelierMotion.glyph = {...originalGlyph, mount(host, options) {
            if (host.id !== 'viewport-loading-motion-host') return originalGlyph.mount(host, options);
            viewportMotionEvents.push(options.state);
            const instance = originalGlyph.mount(host, options);
            return {
              set(state) { viewportMotionEvents.push(state); instance.set(state); },
              destroy() { viewportMotionEvents.push('destroy'); instance.destroy(); }
            };
          }};
        }""")

        def start_mesh(name='Fixture', immediate=False):
            motion_page.evaluate("""args => {
              const game_rel = 'Characters/1029/1029001/Meshes/' + args.name;
              __viewportMotion.configure({immediate:args.immediate,
                skinList:[{name:args.name,game_rel,kind:'body'}]});
              window.viewportOpen = AtelierViewport.openMesh(game_rel, args.name, '1029001');
            }""", {'name': name, 'immediate': immediate})

        def close_preview():
            motion_page.evaluate("async () => {__viewportMotion.guard(''); await AtelierViewport.close(); __viewportMotion.settleMaterials();}")
            assert not motion_page.evaluate("document.getElementById('viewport-overlay').classList.contains('active')")
            assert not motion_page.evaluate('__viewportMotion.state().animating')
            assert motion_page.locator('#viewport-loading-motion-host svg').count() == 0

        start_mesh('Slow materials')
        loader = motion_page.locator('#viewport-loading-motion-host')
        assert loader.get_attribute('data-glyph-state') == 'busy' and loader.get_attribute('data-glyph-asset') == 'mesh'
        assert loader.get_attribute('data-glyph-tier') == 'stage'
        motion_page.evaluate('__viewportMotion.model(0); viewportOpen')
        assert motion_page.locator('#viewport-loading').is_hidden()
        assert motion_page.locator('#viewport-loading-motion-host svg').count() == 0
        assert motion_page.evaluate('__viewportMotion.state().materialRequests') == 1
        assert motion_page.evaluate('__viewportMotion.state().children.length') == 1
        assert motion_page.evaluate("viewportMotionEvents.slice(-2)") == ['busy', 'destroy'], 'A model that arrives never forms the A'
        close_preview()
        start_mesh('Immediate fixture', immediate=True)
        motion_page.evaluate('viewportOpen')
        assert motion_page.locator('#viewport-loading').is_hidden()
        assert motion_page.evaluate("viewportMotionEvents.slice(-2)") == ['busy', 'destroy']
        close_preview()
        checks.append('Real viewport shows the mesh loader, reveals fast geometry immediately and never forms the A, even with pending material responses')

        motion_page.evaluate("__viewportMotion.configure({skinList:[]}); AtelierViewport.open('1029001', 'Empty fixture')")
        assert motion_page.locator('#viewport-loading-motion-host').get_attribute('data-glyph-state') == 'warning'
        assert motion_page.locator('#viewport-loading-msg').inner_text() == 'No meshes found for this skin.'
        close_preview()
        before = motion_page.evaluate('__viewportMotion.state().modelRequests')
        motion_page.evaluate("() => { __viewportMotion.configure(); window.viewportOpen = AtelierViewport.open('1029001', 'Failed skin fixture'); }")
        motion_page.wait_for_function(f'__viewportMotion.state().modelRequests === {before + 1}')
        motion_page.evaluate(f'__viewportMotion.model({before}, true); viewportOpen')
        assert motion_page.locator('#viewport-loading-motion-host').get_attribute('data-glyph-state') == 'error'
        assert motion_page.locator('#viewport-loading-msg').inner_text() == 'Failed to load meshes. Fixture mesh: Fixture decode failure'
        close_preview()
        before = motion_page.evaluate('__viewportMotion.state().modelRequests')
        start_mesh('Failed mesh fixture')
        motion_page.evaluate(f'__viewportMotion.model({before}, true); viewportOpen')
        assert motion_page.locator('#viewport-loading-motion-host').get_attribute('data-glyph-state') == 'error'
        assert 'Fixture decode failure' in motion_page.locator('#viewport-loading-msg').inner_text()
        close_preview()
        before = motion_page.evaluate('__viewportMotion.state().skinRequests')
        motion_page.evaluate("() => { __viewportMotion.configure({deferSkins:true}); window.viewportOpen=AtelierViewport.open('1029001', 'Failed index fixture'); }")
        motion_page.evaluate(f'__viewportMotion.skin({before}, [], true); viewportOpen')
        assert motion_page.locator('#viewport-loading-motion-host').get_attribute('data-glyph-state') == 'error'
        assert 'Fixture index failure' in motion_page.locator('#viewport-loading-msg').inner_text()
        close_preview()
        checks.append('Real viewport maps no meshes, failed decoding and failed index requests to truthful static outcomes')

        # Opening from artwork flies it to the stage; it waits behind arriving geometry and leaves with the sweep.
        from io import BytesIO
        from PIL import Image
        art = BytesIO(); Image.new('RGBA', (96, 96), (210, 160, 60, 255)).save(art, 'PNG'); art = art.getvalue()
        motion_page.route('**/api/catalogue/thumbnail/*', lambda route: route.fulfill(body=art, content_type='image/png'))

        def motion_mode(value):
            motion_page.evaluate("value=>{const c=document.getElementById('settings-motion');c.value=value;c.dispatchEvent(new Event('change'));}", value)

        def open_from_art(name):
            motion_page.evaluate("""async name => {
              document.querySelector('.poster-fixture')?.remove();
              const card=document.createElement('button');card.className='card poster-fixture';
              card.style='position:fixed;left:40px;top:140px;width:120px;height:150px;z-index:5;padding:0';
              const image=new Image();image.className='hero-portrait';image.style='width:100%;height:100%;object-fit:cover';
              image.src='/api/catalogue/thumbnail/1029001';card.append(image);document.body.append(card);
              await image.decode();card.focus();
              const game_rel='Characters/1029/1029001/Meshes/'+name;
              __viewportMotion.configure({skinList:[{name,game_rel,kind:'body'}]});
              window.viewportOpen=AtelierViewport.openMesh(game_rel,name,'1029001');
            }""", name)

        def settle_materials():
            # The studio can ask for its material set more than once; answer until appearance loading ends.
            motion_page.wait_for_function('__viewportMotion.state().materialRequests > 0')
            for _ in range(60):
                motion_page.evaluate('__viewportMotion.settleMaterials()')
                if not motion_page.evaluate("document.getElementById('viewport-stage').classList.contains('vp-assets-loading')"):
                    break
                motion_page.wait_for_timeout(50)

        motion_mode('full')
        before = motion_page.evaluate('__viewportMotion.state().modelRequests')
        open_from_art('Poster fixture')
        motion_page.wait_for_function("document.querySelector('.vp-poster-flight') && document.querySelector('.vp-poster')?.style.visibility === 'hidden'")
        motion_page.wait_for_function("!document.querySelector('.vp-poster-flight') && document.querySelector('.vp-poster')?.style.visibility === ''")
        layout = motion_page.evaluate("""() => {
          const poster=document.querySelector('.vp-poster'),slot=document.getElementById('viewport-loading-slot');
          return {phase:poster.dataset.phase,z:getComputedStyle(poster).zIndex,next:poster.nextElementSibling?.id,
            clear:slot.getBoundingClientRect().top>=poster.getBoundingClientRect().bottom,
            marked:document.getElementById('viewport-stage').classList.contains('vp-has-poster')};
        }""")
        assert layout == {'phase': 'loading', 'z': '4', 'next': 'viewport-canvas', 'clear': True, 'marked': True}, layout
        motion_page.evaluate(f'__viewportMotion.model({before})')
        motion_page.wait_for_function("""() => {
          const poster=document.querySelector('.vp-poster');
          return poster?.dataset.phase==='geometry' && getComputedStyle(poster).zIndex==='auto';
        }""")
        # While the appearance loads, the texture loader works Inline in the corner; the model stays in view.
        motion_page.wait_for_selector('#viewport-appearance:not([hidden]) .viewport-appearance-glyph[data-glyph-state="busy"][data-glyph-asset="texture"][data-glyph-tier="inline"]')
        corner = motion_page.evaluate("""() => {
          const stage=document.getElementById('viewport-stage').getBoundingClientRect(),notice=document.getElementById('viewport-appearance').getBoundingClientRect();
          return {left:notice.left-stage.left<40,bottom:stage.bottom-notice.bottom<40,canvas:getComputedStyle(document.getElementById('viewport-canvas')).visibility};
        }""")
        assert corner == {'left': True, 'bottom': True, 'canvas': 'visible'}, corner
        settle_materials()
        motion_page.wait_for_function("!document.querySelector('.vp-poster')")
        assert motion_page.evaluate("(n => n.hidden && !n.querySelector('svg,canvas') && !n.querySelector('[data-atelier-motion]'))(document.getElementById('viewport-appearance'))")
        assert not motion_page.evaluate("document.getElementById('viewport-stage').classList.contains('vp-has-poster')")
        close_preview()

        motion_mode('off')
        before = motion_page.evaluate('__viewportMotion.state().modelRequests')
        open_from_art('Still poster fixture')
        motion_page.wait_for_function("document.querySelector('.vp-poster')")
        assert not motion_page.locator('.vp-poster-flight').count()
        assert motion_page.evaluate("(p => p.style.visibility === '' && !p.getAnimations().length)(document.querySelector('.vp-poster'))")
        motion_page.evaluate(f'__viewportMotion.model({before})')
        settle_materials()
        motion_page.wait_for_function("!document.querySelector('.vp-poster')")
        close_preview()

        motion_mode('full')
        before = motion_page.evaluate('__viewportMotion.state().modelRequests')
        open_from_art('Failed poster fixture')
        motion_page.wait_for_function("document.querySelector('.vp-poster')")
        motion_page.evaluate(f'__viewportMotion.model({before}, true); viewportOpen')
        motion_page.wait_for_function("!document.querySelector('.vp-poster, .vp-poster-flight')")
        assert 'Fixture decode failure' in motion_page.locator('#viewport-loading-msg').inner_text()
        close_preview()
        before = motion_page.evaluate('__viewportMotion.state().modelRequests')
        open_from_art('Closed poster fixture')
        motion_page.wait_for_function("document.querySelector('.vp-poster-flight')")
        close_preview()
        assert not motion_page.locator('.vp-poster, .vp-poster-flight').count()
        motion_page.evaluate(f'__viewportMotion.model({before}); viewportOpen')
        assert not motion_page.locator('.vp-poster').count()
        motion_page.evaluate("document.querySelector('.poster-fixture')?.remove()")
        checks.append('Opening from costume artwork flies it to the stage above the loader, keeps it behind arriving geometry while the texture loader works in the corner, then folds it away into the stage floor; Off stays still, and failures and closing remove it at once')

        before = motion_page.evaluate('__viewportMotion.state().modelRequests')
        start_mesh('Old fixture')
        motion_page.evaluate("() => { window.oldViewportOpen=viewportOpen; }")
        start_mesh('New fixture')
        assert motion_page.locator('#viewport-loading-motion-host svg').count() == 1
        motion_page.evaluate(f'__viewportMotion.model({before}); oldViewportOpen')
        assert motion_page.locator('#viewport-loading-motion-host').get_attribute('data-glyph-state') == 'busy'
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
        assert motion_page.locator('#viewport-loading-motion-host').get_attribute('data-glyph-state') == 'busy'
        motion_page.evaluate(f'__viewportMotion.model({before + 1}); viewportOpen')
        close_preview()
        for fail in (False, True):
            old_skin = motion_page.evaluate('__viewportMotion.state().skinRequests')
            before = motion_page.evaluate('__viewportMotion.state().modelRequests')
            motion_page.evaluate("() => { __viewportMotion.configure({deferSkins:true}); window.oldViewportOpen=AtelierViewport.open('1029001', 'Old index'); }")
            start_mesh('New index fixture')
            motion_page.evaluate(f'__viewportMotion.skin({old_skin}, [], {str(fail).lower()}); oldViewportOpen')
            assert motion_page.locator('#viewport-loading-motion-host').get_attribute('data-glyph-state') == 'busy'
            motion_page.evaluate(f'__viewportMotion.model({before}); viewportOpen')
            close_preview()
        checks.append('Rapid reopen/close cancels old motion, disposes late geometry and ignores stale failures')

        before = motion_page.evaluate('__viewportMotion.state().modelRequests')
        start_mesh('Protected fixture')
        motion_page.evaluate("window.protectedLoader=document.querySelector('#viewport-loading-motion-host svg'); window.savedConfirm=AtelierDialog; window.AtelierDialog={confirm:async()=>false}")
        try:
            for guard in ('saving', 'edited'):
                motion_page.evaluate("""guard => {
                  __viewportMotion.guard(guard);
                  if (!AtelierViewport.hasPendingEdits()) throw Error('Missing public pending-edit guard');
                  const priorConfirm = window.AtelierDialog;
                  window.AtelierDialog = {confirm:() => { throw Error('Export guard prompted to discard'); }};
                  document.getElementById('viewport-materials').classList.remove('empty');
                  document.getElementById('viewport-mat-section').style.display = 'flex';
                  try { AtelierViewport.focusPendingEdits(); }
                  finally { window.AtelierDialog = priorConfirm; }
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
            motion_page.evaluate("window.AtelierDialog=savedConfirm; __viewportMotion.guard('')")
        motion_page.evaluate(f'__viewportMotion.model({before}); viewportOpen')
        close_preview()
        assert not motion_page.evaluate('AtelierViewport.hasPendingEdits()')
        checks.append('Save/dirty guards protect close/reopen; public export guards retain drafts and focus Save/status without discard prompts')

        for failure in ('missing', 'mount', 'state'):
            motion_page.evaluate("""failure => {
              AtelierMotion.glyph = failure === 'missing' ? undefined : failure === 'mount'
                ? {mount:()=>{throw Error('Fixture mount failure')}}
                : {mount(host, options) {
                    const instance=originalGlyph.mount(host, options);
                    return {set:()=>{throw Error('Fixture state failure')}, destroy:()=>instance.destroy()};
                  }};
            }""", failure)
            before = motion_page.evaluate('__viewportMotion.state().modelRequests')
            start_mesh(f'{failure} presentation fixture')
            if failure != 'state':
                assert motion_page.locator('#viewport-loading-slot .viewport-loader-fallback').is_visible()
            motion_page.evaluate(f'__viewportMotion.model({before}); viewportOpen')
            assert motion_page.locator('#viewport-loading').is_hidden(), failure
            assert motion_page.evaluate('__viewportMotion.state().children.length') == 1
            assert motion_page.locator('#viewport-loading-motion-host svg').count() == 0
            close_preview()
        motion_page.evaluate('AtelierMotion.glyph=originalGlyph')
        checks.append('Missing, throwing mount and throwing state presentation cannot prevent geometry loading or ready cleanup')

        before = motion_page.evaluate('__viewportMotion.state().modelRequests')
        start_mesh('Visible loader fixture')
        for width, height in ((1024, 768), (1400, 900)):
            motion_page.set_viewport_size({'width': width, 'height': height})
            for theme in ('light', 'dark'):
                motion_page.locator('#settings-theme').select_option(theme, force=True)
                dimensions = motion_page.locator('#viewport-loading-motion-host svg').evaluate("""svg => {
                  const rect=svg.getBoundingClientRect();
                  return {width:rect.width, height:rect.height, tier:svg.parentElement.dataset.glyphTier,
                    halo:getComputedStyle(svg.querySelector('.glyph-piece')).stroke};
                }""")
                # Browser transforms can round a CSS pixel to 111.99997 here.
                assert abs(dimensions['width'] - 135) < .01 and abs(dimensions['height'] - 112) < .01, dimensions
                assert dimensions['tier'] == 'stage' and dimensions['halo'] == 'rgb(23, 35, 55)', dimensions
                motion_page.screenshot(path=str(report / f'viewport-loader-{theme}-{width}.png'), animations='disabled')
                assert motion_page.locator('#viewport-inspect-tools').is_hidden()
                assert motion_page.locator('#viewport-tools').is_hidden()
        motion_page.evaluate(f'__viewportMotion.model({before}); viewportOpen')
        close_preview()
        checks.append('Viewport loader stays at the Stage tier on the dark stage in both themes at compact and standard desktop sizes')
        assert not errors, errors
    finally:
        motion_page.close()
