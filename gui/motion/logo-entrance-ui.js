/* Startup presentation only. Never delays init(), APIs, projects or indexing. */
(() => {
  'use strict';
  if (window.AtelierLogoEntranceUI) return;
  let started = false, destroyed = false, ready = false, startupHeld = false, pending = null, instance, host, fallback;
  const hidden = () => document.hidden || document.visibilityState === 'hidden';
  const reduced = () => (window.AtelierMotionPolicy?.query() || window.matchMedia?.('(prefers-reduced-motion: reduce)')).matches;
  // The startup entrance is a showcase moment, so it plays only in Full; an explicit replay still plays in Calm.
  const showcase = () => !reduced() && window.AtelierMotionPolicy?.allows(2) !== false;

  function enterPending() {
    if (destroyed || !ready || startupHeld || !pending) return;
    const request = pending; pending = null;
    if (hidden() || reduced() || request === 'startup' && !showcase()) return;
    instance?.replay();
  }
  function holdStartup() {
    if (destroyed || startupHeld) return;
    startupHeld = true;
    if (started && fallback && !hidden() && showcase()) pending = 'startup';
    instance?.setState('settled');
  }
  function startupDone() {
    startupHeld = false;
    enterPending();
  }
  function onVisibility() { if (hidden()) pending = null; }
  function restore() {
    if (fallback) { fallback.hidden = false; fallback.classList.remove('am-logo-entrance-fallback'); }
    if (host) host.hidden = true;
  }
  function destroy() {
    if (destroyed) return;
    destroyed = true;
    pending = null;
    document.removeEventListener('DOMContentLoaded', start);
    document.removeEventListener('visibilitychange', onVisibility);
    window.removeEventListener('pagehide', destroy);
    fallback?.removeEventListener('load', mount);
    fallback?.removeEventListener('error', restore);
    instance?.destroy(); restore(); host?.remove();
  }
  function mount() {
    fallback?.removeEventListener('load', mount);
    fallback?.removeEventListener('error', restore);
    if (destroyed || hidden() || reduced() || !fallback?.naturalWidth ||
        typeof Element.prototype.animate !== 'function' || !window.AtelierMotion?.logoEntrance) return;
    const brand = fallback.parentElement;
    if (!brand?.isConnected) return;
    host = document.createElement('span'); host.hidden = true;
    host.dataset.atelierMotion = 'logo-entrance'; host.setAttribute('aria-hidden', 'true');
    fallback.after(host);
    fallback.classList.add('am-logo-entrance-fallback');
    try {
      instance = window.AtelierMotion.logoEntrance.mount(host, {
        state: 'settled', reducedMotion: 'system', logoSrc: fallback.currentSrc || fallback.src,
      });
      const owned = instance;
      owned.ready.then(() => {
        if (destroyed || owned !== instance || !host.isConnected || hidden() || reduced()) {
          owned.destroy(); restore(); return;
        }
        // Exchange equal-size slots in one task, with no duplicated visible mark.
        host.hidden = false; fallback.hidden = true;
        ready = true;
        enterPending();
      }).catch(() => { if (!destroyed && owned === instance) { owned.destroy(); restore(); } });
    } catch (_) { instance?.destroy(); restore(); }
  }
  function start() {
    if (started || destroyed) return;
    started = true; // Record before waiting/mounting: a hidden startup never replays later.
    fallback = document.querySelector('#topbar .studio-brand > img');
    const brand = fallback?.parentElement;
    if (brand) {
      brand.setAttribute('role','button'); brand.tabIndex=0; brand.setAttribute('aria-label','Replay Atelier logo entrance');
      const replay = () => {
        if (destroyed || hidden() || reduced() || startupHeld) return;
        pending = 'replay';
        if (instance) enterPending();
        else mount();
      };
      brand.addEventListener('click', replay);
      brand.addEventListener('keydown', event=>{if(['Enter',' '].includes(event.key)){event.preventDefault();replay();}});
    }
    if (!fallback || hidden() || !showcase() || !window.AtelierMotion?.logoEntrance) return;
    pending = 'startup';
    if (fallback.complete) { if (fallback.naturalWidth) mount(); }
    else { fallback.addEventListener('load', mount, { once: true }); fallback.addEventListener('error', restore, { once: true }); }
  }
  window.AtelierLogoEntranceUI = Object.freeze({ start, destroy, holdStartup, startupDone });
  document.addEventListener('visibilitychange', onVisibility);
  window.addEventListener('pagehide', destroy, { once: true });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, { once: true });
  else start();
})();
