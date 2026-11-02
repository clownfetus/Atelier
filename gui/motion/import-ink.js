/*
 * Atelier — Krackle import ink (identity v1.0)
 * Classic-script IIFE adding window.AtelierMotion.importInk.
 *
 * The Edit All dialog's stage, and the ink that joins the real asset cards, the stage
 * and the Mod tray. Application code owns the job; this file only draws what it is told:
 *   begin(sources)     a fresh import. A drop gathers on each visible asset card and travels
 *                      into the stage; the first splashes and is drawn out into the six-dot
 *                      charge ring, whose crest steps once per sixth of the beat (a count).
 *   item(ok, tray)     one asset finished. The crest pops (starburst or splat) and a finished
 *                      asset's ink leaves for the Mod tray; bursts of results coalesce.
 *   finish(kind, tray) the job's result interrupts whatever is playing: success bursts, a warning
 *                      cracks the ring and drops its chunk, failure splats and drips, and a
 *                      cancelled import settles to a still, muted drop. Kept work rides a blue
 *                      core into the Mod tray.
 * mount(host, {state, reducedMotion, shield, window}) also returns setState, replay, setReducedMotion and an
 * idempotent destroy. Drawing steps on twos: 12 fps on the stage, 24 fps in flight. Only Full
 * motion moves; Calm, Off and reduced motion show each state's final pose and nothing travels.
 * Hidden documents and hidden stages stop drawing. No API or storage calls; no text on ink:
 * flights are hidden over `shield` (the dialog) except inside `window` (the stage well).
 */
