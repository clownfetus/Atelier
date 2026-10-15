/*
 * Atelier — Export Feedback Motion Controller
 * Classic-script IIFE adding window.AtelierMotion.exportFeedback.
 * Upstream Material Symbols Rounded geometry licensed under the Apache License, Version 2.0.
 * Studio artwork uses squared corners and sharp joins, rather than unmodified official Sharp glyphs.
 * Adapted from the supplied Gemini controller; Atelier adds lifecycle and static-fallback safeguards.
 */
(function () {
  'use strict';

  var VALID_STATES = new Set(['idle', 'busy', 'success', 'warning', 'error']);

  var EASE_STANDARD = 'cubic-bezier(0.2, 0, 0, 1)';
  var BUSY_DURATION_MS = 1040;
  var TERMINAL_DURATION_MS = 240;
  var instances = new Map();
  // One observer for all instances, disconnected when the last host is destroyed.
  // Covers removeChild/innerHTML as well as the explicit toast dismissal path.
  var removalObserver = new MutationObserver(function () {
    instances.forEach(function (record, host) {
      if (!host.isConnected || record.svg.parentNode !== host) record.instance.destroy();
    });
  });

  var SVG_MARKUP =
    '<svg xmlns="http://www.w3.org/2000/svg" class="am-export-feedback-svg" viewBox="0 0 24 24" aria-hidden="true" focusable="false">' +
      '<g class="am-export-feedback-tray-group">' +
        '<rect class="am-export-feedback-well" x="5.5" y="13.5" width="13" height="5" rx="0" />' +
        '<rect class="am-export-feedback-payload" x="8" y="15.25" width="8" height="2" rx="0" />' +
        '<path class="am-export-feedback-tray" d="M4 15H6V18H18V15H20V20H4Z" />' +
      '</g>' +
      '<g class="am-export-feedback-arrow-group">' +
        '<path class="am-export-feedback-arrow" d="M11 4H13V12L15.5 9.5L17 11L12 16L7 11L8.5 9.5L11 12Z" />' +
      '</g>' +
      '<g class="am-export-feedback-outcome am-export-feedback-outcome-success">' +
        '<circle cx="12" cy="9.75" r="5.25" opacity="0.12" />' +
        '<path class="am-export-feedback-check-path" pathLength="1" d="M8.5 10.1L11.0 12.6L15.75 7.35" />' +
      '</g>' +
      '<g class="am-export-feedback-outcome am-export-feedback-outcome-warning">' +
        '<path d="M12 3.5L18.35 14.5H5.65ZM11 7V10H13V7ZM11 11.5V13H13V11.5Z" fill-rule="evenodd" />' +
      '</g>' +
      '<g class="am-export-feedback-outcome am-export-feedback-outcome-error">' +
        '<circle cx="12" cy="9.75" r="5.25" opacity="0.12" />' +
        '<path class="am-export-feedback-error-stroke" d="M9.35 7.1L14.65 12.4M14.65 7.1L9.35 12.4" />' +
      '</g>' +
    '</svg>';

  function mountExportFeedback(host, options) {
    if (!host || host.nodeType !== 1) {
      throw new Error('AtelierMotion.exportFeedback.mount requires a valid DOM host element.');
    }
    if (instances.has(host)) instances.get(host).instance.destroy();
    if (host.childNodes.length) throw new Error('Export feedback needs an empty icon host.');

    var opts = options || {};
    var currentState = VALID_STATES.has(opts.state) ? opts.state : 'idle';
    var reducedPref = opts.reducedMotion === 'reduce' ? 'reduce' : 'system';
    var destroyed = false;
    var generation = 0;
    var activeAnimations = [];
    var motionUnavailable = false;

    var mql = typeof window.matchMedia === 'function'
      ? window.matchMedia('(prefers-reduced-motion: reduce)')
      : null;

    function isReducedMotion() {
      return motionUnavailable || reducedPref === 'reduce' || Boolean(mql && mql.matches);
    }

    function isDocumentHidden() {
      return Boolean(typeof document !== 'undefined' && document.hidden);
    }

    host.setAttribute('data-atelier-motion', 'export-feedback');
    host.setAttribute('data-am-state', currentState);
    host.setAttribute('data-am-reduced', String(isReducedMotion()));
    host.innerHTML = SVG_MARKUP;

    var svgEl = host.querySelector('.am-export-feedback-svg');
    var trayGroup = host.querySelector('.am-export-feedback-tray-group');
    var payloadEl = host.querySelector('.am-export-feedback-payload');
    var arrowGroup = host.querySelector('.am-export-feedback-arrow-group');
    var successGroup = host.querySelector('.am-export-feedback-outcome-success');
    var checkPath = host.querySelector('.am-export-feedback-check-path');
    var warningGroup = host.querySelector('.am-export-feedback-outcome-warning');
    var errorGroup = host.querySelector('.am-export-feedback-outcome-error');

    function cancelActiveAnimations() {
      generation += 1;
      while (activeAnimations.length > 0) {
        var anim = activeAnimations.pop();
        anim.onfinish = null;
        try {
          anim.cancel();
        } catch (_) {}
      }
    }

    function resetInlineStyles() {
      var nodes = [trayGroup, payloadEl, arrowGroup, successGroup, checkPath, warningGroup, errorGroup];
      for (var i = 0; i < nodes.length; i++) {
        if (nodes[i]) {
          nodes[i].style.transform = '';
          nodes[i].style.opacity = '';
          nodes[i].style.strokeDashoffset = '';
        }
      }
    }

    function trackAnimation(el, keyframes, timing) {
      if (motionUnavailable) return null;
      try {
        if (!el || typeof el.animate !== 'function') throw new Error('Animation unavailable');
        var anim = el.animate(keyframes, timing);
        activeAnimations.push(anim);
        if (timing.iterations !== Infinity) {
          var epoch = generation;
          anim.onfinish = function () {
            if (destroyed || epoch !== generation) return;
            // State selectors already provide the final pose; release filled effects.
            anim.onfinish = null;
            anim.cancel();
            activeAnimations = activeAnimations.filter(function (item) { return item !== anim; });
          };
        }
        return anim;
      } catch (_) {
        // Presentation must never turn a successful export into an application error.
        motionUnavailable = true;
        cancelActiveAnimations();
        host.setAttribute('data-am-reduced', 'true');
        return null;
      }
    }

    function startBusyLoop() {
      cancelActiveAnimations();
      resetInlineStyles();
      if (destroyed || currentState !== 'busy') return;

      var reduced = isReducedMotion();
      host.setAttribute('data-am-reduced', String(reduced));
      if (reduced || isDocumentHidden()) {
        return;
      }

      trackAnimation(
        arrowGroup,
        [
          { transform: 'translateY(-3.2px) scale(0.94)', opacity: 0, offset: 0 },
          { transform: 'translateY(-1.8px) scale(1)', opacity: 1, offset: 0.2 },
          { transform: 'translateY(2.1px) scale(1)', opacity: 1, offset: 0.68 },
          { transform: 'translateY(2.6px) scale(0.95)', opacity: 0, offset: 0.88 },
          { transform: 'translateY(-3.2px) scale(0.94)', opacity: 0, offset: 1 }
        ],
        {
          duration: BUSY_DURATION_MS,
          iterations: Infinity,
          easing: EASE_STANDARD
        }
      );

      trackAnimation(
        trayGroup,
        [
          { transform: 'translateY(0px)', offset: 0 },
          { transform: 'translateY(0px)', offset: 0.56 },
          { transform: 'translateY(0.65px)', offset: 0.72 },
          { transform: 'translateY(0px)', offset: 0.92 },
          { transform: 'translateY(0px)', offset: 1 }
        ],
        {
          duration: BUSY_DURATION_MS,
          iterations: Infinity,
          easing: EASE_STANDARD
        }
      );

      trackAnimation(
        payloadEl,
        [
          { opacity: 0.08, transform: 'scaleX(0.75)', offset: 0 },
          { opacity: 0.14, transform: 'scaleX(0.82)', offset: 0.54 },
          { opacity: 0.48, transform: 'scaleX(1)', offset: 0.72 },
          { opacity: 0.08, transform: 'scaleX(0.75)', offset: 1 }
        ],
        {
          duration: BUSY_DURATION_MS,
          iterations: Infinity,
          easing: EASE_STANDARD
        }
      );
    }

    function playTerminalTransition(targetState, fromState) {
      cancelActiveAnimations();
      resetInlineStyles();
      if (destroyed) return;

      var reduced = isReducedMotion();
      host.setAttribute('data-am-reduced', String(reduced));
      if (reduced || isDocumentHidden()) {
        return;
      }

      if (fromState === 'busy' || fromState === 'idle') {
        trackAnimation(
          arrowGroup,
          [
            { transform: 'translateY(0.5px) scale(1)', opacity: 0.85 },
            { transform: 'translateY(2.2px) scale(0.9)', opacity: 0 }
          ],
          {
            duration: 140,
            easing: EASE_STANDARD,
            fill: 'forwards'
          }
        );
      }

      trackAnimation(
        trayGroup,
        [
          { transform: 'translateY(0.6px)' },
          { transform: 'translateY(0px)' }
        ],
        {
          duration: TERMINAL_DURATION_MS,
          easing: EASE_STANDARD
        }
      );

      if (targetState === 'success') {
        trackAnimation(
          successGroup,
          [
            { opacity: 0, transform: 'scale(0.92)' },
            { opacity: 1, transform: 'scale(1)' }
          ],
          {
            duration: 190,
            easing: EASE_STANDARD,
            fill: 'forwards'
          }
        );

        trackAnimation(
          checkPath,
          [
            { strokeDashoffset: 1 },
            { strokeDashoffset: 0 }
          ],
          {
            duration: TERMINAL_DURATION_MS,
            easing: EASE_STANDARD,
            fill: 'forwards'
          }
        );

      } else if (targetState === 'warning') {
        trackAnimation(
          warningGroup,
          [
            { opacity: 0, transform: 'translateY(-1.2px) scale(0.95)' },
            { opacity: 1, transform: 'translateY(0px) scale(1)' }
          ],
          {
            duration: 200,
            easing: EASE_STANDARD,
            fill: 'forwards'
          }
        );
      } else if (targetState === 'error') {
        trackAnimation(
          errorGroup,
          [
            { opacity: 0, transform: 'scale(0.94)' },
            { opacity: 1, transform: 'scale(1)' }
          ],
          {
            duration: 200,
            easing: EASE_STANDARD,
            fill: 'forwards'
          }
        );
      }
    }

    function applyState(nextState, forceReplay) {
      if (destroyed || !VALID_STATES.has(nextState)) return;
      var prevState = currentState;
      if (!forceReplay && nextState === prevState) {
        return;
      }

      currentState = nextState;
      host.setAttribute('data-am-state', currentState);
      host.setAttribute('data-am-reduced', String(isReducedMotion()));

      if (currentState === 'idle') {
        cancelActiveAnimations();
        resetInlineStyles();
      } else if (currentState === 'busy') {
        startBusyLoop();
      } else {
        playTerminalTransition(currentState, prevState);
      }
    }

    function handleMotionOrVisibilityChange() {
      if (destroyed) return;
      var reduced = isReducedMotion();
      host.setAttribute('data-am-reduced', String(reduced));

      if (reduced || isDocumentHidden()) {
        cancelActiveAnimations();
        resetInlineStyles();
      } else if (currentState === 'busy') {
        startBusyLoop();
      }
    }

    if (mql) {
      if (typeof mql.addEventListener === 'function') {
        mql.addEventListener('change', handleMotionOrVisibilityChange);
      } else if (typeof mql.addListener === 'function') {
        mql.addListener(handleMotionOrVisibilityChange);
      }
    }
    document.addEventListener('visibilitychange', handleMotionOrVisibilityChange);

    var instance = {
      setState: function (nextState) {
        applyState(nextState, false);
      },
      replay: function () {
        if (destroyed) return;
        if (currentState === 'success' || currentState === 'warning' || currentState === 'error') {
          applyState(currentState, true);
        }
      },
      setReducedMotion: function (mode) {
        if (destroyed) return;
        reducedPref = mode === 'reduce' ? 'reduce' : 'system';
        handleMotionOrVisibilityChange();
      },
      destroy: function () {
        if (destroyed) return;
        destroyed = true;
        cancelActiveAnimations();
        if (mql) {
          if (typeof mql.removeEventListener === 'function') {
            mql.removeEventListener('change', handleMotionOrVisibilityChange);
          } else if (typeof mql.removeListener === 'function') {
            mql.removeListener(handleMotionOrVisibilityChange);
          }
        }
        document.removeEventListener('visibilitychange', handleMotionOrVisibilityChange);
        if (svgEl && svgEl.parentNode === host) {
          host.removeChild(svgEl);
        }
        host.removeAttribute('data-atelier-motion');
        host.removeAttribute('data-am-state');
        host.removeAttribute('data-am-reduced');
        instances.delete(host);
        if (!instances.size) removalObserver.disconnect();
      }
    };
    if (!instances.size) removalObserver.observe(document.documentElement, {childList: true, subtree: true});
    instances.set(host, {instance: instance, svg: svgEl});
    // New terminal toasts should animate too, not just busy -> terminal transitions.
    applyState(currentState, true);
    return instance;
  }

  window.AtelierMotion = window.AtelierMotion || {};
  window.AtelierMotion.exportFeedback = {
    mount: mountExportFeedback
  };
})();
