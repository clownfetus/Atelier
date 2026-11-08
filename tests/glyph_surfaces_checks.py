"""The glyph where the app shows it: spinners, bars, captions, empty grids and Activity. Real frontend, local fixtures."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_glyph_surfaces_checks(page, context, url, report, checks):
    tab = context.new_page()
    errors = []
    tab.on('pageerror', lambda error: errors.append(str(error)))
    try:
        tab.goto(url)
        tab.wait_for_function("window.AtelierMotion?.glyph && window.AtelierEmptyGlyph && window.atelierProject?.()")
        tab.wait_for_selector('#grid-area .card')
        tab.emulate_media(reduced_motion='no-preference')

        # Every spinner is the Micro glyph, working, however it was added, and it goes when the spinner does.
        spinner = tab.evaluate("""async () => {
          const box = document.createElement('div'); box.style.cssText = 'position:fixed;left:24px;top:130px;z-index:9999';
          box.innerHTML = '<div class="spinner"></div>';
          document.body.append(box);
          const s = window.spinnerGlyph = box.firstChild;
          await new Promise(resolve => setTimeout(resolve, 50));
          const style = getComputedStyle(s), border = style.borderTopWidth, animation = style.animationName;
          const rect = s.getBoundingClientRect(), first = s.innerHTML;
          let moved = false;
          for (let i = 0; i < 20 && !moved; i++) {
            await new Promise(resolve => setTimeout(resolve, 50));
            moved = s.innerHTML !== first;
          }
          box.remove();
          await new Promise(resolve => setTimeout(resolve, 50));
          return {motion: s.dataset.atelierMotion === 'glyph' || s.classList.contains('atelier-glyph') ? 'left' : 'gone',
            wasMoving: moved, width: rect.width, height: rect.height, border, animation};
        }""")
        assert spinner['motion'] == 'gone' and spinner['wasMoving'], spinner
        assert spinner['width'] == 31 and spinner['height'] == 20, spinner
        assert spinner['border'] == '0px' and spinner['animation'] == 'none', spinner
        tab.evaluate("""async () => {
          const box = document.createElement('div'); box.style.cssText = 'position:fixed;left:24px;top:130px;z-index:9999';
          box.innerHTML = '<div class="spinner"></div>';
          document.body.append(box);
          await new Promise(resolve => setTimeout(resolve, 50));
          const s = box.firstChild;
          if (s.dataset.glyphState !== 'busy' || s.dataset.glyphTier !== 'micro') throw Error('Spinner is not the Micro glyph: ' + s.outerHTML.slice(0, 200));
          const copy = s.cloneNode(true); box.append(copy);
          await new Promise(resolve => setTimeout(resolve, 50));
          if (copy.querySelectorAll('svg').length !== 1 || copy.dataset.glyphState !== 'busy') throw Error('A copied spinner has no working glyph');
          box.remove();
          const original = AtelierMotion.glyph;
          AtelierMotion.glyph = {...original, mount() { throw Error('fixture spinner failure'); }};
          const plain = document.createElement('div'); plain.className = 'spinner'; document.body.append(plain);
          await new Promise(resolve => setTimeout(resolve, 50));
          AtelierMotion.glyph = original;
          const border = getComputedStyle(plain).borderTopWidth;
          plain.remove();
          if (border === '0px') throw Error('A spinner with no glyph lost its plain ring');
          const thumb = document.createElement('div'); thumb.className = 'card-thumb'; thumb.dataset.previewState = 'loading';
          document.body.append(thumb);
          const plate = getComputedStyle(thumb, '::before'), still = [plate.animationName, plate.backgroundImage, plate.content];
          thumb.remove();
          if (still[0] !== 'none' || still[1] !== 'none' || still[2] === 'none') throw Error('A loading thumbnail is not a still plate: ' + still);
        }""")
        checks.append('Every spinner is the Micro glyph at work, a copy gets its own, it leaves with its spinner, and with no glyph the plain ring shows; a loading thumbnail is a still plate')

        # Bars show counted steps only.
        bars = tab.evaluate("""() => {
          const open = document.createElement('progress'), counted = document.createElement('progress');
          counted.max = 4; counted.value = 2;
          const track = document.createElement('div'); track.className = 'progress-bar-bg'; track.innerHTML = '<div class="progress-bar-fill" style="width:40%"></div>';
          document.body.append(open, counted, track);
          const result = {open: getComputedStyle(open).display, counted: getComputedStyle(counted).display,
            fill: getComputedStyle(track.firstChild).backgroundColor, fillImage: getComputedStyle(track.firstChild).backgroundImage,
            trackImage: getComputedStyle(track).backgroundImage, text: getComputedStyle(document.body).color};
          open.remove(); counted.remove(); track.remove();
          return result;
        }""")
        assert bars['open'] == 'none' and bars['counted'] != 'none', bars
        assert bars['fillImage'] == 'none' and bars['trackImage'] == 'none', bars
        checks.append('A bar shows only counted steps in plain colour; with nothing to count there is no bar')

        # Counted bars: the material disc rolls the fill forward to the count, and never past it (SPEC 4.10).
        disc = tab.evaluate("""async () => {
          const setMode = v => { const c = document.getElementById('settings-motion'); c.value = v; c.dispatchEvent(new Event('change')); };
          const wait = ms => new Promise(r => setTimeout(r, ms)), frame = () => new Promise(r => requestAnimationFrame(r));
          const box = document.createElement('div'); box.style.cssText = 'position:fixed;left:40px;top:200px;width:300px;z-index:9999;background:rgb(40, 50, 60);padding:20px';
          box.innerHTML = '<div class="progress-bar-bg"><div class="progress-bar-fill" style="width:0%"></div></div>';
          document.body.append(box);
          setMode('full');
          await wait(50);
          const bar = box.firstChild, fill = bar.firstChild, svg = bar.querySelector('svg.progress-disc'), d = AtelierMotion.progressDisc.of(bar);
          const out = {one: bar.querySelectorAll('svg.progress-disc').length, hidden: getComputedStyle(fill).visibility, aria: svg.getAttribute('aria-hidden'),
            halo: bar.querySelector('.progress-disc-piece').style.stroke === getComputedStyle(box).backgroundColor};
          fill.style.width = '60%';
          await Promise.resolve();
          let most = 0, stretched = 1, landed = null, was = false;
          const t0 = performance.now();
          while (performance.now() - t0 < 1500) {
            await frame();
            most = Math.max(most, d.p); stretched = Math.max(stretched, d.sx);
            if (d.moving) was = true; else if (was && landed === null) landed = performance.now() - t0;
          }
          Object.assign(out, {landed, most, stretched, end: d.p, round: d.sx,
            reaches: Math.abs(+svg.querySelector('.progress-disc-fill').getAttribute('width') - (d.r + (d.W - 2 * d.r) * .6)) < .6});
          fill.style.width = '10%'; await wait(30); out.back = d.p;
          setMode('off'); fill.style.width = '90%'; await wait(30); out.off = d.p;
          setMode('calm'); fill.style.width = '20%'; await wait(30); fill.style.width = '70%';
          let calm = 1; const t1 = performance.now();
          while (performance.now() - t1 < 900) { await frame(); calm = Math.max(calm, d.sx); }
          out.calm = calm; out.calmEnd = d.p;
          setMode('full');
          out.fades = document.getAnimations().filter(a => svg.contains(a.effect?.target)).length;
          box.remove(); await wait(30);
          out.gone = !svg.isConnected && !AtelierMotion.progressDisc.of(bar);

          // A bar counted while its dialog is closed takes the count at once, and shows it when the dialog opens.
          const closed = document.createElement('div'); closed.style.cssText = 'display:none;position:fixed;left:40px;top:260px;width:300px;z-index:9999';
          closed.innerHTML = '<div class="progress-bar-bg"><div class="progress-bar-fill" style="width:0%"></div></div>';
          document.body.append(closed);
          await wait(30);
          closed.firstChild.firstChild.style.width = '30%';
          await wait(30);
          closed.style.display = 'block';
          await wait(700);
          const cd = AtelierMotion.progressDisc.of(closed.firstChild);
          out.closed = {p: cd.p, moving: cd.moving, drawn: getComputedStyle(closed.querySelector('svg.progress-disc')).display};
          closed.remove();

          // The startup bar is a <progress>: it keeps its value and role, and the disc sits on it.
          const splash = document.createElement('div'); splash.style.cssText = 'position:fixed;left:400px;top:200px;z-index:9999;display:flex;flex-direction:column;gap:12px;padding:20px;background:rgb(40, 50, 60)';
          splash.innerHTML = '<span>Opening your library</span><progress max="10" value="4" style="width:180px;height:3px"></progress>';
          document.body.append(splash);
          await wait(50);
          const p = splash.querySelector('progress'), ps = splash.querySelector('svg.progress-disc'), pr = p.getBoundingClientRect(), sr = ps.getBoundingClientRect();
          out.startup = {sibling: p.nextElementSibling === ps, role: p.getAttribute('role') || p.tagName, value: p.value,
            over: Math.abs((sr.top + sr.height / 2) - (pr.top + pr.height / 2)) < 1 && Math.abs(sr.left - pr.left) < 1 && Math.abs(sr.width - pr.width) < 1};
          p.removeAttribute('value'); await wait(30);
          out.startup.empty = getComputedStyle(ps).display;
          splash.remove(); await wait(30);
          out.startup.gone = !ps.isConnected;

          // Activity: a refreshed ring carries on from where the last one was.
          const button = document.createElement('button'); button.style.cssText = 'position:fixed;left:40px;top:300px;z-index:9999';
          const ring = (v) => { const r = document.createElement('span'); r.className = 'activity-ring'; r.style.setProperty('--job-progress', v + '%'); return r; };
          button.append(ring(50), 'Activity');
          document.body.append(button);
          await wait(900);
          const first = AtelierMotion.progressDisc.of(button.firstChild).p;
          button.replaceChildren(document.createTextNode('Activity')); button.prepend(ring(75));
          await wait(0);
          const next = AtelierMotion.progressDisc.of(button.firstChild);
          out.ring = {first, carried: next.p, track: getComputedStyle(button.firstChild).backgroundImage};
          await wait(900); out.ring.end = next.p;
          button.remove();
          return out;
        }""")
        assert disc['one'] == 1 and disc['hidden'] == 'hidden' and disc['aria'] == 'true' and disc['halo'], disc
        assert disc['landed'] is not None and disc['landed'] <= 640 + 60 and disc['most'] <= .6 + 1e-6 and disc['end'] == .6, disc
        assert disc['stretched'] > 1.05 and disc['round'] == 1 and disc['reaches'], disc
        assert disc['back'] == .1 and disc['off'] == .9 and disc['calm'] == 1 and disc['calmEnd'] == .7, disc
        assert disc['fades'] == 0 and disc['gone'], disc
        assert disc['closed'] == {'p': .3, 'moving': False, 'drawn': 'block'}, disc
        assert disc['startup'] == {'sibling': True, 'role': 'PROGRESS', 'value': 4, 'over': True, 'empty': 'none', 'gone': True}, disc
        assert disc['ring']['first'] == .5 and disc['ring']['carried'] >= .5 - 1e-6 and disc['ring']['carried'] < .75 and disc['ring']['end'] == .75, disc
        assert disc['ring']['track'] == 'none', disc
        checks.append('Counted bars roll the material disc to the count, landing within 640 ms and never past it; '
                      'Calm rolls without the stretch, Off steps, a new count goes straight back, and the Activity ring carries on across refreshes')

        # Job toasts resolve from the charge ring into a glyph result that pops once, then holds still.
        # The export-feedback set owns operation toasts; without it, app.js falls back to the small toast glyph.
        # Ordinary informational and warning toasts keep their Material icons.
        tab.evaluate("document.querySelectorAll('#toast-area .toast').forEach(el=>el.remove())")
        tab.evaluate("toast('Plain warning', 'warning', 60000)")
        assert tab.locator('#toast-area .toast.warning [data-atelier-motion=glyph][data-glyph-state=warning]').count() == 1
        assert tab.evaluate("(()=>{const r=document.querySelector('#toast-area .toast.warning [data-atelier-motion=glyph]').getBoundingClientRect();return [r.width,r.height]})()") == [31, 20]
        assert tab.locator('#toast-area .toast.warning svg.lucide').count() == 1
        for state in ('success', 'warning', 'error'):
            tab.evaluate("state => { const t = toastSpinner('Working ' + state); t.resolve('Finished ' + state, state, 60000); }", state)
            assert tab.locator(f'#toast-area .export-feedback-slot [data-atelier-motion=glyph][data-glyph-state={state}]').count() == 1, state
        tab.evaluate("""() => {
          const feedback = window.AtelierExportFeedback;
          window.AtelierExportFeedback = undefined;
          try { const t = toastSpinner('Working glyph'); t.resolve('Finished glyph', 'warning', 60000); }
          finally { window.AtelierExportFeedback = feedback; }
        }""")
        assert tab.locator('#toast-area .toast',has_text='Finished glyph').locator('[data-atelier-motion=glyph][data-glyph-state=warning]').count() == 1
        tab.wait_for_function("!document.querySelector('#toast-area').getAnimations({subtree:true}).some(a=>a.effect?.target?.closest?.('[data-atelier-motion]'))", timeout=8000)
        assert tab.evaluate("[...document.querySelectorAll('#toast-area .toast')].map(t=>t.innerText.trim())") == [
            'Plain warning', 'Finished success', 'Finished warning', 'Finished error', 'Finished glyph']
        tab.evaluate("document.querySelectorAll('#toast-area .toast').forEach(el=>el.remove())")
        assert tab.locator('#toast-area [data-atelier-motion]').count() == 0
        tab.evaluate("""() => {
          const original = window.AtelierMotion.glyph, feedback = window.AtelierExportFeedback;
          window.AtelierMotion.glyph = {mount() { throw Error('fixture glyph failure'); }};
          window.AtelierExportFeedback = undefined;
          let toastEl;
          try { toastEl = toastSpinner('Fallback'); toastEl.resolve('Fallback kept', 'success', 60000); }
          finally { window.AtelierMotion.glyph = original; window.AtelierExportFeedback = feedback; }
          if (!toastEl.querySelector('svg.lucide') || toastEl.querySelector('[data-atelier-motion]')) throw Error('Glyph failure lost the static icon');
          toastEl.remove();
        }""")
        checks.append('Caption notifications use micro formations; job results settle after one pop and controller failures keep the original icon')

        # Grid empty states keep their text; the glyph is decorative and never moves.
        still_glyph = '#empty-state > .empty-state-glyph[data-atelier-motion=glyph]'
        tab.evaluate("buildGrid([])")
        tab.wait_for_selector(still_glyph + '[data-glyph-state=info]')
        assert tab.locator('#empty-state').inner_text().strip().startswith('Empty folder')
        assert tab.locator('#empty-state svg.lucide').count() == 0
        assert tab.evaluate("""async selector => {
          const svg = document.querySelector(selector + ' svg'), first = svg.innerHTML;
          for (let i = 0; i < 12; i++) {
            await new Promise(resolve => setTimeout(resolve, 50));
            if (svg.innerHTML !== first || svg.getAnimations().length) return false;
          }
          return true;
        }""", still_glyph)
        tab.locator('#search-scope').click()
        tab.locator('#search-input').fill('no such asset anywhere')
        tab.evaluate("buildGrid([_makeCard({type:'folder', name:'Characters', rel_path:'Characters'})])")
        tab.wait_for_selector(still_glyph + '[data-glyph-state=info]')
        assert tab.locator('#empty-state').inner_text().strip().startswith('No matches')
        tab.locator('#search-input').fill('')
        tab.screenshot(path=str(report / 'empty-state.png'))
        tab.evaluate("""() => {
          const original = window.AtelierMotion.glyph;
          window.AtelierMotion.glyph = {...original, mount() { throw Error('fixture empty failure'); }};
          try { buildGrid([]); } finally { window.AtelierMotion.glyph = original; }
          const host = document.querySelector('#empty-state');
          const fallback = host?.querySelector(':scope > svg:not(.lucide)');
          if (!fallback || getComputedStyle(fallback).display === 'none' || host.querySelector('.empty-state-glyph'))
            throw Error('Empty-state failure lost the static drawing');
          const failed = document.createElement('div'); failed.id = 'empty-state'; failed.textContent = 'Fixture failure';
          host.replaceWith(failed);
          AtelierEmptyGlyph.mount(failed, 'error');
          if (failed.querySelector('.empty-state-glyph')?.dataset.glyphState !== 'error') throw Error('A failed load has no X');
        }""")
        tab.evaluate("renderGrid()")
        tab.wait_for_selector('#grid-area .card')
        checks.append('Empty folder and no-match grids keep their text with a still glyph at rest, a failed load shows the X, and the drawing is the fallback')

        # Activity: a counted ring in plain colour; work that can't be counted is the Micro glyph.
        tab.evaluate("""async () => {
          const ring = document.createElement('span'); ring.className = 'activity-ring indeterminate spinner';
          document.getElementById('job-activity').prepend(ring);
          await new Promise(resolve => setTimeout(resolve, 50));
          const state = ring.dataset.glyphState, tier = ring.dataset.glyphTier, rect = ring.getBoundingClientRect();
          ring.remove();
          if (state !== 'busy' || tier !== 'micro' || rect.height !== 16) throw Error('Activity is not the Micro glyph: ' + [state, tier, rect.height]);
          const counted = document.createElement('span'); counted.className = 'activity-ring';
          counted.style.setProperty('--job-progress', '50%');
          document.getElementById('job-activity').prepend(counted);
          const after = getComputedStyle(counted, '::after').content, mask = getComputedStyle(counted).maskImage || '';
          counted.remove();
          if (after !== 'none' || mask.startsWith('url(')) throw Error('The counted ring still has dots: ' + [after, mask]);
        }""")
        checks.append('Activity shows a counted ring in plain colour, and the Micro glyph for work it cannot count')

        assert not errors, errors
    finally:
        tab.close()
