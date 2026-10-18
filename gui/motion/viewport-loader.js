/*
 * Atelier — 3D Viewport Loader Motion Controller
 * Classic-script IIFE adding window.AtelierMotion.viewportLoader while preserving
 * existing window.AtelierMotion entries (such as exportFeedback).
 * Krackle artwork (scripts/krackle_art.py, also viewport-loader.svg): twelve dots charge
 * around a ball of energy whose bubbles boil while the model loads; an empty result
 * drains to three resting bubbles and a failure ends in a knocked-out splat.
 * Adapted from the supplied Gemini controller; Atelier adds failure and cleanup safeguards.
 */
(function () {
  'use strict';

  var VALID_STATES = new Set(['idle', 'loading', 'ready', 'empty', 'error']);

  var EASE_STANDARD = 'cubic-bezier(0.2, 0, 0, 1)';
  var EASE_TURN = 'cubic-bezier(0.42, 0, 0.58, 1)';
  var EASE_POP = 'cubic-bezier(0.34, 1.56, 0.64, 1)';
  var EASE_FALL = 'cubic-bezier(0.55, 0, 1, 0.45)';
  var EASE_RISE = 'cubic-bezier(0, 0.55, 0.45, 1)';
  var ASSEMBLY_DURATION_MS = 220;
  var LOOP_DURATION_MS = 1200;
  var SETTLE_DURATION_MS = 180;
  var EMPTY_DURATION_MS = 520;
  var SPLAT_DURATION_MS = 560;
  var DIZZY_DURATION_MS = 1300;
  var DIZZY_ORBIT = {cx: 24, cy: 8.6, rx: 6.2, ry: 1.9, turns: 1.25};

  function px(value) {
    return Math.round(value * 100) / 100 + 'px';
  }

  // Track active instances per host so duplicate mount() calls clean up the prior instance
  var mountedHosts = typeof WeakMap === 'function' ? new WeakMap() : null;

  // krackle-art:viewport-loader:begin
  var SVG_MARKUP = '<svg xmlns="http://www.w3.org/2000/svg" class="am-viewport-loader-svg" viewBox="0 0 48 48" width="72" height="72" aria-hidden="true" focusable="false" fill="currentColor"><g class="am-viewport-loader-loading"><g class="am-viewport-loader-ring"><circle class="am-viewport-loader-energy am-viewport-loader-dot" cx="24" cy="7.5" r="1.95" /><circle class="am-viewport-loader-energy am-viewport-loader-dot" cx="32.25" cy="9.71" r="1.95" /><circle class="am-viewport-loader-energy am-viewport-loader-dot" cx="38.29" cy="15.75" r="1.95" /><circle class="am-viewport-loader-energy am-viewport-loader-dot" cx="40.5" cy="24" r="1.95" /><circle class="am-viewport-loader-energy am-viewport-loader-dot" cx="38.29" cy="32.25" r="1.95" /><circle class="am-viewport-loader-energy am-viewport-loader-dot" cx="32.25" cy="38.29" r="1.95" /><circle class="am-viewport-loader-energy am-viewport-loader-dot" cx="24" cy="40.5" r="1.95" /><circle class="am-viewport-loader-energy am-viewport-loader-dot" cx="15.75" cy="38.29" r="1.95" /><circle class="am-viewport-loader-energy am-viewport-loader-dot" cx="9.71" cy="32.25" r="1.95" /><circle class="am-viewport-loader-energy am-viewport-loader-dot" cx="7.5" cy="24" r="1.95" /><circle class="am-viewport-loader-energy am-viewport-loader-dot" cx="9.71" cy="15.75" r="1.95" /><circle class="am-viewport-loader-energy am-viewport-loader-dot" cx="15.75" cy="9.71" r="1.95" /><circle class="am-viewport-loader-hole am-viewport-loader-dot-hole" cx="24" cy="7.5" r="0.95" /><circle class="am-viewport-loader-hole am-viewport-loader-dot-hole" cx="32.25" cy="9.71" r="0.95" /><circle class="am-viewport-loader-hole am-viewport-loader-dot-hole" cx="38.29" cy="15.75" r="0.95" /><circle class="am-viewport-loader-hole am-viewport-loader-dot-hole" cx="40.5" cy="24" r="0.95" /><circle class="am-viewport-loader-hole am-viewport-loader-dot-hole" cx="38.29" cy="32.25" r="0.95" /><circle class="am-viewport-loader-hole am-viewport-loader-dot-hole" cx="32.25" cy="38.29" r="0.95" /><circle class="am-viewport-loader-hole am-viewport-loader-dot-hole" cx="24" cy="40.5" r="0.95" /><circle class="am-viewport-loader-hole am-viewport-loader-dot-hole" cx="15.75" cy="38.29" r="0.95" /><circle class="am-viewport-loader-hole am-viewport-loader-dot-hole" cx="9.71" cy="32.25" r="0.95" /><circle class="am-viewport-loader-hole am-viewport-loader-dot-hole" cx="7.5" cy="24" r="0.95" /><circle class="am-viewport-loader-hole am-viewport-loader-dot-hole" cx="9.71" cy="15.75" r="0.95" /><circle class="am-viewport-loader-hole am-viewport-loader-dot-hole" cx="15.75" cy="9.71" r="0.95" /></g><g class="am-viewport-loader-sphere"><circle class="am-viewport-loader-energy am-viewport-loader-hull" cx="24" cy="24" r="8.6" /><circle class="am-viewport-loader-glint" cx="21.1" cy="20.9" r="2.4" /><circle class="am-viewport-loader-hole am-viewport-loader-boil" cx="27.4" cy="27.3" r="2.15" /><circle class="am-viewport-loader-hole am-viewport-loader-boil" cx="23.4" cy="29.6" r="1.3" /><circle class="am-viewport-loader-hole am-viewport-loader-boil" cx="29.7" cy="22.9" r="1.15" /><circle class="am-viewport-loader-hole am-viewport-loader-boil" cx="26.3" cy="23.9" r="0.8" /></g><g class="am-viewport-loader-loose"><circle class="am-viewport-loader-rift" cx="6.4" cy="9.2" r="1.55" /><circle class="am-viewport-loader-hole" cx="6.71" cy="9.43" r="0.7" /></g><g class="am-viewport-loader-loose"><circle class="am-viewport-loader-rift" cx="41.6" cy="11.6" r="1.25" /><circle class="am-viewport-loader-hole" cx="41.85" cy="11.79" r="0.56" /></g><g class="am-viewport-loader-loose"><circle class="am-viewport-loader-rift" cx="41.2" cy="39.4" r="1.45" /><circle class="am-viewport-loader-hole" cx="41.49" cy="39.62" r="0.65" /></g></g><g class="am-viewport-loader-outcome am-viewport-loader-outcome-empty"><g class="am-viewport-loader-rest"><circle class="am-viewport-loader-energy" cx="17.6" cy="39.6" r="2.6" /><circle class="am-viewport-loader-hole" cx="18.25" cy="40.12" r="1.17" /></g><g class="am-viewport-loader-rest"><circle class="am-viewport-loader-energy" cx="24.6" cy="40.6" r="1.9" /><circle class="am-viewport-loader-hole" cx="25.08" cy="40.98" r="0.85" /></g><g class="am-viewport-loader-rest"><circle class="am-viewport-loader-energy" cx="30.6" cy="39.8" r="2.25" /><circle class="am-viewport-loader-hole" cx="31.16" cy="40.25" r="1.01" /></g></g><g class="am-viewport-loader-outcome am-viewport-loader-outcome-error"><g class="am-viewport-loader-splat"><circle class="am-viewport-loader-energy" cx="24" cy="27.5" r="9.38" /><circle class="am-viewport-loader-energy" cx="17.06" cy="30.76" r="5.3" /><circle class="am-viewport-loader-energy" cx="30.53" cy="23.42" r="5.3" /><circle class="am-viewport-loader-energy" cx="28.9" cy="33.62" r="4.49" /><circle class="am-viewport-loader-energy" cx="19.92" cy="21.38" r="4.08" /><circle class="am-viewport-loader-hole" cx="24.82" cy="27.09" r="3.67" /><circle class="am-viewport-loader-hole" cx="17.88" cy="30.36" r="1.84" /><circle class="am-viewport-loader-hole" cx="28.08" cy="32.4" r="1.43" /></g><g class="am-viewport-loader-sats"><circle class="am-viewport-loader-energy am-viewport-loader-sat" cx="7.68" cy="20.16" r="2.45" /><circle class="am-viewport-loader-energy am-viewport-loader-sat" cx="41.14" cy="31.58" r="2.24" /><circle class="am-viewport-loader-energy am-viewport-loader-sat" cx="11.76" cy="41.37" r="2.04" /><circle class="am-viewport-loader-energy am-viewport-loader-sat" cx="37.46" cy="12.81" r="2.04" /><circle class="am-viewport-loader-energy am-viewport-loader-sat" cx="38.69" cy="42.19" r="1.63" /></g><g class="am-viewport-loader-drip"><path class="am-viewport-loader-drip-line" d="M18.29 34.84 V42.19" /><circle class="am-viewport-loader-energy" cx="18.29" cy="43.82" r="2.86" /></g><g class="am-viewport-loader-dizzy am-viewport-loader-dizzy-0"><circle class="am-viewport-loader-energy" cx="18.17" cy="7.95" r="1.35" /><circle class="am-viewport-loader-hole" cx="18.47" cy="8.15" r="0.55" /></g><g class="am-viewport-loader-dizzy am-viewport-loader-dizzy-1"><circle class="am-viewport-loader-energy" cx="28.75" cy="7.38" r="1.35" /><circle class="am-viewport-loader-hole" cx="29.05" cy="7.58" r="0.55" /></g><g class="am-viewport-loader-dizzy am-viewport-loader-dizzy-2"><circle class="am-viewport-loader-energy" cx="25.08" cy="10.47" r="1.35" /><circle class="am-viewport-loader-hole" cx="25.38" cy="10.67" r="0.55" /></g></g></svg>';
  // krackle-art:viewport-loader:end

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
    var releaseMoment=null,microMode=false,microHost=null,micro=null,terminalTimer=0;
    function release() {clearTimeout(terminalTimer);terminalTimer=0;if(releaseMoment)releaseMoment();releaseMoment=null;}
    function clearMicro() {micro?.destroy();micro=null;microHost?.remove();microHost=null;microMode=false;if(svgEl)svgEl.style.display='';host.removeAttribute('data-am-micro');}
    function largeAllowed() {return !motionUnavailable&&reducedPref!=='reduce'&&!Boolean(mql&&mql.matches)&&window.AtelierMotionPolicy?.allows(2)!==false&&!isDocumentHidden();}
    function synchronizeMoment(canClaim=true) {
      if(!largeAllowed()||currentState==='idle'||currentState==='ready'){release();clearMicro();return true;}
      if(!canClaim&&!releaseMoment)return true;
      if(!releaseMoment)releaseMoment=window.AtelierMotion.moment?.claim('viewport-load',2)||null;
      if(releaseMoment){clearMicro();return true;}
      cancelActiveAnimations();microMode=true;svgEl.style.display='none';host.setAttribute('data-am-micro','true');host.setAttribute('data-am-sleeping','true');
      const state=currentState==='loading'?'busy':currentState==='empty'?'info':'error';
      if(!microHost){microHost=document.createElement('span');microHost.className='am-stage-micro';host.append(microHost);try{micro=window.AtelierMotion.krackleGlyph.mount(microHost,{state});}catch(_){}}
      micro?.setState(state);return false;
    }

    var mql = null;
    try {
      if (typeof window.matchMedia === 'function') {
        mql = (window.AtelierMotionPolicy?.query() || window.matchMedia('(prefers-reduced-motion: reduce)'));
      }
    } catch (_) {}

    function isReducedMotion() {
      return motionUnavailable || reducedPref === 'reduce' || Boolean(mql && mql.matches) || window.AtelierMotionPolicy?.allows(2)===false || microMode;
    }

    function isDocumentHidden() {
      return Boolean(typeof document !== 'undefined' && document.hidden);
    }

    host.setAttribute('data-atelier-motion', 'viewport-loader');
    host.setAttribute('data-am-state', currentState);
    host.setAttribute('data-am-reduced', String(isReducedMotion()));
    host.innerHTML = SVG_MARKUP;

    function q(selector) { return host.querySelector(selector); }
    function qa(selector) { return Array.prototype.slice.call(host.querySelectorAll(selector)); }

    var svgEl = q('.am-viewport-loader-svg');
    var loadingGroup = q('.am-viewport-loader-loading');
    var ringGroup = q('.am-viewport-loader-ring');
    var sphereGroup = q('.am-viewport-loader-sphere');
    var dots = qa('.am-viewport-loader-dot');
    var dotHoles = qa('.am-viewport-loader-dot-hole');
    var boils = qa('.am-viewport-loader-boil');
    var looseBubbles = qa('.am-viewport-loader-loose');
    var restBubbles = qa('.am-viewport-loader-rest');
    var emptyGroup = q('.am-viewport-loader-outcome-empty');
    var errorGroup = q('.am-viewport-loader-outcome-error');
    var splatGroup = q('.am-viewport-loader-splat');
    var sats = qa('.am-viewport-loader-sat');
    var dripGroup = q('.am-viewport-loader-drip');
    var dizzies = qa('.am-viewport-loader-dizzy');

    var animatedNodes = [loadingGroup, ringGroup, sphereGroup, emptyGroup, errorGroup, splatGroup, dripGroup]
      .concat(dots, dotHoles, boils, looseBubbles, restBubbles, sats, dizzies);

    function centreOf(el) {
      var c = el.querySelector ? (el.querySelector('circle') || el) : el;
      return [Number(c.getAttribute('cx')), Number(c.getAttribute('cy'))];
    }

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

      // The charge travels clockwise around the ring: each dot swells and shows a bubble.
      for (var k = 0; k < dots.length; k++) {
        var timing = {
          duration: LOOP_DURATION_MS,
          delay: (k * LOOP_DURATION_MS) / dots.length,
          iterations: Infinity,
          easing: 'linear'
        };
        runAnimation(dots[k], [
          { transform: 'scale(1)', offset: 0 },
          { transform: 'scale(1.75)', offset: 0.08 },
          { transform: 'scale(1.25)', offset: 0.24 },
          { transform: 'scale(1)', offset: 0.45 },
          { transform: 'scale(1)', offset: 1 }
        ], timing);
        runAnimation(dotHoles[k], [
          { transform: 'scale(0)', offset: 0 },
          { transform: 'scale(1)', offset: 0.08 },
          { transform: 'scale(0.5)', offset: 0.24 },
          { transform: 'scale(0)', offset: 0.4 },
          { transform: 'scale(0)', offset: 1 }
        ], timing);
      }

      // The ball bobs while its bubbles boil, out of step with one another.
      runAnimation(sphereGroup, [
        { transform: 'translateY(0px) scale(1)' },
        { transform: 'translateY(-0.9px) scale(1.03)', offset: 0.5 },
        { transform: 'translateY(0px) scale(1)' }
      ], { duration: LOOP_DURATION_MS, iterations: Infinity, easing: EASE_TURN });
      for (var b = 0; b < boils.length; b++) {
        runAnimation(boils[b], [
          { transform: 'scale(1)' },
          { transform: 'scale(' + (b % 2 ? 0.45 : 1.3) + ')', offset: 0.5 },
          { transform: 'scale(1)' }
        ], { duration: LOOP_DURATION_MS * (0.75 + b * 0.18), delay: -b * 170, iterations: Infinity, easing: EASE_TURN });
      }

      // Loose bubbles drift around the edge of the stage.
      for (var l = 0; l < looseBubbles.length; l++) {
        runAnimation(looseBubbles[l], [
          { transform: 'translate(0px, 0px) scale(1)' },
          { transform: 'translate(' + (l % 2 ? -0.8 : 0.8) + 'px, -1.4px) scale(1.15)', offset: 0.5 },
          { transform: 'translate(0px, 0px) scale(1)' }
        ], { duration: LOOP_DURATION_MS * 2, delay: -l * 400, iterations: Infinity, easing: EASE_TURN });
      }
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

      // 220ms coalesce: the ring's dots gather out of the centre, then the ball swells in.
      var last = null;
      for (var k = 0; k < dots.length; k++) {
        var c = centreOf(dots[k]);
        var from = 'translate(' + px(24 - c[0]) + ', ' + px(24 - c[1]) + ') scale(0.3)';
        last = runAnimation(dots[k], [
          { transform: from, opacity: 0 },
          { transform: 'translate(0px, 0px) scale(1)', opacity: 1 }
        ], { duration: ASSEMBLY_DURATION_MS, delay: k * 6, fill: 'backwards', easing: EASE_STANDARD });
      }
      runAnimation(sphereGroup, [
        { transform: 'scale(0.4)', opacity: 0 },
        { transform: 'scale(1.08)', opacity: 1, offset: 0.7 },
        { transform: 'scale(1)', opacity: 1 }
      ], { duration: ASSEMBLY_DURATION_MS + 66, easing: EASE_STANDARD },
        function () {
          if (destroyed || generation !== myGen || currentState !== 'loading') return;
          startSteadyLoadingLoop(myGen);
        });
      if (!last && !motionUnavailable) startSteadyLoadingLoop(myGen);
    }

    function playOutcomeSettle(targetState) {
      cancelActiveAnimations();
      if (destroyed) return;

      var reduced = isReducedMotion();
      host.setAttribute('data-am-reduced', String(reduced));
      if (reduced || isDocumentHidden()) {
        return;
      }

      if (targetState === 'empty') {
        // The ball drains away and three bubbles drop to the floor and bounce.
        runAnimation(ringGroup, [
          { transform: 'scale(1)', opacity: 1 },
          { transform: 'scale(0.82)', opacity: 0.42 }
        ], { duration: SETTLE_DURATION_MS + 120, easing: EASE_STANDARD });
        for (var r = 0; r < restBubbles.length; r++) {
          var rc = centreOf(restBubbles[r]);
          var lift = 'translate(' + px(24 - rc[0]) + ', ' + px(24 - rc[1]) + ') scale(0.6)';
          runAnimation(restBubbles[r], [
            { transform: lift, opacity: 0, offset: 0 },
            { transform: lift, opacity: 1, offset: 0.12, easing: EASE_FALL },
            { transform: 'translate(0px, 0px) scale(1)', offset: 0.55, easing: EASE_RISE },
            { transform: 'translate(0px, -2.2px) scale(1)', offset: 0.72, easing: EASE_FALL },
            { transform: 'translate(0px, 0px) scale(1)', offset: 0.88, easing: EASE_RISE },
            { transform: 'translate(0px, -0.6px) scale(1)', offset: 0.94, easing: EASE_FALL },
            { transform: 'translate(0px, 0px) scale(1)', opacity: 1, offset: 1 }
          ], { duration: EMPTY_DURATION_MS, delay: r * 60, fill: 'backwards', easing: 'linear' });
        }
        return;
      }

      // Error: squeeze to a point, burst into a splat that drips, then three dazed bubbles circle.
      runAnimation(splatGroup, [
        { transform: 'scale(0.5)', opacity: 0, offset: 0 },
        { transform: 'scale(0.26)', opacity: 1, offset: 0.2 },
        { transform: 'scale(1.18)', opacity: 1, offset: 0.52 },
        { transform: 'scale(0.96)', opacity: 1, offset: 0.74 },
        { transform: 'scale(1)', opacity: 1, offset: 1 }
      ], { duration: SPLAT_DURATION_MS - 40, easing: EASE_STANDARD });
      for (var s2 = 0; s2 < sats.length; s2++) {
        var sc = centreOf(sats[s2]);
        var start = 'translate(' + px(24 - sc[0]) + ', ' + px(27.5 - sc[1]) + ') scale(0.3)';
        runAnimation(sats[s2], [
          { transform: start, opacity: 0, offset: 0 },
          { transform: start, opacity: 0, offset: 0.24 },
          { transform: 'translate(0px, 0px) scale(1.2)', opacity: 1, offset: 0.62 },
          { transform: 'translate(0px, 0px) scale(1)', opacity: 1, offset: 1 }
        ], { duration: SPLAT_DURATION_MS, easing: EASE_STANDARD });
      }
      runAnimation(dripGroup, [
        { transform: 'scaleY(0)', offset: 0 },
        { transform: 'scaleY(0)', offset: 0.45 },
        { transform: 'scaleY(1.15)', offset: 0.82 },
        { transform: 'scaleY(1)', offset: 1 }
      ], { duration: 680, easing: EASE_STANDARD });
      for (var d = 0; d < dizzies.length; d++) {
        var dc = centreOf(dizzies[d]);
        var rest = Math.atan2((dc[1] - DIZZY_ORBIT.cy) / DIZZY_ORBIT.ry, (dc[0] - DIZZY_ORBIT.cx) / DIZZY_ORBIT.rx);
        var frames = [];
        for (var i = 0; i <= 16; i++) {
          var t = i / 16;
          var angle = rest + DIZZY_ORBIT.turns * 2 * Math.PI * (1 - t) * (1 - t);
          frames.push({
            transform: 'translate(' + px(DIZZY_ORBIT.cx + Math.cos(angle) * DIZZY_ORBIT.rx - dc[0]) + ', ' +
              px(DIZZY_ORBIT.cy + Math.sin(angle) * DIZZY_ORBIT.ry - dc[1]) + ')',
            opacity: t < 0.08 ? t / 0.08 : 1,
            offset: t
          });
        }
        runAnimation(dizzies[d], frames, { duration: DIZZY_DURATION_MS, delay: 300, fill: 'backwards', easing: 'linear' });
      }
    }

    function applyState(nextState, forceReplay) {
      if (destroyed || !VALID_STATES.has(nextState)) return;
      if (!forceReplay && nextState === currentState) {
        return;
      }

      currentState = nextState;
      host.setAttribute('data-am-state', currentState);
      clearTimeout(terminalTimer);terminalTimer=0;
      if(!synchronizeMoment())return;
      host.setAttribute('data-am-reduced', String(isReducedMotion()));
      host.setAttribute('data-am-sleeping',String(isReducedMotion()||currentState==='idle'||currentState==='ready'));

      if (currentState === 'loading') {
        startLoadingSequence(true);
      } else if (currentState === 'empty' || currentState === 'error') {
        playOutcomeSettle(currentState);
        if(releaseMoment)terminalTimer=setTimeout(()=>{release();host.setAttribute('data-am-sleeping','true');},currentState==='error'?3300:1500);
      } else {
        // 'idle' or 'ready' stops immediately and releases all WAAPI effects
        cancelActiveAnimations();
      }
    }

    function handleEnvironmentChange() {
      if (destroyed) return;
      if(!synchronizeMoment(currentState==='loading'))return;
      var reduced = isReducedMotion();
      host.setAttribute('data-am-reduced', String(reduced));
      host.setAttribute('data-am-sleeping',String(reduced||isDocumentHidden()||currentState!=='loading'));

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
        release();clearMicro();
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
        host.removeAttribute('data-am-sleeping');
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
