"""Krackle animations added across the app, using the real frontend and local fixtures only."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_krackle_motion_checks(page, context, url, report, checks):
    art = subprocess.run([sys.executable, str(ROOT / 'scripts/krackle_art.py'), '--check'],
                         capture_output=True, text=True)
    assert art.returncode == 0, art.stdout + art.stderr

    tab = context.new_page()
    errors = []
    tab.on('pageerror', lambda error: errors.append(str(error)))
    try:
        tab.goto(url)
        tab.wait_for_function("window.AtelierMotion?.krackleGlyph && window.AtelierEmptyGlyph && window.AtelierMotion?.krackleStage && window.atelierProject?.()")
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
          const thumb = document.createElement('div'); thumb.className = 'card-thumb'; thumb.innerHTML = '<div class="spinner"></div>';
          document.body.append(thumb);
          await new Promise(resolve => setTimeout(resolve, 50));
          const mounted = thumb.firstChild.hasAttribute('data-atelier-motion');
          thumb.remove();
          if (mounted) throw Error('A thumbnail spinner, which is never seen, got a glyph');
        }""")
        checks.append('Every spinner is the Micro glyph at work, a copy gets its own, it leaves with its spinner, and with no glyph the plain ring shows')

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

        # Job toasts resolve from the charge ring into a Krackle result that pops once, then holds still.
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

        tab.evaluate(r"""() => {
          const host = document.createElement('span'); document.body.append(host);
          const glyph = AtelierMotion.krackleGlyph.mount(host, {state:'busy'});
          try {
            if (host.dataset.atelierMotion !== 'glyph' || host.dataset.glyphState !== 'busy') throw Error('The old mount did not reach the new glyph');
            for (const state of ['success','warning','error','info']) {
              glyph.setState(state);
              if (host.dataset.glyphState !== state) throw Error('setState did not reach the new glyph: ' + state);
            }
            const svg = host.querySelector('svg');
            glyph.setReducedMotion('reduce'); glyph.setState('success');
            if (host.querySelector('svg') === svg) throw Error('setReducedMotion did nothing');
            if (host.dataset.glyphState !== 'success') throw Error('setReducedMotion lost the state');
            glyph.replay();
            if (host.getAnimations({subtree:true}).length) throw Error('The glyph used a CSS or WAAPI animation');
          } finally { glyph.destroy(); host.remove(); }
          if (host.childNodes.length || host.hasAttribute('data-atelier-motion')) throw Error('destroy left the glyph behind');
        }""")
        checks.append('The old glyph mount reaches the assembly glyph with the same handle: setState, replay, setReducedMotion and destroy')

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

        # The Krackle stage: busy keeps drawing, a result settles and stops, destroy cleans up.
        tab.evaluate("""() => {
          window.stageHost = document.createElement('div'); document.body.append(stageHost);
          stageHost.style.cssText='position:fixed;top:20px;left:20px;width:160px;height:160px';
          window.stage = AtelierMotion.krackleStage.mount(stageHost, {state:'busy', size:160});
        }""")
        tab.wait_for_timeout(400)
        first = tab.evaluate('stage.frames()')
        tab.wait_for_function('first=>stage.frames()>first&&stageHost.dataset.amSleeping==="false"', arg=first, timeout=8000)
        tab.evaluate("stage.setState('success')")
        tab.wait_for_function("stageHost.dataset.amSleeping === 'true'", timeout=8000)
        settled = tab.evaluate('stage.frames()')
        tab.wait_for_timeout(300)
        assert tab.evaluate('stage.frames()') == settled
        tab.evaluate("stage.setState('error')")
        tab.wait_for_function("stageHost.dataset.amSleeping === 'true'", timeout=10000)
        tab.evaluate("stage.setReducedMotion('reduce'); stage.setState('busy')")
        assert tab.evaluate("stageHost.dataset.amSleeping") == 'true'
        tab.evaluate("stage.destroy(); stage.destroy()")
        assert tab.evaluate("!stageHost.querySelector('canvas, svg') && !stageHost.dataset.atelierMotion")
        checks.append('Krackle stage loops only while busy, stops drawing once a result settles, honours reduced motion and cleans up')

        # A stage in a hidden dialog stops drawing; a busy-after-busy does not restart the drop.
        tab.evaluate("""() => {
          window.hiddenHost = document.createElement('div'); hiddenHost.style.display = 'none'; document.body.append(hiddenHost);
          window.hiddenStage = AtelierMotion.krackleStage.mount(hiddenHost, {state:'busy', size:120});
        }""")
        tab.wait_for_timeout(500)
        assert tab.evaluate('hiddenStage.frames()') <= 2 and tab.evaluate("hiddenHost.dataset.amSleeping") == 'true'
        tab.evaluate("hiddenHost.style.display = ''")
        tab.wait_for_function("hiddenHost.dataset.amSleeping === 'false'", timeout=3000)
        tab.evaluate("hiddenStage.destroy(); hiddenHost.remove()")
        checks.append('Hidden Krackle stages stop drawing and resume when their dialog is shown')

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
          if (after !== 'none' || mask.startsWith('url(')) throw Error('The counted ring still has Krackle dots: ' + [after, mask]);
        }""")
        checks.append('Activity shows a counted ring in plain colour, and the Micro glyph for work it cannot count')

        # The setup check band loops only while busy. The setup drop runs down a dotted line only as
        # far as the rows are valid and falls into the export review's ink-well once all are; the
        # well cooks until then and lands as its success. A row stopping being valid, or
        # reduced motion, settles at once.
        tab.evaluate("""() => {
          const page = window.wellPage = document.createElement('section');
          page.className = 'at-identity'; page.style.cssText = 'position:fixed;left:40px;top:40px;width:400px;height:460px;z-index:9999';
          page.innerHTML = [0, 1, 2].map(i => '<div class="fixture-row" style="position:absolute;left:0;right:0;top:' + (20 + i * 68) + 'px;height:68px">' +
            '<span class="fixture-glyph" style="position:absolute;left:0;top:24px;width:20px;height:20px"></span></div>').join('') +
            '<span id="fixture-well" style="position:absolute;left:0;top:250px"></span><span id="fixture-line" style="position:absolute;left:0;right:0;top:0;height:72px"></span>';
          document.body.append(page);
          window.wellInfo = waiting => ({rows: page.querySelectorAll('.fixture-row'), glyphs: page.querySelectorAll('.fixture-glyph'), waiting});
          window.well = AtelierMotion.setupDrop.mount(page.querySelector('#fixture-well'), {layer: page, size: 176});
          window.line = AtelierMotion.setupCheck.mount(page.querySelector('#fixture-line'), {state: 'busy'});
          well.setProgress(0, wellInfo('busy'));
        }""")
        host = "document.getElementById('fixture-well').dataset"
        state = f"[{host}.amReached, {host}.amFull, {host}.amMoving].join()"
        ink = "document.querySelector('#fixture-well [data-atelier-motion=ink-well]').dataset"
        tab.wait_for_function(f"[{ink}.amState, {ink}.amSleeping].join() === 'busy,false'", timeout=3000)
        lid = "document.querySelector('#fixture-well .am-setup-drop-lid-swing')"
        assert tab.evaluate(f"{host}.amLid") == 'shut' and tab.evaluate(f"getComputedStyle({lid}).transform") == 'none'
        assert tab.evaluate(state) == '0,false,false' and tab.evaluate("document.getElementById('fixture-line').dataset.amRunning") == 'true'
        assert tab.locator('.am-setup-drop-flight .am-setup-drop-flier').count() == 1
        assert tab.locator('.am-setup-drop-flight[data-am-waiting=busy]').count() == 1
        dots = tab.locator('.am-setup-drop-line .am-setup-drop-dot')
        assert dots.count() > 12 and tab.locator('.am-setup-drop-line .is-inked').count() <= 1
        tab.evaluate("well.setProgress(2, wellInfo('still'))")
        assert tab.evaluate(f"{host}.amMoving") == 'true'
        tab.wait_for_function(f"{state} === '2,false,false'", timeout=3000)
        inked = tab.locator('.am-setup-drop-line .is-inked').count()
        assert 1 < inked < dots.count() and tab.locator('.am-setup-drop-flight[data-am-waiting=still]').count() == 1
        tab.evaluate("well.setProgress(3, wellInfo('still'))")
        tab.wait_for_function(f"{state} === '3,true,false'", timeout=3000)
        assert tab.locator('.am-setup-drop-line .is-inked').count() == dots.count()
        # Landed: the well performed its success and its lid swung open in the done colour.
        assert tab.evaluate(f"{ink}.amState") == 'success' and tab.evaluate(f"{host}.amLid") == 'open'
        assert tab.evaluate(f"getComputedStyle({lid}).transform") != 'none'
        tab.evaluate("well.setProgress(1, wellInfo('still'))")
        assert tab.evaluate(state) == '1,false,false' and tab.evaluate(f"{ink}.amState") == 'busy' and tab.evaluate(f"{host}.amLid") == 'shut'
        tab.evaluate("line.setState('success'); document.documentElement.dataset.motion = 'reduce'; well.setProgress(3, wellInfo('still'))")
        assert tab.evaluate(state) == '3,true,false'
        assert tab.evaluate(f"[{ink}.amState, {ink}.amReduced, {ink}.amSleeping].join()") == 'success,true,true'
        assert tab.evaluate(f"{host}.amLid") == 'open' and tab.evaluate(f"getComputedStyle({lid}).transform") != 'none'
        assert tab.evaluate("document.getElementById('fixture-line').dataset.amRunning") == 'false'
        tab.evaluate("delete document.documentElement.dataset.motion; well.destroy(); well.destroy(); line.destroy(); line.destroy()")
        assert tab.evaluate("!wellPage.querySelector('svg') && !document.getElementById('fixture-well').hasAttribute('data-atelier-motion')")
        tab.evaluate("wellPage.remove()")
        checks.append('Setup check loops only while busy; the setup drop travels its dotted line only as far as rows are valid and lands in the cooking ink-well as its success with its lid swung open, settles at once on regression or reduced motion, and cleans up')
        assert not errors, errors
    finally:
        tab.close()
