// The still glyph for a place with nothing in it: the three pieces at rest (D4), or the X when the place
// couldn't load. It's decorative, and whatever it's mounted in keeps its own text and fallback icon.
(() => {
  'use strict';
  // These hosts usually leave when their container is rebuilt, so the glyph is cleaned up when that happens.
  const live = new Map();
  const watcher = new MutationObserver(() => {
    for (const [host, entry] of live) {
      if (host.isConnected) entry.attached = true;
      else if (entry.attached) { live.delete(host); entry.glyph.destroy(); }
    }
    if (!live.size) watcher.disconnect();
  });

  function mount(container, state = 'info') {
    const glyph = window.AtelierMotion?.glyph;
    if (!container || !glyph) return null;
    const host = document.createElement('span');
    host.className = 'empty-state-glyph';
    host.setAttribute('aria-hidden', 'true');
    try {
      container.prepend(host);
      const handle = glyph.mount(host, {state, still: true});
      if (!live.size) watcher.observe(document.documentElement, {childList: true, subtree: true});
      live.set(host, {glyph: handle, attached: host.isConnected});
      return {
        destroy() {
          live.delete(host);
          handle.destroy();
          host.remove();
        },
      };
    } catch (error) {
      host.remove();
      console.warn('Empty state glyph unavailable', error);
      return null;
    }
  }

  window.AtelierEmptyGlyph = Object.freeze({mount});
})();
