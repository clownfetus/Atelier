/* Startup presentation only. Never delays init(), APIs, projects or indexing.
   The header logo builds itself once on launch in Full motion, then hands over to the still mark (SPEC 4.8). */
(() => {
  'use strict';
  if (window.AtelierLogoEntranceUI) return;
  let started = false, destroyed = false, held = false, waiting = false, restarted = false;
  let entrance = null, host = null, mark = null;

  function clear() {
    entrance?.destroy(); entrance = null;
    host?.remove(); host = null;
  }
  // The mark stays in place, unseen, until the pieces have built it, so it never shows twice.
  function showMark() {
    if (mark) { mark.hidden = false; mark.style.visibility = ''; }
  }
  const handOver = () => { clear(); showMark(); };

  function enter() {
    if (destroyed || !waiting || held) return;
    waiting = false;
    if (document.hidden || !window.AtelierMotion?.glyph) { showMark(); return; }
    host = document.createElement('span');
    host.setAttribute('aria-hidden', 'true');
    mark.after(host);
    try {
      const size = parseFloat(getComputedStyle(mark).height) || 32.4;
      entrance = window.AtelierMotion.glyph.entrance(host, {size, preview: restarted, onDone: handOver});
      if (entrance) {
        // The mark's own width, so the wordmark beside it doesn't move at the handover.
        host.style.width = `${size * mark.naturalWidth / mark.naturalHeight}px`;
        host.style.flex = 'none';
        mark.hidden = true;
      }
    } catch (_) { handOver(); }
  }
  // The launch stage goes first. An entrance it interrupts plays in full afterwards; one that has finished doesn't repeat.
  function holdStartup() {
    if (destroyed || held) return;
    held = true;
    if (entrance) {
      clear();
      mark.hidden = false; mark.style.visibility = 'hidden';
      waiting = restarted = true;
    }
  }
  function startupDone() {
    held = false;
    enter();
  }
  function onVisibility() {
    if (document.hidden && waiting) { waiting = false; showMark(); }
  }
  function destroy() {
    if (destroyed) return;
    destroyed = true;
    waiting = false;
    document.removeEventListener('DOMContentLoaded', start);
    document.removeEventListener('visibilitychange', onVisibility);
    window.removeEventListener('pagehide', destroy);
    mark?.removeEventListener('load', ready);
    mark?.removeEventListener('error', failed);
    handOver();
  }
  function failed() { waiting = false; showMark(); }
  function ready() {
    if (mark.naturalWidth) enter();
    else failed();
  }
  function start() {
    if (started || destroyed) return;
    started = true; // Record before waiting: a hidden startup never plays later.
    mark = document.querySelector('#topbar .studio-brand > img');
    if (!mark || document.hidden || !window.AtelierMotion?.glyph || (window.AtelierMotionPolicy && window.AtelierMotionPolicy.mode() !== 'full')) return;
    waiting = true;
    mark.style.visibility = 'hidden';
    if (mark.complete) ready();
    else {
      mark.addEventListener('load', ready, {once: true});
      mark.addEventListener('error', failed, {once: true});
    }
  }
  window.AtelierLogoEntranceUI = Object.freeze({start, destroy, holdStartup, startupDone});
  document.addEventListener('visibilitychange', onVisibility);
  window.addEventListener('pagehide', destroy, {once: true});
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once: true});
  else start();
})();
