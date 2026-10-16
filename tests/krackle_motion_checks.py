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

        # Generic toasts swap their icon for a Krackle glyph that animates once, then holds still.
        tab.evaluate("document.querySelectorAll('#toast-area .toast').forEach(el=>el.remove())")
        for kind, state in (('success', 'success'), ('warning', 'warning'), ('info', 'info')):
            tab.evaluate("([kind]) => toast('Krackle ' + kind, kind, 60000)", [kind])
            host = tab.locator(f'#toast-area .toast.{kind} [data-atelier-motion=krackle-glyph]').last
            assert host.get_attribute('data-am-state') == state
            assert tab.locator(f'#toast-area .toast.{kind} .am-krackle-glyph-slot[data-am-mounted=true]').count() == 1
        tab.wait_for_function("!document.querySelector('#toast-area').getAnimations({subtree:true}).some(a=>a.effect?.target?.closest?.('[data-atelier-motion=krackle-glyph]'))")
        assert tab.evaluate("[...document.querySelectorAll('#toast-area .toast')].map(t=>t.innerText)") == ['Krackle success', 'Krackle warning', 'Krackle info']
        tab.locator('#toast-area .toast.success').click()
        assert tab.locator('#toast-area .toast.success').count() == 0
        tab.evaluate("""() => {
          const original = window.AtelierMotion.krackleGlyph;
          window.AtelierMotion.krackleGlyph = {mount() { throw Error('fixture glyph failure'); }};
          try { toast('Fallback <b>kept</b>', 'success', 60000); } finally { window.AtelierMotion.krackleGlyph = original; }
          const last = [...document.querySelectorAll('#toast-area .toast.success')].pop();
          if (!last.querySelector('svg.lucide') || last.querySelector('[data-atelier-motion]')) throw Error('Glyph failure lost the static icon');
          document.querySelectorAll('#toast-area .toast').forEach(el=>el.remove());
        }""")
        checks.append('Plain toasts gain Krackle glyphs that settle after one pop; removal disposes them and failures keep the original icon')

        # Grid empty states keep their text; the art is decorative and settles.
        tab.evaluate("buildGrid([])")
        tab.wait_for_selector('#empty-state [data-atelier-motion=empty-state][data-am-kind=empty]')
        assert tab.locator('#empty-state').inner_text().strip() == 'Empty folder'
        assert tab.locator('#empty-state svg.lucide').count() == 0
        tab.wait_for_function("!document.querySelector('#grid-area').getAnimations({subtree:true}).length")
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
          if (!document.querySelector('#empty-state svg.lucide') || document.querySelector('.am-empty-state-host'))
            throw Error('Empty-state failure lost the static icon');
        }""")
        tab.evaluate("renderGrid()")
        tab.wait_for_selector('#grid-area .card')
        checks.append('Empty folder, no-match and failure grids keep their text and icons as fallback while Krackle art settles')

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

        # Activity and primary-button presses.
        tab.evaluate("""() => {
          const b = document.getElementById('job-activity');
          b.toggleAttribute('data-krackle-busy', true);
          const name = getComputedStyle(b, '::after').animationName;
          b.toggleAttribute('data-krackle-busy', false);
          if (name !== 'krackle-charge') throw Error('Activity ring missing: ' + name);
        }""")
        box = tab.locator('#install-btn').bounding_box()
        tab.evaluate("document.getElementById('install-btn').disabled = false")
        tab.mouse.move(box['x'] + 20, box['y'] + box['height'] / 2)
        tab.mouse.down()
        assert tab.locator('.krackle-press-pop').count() == 1
        tab.mouse.up()
        tab.wait_for_function("!document.querySelector('.krackle-press-pop')")
        tab.emulate_media(reduced_motion='reduce')
        tab.mouse.down(); tab.mouse.up()
        assert tab.locator('.krackle-press-pop').count() == 0
        tab.emulate_media(reduced_motion='no-preference')
        checks.append('Activity shows a charge ring while jobs run; primary buttons pop bubbles on press, except under reduced motion')

        # Choosing a palette sweeps a halftone wave from the control; programmatic theme changes do not.
        tab.evaluate("document.documentElement.dataset.theme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'")
        assert tab.locator('.krackle-theme-wave').count() == 0
        presets = tab.locator('[data-theme-preset]:not([data-saved-palette])')
        current = tab.evaluate("document.documentElement.dataset.palette")
        target = next(i for i in range(presets.count()) if presets.nth(i).get_attribute('data-theme-preset') not in (current, 'custom'))
        presets.nth(target).evaluate('el => el.click()')
        tab.wait_for_selector('.krackle-theme-wave', state='attached', timeout=2000)
        tab.wait_for_selector('.krackle-theme-wave', state='detached', timeout=3000)
        tab.evaluate("palette => document.querySelector(`[data-theme-preset='${palette}']`).click()", current)
        checks.append('Choosing a theme or palette sweeps a one-shot halftone wave from the control, never on startup or programmatic changes')
        assert not errors, errors
    finally:
        tab.close()
