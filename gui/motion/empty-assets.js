/*!
 * Atelier — 06 Empty Edited-Assets Illustration Controller
 * Classic-script IIFE attaching window.AtelierMotion.emptyAssets.
 * Preserves existing window.AtelierMotion members.
 *
 * Krackle artwork (scripts/krackle_art.py, also empty-assets.svg): a tray of energy
 * holding a few loose bubbles, with a drop of ink waiting above it. The entrance
 * drops the bubbles in with a bounce; afterwards the illustration is still.
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

  // krackle-art:empty-assets:begin
  var SVG_INNER = '<g class="am-empty-assets-plane am-empty-assets-plane--guides"><circle class="am-empty-assets-svg__guide-dot" cx="14" cy="18" r="2.1" /><circle class="am-empty-assets-svg__guide-dot" cx="19.5" cy="18" r="1.4" /><circle class="am-empty-assets-svg__guide-dot" cx="24" cy="18" r="0.8" /><circle class="am-empty-assets-svg__guide-dot" cx="14" cy="23.5" r="1.4" /><circle class="am-empty-assets-svg__guide-dot" cx="14" cy="28" r="0.8" /><circle class="am-empty-assets-svg__guide-dot" cx="98" cy="18" r="2.1" /><circle class="am-empty-assets-svg__guide-dot" cx="92.5" cy="18" r="1.4" /><circle class="am-empty-assets-svg__guide-dot" cx="88" cy="18" r="0.8" /><circle class="am-empty-assets-svg__guide-dot" cx="98" cy="23.5" r="1.4" /><circle class="am-empty-assets-svg__guide-dot" cx="98" cy="28" r="0.8" /></g><g class="am-empty-assets-plane am-empty-assets-plane--deck"><g class="am-empty-assets-svg__drop-group"><path class="am-empty-assets-svg__drop" d="M56 14.5 C58.69 22.27 62.4 29.03 62.4 33 A6.4 6.4 0 1 1 49.6 33 C49.6 29.03 53.31 22.27 56 14.5 Z" /><circle class="am-empty-assets-svg__hole" cx="57.9" cy="34.6" r="2.1" /></g><g class="am-empty-assets-svg__bubble"><circle class="am-empty-assets-svg__charge" cx="40.5" cy="60.5" r="5.2" /><circle class="am-empty-assets-svg__hole" cx="41.8" cy="61.54" r="2.29" /></g><g class="am-empty-assets-svg__bubble"><circle class="am-empty-assets-svg__charge" cx="55" cy="57.5" r="6.6" /><circle class="am-empty-assets-svg__hole" cx="56.65" cy="58.82" r="2.9" /></g><g class="am-empty-assets-svg__bubble"><circle class="am-empty-assets-svg__charge" cx="69.5" cy="61.5" r="4.4" /><circle class="am-empty-assets-svg__hole" cx="70.6" cy="62.38" r="1.94" /></g><g class="am-empty-assets-svg__bubble"><circle class="am-empty-assets-svg__charge" cx="79" cy="64.5" r="2.6" /><circle class="am-empty-assets-svg__hole" cx="79.65" cy="65.02" r="1.14" /></g></g><g class="am-empty-assets-plane am-empty-assets-plane--tray"><path class="am-empty-assets-svg__well" d="M17 56 H95 L104 68 H8 Z" /><path class="am-empty-assets-svg__face" d="M8 68 H104 L97.5 93.5 Q97 96 94.5 96 H17.5 Q15 96 14.5 93.5 Z" /><circle class="am-empty-assets-svg__face" cx="12.5" cy="68.4" r="3" /><circle class="am-empty-assets-svg__face" cx="22" cy="68.4" r="2.4" /><circle class="am-empty-assets-svg__face" cx="32" cy="68.4" r="3.2" /><circle class="am-empty-assets-svg__face" cx="43" cy="68.4" r="2.3" /><circle class="am-empty-assets-svg__face" cx="54" cy="68.4" r="3.1" /><circle class="am-empty-assets-svg__face" cx="65" cy="68.4" r="2.4" /><circle class="am-empty-assets-svg__face" cx="76" cy="68.4" r="3.3" /><circle class="am-empty-assets-svg__face" cx="87" cy="68.4" r="2.4" /><circle class="am-empty-assets-svg__face" cx="98.5" cy="68.4" r="2.9" /><circle class="am-empty-assets-svg__hole" cx="82" cy="85" r="5" /><circle class="am-empty-assets-svg__hole" cx="75" cy="88.5" r="3.6" /><circle class="am-empty-assets-svg__hole" cx="88" cy="79" r="3" /><circle class="am-empty-assets-svg__hole" cx="76.5" cy="80" r="2.2" /><circle class="am-empty-assets-svg__hole" cx="89.5" cy="87" r="2.4" /><circle class="am-empty-assets-svg__hole" cx="66" cy="89" r="1.8" /><circle class="am-empty-assets-svg__hole" cx="70" cy="77" r="1.3" /><circle class="am-empty-assets-svg__hole" cx="58" cy="86" r="1.1" /><circle class="am-empty-assets-svg__hole" cx="93" cy="73.5" r="1" /><circle class="am-empty-assets-svg__speck" cx="80.6" cy="83.7" r="1.2" /><circle class="am-empty-assets-svg__speck" cx="74" cy="87.5" r="0.7" /></g>';
  // krackle-art:empty-assets:end

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
    // Bundled, trusted artwork; no caller data is ever inserted here.
    svg.innerHTML = SVG_INNER;
    function q(selector) { return svg.querySelector(selector); }
    return {
      svg: svg,
      gGuides: q('.am-empty-assets-plane--guides'),
      gDeck: q('.am-empty-assets-plane--deck'),
      gTray: q('.am-empty-assets-plane--tray'),
      drop: q('.am-empty-assets-svg__drop-group'),
      bubbles: Array.prototype.slice.call(svg.querySelectorAll('.am-empty-assets-svg__bubble'))
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
      var planes = [nodes.gGuides, nodes.gDeck, nodes.gTray, nodes.drop].concat(nodes.bubbles);
      for (var i = 0; i < planes.length; i++) {
        if (!planes[i]) continue;
        planes[i].style.transform = '';
        planes[i].style.opacity = '';
      }
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
        var fall = 'cubic-bezier(0.55, 0, 1, 0.45)';
        var rise = 'cubic-bezier(0, 0.55, 0.45, 1)';
        var sway = 'cubic-bezier(0.45, 0, 0.55, 1)';
        // The tray stamps up into place.
        started.push(nodes.gTray.animate(
          [
            { transform: 'translateY(4px) scale(0.96)', opacity: 0.35, easing: easing },
            { transform: 'translateY(-1px) scale(1.01)', opacity: 1, offset: 0.6, easing: sway },
            { transform: 'translateY(0) scale(1)', opacity: 1 }
          ],
          { duration: 300, easing: 'linear', fill: 'both' }
        ));
        // The registration dots fade in like a print plate.
        started.push(nodes.gGuides.animate(
          [{ opacity: 0 }, { opacity: 1 }],
          { duration: 260, easing: easing, fill: 'both' }
        ));
        // Loose bubbles drop into the tray one after another and bounce.
        for (var b = 0; b < nodes.bubbles.length; b++) {
          started.push(nodes.bubbles[b].animate(
            [
              { transform: 'translateY(-26px)', opacity: 0, offset: 0, easing: fall },
              { transform: 'translateY(0)', opacity: 1, offset: 0.5, easing: rise },
              { transform: 'translateY(-5px)', offset: 0.7, easing: fall },
              { transform: 'translateY(0)', offset: 0.86, easing: rise },
              { transform: 'translateY(-1.2px)', offset: 0.93, easing: fall },
              { transform: 'translateY(0)', opacity: 1, offset: 1 }
            ],
            { duration: 420, delay: 40 + b * 55, easing: 'linear', fill: 'both' }
          ));
        }
        // The drop swings in on its thread and hangs, waiting for the first edit.
        started.push(nodes.drop.animate(
          [
            { transform: 'translateY(-10px) scaleY(1.25)', opacity: 0, easing: easing },
            { transform: 'translateY(1.5px) scaleY(0.92)', opacity: 1, offset: 0.6, easing: sway },
            { transform: 'translateY(0) scaleY(1)', opacity: 1 }
          ],
          { duration: 360, delay: 120, easing: 'linear', fill: 'both' }
        ));

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
        mql = global.AtelierMotionPolicy?.query() || global.matchMedia('(prefers-reduced-motion: reduce)');
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
