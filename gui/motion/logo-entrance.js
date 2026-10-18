/* Adapted from the supplied Gemini logo entrance. Original PNG remains caller-owned.
 * Krackle: as the mark rises into place, a ring of six charge bubbles pops out from
 * behind it and fades at the edge of the 32px slot. The mark itself is never redrawn.
 * Image readiness covers both the SVG image and its cache probe; failures never own
 * the fallback. Caller must handle ready and destroy before removing its host. */
(function (global) {
  'use strict';

  var SVG_NS = 'http://www.w3.org/2000/svg';
  var COMPONENT_NAME = 'logo-entrance';
  var VALID_STATES = new Set(['settled', 'entering']);
  var VALID_REDUCED_MOTION = new Set(['system', 'reduce']);
  var ENTRANCE_DURATION_MS = 320;
  var ENTRANCE_EASING = 'cubic-bezier(0.2, 0, 0, 1)';
  var ENTRANCE_START_OPACITY = 0.58;
  var ENTRANCE_START_Y_PX = 2;

  var mountedHosts = typeof WeakMap === 'function' ? new WeakMap() : null;
  var fallbackHostList = [];

  function getMountedRecord(host) {
    if (mountedHosts) {
      return mountedHosts.get(host) || null;
    }
    for (var i = 0; i < fallbackHostList.length; i += 1) {
      if (fallbackHostList[i].host === host) {
        return fallbackHostList[i].record;
      }
    }
    return null;
  }

  function setMountedRecord(host, record) {
    if (mountedHosts) {
      mountedHosts.set(host, record);
      return;
    }
    for (var i = 0; i < fallbackHostList.length; i += 1) {
      if (fallbackHostList[i].host === host) {
        fallbackHostList[i].record = record;
        return;
      }
    }
    fallbackHostList.push({ host: host, record: record });
  }

  function deleteMountedRecord(host) {
    if (mountedHosts) {
      mountedHosts.delete(host);
      return;
    }
    for (var i = fallbackHostList.length - 1; i >= 0; i -= 1) {
      if (fallbackHostList[i].host === host) {
        fallbackHostList.splice(i, 1);
      }
    }
  }

  function isHostEmpty(host) {
    if (host.children && host.children.length > 0) {
      return false;
    }
    var text = host.textContent || '';
    return text.trim().length === 0;
  }

  function isDocumentHidden() {
    if (typeof document === 'undefined') {
      return false;
    }
    return Boolean(document.hidden || document.visibilityState === 'hidden');
  }

  function isHostVisibleInViewport(host) {
    if (!host || !host.isConnected || host.hidden) {
      return false;
    }
    if (typeof host.getBoundingClientRect !== 'function') {
      return true;
    }
    var rect = host.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) {
      return false;
    }
    var vw = typeof window !== 'undefined' ? (window.innerWidth || document.documentElement.clientWidth || 0) : 0;
    var vh = typeof window !== 'undefined' ? (window.innerHeight || document.documentElement.clientHeight || 0) : 0;
    if (vw > 0 && vh > 0) {
      if (rect.bottom <= 0 || rect.right <= 0 || rect.top >= vh || rect.left >= vw) {
        return false;
      }
    }
    return true;
  }

  function createLogoSvg(logoSrc) {
    var svg = document.createElementNS(SVG_NS, 'svg');
    svg.setAttribute('xmlns', SVG_NS);
    svg.setAttribute('width', '32');
    svg.setAttribute('height', '32');
    svg.setAttribute('viewBox', '0 0 32 32');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('class', 'am-logo-entrance-svg');
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('focusable', 'false');

    // Krackle splash: six bubbles behind the mark, hidden unless the entrance plays.
    var splash = document.createElementNS(SVG_NS, 'g');
    splash.setAttribute('class', 'am-logo-entrance-splash');
    var bubbles = [];
    for (var b = 0; b < 6; b++) {
      var bubble = document.createElementNS(SVG_NS, 'g');
      bubble.setAttribute('class', 'am-logo-entrance-bubble');
      var energy = document.createElementNS(SVG_NS, 'circle');
      energy.setAttribute('class', 'am-logo-entrance-energy');
      energy.setAttribute('cx', '16'); energy.setAttribute('cy', '16'); energy.setAttribute('r', b % 2 ? '1.8' : '2.4');
      var hole = document.createElementNS(SVG_NS, 'circle');
      hole.setAttribute('class', 'am-logo-entrance-hole');
      hole.setAttribute('cx', '16.4'); hole.setAttribute('cy', '16.3'); hole.setAttribute('r', b % 2 ? '0.75' : '1');
      bubble.appendChild(energy); bubble.appendChild(hole);
      splash.appendChild(bubble);
      bubbles.push(bubble);
    }
    svg.appendChild(splash);

    var stage = document.createElementNS(SVG_NS, 'g');
    stage.setAttribute('class', 'am-logo-entrance-stage');

    var image = document.createElementNS(SVG_NS, 'image');
    image.setAttribute('class', 'am-logo-entrance-image');
    image.setAttribute('x', '0');
    image.setAttribute('y', '0');
    image.setAttribute('width', '32');
    image.setAttribute('height', '32');
    image.setAttribute('preserveAspectRatio', 'xMidYMid meet');
    image.setAttribute('href', logoSrc);

    stage.appendChild(image);
    svg.appendChild(stage);

    return {
      svg: svg,
      stage: stage,
      image: image,
      bubbles: bubbles
    };
  }

  function mount(emptyHost, options) {
    if (!emptyHost || emptyHost.nodeType !== 1) {
      throw new TypeError('AtelierMotion.logoEntrance.mount requires a valid DOM Element host.');
    }

    var opts = options || {};
    var initialState = opts.state !== undefined ? opts.state : 'settled';
    var initialReducedMotion = opts.reducedMotion !== undefined ? opts.reducedMotion : 'system';
    var logoSrc = typeof opts.logoSrc === 'string' ? opts.logoSrc.trim() : '';
    var onError = typeof opts.onError === 'function' ? opts.onError : null;
    var onReady = typeof opts.onReady === 'function' ? opts.onReady : null;

    if (!VALID_STATES.has(initialState)) {
      throw new RangeError('Invalid state "' + String(initialState) + '". Expected "settled" or "entering".');
    }
    if (!VALID_REDUCED_MOTION.has(initialReducedMotion)) {
      throw new RangeError('Invalid reducedMotion "' + String(initialReducedMotion) + '". Expected "system" or "reduce".');
    }
    if (!logoSrc) {
      var missingSrcErr = new Error('AtelierMotion.logoEntrance.mount requires a non-empty logoSrc option.');
      if (onError) {
        try {
          onError(missingSrcErr);
        } catch (_ignore) {}
      }
      throw missingSrcErr;
    }

    var existingRecord = getMountedRecord(emptyHost);
    if (existingRecord && typeof existingRecord.destroy === 'function') {
      existingRecord.destroy();
    }

    if (!isHostEmpty(emptyHost)) {
      var nonEmptyErr = new Error('AtelierMotion.logoEntrance.mount requires an empty dedicated host.');
      if (onError) {
        try {
          onError(nonEmptyErr);
        } catch (_ignore) {}
      }
      throw nonEmptyErr;
    }

    var hadMotionAttr = emptyHost.hasAttribute('data-atelier-motion');
    var priorMotionAttr = emptyHost.getAttribute('data-atelier-motion');
    var hadAriaHidden = emptyHost.hasAttribute('aria-hidden');
    var priorAriaHidden = emptyHost.getAttribute('aria-hidden');

    emptyHost.setAttribute('data-atelier-motion', COMPONENT_NAME);
    emptyHost.setAttribute('aria-hidden', 'true');

    var nodes = createLogoSvg(logoSrc);
    var svgEl = nodes.svg;
    var stageEl = nodes.stage;

    var isDestroyed = false;
    var isImageReady = false;
    var isImageFailed = false;
    var currentState = 'settled';
    var pendingEntranceRequest = initialState === 'entering' && !isDocumentHidden();
    var reducedMotionMode = initialReducedMotion;
    var isOffscreen = false;
    var activeAnimation = null;
    var splashAnimations = [];
    var finishTimer = null;
    var animationGeneration = 0;
    var probeImg = null;
    var intersectionObserver = null;
    var mql = null;
    var probeReady = false, svgReady = false, readyTimer = null;

    var resolveReadyPromise;
    var rejectReadyPromise;
    var readySettled = false;
    var readyPromise = new Promise(function (resolve, reject) {
      resolveReadyPromise = resolve;
      rejectReadyPromise = reject;
    });
    /* Prevent unhandled rejection warnings when callers use onError instead of .catch(). */
    readyPromise.catch(function () {});

    function resolveReady(value) {
      if (readySettled) {
        return;
      }
      readySettled = true;
      resolveReadyPromise(value);
    }

    function rejectReady(err) {
      if (readySettled) {
        return;
      }
      readySettled = true;
      rejectReadyPromise(err);
    }

    function isReducedMotionEffective() {
      if (reducedMotionMode === 'reduce') {
        return true;
      }
      return Boolean(mql && mql.matches);
    }

    function syncReducedMotionAttr() {
      if (isDestroyed) {
        return;
      }
      emptyHost.setAttribute('data-am-reduced-motion', isReducedMotionEffective() ? 'true' : 'false');
    }

    function clearActiveEffects() {
      animationGeneration += 1;
      if (finishTimer !== null) {
        clearTimeout(finishTimer);
        finishTimer = null;
      }
      if (activeAnimation) {
        var anim = activeAnimation;
        activeAnimation = null;
        anim.onfinish = null;
        anim.oncancel = null;
        try {
          anim.cancel();
        } catch (_ignore) {}
      }
      while (splashAnimations.length) {
        var splashAnim = splashAnimations.pop();
        splashAnim.onfinish = null;
        try {
          splashAnim.cancel();
        } catch (_ignoreSplash) {}
      }
      if (stageEl) {
        stageEl.style.opacity = '';
        stageEl.style.transform = '';
      }
    }

    function playSplash(gen) {
      // Never touches Animation.finished; any failure settles the whole entrance.
      for (var i = 0; i < nodes.bubbles.length; i++) {
        if (gen !== animationGeneration) return;
        var angle = -Math.PI / 2 + i * Math.PI / 3 + 0.35;
        var near = 9.5, far = 14.5;
        var splashAnim = nodes.bubbles[i].animate(
          [
            { transform: 'translate(0px, 0px) scale(0.3)', opacity: 0, easing: ENTRANCE_EASING },
            { transform: 'translate(' + (Math.cos(angle) * near).toFixed(2) + 'px, ' + (Math.sin(angle) * near).toFixed(2) + 'px) scale(1)', opacity: 1, offset: 0.45, easing: 'cubic-bezier(0.55, 0, 1, 0.45)' },
            { transform: 'translate(' + (Math.cos(angle) * far).toFixed(2) + 'px, ' + (Math.sin(angle) * far).toFixed(2) + 'px) scale(0)', opacity: 0 }
          ],
          { duration: ENTRANCE_DURATION_MS - 80, delay: i * 16, easing: 'linear', fill: 'none' }
        );
        if (!splashAnim || typeof splashAnim.cancel !== 'function') throw new Error('Splash unavailable');
        splashAnimations.push(splashAnim);
        splashAnim.onfinish = (function (finished) {
          return function () {
            var idx = splashAnimations.indexOf(finished);
            if (idx !== -1) splashAnimations.splice(idx, 1);
            finished.onfinish = null;
            try { finished.cancel(); } catch (_ignoreFinish) {}
          };
        })(splashAnim);
      }
    }

    function settleNow() {
      if (isDestroyed) {
        return;
      }
      pendingEntranceRequest = false;
      clearActiveEffects();
      currentState = 'settled';
      if (!isImageFailed) {
        emptyHost.setAttribute('data-am-state', 'settled');
      }
    }

    function playEntrance(forceRestart) {
      if (isDestroyed || isImageFailed) {
        return;
      }
      if (!forceRestart && currentState === 'entering' && activeAnimation !== null) {
        return;
      }

      if (!isImageReady) {
        if (isReducedMotionEffective() || isDocumentHidden()) {
          settleNow();
        } else {
          pendingEntranceRequest = true;
        }
        return;
      }

      if (
        isReducedMotionEffective() ||
        isDocumentHidden() ||
        !isHostVisibleInViewport(emptyHost)
      ) {
        settleNow();
        return;
      }

      clearActiveEffects();

      if (!stageEl || typeof stageEl.animate !== 'function') {
        settleNow();
        return;
      }

      var gen = animationGeneration;
      currentState = 'entering';
      emptyHost.setAttribute('data-am-state', 'entering');

      try {
        var anim = stageEl.animate(
          [
            {
              opacity: ENTRANCE_START_OPACITY,
              transform: 'translateY(' + ENTRANCE_START_Y_PX + 'px)'
            },
            {
              opacity: 1,
              transform: 'translateY(0px)'
            }
          ],
          {
            duration: ENTRANCE_DURATION_MS,
            easing: ENTRANCE_EASING,
            fill: 'none'
          }
        );

        if (!anim || typeof anim.cancel !== 'function') {
          settleNow();
          return;
        }

        activeAnimation = anim;

        playSplash(gen);

        if (anim.finished && typeof anim.finished.catch === 'function') {
          anim.finished.catch(function () {});
        }

        anim.onfinish = function () {
          if (isDestroyed || gen !== animationGeneration) {
            return;
          }
          settleNow();
        };

        anim.oncancel = function () {
          if (isDestroyed || gen !== animationGeneration) {
            return;
          }
          activeAnimation = null;
          settleNow();
        };

        finishTimer = setTimeout(function () {
          if (isDestroyed || gen !== animationGeneration) {
            return;
          }
          settleNow();
        }, ENTRANCE_DURATION_MS + 50);
      } catch (_animErr) {
        settleNow();
      }
    }

    function cleanupProbe() {
      if (readyTimer !== null) { clearTimeout(readyTimer); readyTimer = null; }
      nodes.image.removeEventListener('load', onSvgLoaded);
      nodes.image.removeEventListener('error', handleImageError);
      if (probeImg) {
        probeImg.onload = null;
        probeImg.onerror = null;
        probeImg = null;
      }
    }

    function handleImageLoaded() {
      if (isDestroyed || isImageReady || isImageFailed || !probeReady || !svgReady) {
        return;
      }
      cleanupProbe();
      isImageReady = true;
      emptyHost.setAttribute('data-am-ready', 'true');

      if (pendingEntranceRequest) {
        pendingEntranceRequest = false;
        playEntrance(true);
      } else {
        settleNow();
      }

      if (onReady) {
        try { onReady(handle); } catch (_ignore) {}
      }

      resolveReady({
        ready: true,
        state: currentState,
        logoSrc: logoSrc
      });
    }

    function onSvgLoaded() { svgReady = true; handleImageLoaded(); }
    function onProbeLoaded() { probeReady = true; handleImageLoaded(); }

    function handleImageError() {
      if (isDestroyed || isImageReady || isImageFailed) {
        return;
      }
      cleanupProbe();
      isImageFailed = true;
      pendingEntranceRequest = false;
      clearActiveEffects();

      if (svgEl && svgEl.parentNode === emptyHost) {
        emptyHost.removeChild(svgEl);
      }
      emptyHost.setAttribute('data-am-ready', 'error');
      emptyHost.setAttribute('data-am-state', 'settled');

      var loadErr = new Error('Failed to load Atelier logo asset: ' + logoSrc);
      if (onError) {
        try {
          onError(loadErr);
        } catch (_ignore) {}
      }
      rejectReady(loadErr);
    }

    function onMediaQueryChange() {
      if (isDestroyed) {
        return;
      }
      syncReducedMotionAttr();
      if (isReducedMotionEffective()) {
        settleNow();
      }
    }

    function onVisibilityChange() {
      if (isDestroyed) {
        return;
      }
      if (isDocumentHidden() && (currentState === 'entering' || pendingEntranceRequest)) {
        settleNow();
      }
    }

    if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
      try {
        mql = (window.AtelierMotionPolicy?.query() || window.matchMedia('(prefers-reduced-motion: reduce)'));
        if (mql) {
          if (typeof mql.addEventListener === 'function') {
            mql.addEventListener('change', onMediaQueryChange);
          } else if (typeof mql.addListener === 'function') {
            mql.addListener(onMediaQueryChange);
          }
        }
      } catch (_ignore) {
        mql = null;
      }
    }

    if (typeof document !== 'undefined' && typeof document.addEventListener === 'function') {
      document.addEventListener('visibilitychange', onVisibilityChange);
    }

    if (typeof window !== 'undefined' && typeof window.IntersectionObserver === 'function') {
      try {
        intersectionObserver = new window.IntersectionObserver(function (entries) {
          if (isDestroyed) {
            return;
          }
          for (var i = 0; i < entries.length; i += 1) {
            var entry = entries[i];
            if (entry.target === emptyHost) {
              var visible = Boolean(entry.isIntersecting && entry.intersectionRatio > 0);
              isOffscreen = !visible;
              if (!visible && (currentState === 'entering' || pendingEntranceRequest)) {
                settleNow();
              }
            }
          }
        });
        intersectionObserver.observe(emptyHost);
      } catch (_ignore) {
        intersectionObserver = null;
      }
    }

    emptyHost.setAttribute('data-am-state', 'settled');
    emptyHost.setAttribute('data-am-ready', 'loading');
    syncReducedMotionAttr();
    nodes.image.addEventListener('load', onSvgLoaded);
    nodes.image.addEventListener('error', handleImageError);
    emptyHost.appendChild(svgEl);

    var handle = {
      setState: function (nextState) {
        if (isDestroyed) {
          return handle;
        }
        if (!VALID_STATES.has(nextState)) {
          throw new RangeError('Invalid state "' + String(nextState) + '". Expected "settled" or "entering".');
        }
        if (nextState === 'settled') {
          settleNow();
        } else if (nextState === 'entering') {
          playEntrance(false);
        }
        return handle;
      },

      replay: function () {
        if (isDestroyed || isImageFailed) {
          return handle;
        }
        playEntrance(true);
        return handle;
      },

      setReducedMotion: function (mode) {
        if (isDestroyed) {
          return handle;
        }
        if (!VALID_REDUCED_MOTION.has(mode)) {
          throw new RangeError('Invalid reducedMotion "' + String(mode) + '". Expected "system" or "reduce".');
        }
        reducedMotionMode = mode;
        syncReducedMotionAttr();
        if (isReducedMotionEffective()) {
          settleNow();
        }
        return handle;
      },

      destroy: function () {
        if (isDestroyed) {
          return;
        }
        isDestroyed = true;
        pendingEntranceRequest = false;
        clearActiveEffects();
        cleanupProbe();

        if (!readySettled) {
          rejectReady(new Error('AtelierMotion.logoEntrance instance destroyed before logo image loaded.'));
        }

        if (intersectionObserver) {
          try {
            intersectionObserver.disconnect();
          } catch (_ignore) {}
          intersectionObserver = null;
        }

        if (mql) {
          try {
            if (typeof mql.removeEventListener === 'function') {
              mql.removeEventListener('change', onMediaQueryChange);
            } else if (typeof mql.removeListener === 'function') {
              mql.removeListener(onMediaQueryChange);
            }
          } catch (_ignore) {}
          mql = null;
        }

        if (typeof document !== 'undefined' && typeof document.removeEventListener === 'function') {
          document.removeEventListener('visibilitychange', onVisibilityChange);
        }

        if (svgEl && svgEl.parentNode === emptyHost) {
          emptyHost.removeChild(svgEl);
        }

        emptyHost.removeAttribute('data-am-state');
        emptyHost.removeAttribute('data-am-ready');
        emptyHost.removeAttribute('data-am-reduced-motion');

        if (hadMotionAttr) {
          emptyHost.setAttribute('data-atelier-motion', priorMotionAttr);
        } else {
          emptyHost.removeAttribute('data-atelier-motion');
        }

        if (hadAriaHidden) {
          emptyHost.setAttribute('aria-hidden', priorAriaHidden);
        } else {
          emptyHost.removeAttribute('aria-hidden');
        }

        if (getMountedRecord(emptyHost) === handle) {
          deleteMountedRecord(emptyHost);
        }
      },

      getState: function () {
        return currentState;
      },

      ready: readyPromise
    };

    setMountedRecord(emptyHost, handle);

    probeImg = new Image();
    readyTimer = setTimeout(handleImageError, 8000);
    probeImg.onload = onProbeLoaded;
    probeImg.onerror = handleImageError;
    probeImg.src = logoSrc;

    if (probeImg && probeImg.complete) {
      if (probeImg.naturalWidth > 0) {
        onProbeLoaded();
      } else {
        handleImageError();
      }
    }

    return handle;
  }

  var namespace = global.AtelierMotion && typeof global.AtelierMotion === 'object'
    ? global.AtelierMotion
    : {};

  namespace.logoEntrance = {
    mount: mount
  };

  global.AtelierMotion = namespace;
})(typeof window !== 'undefined' ? window : this);
