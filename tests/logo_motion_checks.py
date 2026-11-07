"""The header logo's entrance in the real app: once on launch, then the still mark. Never writes project data."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRANCE = '.studio-brand > [data-glyph-entrance]'
INSTRUMENT = r"""
document.addEventListener('DOMContentLoaded', () => {
  window.logoEntrances = 0;
  new MutationObserver(records => {
    for (const record of records) for (const node of record.addedNodes)
      if (node.nodeType === 1 && node.parentElement?.matches('.studio-brand')) logoEntrances++;
  }).observe(document.querySelector('.studio-brand'), {childList: true});
  window.logoLabel = () => document.querySelector('.studio-wordmark').getBoundingClientRect().x;
  window.logoLabelBefore = logoLabel();
}, {once: true});
"""
STILL = "(el => !el.hidden && getComputedStyle(el).visibility === 'visible' && getComputedStyle(el).display !== 'none')(document.querySelector('.studio-brand > img'))"


def run_logo_motion_checks(page, context, url, report, checks):
    mark = subprocess.run([sys.executable, str(ROOT / 'scripts/brand_mark.py'), '--check'],
                          capture_output=True, text=True)
    assert mark.returncode == 0, mark.stdout + mark.stderr
    checks.append('The A mark vector, interface PNG and application icons match scripts/brand_mark.py')

    tab = context.new_page()
    errors, pending_config = [], []
    tab.on('pageerror', lambda error: errors.append(str(error)))
    tab.add_init_script(INSTRUMENT)
    # Hold the normal application configuration read: startup artwork must not wait.
    tab.route('**/api/config', lambda route: pending_config.append(route))
    try:
        tab.goto(url)
        tab.wait_for_selector(ENTRANCE)
        playing = tab.evaluate(f"""() => {{
          const host = document.querySelector('{ENTRANCE}'), box = host.getBoundingClientRect();
          return {{hidden: document.querySelector('.studio-brand > img').hidden, width: box.width, height: box.height,
                   tier: host.dataset.glyphTier, states: host.dataset.glyphState}};
        }}""")
        assert playing['hidden'] and abs(playing['width'] - 50.08) < .1 and abs(playing['height'] - 32.4) < .1, playing
        tab.wait_for_function(f"!document.querySelector('{ENTRANCE}')", timeout=4000)
        assert tab.evaluate(STILL), 'The still mark did not come back'
        assert abs(tab.evaluate('logoLabel() - logoLabelBefore')) < .5, 'The wordmark moved'
        assert tab.locator('.studio-brand').get_attribute('role') == 'img'
        assert tab.locator('.studio-brand').get_attribute('aria-label') == 'Atelier'
        tab.locator('.studio-brand').click(force=True)
        tab.evaluate("AtelierLogoEntranceUI.start(); document.dispatchEvent(new Event('atelier:navigation')); document.dispatchEvent(new Event('atelier:project-changed'))")
        tab.wait_for_timeout(100)
        assert tab.evaluate('logoEntrances') == 1, 'Clicking or navigating replayed the entrance'
        tab.screenshot(path=str(report / 'logo-startup-light.png'))
        tab.evaluate("document.documentElement.dataset.theme='dark'")
        tab.wait_for_timeout(250)
        tab.screenshot(path=str(report / 'logo-startup-dark.png'))
        assert not errors, errors
        checks.append('Logo entrance runs once without waiting on configuration, holds the mark size and wordmark position, hands over to the still mark, and clicking no longer replays it')
    finally:
        for route in pending_config:
            try:
                route.abort()
            except Exception:
                pass
        tab.unroute_all(behavior='ignoreErrors')
        tab.close()

    # A launch stage that arrives during the entrance goes first; the entrance then plays in full, once.
    tab = context.new_page()
    errors = []
    tab.on('pageerror', lambda error: errors.append(str(error)))
    tab.add_init_script(INSTRUMENT)
    try:
        tab.goto(url)
        tab.wait_for_selector(ENTRANCE)
        tab.evaluate("AtelierLogoEntranceUI.holdStartup()")
        held = tab.evaluate(f"""() => {{
          const img = document.querySelector('.studio-brand > img');
          return {{entrance: !!document.querySelector('{ENTRANCE}'), shown: getComputedStyle(img).visibility, width: img.getBoundingClientRect().width}};
        }}""")
        assert held == {'entrance': False, 'shown': 'hidden', 'width': held['width']} and abs(held['width'] - 50.08) < .1, held
        tab.evaluate("AtelierLogoEntranceUI.startupDone()")
        assert tab.locator(ENTRANCE).count() == 1
        tab.evaluate("AtelierLogoEntranceUI.startupDone()")
        assert tab.locator(ENTRANCE).count() == 1, 'Startup finishing twice played twice'
        tab.wait_for_function(f"!document.querySelector('{ENTRANCE}')", timeout=4000)
        assert tab.evaluate(STILL)
        # Once it has finished, a later launch stage doesn't repeat it.
        tab.evaluate("window.finished = logoEntrances; AtelierLogoEntranceUI.holdStartup(); AtelierLogoEntranceUI.startupDone()")
        assert tab.evaluate('logoEntrances === finished') and tab.evaluate(STILL)
        # Page teardown leaves the still mark.
        tab.evaluate("AtelierLogoEntranceUI.destroy(); window.dispatchEvent(new Event('pagehide'))")
        assert tab.evaluate(STILL)
        assert not errors, errors
        checks.append('The launch stage goes before the entrance, which then plays once; a finished entrance never repeats and teardown leaves the still mark')
    finally:
        tab.close()

    for mode in ('hidden', 'hidden-while-held', 'reduced', 'calm', 'missing-glyph', 'mark-error'):
        quiet = context.new_page()
        quiet.add_init_script(INSTRUMENT)
        if mode == 'hidden':
            quiet.add_init_script("Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});")
        elif mode == 'reduced':
            quiet.emulate_media(reduced_motion='reduce')
        elif mode == 'missing-glyph':
            quiet.route('**/static/motion/assembly/glyph.js', lambda route: route.fulfill(body='', content_type='text/javascript'))
        elif mode == 'mark-error':
            quiet.route('**/static/brand/atelier-mark.svg', lambda route: route.abort('failed'))
        try:
            if mode == 'calm':
                quiet.goto(url)
                quiet.wait_for_function('window.AtelierLogoEntranceUI')
                quiet.evaluate("""() => {
                  const c = document.getElementById('settings-motion'); c.value = 'calm'; c.dispatchEvent(new Event('change'));
                }""")
                quiet.reload()
                quiet.wait_for_function('window.AtelierLogoEntranceUI')
                quiet.wait_for_timeout(100)
                assert quiet.evaluate('logoEntrances') == 0, mode
                quiet.evaluate("""() => {
                  const c = document.getElementById('settings-motion'); c.value = 'full'; c.dispatchEvent(new Event('change'));
                }""")
            else:
                quiet.goto(url)
                quiet.wait_for_function('window.AtelierLogoEntranceUI')
                if mode == 'hidden-while-held':
                    quiet.evaluate("""() => {
                      AtelierLogoEntranceUI.holdStartup();
                      Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});
                      document.dispatchEvent(new Event('visibilitychange'));
                      delete document.hidden; document.dispatchEvent(new Event('visibilitychange'));
                      window.heldEntrances = logoEntrances;
                      AtelierLogoEntranceUI.startupDone();
                    }""")
                    assert quiet.evaluate('logoEntrances === heldEntrances'), mode
                else:
                    quiet.wait_for_timeout(100)
                    assert quiet.evaluate('logoEntrances') == 0, mode
                if mode == 'hidden':
                    quiet.evaluate("delete document.hidden; document.dispatchEvent(new Event('visibilitychange')); AtelierLogoEntranceUI.start()")
                    assert quiet.evaluate('logoEntrances') == 0
            if mode != 'mark-error':
                quiet.wait_for_function(STILL, timeout=4000)
            else:
                assert quiet.evaluate("getComputedStyle(document.querySelector('.studio-brand > img')).visibility") == 'visible', mode
        finally:
            quiet.unroute_all(behavior='ignoreErrors')
            quiet.close()
    checks.append('A hidden window, a launch hidden while held, reduced motion, Calm, a missing glyph and a failed image all leave the still mark, and nothing plays later')
