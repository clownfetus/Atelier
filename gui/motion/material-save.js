/*
 * Atelier — Material-Save Feedback Motion Controller
 * Classic-script IIFE adding window.AtelierMotion.materialSave while preserving
 * existing window.AtelierMotion entries (exportFeedback, viewportLoader).
 * Upstream Material Symbols Rounded geometry licensed under the Apache License, Version 2.0.
 * Studio artwork uses squared corners and sharp joins, rather than unmodified official Sharp glyphs.
 * Adapted from the supplied Gemini component; the caller owns host disposal.
 */
(function () {
  'use strict';

  var VALID_STATES = new Set(['idle', 'saving', 'success', 'warning', 'error']);
  var TERMINAL_STATES = new Set(['success', 'warning', 'error']);

  var EASE_STANDARD = 'cubic-bezier(0.2, 0, 0, 1)';
  var EASE_SAVING = 'cubic-bezier(0.4, 0, 0.2, 1)';
  var SAVING_LOOP_MS = 960;
  var CHECK_REVEAL_MS = 240;
  var OUTCOME_SETTLE_MS = 210;

  // Track mounted hosts so duplicate mount() calls cleanly destroy the prior instance
  var mountedHosts = typeof WeakMap === 'function' ? new WeakMap() : null;

  // Trusted standalone SVG markup matching material-save.svg (24x24 coordinate space)
  var SVG_MARKUP =
    '<svg xmlns="http://www.w3.org/2000/svg" class="am-material-save-svg" viewBox="0 0 24 24" width="24" height="24" fill="none" aria-hidden="true" focusable="false">' +
      '<g class="am-material-save-cartridge-group">' +
        '<path class="am-material-save-body-fill" d="M 2.5 2.5 H 17 L 21.5 7 V 21.5 H 2.5 Z" fill="currentColor" opacity="0.12" />' +
        '<path class="am-material-save-body-stroke" d="M 2.5 2.5 H 17 L 21.5 7 V 21.5 H 2.5 Z" stroke="currentColor" stroke-width="1.9" stroke-linecap="butt" stroke-linejoin="miter" />' +
        '<rect class="am-material-save-shutter" x="6.75" y="2.75" width="8.25" height="4.75" rx="0" fill="currentColor" opacity="0.88" />' +
        '<circle class="am-material-save-disc" cx="12" cy="14.25" r="3.2" stroke="currentColor" stroke-width="1.9" fill="currentColor" fill-opacity="0.12" />' +
      '</g>' +
      '<circle class="am-material-save-saving-ring" pathLength="1" cx="12" cy="12" r="9.75" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-dasharray="0.32 0.68" stroke-dashoffset="0" opacity="0" />' +
      '<g class="am-material-save-outcome am-material-save-outcome-success" opacity="0">' +
        '<circle class="am-material-save-success-disc" cx="12" cy="12" r="9.75" fill="currentColor" opacity="0.12" />' +
        '<circle class="am-material-save-success-ring" pathLength="1" cx="12" cy="12" r="9.75" stroke="currentColor" stroke-width="2" stroke-linecap="round" />' +
        '<path class="am-material-save-check-path" pathLength="1" d="M 7.5 12.25 L 10.55 15.3 L 16.65 8.85" stroke="currentColor" stroke-width="2.35" stroke-linecap="butt" stroke-linejoin="miter" />' +
      '</g>' +
      '<g class="am-material-save-outcome am-material-save-outcome-warning" opacity="0">' +
        '<path class="am-material-save-warning-fill" d="M 12 3.25 L 21.25 19.25 H 2.75 Z" fill="currentColor" opacity="0.12" />' +
        '<path class="am-material-save-warning-stroke" d="M 12 3.25 L 21.25 19.25 H 2.75 Z" stroke="currentColor" stroke-width="2" stroke-linecap="butt" stroke-linejoin="miter" />' +
        '<path class="am-material-save-warning-mark" d="M 12 9.25 V 13.25" stroke="currentColor" stroke-width="2.25" stroke-linecap="butt" />' +
        '<circle class="am-material-save-warning-dot" cx="12" cy="16.35" r="1.25" fill="currentColor" />' +
      '</g>' +
      '<g class="am-material-save-outcome am-material-save-outcome-error" opacity="0">' +
        '<circle class="am-material-save-error-disc" cx="12" cy="12" r="9.75" fill="currentColor" opacity="0.12" />' +
        '<circle class="am-material-save-error-ring" cx="12" cy="12" r="9.75" stroke="currentColor" stroke-width="2" />' +
        '<path class="am-material-save-error-cross" d="M 8.75 8.75 L 15.25 15.25 M 15.25 8.75 L 8.75 15.25" stroke="currentColor" stroke-width="2.25" stroke-linecap="butt" stroke-linejoin="miter" />' +
      '</g>' +
    '</svg>';

  function mountMaterialSave(host, options) {
    if (!host || host.nodeType !== 1 || typeof host.appendChild !== 'function') {
      throw new Error('AtelierMotion.materialSave.mount requires a valid DOM host element.');
    }

    // Destroy any previous instance mounted on the same host
    var prior = mountedHosts ? mountedHosts.get(host) : host.__amMaterialSave;
    if (prior && typeof prior.destroy === 'function') {
      try {
        prior.destroy();
      } catch (_) {}
    }

    var opts = options || {};
    var currentState = VALID_STATES.has(opts.state) ? opts.state : 'idle';
    var reducedPref = opts.reducedMotion === 'reduce' ? 'reduce' : 'system';
    var destroyed = false;
    var generation = 0;
    var activeAnimations = [];

    var mql = null;
    try {
      if (typeof window.matchMedia === 'function') {
        mql = window.matchMedia('(prefers-reduced-motion: reduce)');
      }
    } catch (_) {}

    function isReducedMotion() {
      return reducedPref === 'reduce' || Boolean(mql && mql.matches);
    }

    function isDocumentHidden() {
      return Boolean(typeof document !== 'undefined' && document.hidden);
    }

    host.setAttribute('data-atelier-motion', 'material-save');
    host.setAttribute('data-am-state', currentState);
    host.setAttribute('data-am-reduced', String(isReducedMotion()));
    host.innerHTML = SVG_MARKUP;

    var svgEl = host.querySelector('.am-material-save-svg');
    var cartridgeGroup = host.querySelector('.am-material-save-cartridge-group');
    var shutterEl = host.querySelector('.am-material-save-shutter');
    var discEl = host.querySelector('.am-material-save-disc');
    var savingRing = host.querySelector('.am-material-save-saving-ring');
    var successGroup = host.querySelector('.am-material-save-outcome-success');
    var successRing = host.querySelector('.am-material-save-success-ring');
    var checkPath = host.querySelector('.am-material-save-check-path');
    var warningGroup = host.querySelector('.am-material-save-outcome-warning');
    var errorGroup = host.querySelector('.am-material-save-outcome-error');
    var errorCross = host.querySelector('.am-material-save-error-cross');

    var animatedNodes = [
      cartridgeGroup,
      shutterEl,
      discEl,
      savingRing,
      successGroup,
      successRing,
      checkPath,
      warningGroup,
      errorGroup,
      errorCross
    ];

    function cancelActiveAnimations() {
      generation += 1;
      while (activeAnimations.length > 0) {
        var anim = activeAnimations.pop();
        try {
          anim.onfinish = null;
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

    function runAnimation(el, keyframes, timing) {
      if (!el || typeof el.animate !== 'function') {
        throw new Error('Web Animations API unavailable on element.');
      }
      var myGen = generation;
      var anim = el.animate(keyframes, timing);
      activeAnimations.push(anim);

      if (timing && timing.iterations !== Infinity) {
        anim.onfinish = function () {
          anim.onfinish = null;
          var idx = activeAnimations.indexOf(anim);
          if (idx !== -1) activeAnimations.splice(idx, 1);
          // Release finished finite WAAPI effects so static CSS rules own the resting pose
          try {
            anim.cancel();
          } catch (_) {}
          if (!destroyed && generation === myGen && el.style) {
            el.style.transform = '';
            el.style.opacity = '';
            el.style.strokeDashoffset = '';
          }
        };
      }
      return anim;
    }

    function startSavingLoop() {
      cancelActiveAnimations();
      if (destroyed || currentState !== 'saving') return;

      var reduced = isReducedMotion();
      host.setAttribute('data-am-reduced', String(reduced));
      if (reduced || isDocumentHidden()) {
        return;
      }

      try {
        runAnimation(
          savingRing,
          [
            { transform: 'rotate(0deg)', strokeDashoffset: 1, opacity: 0.72 },
            { transform: 'rotate(180deg)', strokeDashoffset: 0.5, opacity: 1, offset: 0.5 },
            { transform: 'rotate(360deg)', strokeDashoffset: 0, opacity: 0.72 }
          ],
          {
            duration: SAVING_LOOP_MS,
            iterations: Infinity,
            easing: 'linear'
          }
        );

        runAnimation(
          cartridgeGroup,
          [
            { transform: 'scale(0.76)', opacity: 0.78 },
            { transform: 'scale(0.8)', opacity: 0.94, offset: 0.5 },
            { transform: 'scale(0.76)', opacity: 0.78 }
          ],
          {
            duration: SAVING_LOOP_MS,
            iterations: Infinity,
            easing: EASE_SAVING
          }
        );

        runAnimation(
          discEl,
          [
            { transform: 'scale(0.92)' },
            { transform: 'scale(1.08)', offset: 0.5 },
            { transform: 'scale(0.92)' }
          ],
          {
            duration: SAVING_LOOP_MS,
            iterations: Infinity,
            easing: EASE_SAVING
          }
        );
      } catch (_) {
        // Degrade cleanly to static saving pose if WAAPI fails partway through
        cancelActiveAnimations();
      }
    }

    function playTerminalConfirmation(targetState, fromState) {
      cancelActiveAnimations();
      if (destroyed || !TERMINAL_STATES.has(targetState)) return;

      var reduced = isReducedMotion();
      host.setAttribute('data-am-reduced', String(reduced));
      if (reduced || isDocumentHidden()) {
        return;
      }

      try {
        if (fromState === 'saving' || fromState === 'idle') {
          runAnimation(
            cartridgeGroup,
            [
              { transform: 'scale(0.76)', opacity: 0.55 },
              { transform: 'scale(0.62)', opacity: 0 }
            ],
            {
              duration: 130,
              easing: EASE_STANDARD
            }
          );
        }

        if (targetState === 'success') {
          runAnimation(
            successGroup,
            [
              { opacity: 0, transform: 'scale(0.9)' },
              { opacity: 1, transform: 'scale(1)' }
            ],
            {
              duration: 180,
              easing: EASE_STANDARD
            }
          );

          runAnimation(
            successRing,
            [
              { strokeDashoffset: 0.45, opacity: 0.4 },
              { strokeDashoffset: 0, opacity: 1 }
            ],
            {
              duration: 210,
              easing: EASE_STANDARD
            }
          );

          runAnimation(
            checkPath,
            [
              { strokeDashoffset: 1 },
              { strokeDashoffset: 0 }
            ],
            {
              duration: CHECK_REVEAL_MS,
              easing: EASE_STANDARD
            }
          );
        } else if (targetState === 'warning') {
          runAnimation(
            warningGroup,
            [
              { opacity: 0, transform: 'translateY(-1.4px) scale(0.92)' },
              { opacity: 1, transform: 'translateY(0px) scale(1)' }
            ],
            {
              duration: OUTCOME_SETTLE_MS,
              easing: EASE_STANDARD
            }
          );
        } else if (targetState === 'error') {
          runAnimation(
            errorGroup,
            [
              { opacity: 0, transform: 'scale(0.9)' },
              { opacity: 1, transform: 'scale(1)' }
            ],
            {
              duration: OUTCOME_SETTLE_MS,
              easing: EASE_STANDARD
            }
          );

          runAnimation(
            errorCross,
            [
              { transform: 'scale(0.84)', opacity: 0.4 },
              { transform: 'scale(1)', opacity: 1 }
            ],
            {
              duration: OUTCOME_SETTLE_MS,
              easing: EASE_STANDARD
            }
          );
        }
      } catch (_) {
        // Degrade cleanly to static CSS outcome pose if animate() throws
        cancelActiveAnimations();
      }
    }

    function applyState(nextState, forceReplay, isInitialMount) {
      if (destroyed || !VALID_STATES.has(nextState)) return;
      var prevState = currentState;
      if (!forceReplay && !isInitialMount && nextState === prevState) {
        return;
      }

      currentState = nextState;
      host.setAttribute('data-am-state', currentState);
      host.setAttribute('data-am-reduced', String(isReducedMotion()));

      if (currentState === 'idle') {
        cancelActiveAnimations();
      } else if (currentState === 'saving') {
        startSavingLoop();
      } else if (TERMINAL_STATES.has(currentState)) {
        playTerminalConfirmation(currentState, isInitialMount ? 'idle' : prevState);
      }
    }

    function handleEnvironmentChange() {
      if (destroyed) return;
      var reduced = isReducedMotion();
      host.setAttribute('data-am-reduced', String(reduced));

      if (reduced || isDocumentHidden()) {
        // Stop CSS & WAAPI immediately; completed terminal states stay settled
        cancelActiveAnimations();
      } else if (currentState === 'saving') {
        // Resume only genuine busy saving loops when returning to visible/unreduced state
        startSavingLoop();
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

    // Play initial state on mount (including fresh mount directly in success/warning/error)
    applyState(currentState, false, true);

    var instance = {
      setState: function (nextState) {
        applyState(nextState, false, false);
      },
      replay: function () {
        if (destroyed || !TERMINAL_STATES.has(currentState)) return;
        applyState(currentState, true, false);
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
        } else if (host.__amMaterialSave === instance) {
          delete host.__amMaterialSave;
        }
      }
    };

    if (mountedHosts) {
      mountedHosts.set(host, instance);
    } else {
      host.__amMaterialSave = instance;
    }

    return instance;
  }

  window.AtelierMotion = window.AtelierMotion || {};
  window.AtelierMotion.materialSave = {
    mount: mountMaterialSave
  };
})();
