/*
 * Atelier — 3D Viewport Loader Motion Controller
 * Classic-script IIFE adding window.AtelierMotion.viewportLoader while preserving
 * existing window.AtelierMotion entries (such as exportFeedback).
 * Framing proportions inspired by Google Material Symbols Rounded ("box"), Apache License 2.0.
 * Studio artwork uses squared corners and sharp joins, rather than unmodified official Sharp glyphs.
 * Adapted from the supplied Gemini controller; Atelier adds failure and cleanup safeguards.
 */
(function () {
  'use strict';

  var VALID_STATES = new Set(['idle', 'loading', 'ready', 'empty', 'error']);

  var EASE_STANDARD = 'cubic-bezier(0.2, 0, 0, 1)';
  var EASE_TURN = 'cubic-bezier(0.42, 0, 0.58, 1)';
  var ASSEMBLY_DURATION_MS = 220;
  var LOOP_DURATION_MS = 1200;
  var SETTLE_DURATION_MS = 180;

  // Track active instances per host so duplicate mount() calls clean up the prior instance
  var mountedHosts = typeof WeakMap === 'function' ? new WeakMap() : null;

  var SVG_MARKUP =
    '<svg xmlns="http://www.w3.org/2000/svg" class="am-viewport-loader-svg" viewBox="0 0 48 48" width="72" height="72" fill="none" aria-hidden="true" focusable="false">' +
      '<g class="am-viewport-loader-brackets" stroke="currentColor" stroke-width="1.75" stroke-linecap="butt" stroke-linejoin="miter" opacity="0.38">' +
        '<path d="M 8 14 V 8 H 14" />' +
        '<path d="M 34 8 H 40 V 14" />' +
        '<path d="M 40 34 V 40 H 34" />' +
        '<path d="M 14 40 H 8 V 34" />' +
      '</g>' +
      '<g class="am-viewport-loader-cube-group">' +
        '<polygon class="am-viewport-loader-top-face" points="24,11 35.25,17.5 24,24 12.75,17.5" fill="currentColor" opacity="0.08" />' +
        '<g class="am-viewport-loader-rear-group">' +
          '<path class="am-viewport-loader-rear-ribs" pathLength="1" d="M 24 11 L 24 24 M 12.75 30.5 L 24 24 L 35.25 30.5" stroke="currentColor" stroke-width="1.75" stroke-linecap="butt" stroke-linejoin="miter" opacity="0.32" />' +
        '</g>' +
        '<ellipse class="am-viewport-loader-orbit-ring" pathLength="1" cx="24" cy="24" rx="11.25" ry="6.5" stroke="#accbff" stroke-width="1.85" stroke-linecap="round" stroke-dasharray="0.28 0.72" stroke-dashoffset="0" opacity="0" />' +
        '<path class="am-viewport-loader-hull" pathLength="1" d="M 24 11 L 35.25 17.5 L 35.25 30.5 L 24 37 L 12.75 30.5 L 12.75 17.5 Z" stroke="currentColor" stroke-width="2.15" stroke-linecap="butt" stroke-linejoin="miter" />' +
        '<g class="am-viewport-loader-front-group">' +
          '<path class="am-viewport-loader-front-ribs" pathLength="1" d="M 12.75 17.5 L 24 24 L 35.25 17.5 M 24 24 L 24 37" stroke="currentColor" stroke-width="2.15" stroke-linecap="butt" stroke-linejoin="miter" />' +
        '</g>' +
        '<circle class="am-viewport-loader-vertex-core" cx="24" cy="24" r="1.75" fill="currentColor" />' +
      '</g>' +
      '<g class="am-viewport-loader-outcome am-viewport-loader-outcome-empty" opacity="0">' +
        '<circle cx="24" cy="24" r="5.5" fill="#14161b" stroke="currentColor" stroke-width="1.75" />' +
        '<path d="M 21.5 24 H 26.5" stroke="currentColor" stroke-width="2" stroke-linecap="butt" />' +
      '</g>' +
      '<g class="am-viewport-loader-outcome am-viewport-loader-outcome-error" opacity="0">' +
        '<circle cx="24" cy="24" r="6" fill="#14161b" stroke="currentColor" stroke-width="1.85" />' +
        '<path d="M 21.75 21.75 L 26.25 26.25 M 26.25 21.75 L 21.75 26.25" stroke="currentColor" stroke-width="2.1" stroke-linecap="butt" stroke-linejoin="miter" />' +
      '</g>' +
    '</svg>';

  function mountViewportLoader(host, options) {
    if (!host || host.nodeType !== 1) {
      throw new Error('AtelierMotion.viewportLoader.mount requires a valid DOM host element.');
    }

    // Prevent orphan listeners/animations if mount() is called again on the same host
    var existing = mountedHosts ? mountedHosts.get(host) : host.__amViewportLoader;
    if (existing && typeof existing.destroy === 'function') {
      try {
        existing.destroy();
      } catch (_) {}
    }
    if (host.childNodes.length) throw new Error('Viewport loader needs an empty icon host.');

    var opts = options || {};
    var currentState = VALID_STATES.has(opts.state) ? opts.state : 'idle';
    var reducedPref = opts.reducedMotion === 'reduce' ? 'reduce' : 'system';
    var destroyed = false;
    var generation = 0;
    var activeAnimations = [];
    var motionUnavailable = false;

    var mql = null;
    try {
      if (typeof window.matchMedia === 'function') {
        mql = (window.AtelierMotionPolicy?.query() || window.matchMedia('(prefers-reduced-motion: reduce)'));
      }
    } catch (_) {}

    function isReducedMotion() {
      return motionUnavailable || reducedPref === 'reduce' || Boolean(mql && mql.matches);
    }

    function isDocumentHidden() {
      return Boolean(typeof document !== 'undefined' && document.hidden);
    }

    host.setAttribute('data-atelier-motion', 'viewport-loader');
    host.setAttribute('data-am-state', currentState);
    host.setAttribute('data-am-reduced', String(isReducedMotion()));
    host.innerHTML = SVG_MARKUP;

    var svgEl = host.querySelector('.am-viewport-loader-svg');
    var bracketsGroup = host.querySelector('.am-viewport-loader-brackets');
    var cubeGroup = host.querySelector('.am-viewport-loader-cube-group');
    var topFace = host.querySelector('.am-viewport-loader-top-face');
    var rearGroup = host.querySelector('.am-viewport-loader-rear-group');
    var rearRibs = host.querySelector('.am-viewport-loader-rear-ribs');
    var orbitRing = host.querySelector('.am-viewport-loader-orbit-ring');
    var hullPath = host.querySelector('.am-viewport-loader-hull');
    var frontGroup = host.querySelector('.am-viewport-loader-front-group');
    var frontRibs = host.querySelector('.am-viewport-loader-front-ribs');
    var vertexCore = host.querySelector('.am-viewport-loader-vertex-core');
    var emptyGroup = host.querySelector('.am-viewport-loader-outcome-empty');
    var errorGroup = host.querySelector('.am-viewport-loader-outcome-error');

    var animatedNodes = [
      bracketsGroup,
      cubeGroup,
      topFace,
      rearGroup,
      rearRibs,
      orbitRing,
      hullPath,
      frontGroup,
      frontRibs,
      vertexCore,
      emptyGroup,
      errorGroup
    ];

    function cancelActiveAnimations() {
      generation += 1;
      while (activeAnimations.length > 0) {
        var anim = activeAnimations.pop();
        anim.onfinish = null;
        try {
          anim.cancel();
        } catch (_) {}
      }
      for (var i = 0; i < animatedNodes.length; i++) {
        var node = animatedNodes[i];
        if (node && node.style) {
          node.style.transform = '';
          node.style.opacity = '';
          node.style.strokeDashoffset = '';
        }
      }
    }

    function runAnimation(el, keyframes, timing, onComplete) {
      if (motionUnavailable) return null;
      try {
        if (!el || typeof el.animate !== 'function') throw new Error('Animation unavailable');
        var anim = el.animate(keyframes, timing);
        activeAnimations.push(anim);
        if (timing.iterations !== Infinity) {
          var epoch = generation;
          anim.onfinish = function () {
            if (destroyed || generation !== epoch) return;
            // Release finished WAAPI effects immediately so CSS owns the resting state
            var idx = activeAnimations.indexOf(anim);
            if (idx !== -1) activeAnimations.splice(idx, 1);
            anim.onfinish = null;
            try {
              anim.cancel();
            } catch (_) {}
            if (typeof onComplete === 'function') onComplete();
          };
        }
        return anim;
      } catch (_) {
        // A partial WAAPI failure must not start duplicate loops or block geometry.
        motionUnavailable = true;
        cancelActiveAnimations();
        host.setAttribute('data-am-reduced', 'true');
        return null;
      }
    }

    function startSteadyLoadingLoop(expectedGen) {
      if (destroyed || currentState !== 'loading' || generation !== expectedGen) return;
      var reduced = isReducedMotion();
      host.setAttribute('data-am-reduced', String(reduced));
      if (reduced || isDocumentHidden()) return;

      // 1. Calm ~1200ms vertical isometric hover on the cube group
      runAnimation(
        cubeGroup,
        [
          { transform: 'translateY(0px)' },
          { transform: 'translateY(-1.4px)', offset: 0.5 },
          { transform: 'translateY(0px)' }
        ],
        {
          duration: LOOP_DURATION_MS,
          iterations: Infinity,
          easing: EASE_TURN
        }
      );

      // 2. Front Y-ribs gently pan across the isometric plane
      runAnimation(
        frontGroup,
        [
          { transform: 'translateX(0px)' },
          { transform: 'translateX(1.9px)', offset: 0.25 },
          { transform: 'translateX(0px)', offset: 0.5 },
          { transform: 'translateX(-1.9px)', offset: 0.75 },
          { transform: 'translateX(0px)' }
        ],
        {
          duration: LOOP_DURATION_MS,
          iterations: Infinity,
          easing: EASE_TURN
        }
      );

      // 3. Rear inverted-Y ribs pan in counter-phase to convey an isometric turn
      runAnimation(
        rearGroup,
        [
          { transform: 'translateX(0px)' },
          { transform: 'translateX(-1.9px)', offset: 0.25 },
          { transform: 'translateX(0px)', offset: 0.5 },
          { transform: 'translateX(1.9px)', offset: 0.75 },
          { transform: 'translateX(0px)' }
        ],
        {
          duration: LOOP_DURATION_MS,
          iterations: Infinity,
          easing: EASE_TURN
        }
      );

      // 4. Orbiting isometric equator seam travels smoothly around the cube
      runAnimation(
        orbitRing,
        [
          { strokeDashoffset: 1, opacity: 0.55 },
          { strokeDashoffset: 0.5, opacity: 0.9, offset: 0.5 },
          { strokeDashoffset: 0, opacity: 0.55 }
        ],
        {
          duration: LOOP_DURATION_MS,
          iterations: Infinity,
          easing: 'linear'
        }
      );

      // 5. Subtle tonal breathing on the top face
      runAnimation(
        topFace,
        [
          { opacity: 0.1 },
          { opacity: 0.22, offset: 0.5 },
          { opacity: 0.1 }
        ],
        {
          duration: LOOP_DURATION_MS,
          iterations: Infinity,
          easing: EASE_TURN
        }
      );
    }

    function startLoadingSequence(withAssembly) {
      cancelActiveAnimations();
      if (destroyed || currentState !== 'loading') return;

      var reduced = isReducedMotion();
      host.setAttribute('data-am-reduced', String(reduced));
      if (reduced || isDocumentHidden()) {
        return;
      }

      var myGen = generation;
      if (!withAssembly) {
        startSteadyLoadingLoop(myGen);
        return;
      }

      // 220ms edge assembly phase before entering the ~1200ms steady loop
      runAnimation(
        bracketsGroup,
        [
          { opacity: 0, transform: 'scale(0.92)' },
          { opacity: 0.55, transform: 'scale(1)' }
        ],
        {
          duration: ASSEMBLY_DURATION_MS,
          easing: EASE_STANDARD
        }
      );

      runAnimation(
        hullPath,
        [
          { strokeDashoffset: 1, opacity: 0.35 },
          { strokeDashoffset: 0, opacity: 1 }
        ],
        {
          duration: ASSEMBLY_DURATION_MS,
          easing: EASE_STANDARD
        }
      );

      runAnimation(
        rearRibs,
        [
          { strokeDashoffset: 1, opacity: 0 },
          { strokeDashoffset: 0, opacity: 0.34 }
        ],
        {
          duration: ASSEMBLY_DURATION_MS,
          easing: EASE_STANDARD
        }
      );

      runAnimation(
        frontRibs,
        [
          { strokeDashoffset: 1, opacity: 0.2 },
          { strokeDashoffset: 0, opacity: 1 }
        ],
        {
          duration: ASSEMBLY_DURATION_MS,
          easing: EASE_STANDARD
        },
        function () {
          if (destroyed || generation !== myGen || currentState !== 'loading') return;
          startSteadyLoadingLoop(myGen);
        }
      );

    }

    function playOutcomeSettle(targetState) {
      cancelActiveAnimations();
      if (destroyed) return;

      var reduced = isReducedMotion();
      host.setAttribute('data-am-reduced', String(reduced));
      if (reduced || isDocumentHidden()) {
        return;
      }

      var targetGroup = targetState === 'empty' ? emptyGroup : errorGroup;
      runAnimation(
        cubeGroup,
        [
          { transform: 'scale(0.96)' },
          { transform: 'scale(1)' }
        ],
        {
          duration: SETTLE_DURATION_MS,
          easing: EASE_STANDARD
        }
      );

      runAnimation(
        targetGroup,
        [
          { opacity: 0, transform: 'scale(0.88)' },
          { opacity: 1, transform: 'scale(1)' }
        ],
        {
          duration: SETTLE_DURATION_MS,
          easing: EASE_STANDARD
        }
      );
    }

    function applyState(nextState, forceReplay) {
      if (destroyed || !VALID_STATES.has(nextState)) return;
      if (!forceReplay && nextState === currentState) {
        return;
      }

      currentState = nextState;
      host.setAttribute('data-am-state', currentState);
      host.setAttribute('data-am-reduced', String(isReducedMotion()));

      if (currentState === 'loading') {
        startLoadingSequence(true);
      } else if (currentState === 'empty' || currentState === 'error') {
        playOutcomeSettle(currentState);
      } else {
        // 'idle' or 'ready' stops immediately and releases all WAAPI effects
        cancelActiveAnimations();
      }
    }

    function handleEnvironmentChange() {
      if (destroyed) return;
      var reduced = isReducedMotion();
      host.setAttribute('data-am-reduced', String(reduced));

      if (reduced || isDocumentHidden()) {
        cancelActiveAnimations();
      } else if (currentState === 'loading') {
        // Resume steady loop cleanly when returning to visible/unreduced state
        startLoadingSequence(false);
      }
    }

    if (mql) {
      try {
        if (typeof mql.addEventListener === 'function') {
          mql.addEventListener('change', handleEnvironmentChange);
        } else if (typeof mql.addListener === 'function') {
          mql.addListener(handleEnvironmentChange);
        }
      } catch (_) {}
    }
    if (typeof document !== 'undefined' && typeof document.addEventListener === 'function') {
      document.addEventListener('visibilitychange', handleEnvironmentChange);
    }

    var instance = {
      setState: function (nextState) {
        applyState(nextState, false);
      },
      replay: function () {
        if (destroyed) return;
        // For the loader, replay() replays assembly only if still loading; otherwise safe no-op
        if (currentState === 'loading') {
          applyState('loading', true);
        }
      },
      setReducedMotion: function (mode) {
        if (destroyed) return;
        reducedPref = mode === 'reduce' ? 'reduce' : 'system';
        handleEnvironmentChange();
      },
      destroy: function () {
        if (destroyed) return;
        destroyed = true;
        cancelActiveAnimations();
        if (mql) {
          try {
            if (typeof mql.removeEventListener === 'function') {
              mql.removeEventListener('change', handleEnvironmentChange);
            } else if (typeof mql.removeListener === 'function') {
              mql.removeListener(handleEnvironmentChange);
            }
          } catch (_) {}
        }
        if (typeof document !== 'undefined' && typeof document.removeEventListener === 'function') {
          document.removeEventListener('visibilitychange', handleEnvironmentChange);
        }
        if (svgEl && svgEl.parentNode === host) {
          host.removeChild(svgEl);
        }
        host.removeAttribute('data-atelier-motion');
        host.removeAttribute('data-am-state');
        host.removeAttribute('data-am-reduced');
        if (mountedHosts) {
          if (mountedHosts.get(host) === instance) {
            mountedHosts.delete(host);
          }
        } else if (host.__amViewportLoader === instance) {
          delete host.__amViewportLoader;
        }
      }
    };

    if (mountedHosts) {
      mountedHosts.set(host, instance);
    } else {
      host.__amViewportLoader = instance;
    }

    applyState(currentState, true);
    return instance;
  }

  window.AtelierMotion = window.AtelierMotion || {};
  window.AtelierMotion.viewportLoader = {
    mount: mountViewportLoader
  };
})();
