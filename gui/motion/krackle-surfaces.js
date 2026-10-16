/*
 * Atelier — Krackle across the app (ambient integrations)
 * Small, optional hooks that carry the Krackle language into existing surfaces
 * without owning any application state:
 *  - Edit import progress: the "Editing Assets…" dialog gets a Krackle stage that
 *    charges while the import runs (the existing spinner and counter remain).
 *  - Theme switch: choosing a theme or palette sweeps a halftone wave out from the
 *    control you used. Decorative, about 560ms, never on startup or OS changes.
 * Everything here is skipped for reduced motion and fails silently.
 */
(function () {
  'use strict';

  var root = document.documentElement;

  function reduced() {
    if (root.dataset.reducedMotion === 'reduce') return true;
    try { return window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (_) { return false; }
  }

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

  // ── Theme switch wave ──
  var armedAt = 0, point = null;
  var lastKey = root.dataset.theme + '|' + root.dataset.palette;

  function arm(event, target) {
    armedAt = performance.now();
    var box = target && target.getBoundingClientRect ? target.getBoundingClientRect() : null;
    point = event && typeof event.clientX === 'number' && (event.clientX || event.clientY)
      ? [event.clientX, event.clientY]
      : box ? [box.left + box.width / 2, box.top + box.height / 2] : [innerWidth / 2, innerHeight / 2];
  }

  document.addEventListener('click', function (event) {
    var preset = event.target && event.target.closest ? event.target.closest('[data-theme-preset]') : null;
    if (preset) arm(event, preset);
  }, true);
  document.addEventListener('change', function (event) {
    if (event.target && event.target.matches && event.target.matches('[data-theme-picker]')) arm(null, event.target);
  }, true);

  function wave() {
    if (reduced() || document.hidden || typeof Element.prototype.animate !== 'function' || !document.body) return;
    var layer = document.createElement('div');
    layer.className = 'krackle-theme-wave';
    layer.setAttribute('aria-hidden', 'true');
    document.body.appendChild(layer);
    var x = Math.round(point[0]), y = Math.round(point[1]);
    var reach = Math.ceil(Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y))) + 40;
    try {
      var anim = layer.animate([
        { clipPath: 'circle(0px at ' + x + 'px ' + y + 'px)', opacity: 1 },
        { clipPath: 'circle(' + Math.round(reach * 0.7) + 'px at ' + x + 'px ' + y + 'px)', opacity: 0.85, offset: 0.6 },
        { clipPath: 'circle(' + reach + 'px at ' + x + 'px ' + y + 'px)', opacity: 0 }
      ], { duration: 560, easing: 'cubic-bezier(0.2, 0, 0, 1)' });
      anim.onfinish = anim.oncancel = function () { layer.remove(); };
    } catch (_) {
      layer.remove();
    }
  }

  new MutationObserver(function () {
    var key = root.dataset.theme + '|' + root.dataset.palette;
    if (key === lastKey) return;
    lastKey = key;
    if (performance.now() - armedAt < 800 && point) wave();
    armedAt = 0;
  }).observe(root, {attributes: true, attributeFilter: ['data-theme', 'data-palette']});

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', attachImportStage, {once: true});
  else attachImportStage();
})();
