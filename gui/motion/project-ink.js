/*
 * Atelier — Krackle project ink (identity v1.0)
 * Classic-script IIFE adding window.AtelierMotion.projectInk.
 *
 * Projects are portfolios (app.js draws them). This file performs their arrival and departure in
 * the picker, once each, after the real request has succeeded:
 *   form(card)             ink enters from the far edge of the screen and runs along the row's
 *                          baseline (beneath the page's content, so it never crosses text), pools
 *                          in the new card's slot, and the portfolio rises out of it: the front
 *                          panel as liquid whose wavy lip settles flat, then the back and its tab,
 *                          then the punched clasp and the Smalt drop; the artwork sheet slides up
 *                          and the name prints in two steps.
 *   snapshot(grid)         records every card before a delete;
 *   dissolve(snap, names)  plays the arrival backwards for the deleted cards (inert ghosts beneath
 *                          the already-updated list) and drains their ink along the baseline to the
 *                          nearer edge, while the surviving cards hold, then glide into the gap.
 *
 * The bleed keeps a fixed, seeded edge and is drawn every display frame, so it flows rather than
 * flickers. Liquid outlines follow the portfolio geometry and hand over to the drawn parts when they
 * settle. Full motion only; Calm, Off, reduced motion or a hidden document leave every card still.
 * A card that leaves the screen, or a picker that closes, ends the performance at once. No API or
 * storage calls.
 */
