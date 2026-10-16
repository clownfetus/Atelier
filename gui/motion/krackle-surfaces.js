/*
 * Atelier — Krackle across the app (ambient integrations)
 * Small, optional hooks that carry Krackle into substantial job feedback without
 * owning any application state. The "Editing Assets…" import dialog gets a Krackle
 * stage that charges while the import runs; its counter, segments and controls stay
 * authoritative and appear immediately. Hidden dialogs stop drawing. Fails silently.
 */
(function () {
  'use strict';

  var root = document.documentElement;

  // ── Import progress: a stage inside #prog-box while the overlay is active ──
  function attachImportStage() {
    var overlay = document.getElementById('prog-overlay');
    var box = document.getElementById('prog-box');
    if (!overlay || !box || !window.AtelierMotion || !window.AtelierMotion.krackleStage) return;
    var host = document.createElement('div');
    host.className = 'prog-krackle-stage';
    var heading = box.querySelector('h2');
    if (heading) heading.after(host); else box.prepend(host);
    var stage = null;
    function sync() {
      var on = overlay.classList.contains('active');
      try {
        if (on && !stage) {
          stage = window.AtelierMotion.krackleStage.mount(host, {state: 'idle', size: 132});
          box.dataset.krackleStage = 'true';
        }
        if (stage) stage.setState(on ? 'busy' : 'idle');
      } catch (_) {
        stage = null;
        host.replaceChildren();
        delete box.dataset.krackleStage;
      }
    }
    new MutationObserver(sync).observe(overlay, {attributes: true, attributeFilter: ['class']});
    sync();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', attachImportStage, {once: true});
  else attachImportStage();
})();
