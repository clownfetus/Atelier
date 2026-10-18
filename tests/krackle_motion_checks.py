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
        tab.wait_for_function("window.AtelierMotion?.krackleGlyph && window.AtelierMotion?.emptyState && window.AtelierMotion?.krackleStage && window.atelierProject?.()")
        tab.wait_for_selector('#grid-area .card')
        tab.emulate_media(reduced_motion='no-preference')

        # Every .spinner is the CSS charge ring: six dots, a crest that counts round in steps.
        spinner = tab.evaluate("""() => {
          const s = document.createElement('div'); s.className = 'spinner'; document.body.append(s);
          const after = getComputedStyle(s, '::after'), before = getComputedStyle(s, '::before');
          const result = {name: after.animationName, timing: after.animationTimingFunction,
            mask: (after.maskImage || after.webkitMaskImage || '').startsWith('url('),
            ring: (before.maskImage || before.webkitMaskImage || '').startsWith('url('), border: getComputedStyle(s).borderTopWidth};
          s.remove(); return result;
        }""")
        assert spinner['name'] == 'krackle-charge' and 'steps' in spinner['timing'], spinner
        assert spinner['mask'] and spinner['ring'] and spinner['border'] == '0px', spinner
        tab.emulate_media(reduced_motion='reduce')
        assert tab.evaluate("""() => { const s = document.createElement('div'); s.className = 'spinner'; document.body.append(s);
          const name = getComputedStyle(s, '::after').animationName; s.remove(); return name; }""") == 'none'
        tab.emulate_media(reduced_motion='no-preference')
        checks.append('Every spinner renders as the Krackle charge ring and stops under reduced motion')

        # Job toasts resolve from the charge ring into a Krackle result that pops once, then holds still.
        # The export-feedback set owns operation toasts; without it, app.js falls back to a Krackle glyph.
        # Ordinary informational and warning toasts keep their Material icons.
        tab.evaluate("document.querySelectorAll('#toast-area .toast').forEach(el=>el.remove())")
        tab.evaluate("toast('Plain warning', 'warning', 60000)")
        assert tab.locator('#toast-area .toast.warning [data-atelier-motion]').count() == 0
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
        assert tab.locator('#toast-area [data-atelier-motion=krackle-glyph][data-am-state=warning]').count() == 1
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
        checks.append('Job toasts resolve into Krackle results that settle after one pop; plain notifications keep Material icons; failures keep the original icon')

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
          window.stage = AtelierMotion.krackleStage.mount(stageHost, {state:'busy', size:160});
        }""")
        tab.wait_for_timeout(400)
        first = tab.evaluate('stage.frames()')
        tab.wait_for_timeout(400)
        assert tab.evaluate('stage.frames()') > first and tab.evaluate("stageHost.dataset.amSleeping") == 'false'
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
