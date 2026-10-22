/*
 * Atelier — Krackle micro glyphs for notifications
 * Classic-script IIFE adding window.AtelierMotion.krackleGlyph and window.AtelierKrackleGlyph.
 * States: busy (six-dot charge ring), info (a drop of ink), success (starburst),
 * warning (cracked ring, chunk falls out) and error (splat). Artwork is generated
 * by scripts/krackle_art.py, which also writes krackle-glyph.svg.
 * Results animate once and then hold still; only busy loops. Reduced motion,
 * hidden documents and missing/throwing Web Animations all leave the static pose.
 */
(function () {
  'use strict';

  var VALID_STATES = new Set(['busy', 'info', 'success', 'warning', 'error']);
  var EASE_STANDARD = window.AtelierMotion.ease.standard;
  var EASE_FALL = window.AtelierMotion.ease.fall;
  var EASE_RISE = window.AtelierMotion.ease.rise;
  var EASE_SWAY = window.AtelierMotion.ease.sway;
  var BUSY_DURATION_MS = window.AtelierMotion.beatMs;
  var CHUNK_FROM = [-1.54, -4.02];
  var DIZZY_ORBIT = {cx: 12, cy: 3, rx: 4.4, ry: 1, rest: [7.6, 3.3], turns: 1.5};
  var mounted = typeof WeakMap === 'function' ? new WeakMap() : null;

  // krackle-art:krackle-glyph:begin
  var SVG_MARKUP = '<svg xmlns="http://www.w3.org/2000/svg" class="am-krackle-glyph-svg" viewBox="0 0 24 24" width="24" height="24" aria-hidden="true" focusable="false" fill="currentColor"><g class="am-krackle-glyph-busy"><circle class="am-krackle-glyph-energy am-krackle-glyph-dot am-krackle-glyph-dot-0" cx="12" cy="3.8" r="2.15" /><circle class="am-krackle-glyph-energy am-krackle-glyph-dot am-krackle-glyph-dot-1" cx="19.1" cy="7.9" r="2.15" /><circle class="am-krackle-glyph-energy am-krackle-glyph-dot am-krackle-glyph-dot-2" cx="19.1" cy="16.1" r="2.15" /><circle class="am-krackle-glyph-energy am-krackle-glyph-dot am-krackle-glyph-dot-3" cx="12" cy="20.2" r="2.15" /><circle class="am-krackle-glyph-energy am-krackle-glyph-dot am-krackle-glyph-dot-4" cx="4.9" cy="16.1" r="2.15" /><circle class="am-krackle-glyph-energy am-krackle-glyph-dot am-krackle-glyph-dot-5" cx="4.9" cy="7.9" r="2.15" /><circle class="am-krackle-glyph-hole am-krackle-glyph-dot-hole am-krackle-glyph-dot-hole-0" cx="12" cy="3.8" r="1.05" /><circle class="am-krackle-glyph-hole am-krackle-glyph-dot-hole am-krackle-glyph-dot-hole-1" cx="19.1" cy="7.9" r="1.05" /><circle class="am-krackle-glyph-hole am-krackle-glyph-dot-hole am-krackle-glyph-dot-hole-2" cx="19.1" cy="16.1" r="1.05" /><circle class="am-krackle-glyph-hole am-krackle-glyph-dot-hole am-krackle-glyph-dot-hole-3" cx="12" cy="20.2" r="1.05" /><circle class="am-krackle-glyph-hole am-krackle-glyph-dot-hole am-krackle-glyph-dot-hole-4" cx="4.9" cy="16.1" r="1.05" /><circle class="am-krackle-glyph-hole am-krackle-glyph-dot-hole am-krackle-glyph-dot-hole-5" cx="4.9" cy="7.9" r="1.05" /></g><g class="am-krackle-glyph-outcome am-krackle-glyph-outcome-info"><path class="am-krackle-glyph-energy am-krackle-glyph-drop" d="M12 2.2 C14.27 7.24 17.4 10.85 17.4 14.2 A5.4 5.4 0 1 1 6.6 14.2 C6.6 10.85 9.73 7.24 12 2.2 Z" /><circle class="am-krackle-glyph-hole" cx="13.7" cy="15.4" r="1.7" /><circle class="am-krackle-glyph-glint" cx="10.1" cy="12.9" r="0.7" /></g><g class="am-krackle-glyph-outcome am-krackle-glyph-outcome-success"><path class="am-krackle-glyph-energy am-krackle-glyph-burst" d="M22.98 14.23 L17.57 15.15 L19.57 20.25 L14.66 17.82 L13.28 23.13 L10.73 18.27 L6.49 21.75 L7.28 16.33 L1.81 16.65 L5.64 12.73 L1.02 9.77 L6.43 8.85 L4.43 3.75 L9.34 6.18 L10.72 0.87 L13.27 5.73 L17.51 2.25 L16.72 7.67 L22.19 7.35 L18.36 11.27 Z" /><circle class="am-krackle-glyph-hole am-krackle-glyph-burst-hole" cx="12.6" cy="12.4" r="2.35" /><g class="am-krackle-glyph-flecks"><circle class="am-krackle-glyph-energy am-krackle-glyph-fleck" cx="16.51" cy="3.52" r="1.05" /><circle class="am-krackle-glyph-energy am-krackle-glyph-fleck" cx="20.31" cy="16.8" r="1.05" /><circle class="am-krackle-glyph-energy am-krackle-glyph-fleck" cx="7.49" cy="20.48" r="1.05" /><circle class="am-krackle-glyph-energy am-krackle-glyph-fleck" cx="3.52" cy="7.49" r="1.05" /></g></g><g class="am-krackle-glyph-outcome am-krackle-glyph-outcome-warning"><g class="am-krackle-glyph-ring"><path class="am-krackle-glyph-arc" d="M11.61 17.99 A7.2 7.2 0 1 1 18.67 13.51" /><circle class="am-krackle-glyph-hole am-krackle-glyph-arc-hole" cx="5.05" cy="9.15" r="1.2" /></g><g class="am-krackle-glyph-chunk"><circle class="am-krackle-glyph-energy" cx="17.4" cy="20.9" r="2.2" /><circle class="am-krackle-glyph-hole" cx="17.9" cy="21.2" r="0.75" /></g></g><g class="am-krackle-glyph-outcome am-krackle-glyph-outcome-error"><g class="am-krackle-glyph-splat"><circle class="am-krackle-glyph-energy" cx="12" cy="12" r="5.52" /><circle class="am-krackle-glyph-energy" cx="7.92" cy="13.92" r="3.12" /><circle class="am-krackle-glyph-energy" cx="15.84" cy="9.6" r="3.12" /><circle class="am-krackle-glyph-energy" cx="14.88" cy="15.6" r="2.64" /><circle class="am-krackle-glyph-energy" cx="9.6" cy="8.4" r="2.4" /><circle class="am-krackle-glyph-hole" cx="12.48" cy="11.76" r="2.16" /><circle class="am-krackle-glyph-hole" cx="8.4" cy="13.68" r="1.08" /></g><g class="am-krackle-glyph-sats"><circle class="am-krackle-glyph-energy am-krackle-glyph-sat" cx="2.4" cy="7.68" r="1.44" /><circle class="am-krackle-glyph-energy am-krackle-glyph-sat" cx="22.08" cy="14.4" r="1.32" /><circle class="am-krackle-glyph-energy am-krackle-glyph-sat" cx="4.8" cy="20.16" r="1.2" /><circle class="am-krackle-glyph-energy am-krackle-glyph-sat" cx="19.92" cy="3.36" r="1.2" /><circle class="am-krackle-glyph-energy am-krackle-glyph-sat" cx="20.64" cy="20.64" r="0.96" /></g><g class="am-krackle-glyph-drip"><path class="am-krackle-glyph-drip-line" d="M8.64 16.32 V20.64" /><circle class="am-krackle-glyph-energy" cx="8.64" cy="21.6" r="1.68" /></g><g class="am-krackle-glyph-dizzy"><circle class="am-krackle-glyph-energy" cx="7.6" cy="3.3" r="1.45" /><circle class="am-krackle-glyph-hole" cx="7.9" cy="3.4" r="0.62" /></g></g></svg>';
  // krackle-art:krackle-glyph:end

  function px(value) {
    return Math.round(value * 100) / 100 + 'px';
  }

  function mount(host, options) {
    if (!host || host.nodeType !== 1) throw new Error('AtelierMotion.krackleGlyph.mount requires a DOM host.');
    var prior = mounted ? mounted.get(host) : null;
    if (prior) prior.destroy();
    if (host.childNodes.length) throw new Error('Krackle glyph needs an empty host.');

    var opts = options || {};
    var state = VALID_STATES.has(opts.state) ? opts.state : 'info';
    var reducedPref = opts.reducedMotion === 'reduce' ? 'reduce' : 'system';
    var destroyed = false;
    var unavailable = false;
    var generation = 0;
    var active = [];
    var mql = null;
    try { mql = (window.AtelierMotionPolicy && window.AtelierMotionPolicy.query()) || window.matchMedia('(prefers-reduced-motion: reduce)'); } catch (_) {}

    function reduced() { return unavailable || reducedPref === 'reduce' || Boolean(mql && mql.matches); }
    // Decorative follow-through (flecks, the dazed orbit) is Full only; Calm keeps the state change.
    function decorative() { return !window.AtelierMotionPolicy || window.AtelierMotionPolicy.allows(2); }
    function hidden() { return Boolean(document.hidden); }

    host.setAttribute('data-atelier-motion', 'krackle-glyph');
    host.setAttribute('data-am-state', state);
    host.setAttribute('data-am-reduced', String(reduced()));
    host.innerHTML = SVG_MARKUP;
    var svg = host.querySelector('svg');
    function repaintEnergy() {
      if (destroyed) return;
      var palette = window.AtelierMotion.energy?.resolve(host);
      var artwork = host.querySelector('svg');
      if (!artwork || !palette) return;
      artwork.style.setProperty('--am-local-charge', palette.charge);
      artwork.style.setProperty('--am-local-rift', palette.rift);
    }
    repaintEnergy();
    window.addEventListener('atelier:energy', repaintEnergy);
    window.addEventListener('atelier:inks', repaintEnergy);

    function q(sel) { return host.querySelector(sel); }
    function qa(sel) { return Array.prototype.slice.call(host.querySelectorAll(sel)); }
    var parts = {
      busy: q('.am-krackle-glyph-busy'), dots: qa('.am-krackle-glyph-dot'), holes: qa('.am-krackle-glyph-dot-hole'),
      drop: q('.am-krackle-glyph-outcome-info'), burst: q('.am-krackle-glyph-burst'), burstHole: q('.am-krackle-glyph-burst-hole'),
      flecks: qa('.am-krackle-glyph-fleck'), ring: q('.am-krackle-glyph-ring'), chunk: q('.am-krackle-glyph-chunk'),
      splat: q('.am-krackle-glyph-splat'), sats: qa('.am-krackle-glyph-sat'), drip: q('.am-krackle-glyph-drip'),
      dizzy: q('.am-krackle-glyph-dizzy')
    };

    function cancel() {
      generation += 1;
      while (active.length) {
        var anim = active.pop();
        anim.onfinish = null;
        try { anim.cancel(); } catch (_) {}
      }
    }

    function run(el, frames, timing) {
      if (unavailable || !el) return null;
      try {
        if (typeof el.animate !== 'function') throw new Error('Animation unavailable');
        var anim = el.animate(frames, timing);
        active.push(anim);
        if (timing.iterations !== Infinity) {
          var epoch = generation;
          anim.onfinish = function () {
            if (destroyed || epoch !== generation) return;
            anim.onfinish = null;
            anim.cancel();
            active = active.filter(function (item) { return item !== anim; });
          };
        }
        return anim;
      } catch (_) {
        unavailable = true;
        cancel();
        host.setAttribute('data-am-reduced', 'true');
        return null;
      }
    }

    function centre(el) { return [Number(el.getAttribute('cx')) - 12, Number(el.getAttribute('cy')) - 12]; }

    function play(previousState) {
      cancel();
      if (parts.busy) parts.busy.style.color = 'var(--am-local-charge, var(--krackle-energy, var(--krackle-charge)))';
      host.setAttribute('data-am-reduced', String(reduced()));
      if (destroyed || reduced() || hidden()) return;
      if (previousState === 'busy' && state !== 'busy') {
        run(parts.busy, [
          { opacity: 1, transform: 'scale(1)' },
          { opacity: 0, transform: 'scale(0.7)' }
        ], { duration: 140, easing: EASE_STANDARD, fill: 'forwards' });
      }
      if (state === 'busy') {
        // Compact paired charge: the glyph gathers in place without spinning.
        for (var k = 0; k < parts.dots.length; k++) {
          var d = centre(parts.dots[k]);
          var inward = 'translate(' + px(-d[0] * .2) + ', ' + px(-d[1] * .2) + ')';
          var timing = {duration: BUSY_DURATION_MS, delay: (k % 3) * 65, iterations: Infinity, easing: EASE_STANDARD};
          run(parts.dots[k], [
            {transform: 'translate(0px, 0px) scale(1)', offset: 0},
            {transform: inward + ' scale(1.12)', offset: .3},
            {transform: inward + ' scale(.9)', offset: .48},
            {transform: 'translate(0px, 0px) scale(1)', offset: .76},
            {transform: 'translate(0px, 0px) scale(1)', offset: 1}
          ], timing);
          run(parts.holes[k], [
            {transform: 'scale(0)', offset: 0}, {transform: inward + ' scale(.8)', offset: .3},
            {transform: inward + ' scale(.3)', offset: .48}, {transform: 'scale(0)', offset: .76},
            {transform: 'scale(0)', offset: 1}
          ], timing);
        }
      } else if (state === 'info') {
        // A drop falls into place and squashes as it lands.
        run(parts.drop, [
          { transform: 'translateY(-7px) scaleY(1.2)', opacity: 0, offset: 0, easing: EASE_FALL },
          { transform: 'translateY(0px) scale(1.12, 0.84)', opacity: 1, offset: 0.55, easing: EASE_RISE },
          { transform: 'translateY(-0.8px) scale(0.96, 1.05)', opacity: 1, offset: 0.78 },
          { transform: 'translateY(0px) scale(1)', opacity: 1, offset: 1 }
        ], { duration: 420, easing: 'linear' });
      } else if (state === 'success') {
        run(parts.burst, [
          { transform: 'scale(0.2) rotate(-28deg)', opacity: 0, offset: 0, easing: EASE_STANDARD },
          { transform: 'scale(1.04, .92) rotate(2deg)', opacity: 1, offset: 0.38, easing: EASE_SWAY },
          { transform: 'scale(0.95) rotate(-1deg)', opacity: 1, offset: 0.66, easing: EASE_SWAY },
          { transform: 'scale(1) rotate(0deg)', opacity: 1, offset: 1 }
        ], { duration: 380, easing: 'linear' });
        run(parts.burstHole, [
          { transform: 'scale(0)', offset: 0 }, { transform: 'scale(0)', offset: 0.36, easing: EASE_STANDARD },
          { transform: 'scale(1.35)', offset: 0.64, easing: EASE_SWAY }, { transform: 'scale(1)', offset: 1 }
        ], { duration: 380, easing: 'linear' });
        if (decorative()) parts.flecks.forEach(function (fleck) {
          var d = centre(fleck);
          run(fleck, [
            { transform: 'translate(' + px(-d[0] * 0.8) + ', ' + px(-d[1] * 0.8) + ') scale(0.3)', opacity: 0, offset: 0, easing: EASE_STANDARD },
            { opacity: 1, offset: 0.25 },
            { transform: 'translate(0px, 0px) scale(1)', opacity: 1, offset: 0.55, easing: EASE_FALL },
            { transform: 'translate(' + px(d[0] * 0.25) + ', ' + px(d[1] * 0.25) + ') scale(0)', opacity: 0, offset: 1 }
          ], { duration: 420, easing: 'linear' });
        });
      } else if (state === 'warning') {
        run(parts.ring, [
          { transform: 'scale(1.3)', opacity: 0, offset: 0, easing: EASE_FALL }, { transform: 'scale(0.93)', opacity: 1, offset: 0.3, easing: EASE_STANDARD },
          { transform: 'scale(1.03)', opacity: 1, offset: 0.6, easing: EASE_SWAY }, { transform: 'scale(1)', opacity: 1, offset: 1 }
        ], { duration: 380, easing: 'linear' });
        var from = 'translate(' + px(CHUNK_FROM[0]) + ', ' + px(CHUNK_FROM[1]) + ')';
        run(parts.chunk, [
          { transform: from, offset: 0 }, { transform: from, offset: 0.18, easing: EASE_FALL },
          { transform: 'translate(0px, 0px)', offset: 0.56, easing: EASE_RISE },
          { transform: 'translate(0px, -1.6px)', offset: 0.7, easing: EASE_FALL },
          { transform: 'translate(0px, 0px)', offset: 0.84, easing: EASE_RISE },
          { transform: 'translate(0px, -0.5px)', offset: 0.92, easing: EASE_FALL },
          { transform: 'translate(0px, 0px)', offset: 1 }
        ], { duration: 620, easing: 'linear' });
      } else if (state === 'error') {
        run(parts.splat, [
          { transform: 'scale(0.5)', opacity: 0, offset: 0, easing: EASE_SWAY }, { transform: 'scale(0.26)', opacity: 1, offset: 0.22, easing: EASE_STANDARD },
          { transform: 'scale(1.2)', opacity: 1, offset: 0.48, easing: EASE_SWAY }, { transform: 'scale(0.95)', opacity: 1, offset: 0.72, easing: EASE_STANDARD },
          { transform: 'scale(1)', opacity: 1, offset: 1 }
        ], { duration: 520, easing: 'linear' });
        parts.sats.forEach(function (sat) {
          var d = centre(sat), start = 'translate(' + px(-d[0]) + ', ' + px(-d[1]) + ') scale(0.3)';
          run(sat, [
            { transform: start, opacity: 0, offset: 0 }, { transform: start, opacity: 0, offset: 0.26, easing: EASE_STANDARD },
            { transform: 'translate(' + px(d[0] * 0.12) + ', ' + px(d[1] * 0.12) + ') scale(1.2)', opacity: 1, offset: 0.55, easing: EASE_SWAY },
            { transform: 'translate(0px, 0px) scale(1)', opacity: 1, offset: 1 }
          ], { duration: 560, easing: 'linear' });
        });
        run(parts.drip, [
          { transform: 'scaleY(0)', offset: 0 }, { transform: 'scaleY(0)', offset: 0.45, easing: EASE_FALL },
          { transform: 'scaleY(1.15)', offset: 0.8, easing: EASE_STANDARD }, { transform: 'scaleY(1)', offset: 1 }
        ], { duration: 640, easing: 'linear' });
        var frames = [];
        var rest = Math.atan2((DIZZY_ORBIT.rest[1] - DIZZY_ORBIT.cy) / DIZZY_ORBIT.ry, (DIZZY_ORBIT.rest[0] - DIZZY_ORBIT.cx) / DIZZY_ORBIT.rx);
        for (var i = 0; i <= 16; i++) {
          var t = i / 16, a = rest + DIZZY_ORBIT.turns * 2 * Math.PI * (1 - t) * (1 - t);
          frames.push({
            transform: 'translate(' + px(DIZZY_ORBIT.cx + Math.cos(a) * DIZZY_ORBIT.rx - DIZZY_ORBIT.rest[0]) + ', ' +
              px(DIZZY_ORBIT.cy + Math.sin(a) * DIZZY_ORBIT.ry - DIZZY_ORBIT.rest[1]) + ')',
            opacity: t < 0.08 ? t / 0.08 : 1, offset: t
          });
        }
        if (decorative()) run(parts.dizzy, frames, { duration: 1100, delay: 260, fill: 'backwards', easing: 'linear' });
      }
    }

    function onEnvironment() {
      if (destroyed) return;
      host.setAttribute('data-am-reduced', String(reduced()));
      if (reduced() || hidden()) cancel();
      else if (state === 'busy') play();
    }
    if (mql && typeof mql.addEventListener === 'function') mql.addEventListener('change', onEnvironment);
    document.addEventListener('visibilitychange', onEnvironment);

    var handle = {
      setState: function (next) {
        if (destroyed || !VALID_STATES.has(next) || next === state) return;
        var previousState = state;
        state = next;
        host.setAttribute('data-am-state', state);
        play(previousState);
      },
      replay: function () { if (!destroyed && state !== 'busy') play(); },
      setReducedMotion: function (mode) {
        if (destroyed) return;
        reducedPref = mode === 'reduce' ? 'reduce' : 'system';
        onEnvironment();
      },
      destroy: function () {
        if (destroyed) return;
        destroyed = true;
        window.removeEventListener('atelier:energy', repaintEnergy);
        window.removeEventListener('atelier:inks', repaintEnergy);
        cancel();
        if (mql && typeof mql.removeEventListener === 'function') mql.removeEventListener('change', onEnvironment);
        document.removeEventListener('visibilitychange', onEnvironment);
        if (svg && svg.parentNode === host) host.removeChild(svg);
        host.removeAttribute('data-atelier-motion');
        host.removeAttribute('data-am-state');
        host.removeAttribute('data-am-reduced');
        if (mounted && mounted.get(host) === handle) mounted.delete(host);
      }
    };
    if (mounted) mounted.set(host, handle);
    play();
    return handle;
  }

  // Replace a generic toast's icon with a Krackle glyph. The original icon stays as the
  // fallback until mounting succeeds; every removal path (timeout, click) destroys motion.
  function toastIcon(toast, type) {
    var icon = toast && toast.querySelector(':scope > i[data-lucide], :scope > svg');
    if (!icon || !window.AtelierMotion || !window.AtelierMotion.krackleGlyph) return null;
    var slot = document.createElement('span');
    slot.className = 'am-krackle-glyph-slot';
    slot.setAttribute('aria-hidden', 'true');
    var host = document.createElement('span');
    toast.insertBefore(slot, icon);
    slot.appendChild(icon);
    icon.classList.add('am-krackle-glyph-fallback');
    slot.appendChild(host);
    var state = type === 'success' || type === 'warning' || type === 'error' ? type : 'info';
    try {
      var handle = window.AtelierMotion.krackleGlyph.mount(host, {state: state});
      slot.dataset.amMounted = 'true';
      var remove = toast.remove.bind(toast);
      toast.remove = function () {
        try { handle.destroy(); } catch (_) {}
        remove();
      };
      return handle;
    } catch (_) {
      host.remove();
      return null;
    }
  }

  window.AtelierMotion = window.AtelierMotion || {};
  window.AtelierMotion.krackleGlyph = {mount: mount};
  window.AtelierKrackleGlyph = Object.freeze({toastIcon: toastIcon});
})();
