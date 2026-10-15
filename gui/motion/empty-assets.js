/*!
 * Atelier — 06 Empty Edited-Assets Illustration Controller
 * Classic-script IIFE attaching window.AtelierMotion.emptyAssets.
 * Preserves existing window.AtelierMotion members.
 *
 * Portions of the sharp package slot motif reference Material Design Icons
 * (https://github.com/google/material-design-icons, commit 49d4db35df873165d6bd6ba09b063c7dafbac2f4),
 * licensed under the Apache License, Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0).
 */
(function (global) {
  'use strict';

  var SVG_NS = 'http://www.w3.org/2000/svg';
  var COMPONENT_ATTR = 'data-atelier-motion';
  var COMPONENT_ID = 'empty-assets';
  var STATE_ATTR = 'data-am-state';
  var REDUCED_ATTR = 'data-am-reduced-motion';

  var VALID_STATES = new Set(['settled', 'entering']);
  var VALID_REDUCED_MOTION = new Set(['system', 'reduce']);

  var activeInstances = new WeakMap();

  function isElement(node) {
    return Boolean(node && typeof node === 'object' && node.nodeType === 1);
  }

  function hasUnrelatedChildren(host) {
    for (var i = 0; i < host.childNodes.length; i++) {
      var child = host.childNodes[i];
      if (child.nodeType === 1) {
        return true;
      }
      if (child.nodeType === 3 && child.nodeValue && child.nodeValue.trim().length > 0) {
        return true;
      }
    }
    return false;
  }

  function createSvgNode(tag, attrs) {
    var el = document.createElementNS(SVG_NS, tag);
    var keys = Object.keys(attrs);
    for (var i = 0; i < keys.length; i++) {
      var k = keys[i];
      el.setAttribute(k, attrs[k]);
    }
    return el;
  }

  function buildTraySvg() {
    var svg = createSvgNode('svg', {
      'class': 'am-empty-assets-svg',
      'viewBox': '0 0 112 112',
      'width': '112',
      'height': '112',
      'fill': 'none',
      'aria-hidden': 'true',
      'focusable': 'false'
    });

    // Layer 1: Upper technical registration & datum frame guides
    var gGuides = createSvgNode('g', {
      'class': 'am-empty-assets-plane am-empty-assets-plane--guides'
    });
    var pathGuideStroke = createSvgNode('path', {
      'class': 'am-empty-assets-svg__guide-stroke',
      'd': 'M 14 32 V 20 L 18 16 H 30 M 82 16 H 94 L 98 20 V 32',
      'stroke': 'currentColor',
      'stroke-width': '1.75',
      'stroke-linecap': 'square',
      'stroke-linejoin': 'miter',
      'opacity': '0.72'
    });
    var pathGuideDatum = createSvgNode('path', {
      'class': 'am-empty-assets-svg__guide-datum',
      'd': 'M 44 16 H 68 M 56 12 V 20 M 22 23 H 34 M 78 23 H 90',
      'stroke': 'currentColor',
      'stroke-width': '1.5',
      'stroke-linecap': 'square',
      'stroke-linejoin': 'miter',
      'opacity': '0.58'
    });
    gGuides.appendChild(pathGuideStroke);
    gGuides.appendChild(pathGuideDatum);

    // Layer 2: Recessed staging deck & single subtle tonal plane
    var gDeck = createSvgNode('g', {
      'class': 'am-empty-assets-plane am-empty-assets-plane--deck'
    });
    var pathTonal = createSvgNode('path', {
      'class': 'am-empty-assets-svg__tonal',
      'd': 'M 24 30 H 88 L 94 36 V 64 H 76 L 70 70 H 42 L 36 64 H 18 V 36 Z',
      'fill': 'var(--acc, #37639d)',
      'fill-opacity': '0.1'
    });
    var pathAccentStroke = createSvgNode('path', {
      'class': 'am-empty-assets-svg__accent-stroke',
      'pathLength': '100',
      'd': 'M 18 64 V 36 L 24 30 H 88 L 94 36 V 64',
      'stroke': 'var(--acc, #37639d)',
      'stroke-width': '2',
      'stroke-linecap': 'square',
      'stroke-linejoin': 'miter'
    });
    var pathAccentSlot = createSvgNode('path', {
      'class': 'am-empty-assets-svg__accent-slot',
      'd': 'M 42 43 H 70 V 51 H 42 Z M 28 39 H 36 M 76 39 H 84 M 30 57 H 82',
      'stroke': 'var(--acc, #37639d)',
      'stroke-width': '1.75',
      'stroke-linecap': 'square',
      'stroke-linejoin': 'miter',
      'opacity': '0.88'
    });
    gDeck.appendChild(pathTonal);
    gDeck.appendChild(pathAccentStroke);
    gDeck.appendChild(pathAccentSlot);

    // Layer 3: Primary structural asset tray chassis (96px painted width: x=8..104)
    var gTray = createSvgNode('g', {
      'class': 'am-empty-assets-plane am-empty-assets-plane--tray'
    });
    var pathChassis = createSvgNode('path', {
      'class': 'am-empty-assets-svg__chassis',
      'pathLength': '100',
      'd': 'M 18 44 H 14 L 8 50 V 88 L 16 96 H 96 L 104 88 V 50 L 98 44 H 94',
      'stroke': 'currentColor',
      'stroke-width': '2.25',
      'stroke-linecap': 'square',
      'stroke-linejoin': 'miter'
    });
    var pathLip = createSvgNode('path', {
      'class': 'am-empty-assets-svg__lip',
      'd': 'M 8 64 H 36 L 42 70 H 70 L 76 64 H 104',
      'stroke': 'currentColor',
      'stroke-width': '2.25',
      'stroke-linecap': 'square',
      'stroke-linejoin': 'miter'
    });
    var pathBed = createSvgNode('path', {
      'class': 'am-empty-assets-svg__bed',
      'd': 'M 16 73 V 84 L 20 88 H 92 L 96 84 V 73 M 36 88 V 83 M 56 88 V 81 M 76 88 V 83',
      'stroke': 'currentColor',
      'stroke-width': '1.75',
      'stroke-linecap': 'square',
      'stroke-linejoin': 'miter',
      'opacity': '0.85'
    });
    gTray.appendChild(pathChassis);
    gTray.appendChild(pathLip);
    gTray.appendChild(pathBed);

    svg.appendChild(gGuides);
    svg.appendChild(gDeck);
    svg.appendChild(gTray);

    return {
      svg: svg,
      gGuides: gGuides,
      gDeck: gDeck,
      gTray: gTray,
      pathChassis: pathChassis,
      pathAccentStroke: pathAccentStroke
    };
  }

  function isHostVisibleAndInViewport(host) {
    if (!host || !host.isConnected) {
      return false;
    }
    if (typeof document !== 'undefined' && document.hidden) {
      return false;
    }
    if (typeof host.getBoundingClientRect !== 'function') {
      return true;
    }
    var rect = host.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) {
      return false;
    }
    var vw = global.innerWidth || document.documentElement.clientWidth || 0;
    var vh = global.innerHeight || document.documentElement.clientHeight || 0;
    if (vw > 0 && vh > 0) {
      if (rect.bottom <= 0 || rect.right <= 0 || rect.top >= vh || rect.left >= vw) {
        return false;
      }
    }
    return true;
  }

  function mount(emptyHost, options) {
    if (!isElement(emptyHost)) {
      throw new TypeError('AtelierMotion.emptyAssets.mount requires a valid Element host.');
    }

    var opts = options && typeof options === 'object' ? options : {};
    var initialState = opts.state !== undefined ? opts.state : 'settled';
    var initialReducedMotion = opts.reducedMotion !== undefined ? opts.reducedMotion : 'system';

    if (!VALID_STATES.has(initialState)) {
      throw new RangeError('Invalid state "' + String(initialState) + '". Expected "settled" or "entering".');
    }
    if (!VALID_REDUCED_MOTION.has(initialReducedMotion)) {
      throw new RangeError('Invalid reducedMotion "' + String(initialReducedMotion) + '". Expected "system" or "reduce".');
    }

    // A second mount on the same host destroys its prior instance first
    var existing = activeInstances.get(emptyHost);
    if (existing && typeof existing.destroy === 'function') {
      existing.destroy();
    }

    // Require an empty dedicated host (do not overwrite unrelated descendants)
    if (hasUnrelatedChildren(emptyHost)) {
      throw new Error('AtelierMotion.emptyAssets.mount requires an empty dedicated host element.');
    }

    // Remove any whitespace-only text nodes
    while (emptyHost.firstChild) {
      emptyHost.removeChild(emptyHost.firstChild);
    }

    var nodes = buildTraySvg();
    emptyHost.setAttribute(COMPONENT_ATTR, COMPONENT_ID);
    emptyHost.setAttribute(STATE_ATTR, 'settled');
    emptyHost.setAttribute(REDUCED_ATTR, initialReducedMotion);
    emptyHost.appendChild(nodes.svg);

    var destroyed = false;
    var currentState = 'settled';
    var reducedMotionMode = initialReducedMotion;
    var activeAnimations = [];
    var generation = 0;
    var intersectionObserver = null;
    var mql = null;

    function isReducedMotionActive() {
      if (reducedMotionMode === 'reduce') {
        return true;
      }
      if (mql && mql.matches) {
        return true;
      }
      if (typeof global.matchMedia === 'function') {
        try {
          return global.matchMedia('(prefers-reduced-motion: reduce)').matches;
        } catch (_err) {
          return false;
        }
      }
      return false;
    }

    function clearInlineAnimationStyles() {
      var planes = [nodes.gGuides, nodes.gDeck, nodes.gTray];
      for (var i = 0; i < planes.length; i++) {
        planes[i].style.transform = '';
        planes[i].style.opacity = '';
      }
      nodes.pathChassis.style.strokeDasharray = '';
      nodes.pathChassis.style.strokeDashoffset = '';
      nodes.pathAccentStroke.style.strokeDasharray = '';
      nodes.pathAccentStroke.style.strokeDashoffset = '';
    }

    function cancelActiveAnimations() {
      var list = activeAnimations;
      activeAnimations = [];
      for (var i = 0; i < list.length; i++) {
        try {
          list[i].cancel();
        } catch (_err) {
          // Ignore cancellation errors
        }
      }
      clearInlineAnimationStyles();
    }

    function settleImmediate() {
      if (destroyed) {
        return;
      }
      generation += 1;
      cancelActiveAnimations();
      currentState = 'settled';
      emptyHost.setAttribute(STATE_ATTR, 'settled');
    }

    function runEntrance() {
      if (destroyed) {
        return;
      }

      // Skip and settle immediately if reduced motion, hidden, disconnected, or offscreen
      if (isReducedMotionActive() || !isHostVisibleAndInViewport(emptyHost)) {
        settleImmediate();
        return;
      }

      if (typeof nodes.gTray.animate !== 'function') {
        settleImmediate();
        return;
      }

      generation += 1;
      var runGen = generation;
      cancelActiveAnimations();

      currentState = 'entering';
      emptyHost.setAttribute(STATE_ATTR, 'entering');

      var easing = 'cubic-bezier(0.2, 0, 0, 1)';
      var started = [];

      try {
        // Layer 3: Tray structural chassis (2.5px vertical alignment + subtle stroke reveal over 300ms)
        nodes.pathChassis.style.strokeDasharray = '100';
        var animTrayPlane = nodes.gTray.animate(
          [
            { transform: 'translate3d(0, 2.5px, 0)', opacity: 0.35 },
            { transform: 'translate3d(0, 0, 0)', opacity: 1 }
          ],
          { duration: 290, easing: easing, fill: 'both' }
        );
        started.push(animTrayPlane);

        var animChassisStroke = nodes.pathChassis.animate(
          [
            { strokeDashoffset: 28 },
            { strokeDashoffset: 0 }
          ],
          { duration: 300, easing: easing, fill: 'both' }
        );
        started.push(animChassisStroke);

        // Layer 2: Recessed staging deck (-3px alignment + stroke reveal over 320ms)
        nodes.pathAccentStroke.style.strokeDasharray = '100';
        var animDeckPlane = nodes.gDeck.animate(
          [
            { transform: 'translate3d(0, -3px, 0)', opacity: 0 },
            { transform: 'translate3d(0, 0, 0)', opacity: 1 }
          ],
          { duration: 320, easing: easing, fill: 'both' }
        );
        started.push(animDeckPlane);

        var animAccentStroke = nodes.pathAccentStroke.animate(
          [
            { strokeDashoffset: 36 },
            { strokeDashoffset: 0 }
          ],
          { duration: 320, easing: easing, fill: 'both' }
        );
        started.push(animAccentStroke);

        // Layer 1: Upper technical frame guides (-2px alignment over 340ms)
        var animGuidesPlane = nodes.gGuides.animate(
          [
            { transform: 'translate3d(0, -2px, 0)', opacity: 0 },
            { transform: 'translate3d(0, 0, 0)', opacity: 1 }
          ],
          { duration: 340, easing: easing, fill: 'both' }
        );
        started.push(animGuidesPlane);

        activeAnimations = started;

        var finishPromises = [];
        for (var i = 0; i < started.length; i++) {
          if (started[i] && started[i].finished && typeof started[i].finished.then === 'function') {
            finishPromises.push(started[i].finished);
          }
        }

        if (finishPromises.length > 0 && typeof Promise !== 'undefined') {
          Promise.all(finishPromises).then(
            function () {
              if (destroyed || runGen !== generation) {
                return;
              }
              settleImmediate();
            },
            function () {
              if (destroyed || runGen !== generation) {
                return;
              }
              settleImmediate();
            }
          );
        } else {
          // Fallback if Animation.finished is unsupported
          var longestAnim = started[started.length - 1];
          if (longestAnim) {
            longestAnim.onfinish = function () {
              if (!destroyed && runGen === generation) {
                settleImmediate();
              }
            };
            longestAnim.oncancel = function () {
              if (!destroyed && runGen === generation) {
                settleImmediate();
              }
            };
          } else {
            settleImmediate();
          }
        }
      } catch (_err) {
        // Missing, throwing, or partially failing WAAPI cancels started effects and leaves static artwork
        for (var j = 0; j < started.length; j++) {
          try {
            started[j].cancel();
          } catch (_cancelErr) {
            // Ignore
          }
        }
        settleImmediate();
      }
    }

    function onMediaQueryChange() {
      if (destroyed) {
        return;
      }
      if (isReducedMotionActive() && currentState === 'entering') {
        settleImmediate();
      }
    }

    function onVisibilityChange() {
      if (destroyed) {
        return;
      }
      if (typeof document !== 'undefined' && document.hidden && currentState === 'entering') {
        settleImmediate();
      }
    }

    if (typeof global.matchMedia === 'function') {
      try {
        mql = global.matchMedia('(prefers-reduced-motion: reduce)');
        if (typeof mql.addEventListener === 'function') {
          mql.addEventListener('change', onMediaQueryChange);
        } else if (typeof mql.addListener === 'function') {
          mql.addListener(onMediaQueryChange);
        }
      } catch (_err) {
        mql = null;
      }
    }

    if (typeof document !== 'undefined' && typeof document.addEventListener === 'function') {
      document.addEventListener('visibilitychange', onVisibilityChange);
    }

    if (typeof global.IntersectionObserver === 'function') {
      try {
        intersectionObserver = new global.IntersectionObserver(function (entries) {
          if (destroyed || currentState !== 'entering') {
            return;
          }
          for (var i = 0; i < entries.length; i++) {
            if (entries[i].target === emptyHost && !entries[i].isIntersecting) {
              settleImmediate();
              break;
            }
          }
        }, { threshold: 0 });
        intersectionObserver.observe(emptyHost);
      } catch (_err) {
        intersectionObserver = null;
      }
    }

    var handle = {
      setState: function (nextState) {
        if (destroyed) {
          return handle;
        }
        if (!VALID_STATES.has(nextState)) {
          throw new RangeError('Invalid state "' + String(nextState) + '". Expected "settled" or "entering".');
        }
        if (nextState === 'settled') {
          settleImmediate();
          return handle;
        }
        // Repeated identical setState('entering') calls during an active entrance must not restart it
        if (currentState === 'entering' && activeAnimations.length > 0) {
          return handle;
        }
        runEntrance();
        return handle;
      },

      replay: function () {
        if (destroyed) {
          return handle;
        }
        settleImmediate();
        runEntrance();
        return handle;
      },

      setReducedMotion: function (mode) {
        if (destroyed) {
          return handle;
        }
        if (!VALID_REDUCED_MOTION.has(mode)) {
          throw new RangeError('Invalid reducedMotion "' + String(mode) + '". Expected "system" or "reduce".');
        }
        reducedMotionMode = mode;
        emptyHost.setAttribute(REDUCED_ATTR, mode);
        if (isReducedMotionActive() && currentState === 'entering') {
          settleImmediate();
        }
        return handle;
      },

      destroy: function () {
        if (destroyed) {
          return;
        }
        destroyed = true;
        generation += 1;
        cancelActiveAnimations();

        if (intersectionObserver) {
          try {
            intersectionObserver.disconnect();
          } catch (_err) {
            // Ignore
          }
          intersectionObserver = null;
        }

        if (mql) {
          try {
            if (typeof mql.removeEventListener === 'function') {
              mql.removeEventListener('change', onMediaQueryChange);
            } else if (typeof mql.removeListener === 'function') {
              mql.removeListener(onMediaQueryChange);
            }
          } catch (_err) {
            // Ignore
          }
          mql = null;
        }

        if (typeof document !== 'undefined' && typeof document.removeEventListener === 'function') {
          document.removeEventListener('visibilitychange', onVisibilityChange);
        }

        if (nodes.svg && nodes.svg.parentNode === emptyHost) {
          emptyHost.removeChild(nodes.svg);
        }

        emptyHost.removeAttribute(COMPONENT_ATTR);
        emptyHost.removeAttribute(STATE_ATTR);
        emptyHost.removeAttribute(REDUCED_ATTR);

        if (activeInstances.get(emptyHost) === handle) {
          activeInstances.delete(emptyHost);
        }
      }
    };

    activeInstances.set(emptyHost, handle);

    if (initialState === 'entering') {
      runEntrance();
    } else {
      settleImmediate();
    }

    return handle;
  }

  var namespace = global.AtelierMotion = global.AtelierMotion || {};
  namespace.emptyAssets = {
    mount: mount
  };
})(typeof window !== 'undefined' ? window : globalThis);