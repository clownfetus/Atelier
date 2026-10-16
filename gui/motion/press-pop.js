/*
 * Atelier — Krackle press pop
 * Pressing a primary button throws a short pop of six to eight Krackle bubbles
 * from the press point (about 320ms), then removes them. It is decoration only:
 * one delegated listener, no effect on clicks, focus or the button's own state.
 * Skipped for reduced motion, hidden documents and missing Web Animations.
 */
(function () {
  'use strict';

  var DURATION_MS = 320;
  var MAX_LIVE = 3;
  var live = [];
  var seed = 1;

  function random() {
    seed = (seed * 16807) % 2147483647;
    return (seed - 1) / 2147483646;
  }

  function reduced() {
    if (document.documentElement.dataset.reducedMotion === 'reduce') return true;
    try { return window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (_) { return false; }
  }

  function pop(event) {
    if (event.button !== 0 || reduced() || document.hidden) return;
    var button = event.target && event.target.closest ? event.target.closest('.btn.primary') : null;
    if (!button || button.disabled || typeof Element.prototype.animate !== 'function') return;
    while (live.length >= MAX_LIVE) live.shift().remove();

    var style = getComputedStyle(button);
    var root = getComputedStyle(document.documentElement);
    var layer = document.createElement('div');
    layer.className = 'krackle-press-pop';
    layer.setAttribute('aria-hidden', 'true');
    layer.style.left = event.clientX + 'px';
    layer.style.top = event.clientY + 'px';
    layer.style.setProperty('--krackle-pop-energy', style.backgroundColor);
    layer.style.setProperty('--krackle-pop-hole', root.getPropertyValue('--krackle-hole').trim() || '#121216');
    document.body.appendChild(layer);
    live.push(layer);

    var count = 6 + Math.floor(random() * 3);
    var remaining = count;
    function done() {
      remaining -= 1;
      if (remaining > 0) return;
      layer.remove();
      live = live.filter(function (item) { return item !== layer; });
    }
    try {
      for (var i = 0; i < count; i++) {
        var size = 5 + random() * 7;
        var angle = (i / count) * Math.PI * 2 + random() * 0.6;
        var reach = 18 + random() * 16;
        var bubble = document.createElement('i');
        bubble.style.width = bubble.style.height = size.toFixed(1) + 'px';
        bubble.style.left = bubble.style.top = (-size / 2).toFixed(1) + 'px';
        layer.appendChild(bubble);
        var x = Math.cos(angle) * reach, y = Math.sin(angle) * reach;
        var anim = bubble.animate([
          { transform: 'translate(0px, 0px) scale(0.3)', opacity: 1 },
          { transform: 'translate(' + (x * 0.8).toFixed(1) + 'px, ' + (y * 0.8).toFixed(1) + 'px) scale(1)', opacity: 1, offset: 0.55 },
          { transform: 'translate(' + x.toFixed(1) + 'px, ' + (y + 4).toFixed(1) + 'px) scale(0)', opacity: 0 }
        ], { duration: DURATION_MS + i * 12, easing: 'cubic-bezier(0.2, 0, 0, 1)' });
        anim.onfinish = done;
        anim.oncancel = done;
      }
    } catch (_) {
      layer.remove();
      live = live.filter(function (item) { return item !== layer; });
    }
  }

  document.addEventListener('pointerdown', pop, {passive: true});
  window.AtelierPressPop = Object.freeze({
    destroy: function () {
      document.removeEventListener('pointerdown', pop);
      live.forEach(function (layer) { layer.remove(); });
      live = [];
    }
  });
})();
