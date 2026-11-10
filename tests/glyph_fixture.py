"""A bare page holding the production glyph modules, for the assembly checks.

It loads the real files from the app's own static route, with a stand-in for the Motion setting
so a check can change it. The fake clock steps time by hand with seeded randomness, so a run is
repeatable, and it counts the animation frames requested.
"""

CLOCK = """
(() => {
  let now = 0, id = 1, seed = 12345;
  const timers = [], frames = [];
  const realTimeout = window.setTimeout.bind(window);
  performance.now = () => now;
  window.requestAnimationFrame = fn => { window.__frames++; frames.push(fn); return id++; };
  window.setTimeout = (fn, ms = 0) => { timers.push({at: now + ms, fn}); return id++; };
  Math.random = () => (seed = (seed * 1664525 + 1013904223) % 4294967296) / 4294967296;
  const settle = () => new Promise(r => realTimeout(r, 0));
  window.__frames = 0;
  window.__step = async (dt, count = 1) => {
    for (let i = 0; i < count; i++) {
      now += dt;
      for (const t of timers.filter(t => t.at <= now)) { timers.splice(timers.indexOf(t), 1); t.fn(); }
      await settle();
      const fs = frames.splice(0);
      fs.forEach(f => f(now));
      await settle();
    }
  };
})();
"""

POLICY = """
window.__ATELIER_GLYPH_TEST__ = true;
window.__motion = 'full';
window.AtelierMotionPolicy = {
  mode: () => window.__motion,
  tier: () => ({full: 3, calm: 1, off: 0}[window.__motion]),
  allows: value => Number(value) <= ({full: 3, calm: 1, off: 0}[window.__motion]),
  query: () => window.matchMedia('(prefers-reduced-motion: reduce)'),
};
window.__setMotion = mode => { window.__motion = mode; window.dispatchEvent(new Event('atelier:preferences')); };
"""

PAGE = """<!doctype html><html lang="en-GB"><meta charset="utf-8">
<link rel="stylesheet" href="/static/motion/assembly/assembly.css">
<style>:root{--bg:#0D151F;--glyph-halo:#0D151F;--status-complete:#B6EBA8;--status-warning:#E6C35C;--status-error:#EC6A86}
body{background:#0D151F;margin:0}</style>
<div id="root"></div>
<script src="/static/motion/assembly/pieces.js"></script>
<script src="/static/motion/assembly/planner.js"></script>
<script src="/static/motion/assembly/engine.js"></script>
<script src="/static/motion/assembly/glyph.js"></script>
<script>
window.__mount = (size, options) => {
  const host = document.createElement('div');
  document.getElementById('root').append(host);
  return AtelierMotion.glyph.mount(host, {size, ...options});
};
</script></html>"""


def open_glyph_page(context, url, clock=False, motion='full'):
    """A new tab on the fixture page. Returns (tab, errors)."""
    tab = context.new_page()
    errors = []
    tab.on('pageerror', lambda error: errors.append(str(error)))
    if clock:
        tab.add_init_script(CLOCK)
    tab.add_init_script(POLICY + f"window.__motion = {motion!r};")
    fixture = url.rstrip('/') + '/__glyph_fixture'
    tab.route(fixture, lambda route: route.fulfill(content_type='text/html', body=PAGE))
    tab.goto(fixture)
    tab.wait_for_function("window.AtelierMotion && window.AtelierMotion.glyph")
    return tab, errors
