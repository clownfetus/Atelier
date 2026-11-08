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
      // The inline frame leaves the disc room to travel, so the still pose sits off its middle. It never
      // moves, so the drawing is measured once and nudged until its own bounds are centred in the box.
      const centre = () => {
        const svg = host.querySelector('svg'), shape = svg?.querySelector('g'), view = svg?.viewBox.baseVal;
        const bounds = shape?.getBBox();
        if (!bounds?.width || !view?.width) return false;
        const dx = view.x + view.width / 2 - (bounds.x + bounds.width / 2);
        const dy = view.y + view.height / 2 - (bounds.y + bounds.height / 2);
        svg.style.transform = `translate(${(dx / view.width * 100).toFixed(2)}%, ${(dy / view.height * 100).toFixed(2)}%)`;
        return true;
      };
      requestAnimationFrame(() => { if (host.isConnected && !centre()) requestAnimationFrame(centre); });
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