(function () {
  'use strict';

  var NS = 'http://www.w3.org/2000/svg';
  var FOOT = 236, current = null;

  function clamp(v, a, b) { return v < a ? a : v > b ? b : v; }
  function P(t) { return clamp(t, 0, 1); }
  function lerp(a, b, t) { return a + (b - a) * t; }
  function r1(v) { return Math.round(v * 10) / 10; }
  function C(x, y, r) { return r > 0.3 ? '<circle cx="' + r1(x) + '" cy="' + r1(y) + '" r="' + r1(r) + '"/>' : ''; }
  function outQ(t) { t = P(t); return 1 - Math.pow(1 - t, 3); }
  function inQ(t) { t = P(t); return t * t * t; }
  // A damped settle: liquid overshoots a little and comes to rest.
  function spring(t) { return t <= 0 ? 0 : t >= 1 ? 1 : 1 - Math.exp(-6 * t) * Math.cos(8.5 * t); }
  function noise(i) { var x = Math.sin(i * 127.1 + 311.7) * 43758.5453; return x - Math.floor(x); }
  function full() {
    if (document.documentElement.dataset.motion === 'reduce') return false;
    if (window.AtelierMotionPolicy) return window.AtelierMotionPolicy.allows(3);
    try { return !window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (_) { return true; }
  }
  function visibleRect(el) {
    if (!el || !el.isConnected || !el.getClientRects().length) return null;
    var r = el.getBoundingClientRect();
    if (r.width < 8 || r.bottom < 0 || r.right < 0 || r.top > innerHeight || r.left > innerWidth) return null;
    return r;
  }
  // One large formation at a time, but the picker is an opaque page: a stage still busy behind it
  // (the startup loader while the library indexes) must not take the picker's moment from it.
  function claim(kind, el) {
    var m = window.AtelierMotion && AtelierMotion.moment;
    var release = m && m.claim ? m.claim(kind, 2) : function () {};
    var page = el && el.closest && el.closest('#project-overlay');
    if (!release && page && page.classList.contains('active')) release = function () {};
    return release;
  }
  function pickerOpen(el) {
    var page = el && el.closest && el.closest('#project-overlay');
    return !page || page.classList.contains('active');
  }

  // ── The baseline layer: beneath the picker's content, so ink never crosses text ──
  function baseline(host, ink) {
    var svg = document.createElementNS(NS, 'svg'), id = 'am-project-run-' + Math.random().toString(36).slice(2, 8);
    svg.setAttribute('class', 'am-project-bleed');
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('focusable', 'false');
    svg.innerHTML = '<defs><filter id="' + id + '" x="-10%" y="-200%" width="120%" height="500%" color-interpolation-filters="sRGB">' +
      '<feGaussianBlur in="SourceGraphic" stdDeviation="3" result="b"/>' +
      '<feColorMatrix in="b" type="matrix" values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 20 -8"/></filter></defs>' +
      '<g filter="url(#' + id + ')"></g>';
    var g = svg.lastChild;
    g.style.fill = ink;
    var page = host && host.closest && host.closest('#project-overlay');
    if (page) page.prepend(svg); else document.body.prepend(svg);
    return {
      // A run of ink from x0 to x1 along y: thickest at its leading end (x1), beaded with a few
      // drops. The edge is seeded by position, not time, so the run grows instead of shimmering.
      draw: function (x0, x1, y, sc, thin, pool) {
        svg.setAttribute('viewBox', '0 0 ' + innerWidth + ' ' + innerHeight);
        var b = '', dir = x1 >= x0 ? 1 : -1, len = Math.abs(x1 - x0);
        if (thin > 0) {
          for (var s = 0; s <= len; s += 5) {
            var x = x0 + dir * s, u = s / Math.max(1, len), k = Math.floor(x / 5);
            var r = (2.2 + 3.6 * Math.pow(u, 0.8)) * (0.8 + 0.4 * noise(k)) * sc * thin;
            b += C(x, y + 1.2 * sc * Math.sin(x * 0.05), r);
            if (noise(k * 7) > 0.87 && u < 0.85) b += C(x, y + (noise(k * 3) > 0.5 ? 1 : -1) * (r + 3 * sc), 1.6 * sc * thin);
          }
          if (len > 1) b += C(x1, y, 6.5 * sc * thin);
        }
        if (pool && pool.k > 0) for (var p = -pool.w; p <= pool.w; p += 6) b += C(pool.x + p, y - 2 * sc, (5.5 - 3 * Math.abs(p) / Math.max(1, pool.w)) * sc * pool.k);
        g.innerHTML = b;
      },
      clear: function () { g.innerHTML = ''; },
      remove: function () { svg.remove(); }
    };
  }

  // ── A portfolio's live outlines, drawn into the card's own SVG between its parts ──
  function live(svg) {
    var part = function (sel) { return svg.querySelector(sel); };
    var back = part('.pp-back'), front = part('.pp-front'), halo = part('.pp-halo'), drop = part('.pp-drop'), punch = part('.pp-punch'), ring = part('.pp-drop-halo');
    var slots = {}, slide = part('.pp-sheet-slide');
    svg.querySelectorAll('.pp-live').forEach(function (g) { slots[g.dataset.slot] = g; });
    if (!back || !front || !halo || !drop || !punch || !ring || !slide || !slots.back || !slots.front || !slots.top) return null;
    var col = {ink: getComputedStyle(back).fill, ground: getComputedStyle(halo).fill, drop: getComputedStyle(drop).fill};
    var D = {back: back.getAttribute('d'), halo: halo.getAttribute('d'), front: front.getAttribute('d')};
    var pc = {x: +punch.getAttribute('cx'), y: +punch.getAttribute('cy'), r: +punch.getAttribute('r')};
    var dc = {x: +drop.getAttribute('cx'), y: +drop.getAttribute('cy'), r: +drop.getAttribute('r'), h: +ring.getAttribute('r')};
    // The tab stands 18 units above the back panel; the liquid follows that profile.
    function backTop(x) { return x < 88 ? 6 : x < 100 ? lerp(6, 24, (x - 88) / 12) : 24; }
    function frontTop() { return 100; }
    function liquid(h, amp, ph, top) {
      var d = 'M6 ' + FOOT;
      for (var x = 6; x <= 194; x += 6) d += 'L' + x + ' ' + r1(FOOT - (FOOT - top(x)) * h + amp * Math.sin(x * 0.075 + ph));
      return d + 'L194 ' + FOOT + 'Z';
    }
    svg.classList.add('is-live');
    slots.back.style.fill = slots.front.style.fill = col.ink;
    return {
      draw: function (s) {
        var settled = s.amp < 0.08;
        slots.back.innerHTML = s.back <= 0.002 ? '' : '<path d="' + (settled && s.back >= 0.999 ? D.back : liquid(s.back, s.amp * 0.8, s.ph, backTop)) + '"/>';
        slots.front.innerHTML = s.front <= 0.002 ? '' : settled && s.front >= 0.999
          ? '<path style="fill:' + col.ground + '" d="' + D.halo + '"/><path d="' + D.front + '"/>'
          : '<path d="' + liquid(s.front, s.amp, s.ph + 1.3, frontTop) + '"/>';
        var top = '';
        if (s.punch > 0) top += '<circle style="fill:' + col.ground + '" cx="' + pc.x + '" cy="' + pc.y + '" r="' + r1(pc.r * s.punch) + '"/>';
        if (s.drop > 0) top += '<circle style="fill:' + col.ground + '" cx="' + dc.x + '" cy="' + dc.y + '" r="' + r1(dc.h * s.drop) + '"/>';
        if (s.drop > 0 || s.dropLift) top += '<circle style="fill:' + col.drop + '" cx="' + dc.x + '" cy="' + r1(dc.y - (s.dropLift || 0)) + '" r="' + r1(dc.r * Math.max(s.drop, s.dropLift ? 1 - s.dropLift / 40 : 0)) + '"/>';
        slots.top.innerHTML = top;
        slide.style.visibility = s.sheet > 0 ? '' : 'hidden';
        slide.setAttribute('transform', 'translate(0 ' + r1(66 * (1 - s.sheet)) + ')');
      },
      end: function () {
        slots.back.innerHTML = slots.front.innerHTML = slots.top.innerHTML = '';
        slide.style.visibility = ''; slide.removeAttribute('transform');
        svg.classList.remove('is-live');
      }
    };
  }

  function frameOf(svg) {
    var r = visibleRect(svg); if (!r) return null;
    var sc = Math.min(r.width / 200, r.height / 240);
    var x = r.left + (r.width - 200 * sc) / 2, y = r.top + (r.height - 240 * sc) / 2;
    return {sc: sc, cx: x + 100 * sc, foot: y + (FOOT - 2) * sc, w: 94 * sc};
  }

  // ── Creating ──
  var RUN = 650, END = 1520;
  function form(card) {
    if (current) current.finish();
    var svg = card && card.querySelector('.proj-portfolio');
    if (!svg || !visibleRect(svg) || !full() || document.hidden) return null;
    var release = claim('new-project', card);
    if (!release) return null;
    var L = live(svg);
    if (!L) { release(); return null; }
    var run = baseline(card, getComputedStyle(svg.querySelector('.pp-back')).fill);
    card.classList.add('is-forming');
    var f0 = frameOf(svg), from = f0.cx < innerWidth / 2 ? innerWidth + 12 : -12;   // the far edge: room to read
    var t0 = performance.now(), raf = 0, done = false;
    function finish() {
      if (done) return;
      done = true;
      if (raf) cancelAnimationFrame(raf);
      L.end(); run.remove();
      card.classList.remove('is-forming', 'is-printing');
      document.removeEventListener('visibilitychange', onHidden);
      window.removeEventListener('atelier:preferences', onPolicy);
      if (current === handle) current = null;
      release();
    }
    function onHidden() { if (document.hidden) finish(); }
    function onPolicy() { if (!full()) finish(); }
    document.addEventListener('visibilitychange', onHidden);
    window.addEventListener('atelier:preferences', onPolicy);
    function frame(now) {
      raf = 0;
      if (done) return;
      var t = now - t0, f = frameOf(svg);
      if (!f || t >= END || !pickerOpen(card)) { finish(); return; }
      var len = Math.abs(f.cx - from), dir = f.cx > from ? 1 : -1;
      var head = len * outQ(t / RUN), tail = len * P((t - RUN * 0.8) / 620);
      var pool = t > RUN * 0.85 ? {x: f.cx, w: f.w * outQ((t - RUN * 0.85) / 260), k: 1 - P((t - 1100) / 300)} : null;
      if (t < 1400) run.draw(from + dir * tail, from + dir * head, f.foot, f.sc, 1 - P((t - 760) / 520), pool); else run.clear();
      L.draw({
        front: spring(P((t - RUN) / 450)), back: spring(P((t - 760) / 440)),
        amp: 7 * (1 - P((t - RUN) / 700)), ph: t * 0.012,
        punch: spring(P((t - 1080) / 220)), drop: spring(P((t - 1150) / 220)), sheet: outQ(P((t - 1150) / 250))
      });
      // The name arrives on the panel it is printed on, in two steps; the status line said it first.
      if (t >= 1350 && card.classList.contains('is-forming')) { card.classList.remove('is-forming'); card.classList.add('is-printing'); }
      if (t >= 1420) card.classList.remove('is-printing');
      raf = requestAnimationFrame(frame);
    }
    var handle = {finish: finish};
    current = handle;
    raf = requestAnimationFrame(frame);
    return handle;
  }

  // ── Deleting: the arrival, backwards ──
  var GHOST_END = 1200, MAX_GHOSTS = 6, HOLD = 700, SLIDE = 360;
  function snapshot(grid) {
    if (!grid) return null;
    var cards = {};
    grid.querySelectorAll('[data-name]').forEach(function (card) { cards[card.dataset.name] = {card: card, rect: card.getBoundingClientRect()}; });
    return {grid: grid, cards: cards};
  }
  // Survivors hold while the portfolio melts, then glide into the gap and settle.
  function glide(dx, dy, hold) {
    var h = hold / (hold + SLIDE), at = 'translate(' + dx + 'px,' + dy + 'px)';
    return [{transform: at, offset: 0}, {transform: at, offset: h, easing: 'cubic-bezier(.34, 1.3, .64, 1)'}, {transform: 'none', offset: 1}];
  }
  function dissolve(snap, names) {
    if (!snap || !names || !names.length || !snap.grid.isConnected || !full() || document.hidden) return null;
    var grid = snap.grid, release = claim('delete-project', grid);
    if (!release) return null;
    var gr = grid.getBoundingClientRect(), ghosts = [], gone = {};
    names.forEach(function (name) { gone[name] = true; });
    names.slice(0, MAX_GHOSTS).forEach(function (name, i) {
      var entry = snap.cards[name], r = entry && entry.rect;
      if (!r || r.bottom < gr.top || r.top > gr.bottom) return;
      var ghost = entry.card.cloneNode(true);
      ghost.removeAttribute('data-name');
      ghost.querySelectorAll('[id]').forEach(function (node) { node.removeAttribute('id'); });
      ghost.classList.add('am-project-ghost');
      ghost.classList.remove('sel');
      ghost.setAttribute('aria-hidden', 'true');
      ghost.inert = true;
      ghost.tabIndex = -1;
      // Beneath the live cards: the ones gliding into the gap cover what is left of it.
      Object.assign(ghost.style, {position: 'absolute', margin: '0', zIndex: '-1', pointerEvents: 'none',
        left: r1(r.left - gr.left + grid.scrollLeft) + 'px', top: r1(r.top - gr.top + grid.scrollTop) + 'px',
        width: r1(r.width) + 'px', height: r1(r.height) + 'px'});
      grid.append(ghost);
      var svg = ghost.querySelector('.proj-portfolio'), L = svg && live(svg);
      if (!L) { ghost.remove(); return; }
      var f = frameOf(svg);
      ghosts.push({el: ghost, svg: svg, L: L, delay: i * 70, body: ghost.querySelector('.proj-body'),
        to: f && f.cx < innerWidth / 2 ? -12 : innerWidth + 12,
        run: baseline(grid, getComputedStyle(svg.querySelector('.pp-back')).fill)});
    });
    var moves = [];
    grid.querySelectorAll('[data-name]').forEach(function (card) {
      var before = snap.cards[card.dataset.name]; if (!before || gone[card.dataset.name]) return;
      var now = card.getBoundingClientRect(), dx = r1(before.rect.left - now.left), dy = r1(before.rect.top - now.top);
      if (!dx && !dy) return;
      var hold = HOLD + (ghosts.length - 1) * 70;
      try { moves.push(card.animate(glide(dx, dy, hold), {duration: hold + SLIDE})); } catch (_) {}
    });
    if (!ghosts.length && !moves.length) { release(); return null; }

    var t0 = performance.now(), raf = 0, done = false;
    function finish() {
      if (done) return;
      done = true;
      if (raf) cancelAnimationFrame(raf);
      ghosts.forEach(function (gh) { gh.run.remove(); gh.el.remove(); });
      moves.forEach(function (m) { try { m.finish(); } catch (_) {} });
      document.removeEventListener('visibilitychange', onHidden);
      release();
    }
    function onHidden() { if (document.hidden) finish(); }
    document.addEventListener('visibilitychange', onHidden);
    function melt(gh, t) {
      // The name goes first, in two steps; the sheet slides back in; the drop lifts off the clasp.
      if (gh.body) gh.body.style.opacity = t < 60 ? '1' : t < 140 ? '0.5' : '0';
      var sink = 1 - inQ(P((t - 200) / 380)), sinkBack = 1 - inQ(P((t - 300) / 380));
      gh.L.draw({
        front: sink, back: sinkBack, amp: sinkBack > 0 ? 6 * P((t - 200) / 200) : 0, ph: t * 0.012,
        punch: 1 - outQ(P((t - 120) / 160)), drop: 0, dropLift: t < 240 ? 30 * outQ(P((t - 80) / 160)) + 0.01 : 0,
        sheet: 1 - outQ(P(t / 220))
      });
      // What is left pools at the foot and drains along the baseline to the nearer edge.
      var f = frameOf(gh.svg);
      if (!f) { gh.run.clear(); return; }
      var pool = t > 380 && t < 900 ? {x: f.cx, w: f.w * outQ((t - 380) / 220) * (1 - P((t - 700) / 200)), k: 1 - P((t - 760) / 200)} : null;
      var len = Math.abs(gh.to - f.cx), dir = gh.to > f.cx ? 1 : -1;
      var head = len * outQ(P((t - 650) / 450)), tail = len * inQ(P((t - 720) / 480));
      if (t < 650) gh.run.draw(f.cx, f.cx, f.foot, f.sc, 0, pool);
      else if (tail < len - 2) gh.run.draw(f.cx + dir * tail, f.cx + dir * head, f.foot, f.sc, 1 - 0.5 * P((t - 900) / 300), pool);
      else gh.run.clear();
    }
    function frame(now) {
      raf = 0;
      if (done) return;
      var t = now - t0;
      if (t >= GHOST_END + MAX_GHOSTS * 70 || !grid.isConnected || !pickerOpen(grid)) { finish(); return; }
      var playing = false;
      ghosts.forEach(function (gh) {
        var tg = t - gh.delay;
        if (tg >= GHOST_END) { gh.el.style.visibility = 'hidden'; gh.run.clear(); return; }
        playing = true;
        melt(gh, Math.max(0, tg));
      });
      if (!playing && moves.every(function (m) { return m.playState === 'finished'; })) { finish(); return; }
      raf = requestAnimationFrame(frame);
    }
    raf = requestAnimationFrame(frame);
    return {finish: finish};
  }

  window.AtelierMotion = window.AtelierMotion || {};
  window.AtelierMotion.projectInk = {form: form, snapshot: snapshot, dissolve: dissolve};
})();