(function () {
  'use strict';

  var NS = 'http://www.w3.org/2000/svg';
  var TAU = Math.PI * 2, DEG = Math.PI / 180;
  var BEAT = 1040, STAGE_STEP = 1000 / 12, FLIGHT_STEP = 1000 / 24, SPLASH = 560;
  var SC = {x: 110, y: 110}, RING = 58;
  var serial = 0;

  function clamp(v, a, b) { return v < a ? a : v > b ? b : v; }
  function P(t) { return clamp(t, 0, 1); }
  function lerp(a, b, t) { return a + (b - a) * t; }
  function r1(v) { return Math.round(v * 10) / 10; }
  function C(x, y, r) { return r > 0.35 ? '<circle cx="' + r1(x) + '" cy="' + r1(y) + '" r="' + r1(r) + '"/>' : ''; }
  function rnd(i) { var x = Math.sin(i * 127.1 + 311.7) * 43758.5453; return x - Math.floor(x); }
  function norm(v) { var d = Math.hypot(v.x, v.y) || 1; return {x: v.x / d, y: v.y / d}; }
  function stepped(t, step) { return Math.floor(t / step) * step; }
  function cubic(x1, y1, x2, y2) {
    var cx = 3 * x1, bx = 3 * (x2 - x1) - cx, ax = 1 - cx - bx;
    var cy = 3 * y1, by = 3 * (y2 - y1) - cy, ay = 1 - cy - by;
    function sx(t) { return ((ax * t + bx) * t + cx) * t; }
    function sy(t) { return ((ay * t + by) * t + cy) * t; }
    function dx(t) { return (3 * ax * t + 2 * bx) * t + cx; }
    return function (x) {
      if (x <= 0) return 0; if (x >= 1) return 1;
      var t = x;
      for (var i = 0; i < 7; i++) { var e = sx(t) - x, d = dx(t); if (Math.abs(e) < 1e-4 || !d) break; t -= e / d; }
      return sy(clamp(t, 0, 1));
    };
  }
  // The identity's motion curves (--ease-gather, --ease-pour, --ease-pop) plus the landing shapes.
  var E = {
    gather: cubic(.55, 0, .8, .35), pour: cubic(.25, .1, .15, 1),
    outExpo: function (t) { return t >= 1 ? 1 : t <= 0 ? 0 : 1 - Math.pow(2, -10 * t); },
    inExpo: function (t) { return t <= 0 ? 0 : t >= 1 ? 1 : Math.pow(2, 10 * t - 10); },
    outBack: function (t) { t = P(t); var c1 = 1.70158, c3 = c1 + 1; return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2); },
    inOut: function (t) { t = P(t); return t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; },
    outBounce: function (t) {
      t = P(t); var n = 7.5625, d = 2.75;
      if (t < 1 / d) return n * t * t;
      if (t < 2 / d) return n * (t -= 1.5 / d) * t + .75;
      if (t < 2.5 / d) return n * (t -= 2.25 / d) * t + .9375;
      return n * (t -= 2.625 / d) * t + .984375;
    }
  };
  function burstPath(cx, cy, ro, ri, n, rot) {
    var d = '';
    for (var k = 0; k < n * 2; k++) {
      var a = (rot + k * 180 / n) * DEG, r = k % 2 ? ri : ro * (k % 4 === 2 ? 0.88 : 1);
      d += (k ? 'L' : 'M') + r1(cx + Math.cos(a) * r) + ' ' + r1(cy + Math.sin(a) * r);
    }
    return d + 'Z';
  }
  function blobPath(cx, cy, radii, rot) {
    var n = radii.length, p = radii.map(function (r, i) { var a = (rot + i * 360 / n) * DEG; return [cx + Math.cos(a) * r, cy + Math.sin(a) * r]; });
    var d = 'M' + r1(p[0][0]) + ' ' + r1(p[0][1]);
    for (var i = 0; i < n; i++) {
      var p0 = p[(i - 1 + n) % n], a = p[i], b = p[(i + 1) % n], p3 = p[(i + 2) % n];
      d += 'C' + r1(a[0] + (b[0] - p0[0]) / 6) + ' ' + r1(a[1] + (b[1] - p0[1]) / 6) + ' ' +
        r1(b[0] - (p3[0] - a[0]) / 6) + ' ' + r1(b[1] - (p3[1] - a[1]) / 6) + ' ' + r1(b[0]) + ' ' + r1(b[1]);
    }
    return d + 'Z';
  }

  // ── Screen geometry: real, visible endpoints only ──
  function visibleRect(el) {
    if (!el || !el.isConnected || !el.getClientRects().length) return null;
    var r = el.getBoundingClientRect();
    if (r.width < 4 || r.height < 4 || r.right < 0 || r.bottom < 0 || r.left > innerWidth || r.top > innerHeight) return null;
    return r;
  }
  // The edge of r that faces pt, with its outward normal and tangent.
  function facing(r, pt) {
    var cx = r.left + r.width / 2, cy = r.top + r.height / 2, dx = pt.x - cx, dy = pt.y - cy, s;
    if (Math.abs(dx) / r.width > Math.abs(dy) / r.height) {
      s = dx >= 0 ? 1 : -1;
      return {p: {x: s > 0 ? r.right : r.left, y: clamp(pt.y, r.top + Math.min(16, r.height / 2), r.bottom - Math.min(16, r.height / 2))}, n: {x: s, y: 0}, tg: {x: 0, y: 1}};
    }
    s = dy >= 0 ? 1 : -1;
    return {p: {x: clamp(pt.x, r.left + Math.min(16, r.width / 2), r.right - Math.min(16, r.width / 2)), y: s > 0 ? r.bottom : r.top}, n: {x: 0, y: s}, tg: {x: 1, y: 0}};
  }
  function curve(a, na, z, nz) {
    var dx = z.x - a.x, dy = z.y - a.y, d = Math.hypot(dx, dy) || 1, k = Math.min(170, d * 0.32);
    var px = -dy / d, py = dx / d;
    if (Math.abs(dx) >= Math.abs(dy)) { if (py > 0) { px = -px; py = -py; } } else if (px < 0) { px = -px; py = -py; }
    var L = d * 0.09;
    return [a, {x: a.x + na.x * k + px * L, y: a.y + na.y * k + py * L}, {x: z.x + nz.x * k * 0.6 + px * L, y: z.y + nz.y * k * 0.6 + py * L}, z];
  }
  function bez(p, t) {
    var u = 1 - t;
    return {x: u * u * u * p[0].x + 3 * u * u * t * p[1].x + 3 * u * t * t * p[2].x + t * t * t * p[3].x,
            y: u * u * u * p[0].y + 3 * u * u * t * p[1].y + 3 * u * t * t * p[2].y + t * t * t * p[3].y};
  }

  // WebKitGTK renders the merge filter slowly; there the circles overlap without it.
  var mergeFilter = !(/AppleWebKit/.test(navigator.userAgent) && !/Chrome|Edg/.test(navigator.userAgent));
  var MERGE = '<feGaussianBlur in="SourceGraphic" stdDeviation="4" result="b"/>' +
    '<feColorMatrix in="b" type="matrix" values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 22 -9"/>';

  function mount(host, opts) {
    if (!host || host.nodeType !== 1) throw new Error('AtelierMotion.importInk.mount requires a DOM host.');
    if (host.__atelierImportInk) host.__atelierImportInk.destroy();
    opts = opts || {};
    var uid = 'am-import-ink-' + (++serial), destroyed = false, raf = 0, sleeping = false;
    var reducedPref = opts.reducedMotion === 'reduce' ? 'reduce' : 'system';

    host.replaceChildren();
    host.setAttribute('data-atelier-motion', 'import-ink');
    var svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', '0 0 220 220');
    svg.setAttribute('class', 'am-import-ink-stage');
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('focusable', 'false');
    var boil = mergeFilter ? ' filter="url(#' + uid + '-boil)"' : '';
    svg.innerHTML = '<defs>' +
      '<filter id="' + uid + '-boil" x="-40%" y="-40%" width="180%" height="180%" color-interpolation-filters="sRGB">' +
        '<feTurbulence type="fractalNoise" baseFrequency="0.045" numOctaves="2" seed="1" result="n"/>' +
        '<feDisplacementMap in="SourceGraphic" in2="n" scale="4" xChannelSelector="R" yChannelSelector="G" result="d"/>' +
        '<feGaussianBlur in="d" stdDeviation="4.2" result="b"/>' +
        '<feColorMatrix in="b" type="matrix" values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 22 -9"/>' +
      '</filter>' +
      '<mask id="' + uid + '-mask" maskUnits="userSpaceOnUse" x="-80" y="-80" width="380" height="380">' +
        '<rect x="-80" y="-80" width="380" height="380" fill="#fff"/><g class="h" fill="#000"></g></mask>' +
      '</defs>' +
      '<g mask="url(#' + uid + '-mask)"><g class="e"' + boil + '></g><g class="r"' + boil + '></g></g>' +
      '<g class="crisp"></g><g class="rc"></g><g class="pop-ok"></g><g class="pop-fail"></g><g class="core"></g><g class="glint"></g>';
    host.append(svg);
    var g = {};
    ['e', 'r', 'h', 'crisp', 'rc', 'pop-ok', 'pop-fail', 'core', 'glint'].forEach(function (k) { g[k] = svg.querySelector('.' + k); });
    var turb = svg.querySelector('feTurbulence'), disp = svg.querySelector('feDisplacementMap');

    // Flight layer: one fixed SVG above the dialog scrim, created on first use.
    var flight = null, fl = {};
    function flightLayer() {
      if (flight) return flight;
      flight = document.createElementNS(NS, 'svg');
      flight.setAttribute('class', 'am-import-ink-flight at-identity');
      flight.setAttribute('aria-hidden', 'true');
      flight.setAttribute('focusable', 'false');
      flight.innerHTML = '<defs><filter id="' + uid + '-goo" x="-40%" y="-40%" width="180%" height="180%" color-interpolation-filters="sRGB">' + MERGE + '</filter>' +
        '<mask id="' + uid + '-fmask" maskUnits="userSpaceOnUse" x="-100" y="-100" width="10000" height="10000">' +
        '<rect x="-100" y="-100" width="10000" height="10000" fill="#fff"/><rect class="shield" fill="#000" width="0" height="0"/>' +
        '<rect class="win" fill="#fff" width="0" height="0"/><g class="h" fill="#000"></g></mask>' +
        '<mask id="' + uid + '-fshield" maskUnits="userSpaceOnUse" x="-100" y="-100" width="10000" height="10000">' +
        '<rect x="-100" y="-100" width="10000" height="10000" fill="#fff"/><rect class="shield" fill="#000" width="0" height="0"/>' +
        '<rect class="win" fill="#fff" width="0" height="0"/></mask></defs>' +
        '<g mask="url(#' + uid + '-fmask)"><g class="e"' + (mergeFilter ? ' filter="url(#' + uid + '-goo)"' : '') + '></g></g>' +
        '<g mask="url(#' + uid + '-fshield)"><g class="crisp"></g><g class="core"></g><g class="glint"></g></g>';
      ['e', 'h', 'crisp', 'core', 'glint'].forEach(function (k) { fl[k] = flight.querySelector('.' + k); });
      fl.shields = flight.querySelectorAll('.shield'); fl.wins = flight.querySelectorAll('.win');
      document.body.append(flight);
      return flight;
    }

    function full() {
      if (reducedPref === 'reduce' || document.documentElement.dataset.motion === 'reduce') return false;
      if (window.AtelierMotionPolicy) return window.AtelierMotionPolicy.allows(3);
      try { return !window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (_) { return true; }
    }
    function now() { return performance.now(); }

    // ── Stage state ──
    var stage = {mode: 'idle', kind: 'idle', freshAt: -1e9, busyAt: 0, bulges: [], pops: [], final: null, emits: [],
      coreOut: false, dirty: true, lastDrawn: -1, pendingOk: 0, lastEmit: -1e9, tray: null, awaiting: 0};
    var fx = [], flightDrawn = false;
    function ang(i) { return (-90 + i * 60) * DEG; }
    function ringPos(a, r) { r = r == null ? RING : r; return {x: SC.x + Math.cos(a) * r, y: SC.y + Math.sin(a) * r}; }
    function crestAt(t) {
      var tb = t - stage.busyAt, sd = BEAT / 6, step = Math.floor(tb / sd), ph = (tb - step * sd) / sd;
      var ci = ((step % 6) + 6) % 6, pi = (ci + 5) % 6, hop = E.outBack(P(ph / 0.42));
      var a = lerp(ang(pi), ang(pi) + Math.PI / 3, hop);
      return {a: a, p: ringPos(a), step: step, ph: ph};
    }
    function stageScreen() {
      var r = visibleRect(svg); if (!r) return null;
      return {x: r.left + r.width / 2, y: r.top + r.height / 2, s: r.width / 220, r: r};
    }
    function setHostState(kind) { stage.kind = kind; host.setAttribute('data-am-state', kind); }

    // ── Flights ──
    function addFx(f) { fx.push(f); kick(); }
    function gatherFx(el, done) {
      var t0 = now(), dur = 200;
      return {done: done, draw: function (t, b) {
        var r = visibleRect(el), sc = stageScreen(); if (!r || !sc) { this.failed = true; return false; }
        var u = P((t - t0) / dur), e = facing(r, sc);
        var rr = 10 * Math.max(0, E.outBack(u)), wob = Math.sin(u * Math.PI * 3) * 0.16 * (1 - u), spread = 18 * (1 - E.gather(u));
        for (var k = -2; k <= 2; k++) b.e += C(e.p.x + e.tg.x * k * spread / 2, e.p.y + e.tg.y * k * spread / 2, 3.6 * (1 - Math.abs(k) * 0.16) * (0.55 + 0.45 * (1 - u)));
        var dc = {x: e.p.x + e.n.x * rr * 0.95, y: e.p.y + e.n.y * rr * 0.95};
        b.e += C(e.p.x + e.n.x * rr * 0.35, e.p.y + e.n.y * rr * 0.35, rr * 0.55);
        b.e += C(dc.x + e.tg.x * rr * wob, dc.y + e.tg.y * rr * wob, rr * (1 + wob));
        b.e += C(dc.x - e.tg.x * rr * wob, dc.y - e.tg.y * rr * wob, rr * (1 - wob * 0.6));
        if (u > 0.45) b.glint += C(dc.x - rr * 0.34, dc.y - rr * 0.4, 1.8);
        return u < 1;
      }};
    }
    // A tapered stream with a bubbled head, shedding satellites; `core` carries the blue drop.
    function travelFx(from, to, o, done) {
      var t0 = now(), dur = o.dur || 380, R0 = o.r || 10, seed = Math.random() * 999, hit = false;
      var sats = [0.16, 0.3, 0.46, 0.62, 0.76].map(function (s, i) { return {s: s, off: (rnd(seed + i) - 0.5) * 30, born: null}; });
      function land() { if (!hit) { hit = true; if (o.onHit) o.onHit(); } }
      return {done: function (ok) { if (ok) land(); if (done) done(ok); }, draw: function (t, b) {
        var A = from(), Z = to(); if (!A || !Z) { this.failed = true; return false; }
        var u = P((t - t0) / dur), pts = curve(A.p, A.n, Z.p, Z.n);
        var sh = E.pour(P(u / 0.8)), st = E.pour(P((u - 0.22) / 0.78));
        if (u >= 0.8) land();
        var N = 12, head = null, prev = null;
        for (var i = 0; i < N; i++) {
          var f = i / (N - 1), p = bez(pts, lerp(st, sh, f));
          b.e += C(p.x, p.y, lerp(1.4, R0, Math.pow(f, 1.6)));
          if (i === N - 2) prev = p; if (i === N - 1) head = p;
        }
        var d = norm({x: head.x - prev.x, y: head.y - prev.y});
        if (head.x === prev.x && head.y === prev.y) d = norm({x: Z.p.x - A.p.x, y: Z.p.y - A.p.y});
        var pr = d.x >= 0 ? {x: -d.y, y: d.x} : {x: d.y, y: -d.x}, stretch = 1 + 0.5 * Math.sin(u * Math.PI);
        b.e += C(head.x - d.x * R0 * 0.7 * stretch, head.y - d.y * R0 * 0.7 * stretch, R0 * 0.78);
        b.e += C(head.x + d.x * R0 * 0.3, head.y + d.y * R0 * 0.3, R0 * 0.86);
        // Bubbles gather at the back of the head, on its shadow side.
        if (u > 0.08 && u < 0.97) {
          b.h += C(head.x + pr.x * R0 * 0.36 - d.x * R0 * 0.3, head.y + pr.y * R0 * 0.36 - d.y * R0 * 0.3, R0 * (o.core ? 0.22 : 0.3));
          if (!o.core) b.h += C(head.x + pr.x * R0 * 0.48 + d.x * R0 * 0.28, head.y + pr.y * R0 * 0.48 + d.y * R0 * 0.28, R0 * 0.15);
        }
        b.glint += C(head.x - pr.x * R0 * 0.48 + d.x * R0 * 0.12, head.y - pr.y * R0 * 0.48 + d.y * R0 * 0.12, 1.9);
        if (o.core) b.core += C(head.x + d.x * R0 * 0.18, head.y + d.y * R0 * 0.18, R0 * 0.38);
        sats.forEach(function (sa, j) {
          if (sa.born == null && sh >= sa.s) sa.born = t;
          if (sa.born == null) return;
          var age = (t - sa.born) / 260; if (age >= 1) return;
          var q = bez(pts, sa.s);
          b.crisp += C(q.x + pr.x * sa.off * (0.3 + age), q.y + pr.y * sa.off * (0.3 + age) + age * 8, (j % 2 ? 1.8 : 2.8) * (1 - age));
        });
        return u < 1;
      }};
    }
    // Landing: compress against the receiving edge, rebound once, spread a seam along its border.
    function landFx(el, core) {
      var t0 = now(), dur = 420;
      return {draw: function (t, b) {
        var r = visibleRect(el), sc = stageScreen() || {x: innerWidth / 2, y: innerHeight / 2}; if (!r) { this.failed = true; return false; }
        var tt = t - t0, e = facing(r, sc), W = r.width, H = r.height, per = 2 * (W + H), p = e.p, R0 = 10, s0, s, k;
        function at(v) {
          v = ((v % per) + per) % per;
          if (v < W) return {x: r.left + v, y: r.top}; v -= W;
          if (v < H) return {x: r.right, y: r.top + v}; v -= H;
          if (v < W) return {x: r.right - v, y: r.bottom}; v -= W;
          return {x: r.left, y: r.bottom - v};
        }
        if (Math.abs(p.y - r.top) < 1) s0 = p.x - r.left;
        else if (Math.abs(p.x - r.right) < 1) s0 = W + (p.y - r.top);
        else if (Math.abs(p.y - r.bottom) < 1) s0 = W + H + (r.right - p.x);
        else s0 = 2 * W + H + (r.bottom - p.y);
        if (tt < 100) {
          k = E.outExpo(tt / 100);
          var c = {x: p.x + e.n.x * R0 * lerp(1, 0.35, k), y: p.y + e.n.y * R0 * lerp(1, 0.35, k)};
          b.e += C(c.x, c.y, R0 * 0.85) + C(c.x + e.tg.x * R0 * 0.7 * k, c.y + e.tg.y * R0 * 0.7 * k, R0 * 0.7) + C(c.x - e.tg.x * R0 * 0.7 * k, c.y - e.tg.y * R0 * 0.7 * k, R0 * 0.7);
        } else if (tt < 380) {
          k = (tt - 100) / 280;
          var bounce = Math.sin(P(k / 0.4) * Math.PI) * 0.35, shrink = 1 - E.inOut(P((k - 0.3) / 0.7));
          b.e += C(p.x + e.n.x * R0 * (0.35 + bounce), p.y + e.n.y * R0 * (0.35 + bounce), R0 * (0.8 + bounce * 0.4) * shrink);
        }
        var prog = E.outExpo(P((tt - 50) / 260)), fade = 1 - E.inOut(P((tt - 280) / 140)), Lmax = Math.min(per * 0.3, H / 2 + W * 0.42);
        for (s = 0; s <= Lmax * prog; s += 5) {
          var rr = (3.3 * Math.pow(1 - s / Lmax, 0.6) + 0.6) * fade, a1 = at(s0 + s), a2 = at(s0 - s);
          b.e += C(a1.x, a1.y, rr) + C(a2.x, a2.y, rr);
        }
        if (tt < 280) {
          k = E.outExpo(tt / 280);
          for (var i = -1; i <= 1; i += 2) b.crisp += C(p.x + e.n.x * (6 + 26 * k) + e.tg.x * i * 12 * k, p.y + e.n.y * (6 + 26 * k) + e.tg.y * i * 12 * k + 10 * k * k, 2.4 * (1 - k));
        }
        // The blue core rides the seam the shorter way round to the top-right corner.
        if (core) {
          var target = W - 12, cw = ((target - s0) % per + per) % per, dir = cw <= per - cw ? 1 : -1, dist = Math.min(cw, per - cw);
          var kc = E.inOut(P((tt - 30) / 300));
          if (kc < 1) { var cp = at(s0 + dir * dist * kc); b.core += C(cp.x, cp.y + 3, 4.4); }
        }
        return tt < dur;
      }};
    }
    function drawFlight(t) {
      if (!fx.length) {
        if (flightDrawn) { fl.e.innerHTML = fl.h.innerHTML = fl.crisp.innerHTML = fl.core.innerHTML = fl.glint.innerHTML = ''; flightDrawn = false; }
        return false;
      }
      flightLayer();
      flight.setAttribute('viewBox', '0 0 ' + innerWidth + ' ' + innerHeight);
      for (var m = 0; m < 2; m++) { cutout(fl.shields[m], opts.shield, 14); cutout(fl.wins[m], opts.window, 10); }
      var b = {e: '', h: '', crisp: '', core: '', glint: ''}, ended = [];
      fx = fx.filter(function (f) {
        var alive = f.draw(t, b);
        if (!alive) ended.push(f);
        return alive;
      });
      fl.e.innerHTML = b.e; fl.h.innerHTML = b.h; fl.crisp.innerHTML = b.crisp; fl.core.innerHTML = b.core; fl.glint.innerHTML = b.glint;
      flightDrawn = true;
      // An endpoint that moved out of view ends its flight without landing.
      ended.forEach(function (f) { if (f.done) f.done(!f.failed); });
      return true;
    }
    // Text and controls stay clear of ink: the shield hides it, the window lets it into the well.
    function cutout(rect, el, rx) {
      var r = visibleRect(el);
      rect.setAttribute('x', r ? r1(r.left) : 0); rect.setAttribute('y', r ? r1(r.top) : 0);
      rect.setAttribute('width', r ? r1(r.width) : 0); rect.setAttribute('height', r ? r1(r.height) : 0);
      rect.setAttribute('rx', rx);
    }
    function dropFlights() {
      var pending = fx; fx = [];
      pending.forEach(function (f) { if (f.done) { try { f.done(false); } catch (_) {} } });
      drawFlight(0);
    }
    function trayEndpoint(el) {
      return function () {
        var sc = stageScreen(), r = visibleRect(el); if (!sc || !r) return null;
        var e = facing(r, sc);
        return {p: {x: e.p.x + e.n.x * 9, y: e.p.y + e.n.y * 9}, n: e.n};
      };
    }
    // Ink leaves the stage at `origin` (stage units) heading for the Mod tray.
    function emitToTray(origin, rOut, tray, core) {
      if (!visibleRect(tray)) return;
      var from = function () {
        var sc = stageScreen(), r = visibleRect(tray); if (!sc || !r) return null;
        var e = facing(r, sc), d = norm({x: e.p.x - sc.x, y: e.p.y - sc.y}), o = origin();
        return {p: {x: sc.r.left + (o.x + d.x * (rOut + 12)) * sc.s, y: sc.r.top + (o.y + d.y * (rOut + 12)) * sc.s}, n: d};
      };
      addFx(travelFx(from, trayEndpoint(tray), {core: core, dur: 360, r: core ? 10 : 7}, function (ok) {
        if (ok && full()) addFx(landFx(tray, core));
      }));
    }

    // ── Stage drawing (stage units, 220 box) ──
    var BUSY_HOLES = [[7, 7, 4], [0, 7, 3], [7, 0, 3], [-7, 7, 2.2], [7, -7, 2.2], [0, 14, 2], [14, 0, 2]];
    function drawSplash(tf, b) {
      var d = 4, k, i;
      function pud(j) { return {a: (j * 36 + 18) * DEG + rnd(j) * 0.3, d: RING * (0.7 + rnd(j + 20) * 0.26)}; }
      if (tf < 90) {
        k = E.outExpo(tf / 90);
        b.e += C(SC.x, SC.y, 25 - 4 * k) + C(SC.x - 15 * k, SC.y + 5 * k, 17) + C(SC.x + 15 * k, SC.y + 5 * k, 17);
        d = 13;
      } else if (tf < 330) {
        k = E.outExpo((tf - 60) / 270);
        for (i = 0; i < 10; i++) { var p = pud(i), dd = lerp(10, p.d, k); b.e += C(SC.x + Math.cos(p.a) * dd, SC.y + Math.sin(p.a) * dd, lerp(14, 9, k)); }
        b.e += C(SC.x, SC.y, lerp(25, 20, k));
        var v = Math.sin(P((tf - 90) / 240) * Math.PI);
        b.h += C(SC.x + 8, SC.y + 6, 7 * v) + C(SC.x - 6, SC.y + 11, 4 * v) + C(SC.x + 13, SC.y - 5, 3 * v);
        d = lerp(13, 5, k);
      } else {
        k = E.outBack(P((tf - 330) / 230));
        for (i = 0; i < 10; i++) {
          var q = pud(i), s = {x: SC.x + Math.cos(q.a) * q.d, y: SC.y + Math.sin(q.a) * q.d};
          var j = ((Math.round(((q.a / DEG) + 90) / 60) % 6) + 6) % 6, tg = ringPos(ang(j));
          b.e += C(lerp(s.x, tg.x, k), lerp(s.y, tg.y, k), lerp(9, 9.5, k));
        }
        b.e += C(SC.x, SC.y, 20);
        var cp = ringPos(ang(0)); b.e += C(cp.x, cp.y, 13.5 * P(k));
      }
      if (tf < 320) { k = E.outExpo(tf / 320); for (i = 0; i < 14; i++) { var a = i * TAU / 14, dist = lerp(28, 120, k); b.crisp += C(SC.x + Math.cos(a) * dist, SC.y + Math.sin(a) * dist, 4.6 * (1 - k)); } }
      b.glint += C(SC.x - 9, SC.y - 11, 2.6);
      b.core += C(SC.x, SC.y, 6.4 * E.outBack(P(tf / 300)));
      return d;
    }
    function drawBusy(t, b) {
      var tf = t - stage.freshAt;
      if (tf < SPLASH) return drawSplash(tf, b);
      var c = crestAt(t), bulge = 0, i;
      stage.bulges = stage.bulges.filter(function (b0) { return t - b0 < 520; });
      stage.bulges.forEach(function (b0) { var k = (t - b0) / 520; if (k >= 0) bulge += 0.5 * Math.sin(Math.min(1, k * 4) * Math.PI / 2) * (1 - k); });
      bulge = Math.min(bulge, 0.6);
      for (i = 0; i < 6; i++) { var p = ringPos(ang(i)); b.e += C(p.x, p.y, 9.5); }
      var cr = 13.5 + 2.2 * Math.sin(P(c.ph / 0.42) * Math.PI);
      b.e += C(c.p.x, c.p.y, cr);
      var rr = 21 * (1 + bulge) + 1.2 * Math.sin(t * 0.012);
      for (i = 0; i < 4; i++) { var a = i * TAU / 4 + t * 0.0016; b.e += C(SC.x + Math.cos(a) * 5.5, SC.y + Math.sin(a) * 5.5, rr * 0.78); }
      var ch = 1 - 0.7 * P(c.ph / 0.7);
      [0.38, 0.58, 0.78].forEach(function (f, j) { b.e += C(lerp(SC.x, c.p.x, f), lerp(SC.y, c.p.y, f), (j === 2 ? 6.6 : 5.6 - j * 0.6) * ch); });
      for (i = 0; i < 3; i++) { var h = BUSY_HOLES[Math.floor(rnd(c.step * 3 + i) * BUSY_HOLES.length)]; b.h += C(SC.x + h[0], SC.y + h[1], h[2] * (1 + bulge * 0.4)); }
      if (c.step % 2) b.h += C(c.p.x + 4, c.p.y + 4, 2.6);
      b.glint += C(c.p.x - cr * 0.42, c.p.y - cr * 0.44, 2.1) + C(SC.x - rr * 0.5, SC.y - rr * 0.55, 2.4);
      b.core += C(SC.x + Math.cos(t * 0.004) * 2.5, SC.y + Math.sin(t * 0.004) * 2.5, 6.4 + 0.8 * Math.sin(t * 0.02));
      return 3.5 + bulge * 16;
    }
    // The still busy pose: the charged ring with its crest at the top.
    function drawBusyStill(b) {
      for (var i = 0; i < 6; i++) { var p = ringPos(ang(i)); b.e += C(p.x, p.y, 9.5); }
      var c = ringPos(ang(0)); b.e += C(c.x, c.y, 13.5);
      b.e += C(SC.x, SC.y, 21);
      [0.38, 0.58, 0.78].forEach(function (f, j) { b.e += C(SC.x, lerp(SC.y, c.y, f), j === 2 ? 6.6 : 5.6 - j * 0.6); });
      b.h += C(SC.x + 7, SC.y + 7, 4) + C(SC.x + 14, SC.y, 2);
      b.glint += C(c.x - 5.7, c.y - 5.9, 2.1) + C(SC.x - 10.5, SC.y - 11.5, 2.4);
      b.core += C(SC.x, SC.y, 6.4);
    }
    var SPLAT = [54, 32, 50, 30, 58, 34, 48, 30, 52];
    var SATS = [[-150, 86], [-40, 92], [20, 78], [120, 96], [200, 80]];
    function drawFinal(t, b) {
      var tf = t - stage.final.t0, kind = stage.final.kind, d = 0, end = 0, k, kk, i;
      function busyRing(kr, squash) {
        for (var j = 0; j < 6; j++) { var p = ringPos(ang(j), RING * (1 - kr)); b.e += C(SC.x + (p.x - SC.x) * (1 + squash * 0.3), SC.y + (p.y - SC.y) * (1 - squash * 0.55), 9.5 * (1 - 0.3 * kr)); }
        b.e += C(SC.x, SC.y, 21 * (1 - 0.2 * kr));
      }
      if (kind === 'success') {
        end = 560;
        if (tf < 120) busyRing(E.inExpo(tf / 120), 0);
        if (tf >= 100) {
          k = E.outBack(P((tf - 100) / 260));
          b.r += '<path d="' + burstPath(SC.x, SC.y, 64 * k, 30 * k, 8, -90) + '"/>';
          kk = E.outExpo(P((tf - 100) / 340));
          for (i = 0; i < 4; i++) { var a = (45 + i * 90) * DEG, dd = lerp(34, 100, kk); b.rc += C(SC.x + Math.cos(a) * dd, SC.y + Math.sin(a) * dd, lerp(8, 3.2, kk)); }
          b.h += C(SC.x + 18, SC.y + 16, 4.2 * P((tf - 160) / 80));
          b.glint += C(SC.x - 16, SC.y - 18, 3.2 * P((tf - 140) / 80));
          d = 10 * (1 - P((tf - 100) / 320));
        }
        if (!stage.coreOut) b.core += C(SC.x, SC.y, 8);
      } else if (kind === 'warning') {
        end = 700;
        var N = 30, chunk = [9, 10, 11], cracked = tf >= 140;
        k = E.outExpo(P(tf / 140));
        for (i = 0; i < N; i++) {
          if (cracked && chunk.indexOf(i) >= 0) continue;
          var pos = ringPos(lerp(ang(Math.floor(i / 5)), (-90 + i * 12) * DEG, k));
          if (cracked) b.r += C(pos.x, pos.y, 8.2); else b.e += C(pos.x, pos.y, 8.2 + (1 - k));
        }
        if (!cracked) b.e += C(SC.x, SC.y, 21 * (1 - k));
        if (cracked) {
          var tc = tf - 140, s0 = ringPos(30 * DEG), floorY = SC.y + RING + 30;
          var y = lerp(s0.y, floorY, E.outBounce(P(tc / 480))), x = s0.x + 20 * E.outExpo(P(tc / 480)), rot = 1.1 * E.outExpo(P(tc / 480));
          chunk.forEach(function (j) {
            var q = ringPos((-90 + j * 12) * DEG), ox = q.x - s0.x, oy = q.y - s0.y;
            b.r += C(x + ox * Math.cos(rot) - oy * Math.sin(rot), y + ox * Math.sin(rot) + oy * Math.cos(rot), 8.2);
          });
          if (tc < 300) { kk = E.outExpo(tc / 300); [[-40, 30], [10, 42], [55, 28]].forEach(function (v) { var a2 = (30 + v[0]) * DEG; b.rc += C(s0.x + Math.cos(a2) * v[1] * kk, s0.y + Math.sin(a2) * v[1] * kk + 14 * kk * kk, 2.8 * (1 - kk)); }); }
          [200, 290].forEach(function (a3) { var q2 = ringPos(a3 * DEG); b.h += C(q2.x, q2.y, 2.4); });
          var gp = ringPos(-140 * DEG); b.glint += C(gp.x - 2, gp.y - 3, 2.2);
          d = 9 * (1 - P(tc / 360));
        }
        if (!stage.coreOut) b.core += C(SC.x, SC.y, 7.5);
      } else {
        end = 1080;
        if (tf < 190) { k = E.inExpo(P(tf / 180)); busyRing(k * 0.85, k); b.core += C(SC.x, SC.y, 6.4 * (1 - k)); }
        if (tf >= 170) {
          k = E.outBack(P((tf - 170) / 260));
          b.r += '<path d="' + blobPath(SC.x, SC.y, SPLAT.map(function (v) { return v * k; }), -80) + '"/>';
          var ks = E.outExpo(P((tf - 170) / 300));
          SATS.forEach(function (v, j) { b.rc += C(SC.x + Math.cos(v[0] * DEG) * lerp(26, v[1], ks), SC.y + Math.sin(v[0] * DEG) * lerp(26, v[1], ks), lerp(5.6, j % 2 ? 2.8 : 3.8, ks)); });
          if (tf >= 300) {
            var kd = E.inOut(P((tf - 300) / 700)), hy = lerp(SC.y + 30, SC.y + 92, kd);
            for (i = 0; i <= 5; i++) { var f = i / 5; b.r += C(SC.x - 6, lerp(SC.y + 30, hy, f), lerp(7, 4.4, f)); }
            b.r += C(SC.x - 6, hy + 2, 7.4);
          }
          // One substantial mass on the shadow side; a dazed bubble circles to rest.
          var vv = P((tf - 260) / 120);
          b.h += C(SC.x + 15, SC.y + 9, 9 * vv) + C(SC.x + 28, SC.y + 1, 4.6 * vv) + C(SC.x + 6, SC.y + 25, 3.8 * vv);
          if (tf >= 440) { var kz = P((tf - 440) / 620), orb = 12 * (1 - E.outExpo(kz)), a4 = (tf - 440) * 0.014; b.h += C(SC.x - 13 + Math.cos(a4) * orb, SC.y - 10 + Math.sin(a4) * orb, 4.4); }
          else b.h += C(SC.x - 13, SC.y + 2, 4.4 * P((tf - 380) / 60));
          b.glint += C(SC.x - 28, SC.y - 18, 2.6) + C(SC.x - 20, SC.y - 30, 1.6);
          d = 12 * (1 - P((tf - 170) / 520));
        }
      }
      return {disp: d, settled: tf >= end};
    }
    function drawIdle(b) {
      b.e += '<path d="M110 60C110 60 77 97 77 121C77 139 92 154 110 154C128 154 143 139 143 121C143 97 110 60 110 60Z"/>';
      b.glint += C(97, 127, 3.4);
    }
    function drawPops(t, b) {
      stage.pops = stage.pops.filter(function (p) { return t - p.t0 < 360; });
      stage.pops.forEach(function (p) {
        var tf = t - p.t0; if (tf < 0) return;
        var k = E.outBack(P(tf / 200)), fade = 1 - E.inOut(P((tf - 220) / 140)), s = k * fade, x = p.p.x, y = p.p.y, kk = E.outExpo(P(tf / 300)), i;
        if (p.ok) {
          var m = '<path d="' + burstPath(x, y, 22 * s, 10 * s, 8, -90) + '"/>';
          for (i = 0; i < 4; i++) { var a = (45 + i * 90) * DEG; m += C(x + Math.cos(a) * lerp(14, 34, kk), y + Math.sin(a) * lerp(14, 34, kk), 3 * fade); }
          b.ok += m;
        } else {
          var n = '<path d="' + blobPath(x, y, SPLAT.map(function (v) { return v * 0.34 * s; }), -80) + '"/>';
          [[-30, 30], [100, 28], [200, 34]].forEach(function (v) { n += C(x + Math.cos(v[0] * DEG) * v[1] * kk, y + Math.sin(v[0] * DEG) * v[1] * kk, 2.6 * fade); });
          b.fail += n;
        }
      });
    }
    // Ink pinches off the stage edge toward the tray, then becomes a flight.
    function drawEmits(t, b) {
      stage.emits.forEach(function (em) {
        var age = t - em.t0; if (age < 0) return;
        var sc = stageScreen(), r = visibleRect(em.tray);
        if (!sc || !r) { em.fired = true; return; }
        var e = facing(r, sc), d = norm({x: e.p.x - sc.x, y: e.p.y - sc.y}), o = em.origin(), k = P(age / 120);
        var base = {x: o.x + d.x * em.rOut, y: o.y + d.y * em.rOut};
        b.e += C(base.x + d.x * 4, base.y + d.y * 4, 5 * k) + C(base.x + d.x * (4 + 10 * E.outBack(k)), base.y + d.y * (4 + 10 * E.outBack(k)), 4 + 6 * k);
        if (age >= 120 && !em.fired) { em.fired = true; if (em.final) stage.coreOut = true; emitToTray(em.origin, em.rOut, em.tray, em.final); }
      });
      stage.emits = stage.emits.filter(function (em) { return !em.fired; });
    }
    var lastSeed = -1;
    function drawStage(t, force) {
      var moving = full(), tq = stepped(t, STAGE_STEP), live = false;
      if (!force && !stage.dirty && tq === stage.lastDrawn) return stage.live;
      var b = {e: '', r: '', h: '', crisp: '', rc: '', ok: '', fail: '', core: '', glint: ''}, d = 0;
      if (stage.mode === 'idle') drawIdle(b);
      else if (stage.mode === 'busy') {
        // Until the first ink lands, the stage holds its drop.
        if (stage.freshAt < 0) { drawIdle(b); live = moving; }
        else if (moving) { d = drawBusy(tq, b); live = true; } else drawBusyStill(b);
      } else {
        var res = drawFinal(moving ? tq : stage.final.t0 + 2000, b);
        d = moving ? res.disp : 0; stage.settled = !moving || res.settled; live = !stage.settled;
      }
      if (moving) { drawPops(tq, b); drawEmits(tq, b); } else { stage.pops = []; stage.emits = []; }
      g.e.innerHTML = b.e; g.r.innerHTML = b.r; g.h.innerHTML = b.h; g.crisp.innerHTML = b.crisp; g.rc.innerHTML = b.rc;
      g['pop-ok'].innerHTML = b.ok; g['pop-fail'].innerHTML = b.fail; g.core.innerHTML = b.core; g.glint.innerHTML = b.glint;
      // The boil re-seeds once per drawn frame, so the ink's edge steps like printed frames.
      var seed = Math.floor(tq / STAGE_STEP) % 97;
      if (moving && seed !== lastSeed) { turb.setAttribute('seed', String(seed)); lastSeed = seed; }
      disp.setAttribute('scale', String(r1(Math.max(0, d))));
      stage.dirty = false; stage.lastDrawn = tq;
      stage.live = live || stage.pops.length > 0 || stage.emits.length > 0;
      return stage.live;
    }

    // ── Item results coalesce into at most one tray flight per 320ms ──
    function pumpItems(t) {
      if (!stage.pendingOk || stage.mode !== 'busy' || t - stage.lastEmit < 320 || fx.length > 4) return;
      if (!full() || !visibleRect(stage.tray)) { stage.pendingOk = 0; return; }
      stage.pendingOk = 0; stage.lastEmit = t;
      stage.emits.push({t0: t + 60, origin: function () { return crestAt(stepped(now(), STAGE_STEP)).p; }, tray: stage.tray, rOut: 12});
    }

    // ── Clock ──
    function frame(ts) {
      raf = 0;
      if (destroyed) return;
      if (document.hidden) { sleep(); return; }
      var t = ts || now();
      if (!svg.getClientRects().length) { dropFlights(); sleep(); return; }
      pumpItems(t);
      var stageLive = drawStage(t, false);
      var flying = drawFlight(stepped(t, FLIGHT_STEP));
      if (stageLive || flying || stage.pendingOk) { wake(); raf = requestAnimationFrame(frame); }
      else sleep();
    }
    function kick() { if (!destroyed && !raf) raf = requestAnimationFrame(frame); }
    function sleep() { if (!sleeping) { sleeping = true; host.setAttribute('data-am-sleeping', 'true'); } }
    function wake() { if (sleeping) { sleeping = false; host.setAttribute('data-am-sleeping', 'false'); } }

    // ── Commands ──
    function receive() {
      if (stage.mode !== 'busy') return;
      if (stage.freshAt < 0) { stage.freshAt = now(); stage.busyAt = stage.freshAt + SPLASH; }
      else stage.bulges.push(now());
      stage.dirty = true; kick();
    }
    function begin(sources) {
      if (destroyed) return;
      var t = now(), wasBusy = stage.mode === 'busy';
      setHostState('busy');
      // Busy after busy continues the current ring rather than dropping new ink.
      if (!wasBusy) Object.assign(stage, {mode: 'busy', freshAt: -1, busyAt: t, bulges: [], pops: [], final: null, emits: [], coreOut: false, pendingOk: 0, lastEmit: -1e9, settled: false});
      stage.dirty = true;
      var list = (sources || []).filter(function (el) { return visibleRect(el); }).slice(0, 5);
      if (!full() || !list.length || wasBusy) { if (!wasBusy) receive(); kick(); return; }
      stage.awaiting = list.length;
      // The ring can't wait on ink that never lands; it charges after the longest possible trip.
      setTimeout(function () { if (!destroyed && stage.mode === 'busy' && stage.freshAt < 0) receive(); }, 900 + list.length * 85);
      list.forEach(function (el, i) {
        setTimeout(function () {
          if (destroyed || stage.mode !== 'busy') return;
          addFx(gatherFx(el, function (ok) {
            if (!ok || stage.mode !== 'busy') return;
            var from = function () { var r = visibleRect(el), sc = stageScreen(); if (!r || !sc) return null; var e = facing(r, sc); return {p: {x: e.p.x + e.n.x * 9.5, y: e.p.y + e.n.y * 9.5}, n: e.n}; };
            var to = function () { var sc = stageScreen(), a = from(); if (!sc || !a) return null; return {p: {x: sc.x, y: sc.y}, n: norm({x: a.p.x - sc.x, y: a.p.y - sc.y})}; };
            addFx(travelFx(from, to, {dur: 400, onHit: receive}));
          }));
        }, i * 85);
      });
      kick();
    }
    function item(ok, tray) {
      if (destroyed || stage.mode !== 'busy') return;
      if (tray) stage.tray = tray;
      if (!full()) return;
      var t = now();
      if (stage.freshAt >= 0 && t >= stage.busyAt && stage.pops.length < 3) {
        var c = crestAt(stepped(t, STAGE_STEP));
        stage.pops.push({ok: ok !== false, t0: t, p: c.p});
      }
      if (ok !== false) stage.pendingOk++;
      stage.dirty = true; kick();
    }
    function finish(kind, tray) {
      if (destroyed) return;
      kind = ['success', 'warning', 'error', 'cancelled'].indexOf(kind) >= 0 ? kind : 'error';
      // A real result interrupts: inbound ink and queued pops give way at once.
      dropFlights();
      stage.pops = []; stage.emits = []; stage.pendingOk = 0;
      setHostState(kind);
      if (kind === 'cancelled') { stage.mode = 'idle'; stage.final = null; stage.dirty = true; kick(); return; }
      var t = now();
      stage.mode = 'result'; stage.final = {kind: kind, t0: t}; stage.coreOut = false; stage.settled = false; stage.dirty = true;
      if (tray && kind !== 'error' && full()) stage.emits.push({t0: t + (kind === 'success' ? 330 : 560), origin: function () { return SC; }, tray: tray, rOut: kind === 'success' ? 46 : RING + 4, final: true});
      kick();
    }
    function setState(state) {
      if (state === 'busy') begin([]);
      else if (state === 'idle') { dropFlights(); setHostState('idle'); Object.assign(stage, {mode: 'idle', final: null, pops: [], emits: [], pendingOk: 0, dirty: true}); kick(); }
      else finish(state);
    }
    function onEnvironment() { stage.dirty = true; if (!full()) dropFlights(); kick(); }
    document.addEventListener('visibilitychange', onEnvironment);
    window.addEventListener('atelier:preferences', onEnvironment);
    window.addEventListener('resize', onEnvironment);

    var handle = {
      begin: begin, item: item, finish: finish, setState: setState,
      replay: function () { if (!destroyed && stage.mode === 'result') { stage.final.t0 = now(); stage.settled = false; stage.dirty = true; kick(); } },
      setReducedMotion: function (mode) { if (destroyed) return; reducedPref = mode === 'reduce' ? 'reduce' : 'system'; onEnvironment(); },
      destroy: function () {
        if (destroyed) return;
        destroyed = true;
        if (raf) cancelAnimationFrame(raf);
        raf = 0; fx = [];
        document.removeEventListener('visibilitychange', onEnvironment);
        window.removeEventListener('atelier:preferences', onEnvironment);
        window.removeEventListener('resize', onEnvironment);
        if (flight) flight.remove();
        host.replaceChildren();
        ['data-atelier-motion', 'data-am-state', 'data-am-sleeping'].forEach(function (name) { host.removeAttribute(name); });
        if (host.__atelierImportInk === handle) delete host.__atelierImportInk;
      }
    };
    host.__atelierImportInk = handle;
    setHostState('idle');
    if (opts.state && opts.state !== 'idle') setState(opts.state);
    drawStage(now(), true);
    sleep();
    return handle;
  }

  window.AtelierMotion = window.AtelierMotion || {};
  window.AtelierMotion.importInk = {mount: mount};
})();
