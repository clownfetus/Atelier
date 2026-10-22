"""Krackle animations added across the app, using the real frontend and local fixtures only."""
import subprocess
from io import BytesIO

from PIL import Image, ImageChops
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
        tab.wait_for_function("window.AtelierMotion?.krackleGlyph && window.AtelierMotion?.emptyState && window.AtelierMotion?.krackleStage && window.atelierProject?.()")
        tab.wait_for_selector('#grid-area .card')
        tab.emulate_media(reduced_motion='no-preference')

        # Native 20px spinners carry opaque connected ink; pressure follows the conduit, not a rotation.
        spinner = tab.evaluate("""() => {
          const s = window.fluidSpinner = document.createElement('div'); s.className = 'spinner';
          s.style.cssText='position:fixed;left:24px;top:130px;background:#14161b;--krackle-energy:#e0a552;z-index:9999';
          document.body.append(s);
          const after = getComputedStyle(s, '::after'), before = getComputedStyle(s, '::before');
          const mask = decodeURIComponent(before.maskImage || before.webkitMaskImage || '');
          return {name:after.animationName,timing:after.animationTimingFunction,duration:after.animationDuration,
            pressure:(after.maskImage || after.webkitMaskImage || '').startsWith('url('),
            connected:mask.includes('M5 5C5 9 10 7 10 11C10 15 16 12 16 18'),
            holes:mask.includes('<mask') && mask.includes("fill='black'"),
            opaque:before.opacity,border:getComputedStyle(s).borderTopWidth,width:s.getBoundingClientRect().width,
            stationary:before.transform==='none' && before.animationName==='none'};
        }""")
        assert spinner['name'] == 'krackle-fluid-charge' and 'steps' not in spinner['timing'], spinner
        assert spinner['duration'] == '1.04s' and spinner['width'] == 20, spinner
        assert spinner['pressure'] and spinner['connected'] and spinner['holes'], spinner
        assert spinner['opaque'] == '1' and spinner['stationary'] and spinner['border'] == '0px', spinner
        samples = []
        for phase in (220, 660):
            tab.evaluate('phase=>{for(const a of fluidSpinner.getAnimations()){a.pause();a.currentTime=phase;}}', phase)
            pixels = Image.open(BytesIO(tab.locator('.spinner').last.screenshot())).convert('RGB')
            assert pixels.size == (20, 20), pixels.size
            ink = {(x, y) for y in range(20) for x in range(20)
                   if max(abs(pixels.getpixel((x, y))[c] - (20, 22, 27)[c]) for c in range(3)) > 28}
            count = len(ink)
            largest = 0
            while ink:
                todo = [ink.pop()]
                size = 0
                while todo:
                    x, y = todo.pop()
                    size += 1
                    for dx, dy in ((-1,-1),(0,-1),(1,-1),(-1,0),(1,0),(-1,1),(0,1),(1,1)):
                        point = (x+dx, y+dy)
                        if point in ink:
                            ink.remove(point)
                            todo.append(point)
                largest = max(largest, size)
            assert count >= 60 and largest >= count * .9, (phase, count, largest)
            pixels.save(report / f'fluid-spinner-{phase}.png')
            samples.append(pixels)
        assert ImageChops.difference(*samples).getbbox(), 'Pressure did not travel through the stationary fluid carrier'
        tab.evaluate('for(const a of fluidSpinner.getAnimations())a.play()')
        for mode in ('calm', 'off'):
            tab.evaluate("mode=>{window.spinnerOldMode=document.documentElement.dataset.krackle;document.documentElement.dataset.krackle=mode;}", mode)
            assert tab.evaluate("getComputedStyle(fluidSpinner,'::after').animationName") == 'none'
            assert tab.evaluate("getComputedStyle(fluidSpinner,'::before').opacity") == '1'
            tab.evaluate('document.documentElement.dataset.krackle=spinnerOldMode')
        tab.evaluate("document.documentElement.setAttribute('data-krackle-hidden','')")
        assert tab.evaluate("getComputedStyle(fluidSpinner,'::after').animationPlayState") == 'paused'
        tab.evaluate("document.documentElement.removeAttribute('data-krackle-hidden')")
        tab.emulate_media(reduced_motion='reduce')
        assert tab.evaluate("getComputedStyle(fluidSpinner,'::after').animationName") == 'none'
        tab.emulate_media(reduced_motion='no-preference')
        tab.evaluate('fluidSpinner.remove()')
        checks.append('Native20px spinners render one opaque masked reservoir/conduit/receiver with travelling pressure; Calm/Off/reduced keep the connected pose and hidden pauses it')

        # Job toasts resolve from the charge ring into a Krackle result that pops once, then holds still.
        # The export-feedback set owns operation toasts; without it, app.js falls back to a Krackle glyph.
        # Ordinary informational and warning toasts keep their Material icons.
        tab.evaluate("document.querySelectorAll('#toast-area .toast').forEach(el=>el.remove())")
        tab.evaluate("toast('Plain warning', 'warning', 60000)")
        assert tab.locator('#toast-area .toast.warning [data-atelier-motion=krackle-glyph]').count() == 1
        assert tab.locator('#toast-area .toast.warning svg.lucide').count() == 1
        for state in ('success', 'warning', 'error'):
            tab.evaluate("state => { const t = toastSpinner('Working ' + state); t.resolve('Finished ' + state, state, 60000); }", state)
            assert tab.locator(f'#toast-area [data-atelier-motion=export-feedback][data-am-state={state}]').count() == 1, state
        tab.evaluate("""() => {
          const feedback = window.AtelierExportFeedback;
          window.AtelierExportFeedback = undefined;
          try { const t = toastSpinner('Working glyph'); t.resolve('Finished glyph', 'warning', 60000); }
          finally { window.AtelierExportFeedback = feedback; }
        }""")
        assert tab.locator('#toast-area .toast',has_text='Finished glyph').locator('[data-atelier-motion=krackle-glyph][data-am-state=warning]').count() == 1
        tab.wait_for_function("!document.querySelector('#toast-area').getAnimations({subtree:true}).some(a=>a.effect?.target?.closest?.('[data-atelier-motion]'))", timeout=8000)
        assert tab.evaluate("[...document.querySelectorAll('#toast-area .toast')].map(t=>t.innerText.trim())") == [
            'Plain warning', 'Finished success', 'Finished warning', 'Finished error', 'Finished glyph']
        tab.evaluate("document.querySelectorAll('#toast-area .toast').forEach(el=>el.remove())")
        assert tab.locator('#toast-area [data-atelier-motion]').count() == 0
        tab.evaluate("""() => {
          const original = window.AtelierMotion.krackleGlyph, feedback = window.AtelierExportFeedback;
          window.AtelierMotion.krackleGlyph = {mount() { throw Error('fixture glyph failure'); }};
          window.AtelierExportFeedback = undefined;
          let toastEl;
          try { toastEl = toastSpinner('Fallback'); toastEl.resolve('Fallback kept', 'success', 60000); }
          finally { window.AtelierMotion.krackleGlyph = original; window.AtelierExportFeedback = feedback; }
          if (!toastEl.querySelector('svg.lucide') || toastEl.querySelector('[data-atelier-motion]')) throw Error('Glyph failure lost the static icon');
          toastEl.remove();
        }""")
        checks.append('Caption notifications use micro formations; job results settle after one pop and controller failures keep the original icon')

        tab.evaluate(r"""() => {
          const host = document.createElement('span'); document.body.append(host);
          const glyph = AtelierMotion.krackleGlyph.mount(host, {state:'busy'});
          try {
            for (const state of ['success','warning','error']) {
              glyph.setState('busy');
              const loops = host.getAnimations({subtree:true});
              glyph.setState(state);
              const ring = host.querySelector('.am-krackle-glyph-busy');
              const fade = ring.getAnimations()[0];
              if (!fade || fade.effect.getTiming().duration !== 140 || !loops.every(a=>a.playState==='idle'))
                throw Error('Busy glyph hard-cut or retained its old loop');
              fade.pause(); fade.currentTime = 70;
              const opacity = Number(getComputedStyle(ring).opacity);
              if (!(opacity > 0 && opacity < 1)) throw Error('Ring fade is not visible');
              glyph.setState('busy');
              if (fade.playState !== 'idle') throw Error('New work retained a stale result fade');
            }
            glyph.setReducedMotion('reduce'); glyph.setState('success');
            if (host.getAnimations({subtree:true}).length) throw Error('Reduced glyph faded');
          } finally { glyph.destroy(); host.remove(); }
        }""")
        checks.append('Activity glyph rings fade into real results for 140ms, cancel on new work, and stay still under reduced motion')

        # Grid empty states keep their text; the art is decorative and settles.
        tab.evaluate("buildGrid([])")
        tab.wait_for_selector('#empty-state [data-atelier-motion=empty-state][data-am-kind=empty]')
        assert tab.locator('#empty-state').inner_text().strip().startswith('Empty folder')
        assert tab.locator('#empty-state svg.lucide').count() == 0
        tab.wait_for_function("!document.querySelector('#grid-area').getAnimations({subtree:true}).length")
        tab.locator('#search-scope').click()
        tab.locator('#search-input').fill('no such asset anywhere')
        tab.evaluate("buildGrid([_makeCard({type:'folder', name:'Characters', rel_path:'Characters'})])")
        tab.wait_for_selector('#empty-state [data-atelier-motion=empty-state][data-am-kind=none]')
        assert tab.locator('#empty-state').inner_text().strip().startswith('No matches')
        tab.locator('#search-input').fill('')
        tab.screenshot(path=str(report / 'krackle-empty-state.png'))
        tab.evaluate("""() => {
          const original = window.AtelierMotion.emptyState;
          window.AtelierMotion.emptyState = {mount() { throw Error('fixture empty failure'); }};
          try { buildGrid([]); } finally { window.AtelierMotion.emptyState = original; }
          const host = document.querySelector('#empty-state');
          if (!host?.querySelector(':scope > svg:not(.lucide)') || host.querySelector('.am-empty-state-host'))
            throw Error('Empty-state failure lost the static drawing');
        }""")
        tab.evaluate("renderGrid()")
        tab.wait_for_selector('#grid-area .card')
        checks.append('Empty folder, no-match and failure grids keep their text and the static drawing as fallback while Krackle art settles')

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

        # Activity's running-jobs ring is six dots with a counting crest.
        tab.evaluate("""() => {
          const ring = document.createElement('span'); ring.className = 'activity-ring indeterminate';
          document.getElementById('job-activity').prepend(ring);
          const after = getComputedStyle(ring, '::after');
          const result = [after.animationName, (after.maskImage || after.webkitMaskImage || '').startsWith('url(')];
          ring.remove();
          if (result[0] !== 'krackle-charge' || !result[1]) throw Error('Activity ring is not Krackle: ' + result);
        }""")
        checks.append('Activity shows its running-jobs ring as six Krackle dots with a counting crest')
        assert not errors, errors
    finally:
        tab.close()
