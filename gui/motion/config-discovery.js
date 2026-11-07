// Presentation for the actual setup-status request in Settings. It never discovers or validates data.
// The working glyph, Inline on an 88 px host, runs while the request does and takes the real result
// (surface map row 13). The cover lifts as soon as the result is in, so the glyph goes with it.
(() => {
  'use strict';
  const motion = window.AtelierMotion ||= {}, instances = new WeakMap(), live = new Set();
  const noop = () => {}; noop.dispose = noop;

  function begin(target) {
    const loader = target?.matches?.('#setup-loading') ? target : target?.querySelector?.('#setup-loading');
    const panel = loader?.closest('.modal');
    if (!loader || !panel) return noop;
    instances.get(loader)?.dispose();
    const overlay = panel.closest('.overlay'), host = document.createElement('span');
    host.className = 'am-config-art'; host.setAttribute('aria-hidden', 'true');
    loader.prepend(host); loader.classList.add('am-config-discovery-active');
    let glyph = null;
    try { glyph = motion.glyph?.mount(host, {state: 'busy'}) || null; } catch (_) { glyph = null; }
    if (!glyph) { host.remove(); loader.classList.remove('am-config-discovery-active'); return noop; }

    let ended = false, destroyed = false;
    const current = () => panel.isConnected && (!overlay || overlay.classList.contains('active'));
    const observer = new MutationObserver(sync);
    for (const element of new Set([loader, panel, overlay].filter(Boolean))) observer.observe(element, {attributes: true, attributeFilter: ['class', 'hidden']});
    function sync() {
      if (destroyed) return;
      if (!current() || !loader.classList.contains('active') || !loader.getClientRects().length) dispose();
    }
    function dispose() {
      if (destroyed) return;
      destroyed = true; ended = true; observer.disconnect();
      try { glyph.destroy(); } catch (_) { /* The cover still closes. */ }
      host.remove(); loader.classList.remove('am-config-discovery-active');
      if (instances.get(loader) === finish) instances.delete(loader);
      live.delete(finish);
    }
    function finish(outcome = 'cancel') {
      if (ended || destroyed) return;
      ended = true;
      const state = ['success', 'warning', 'error'].includes(outcome) ? outcome : null;
      if (!state || !current()) { dispose(); return; }
      try { glyph.set(state); } catch (_) { dispose(); return; }
      sync();
    }
    finish.dispose = dispose;
    instances.set(loader, finish); live.add(finish);
    return finish;
  }
  window.addEventListener('pagehide', () => { for (const finish of [...live]) finish.dispose(); });
  motion.configDiscovery = Object.freeze({begin});
})();
