/*
 * Atelier — Krackle ink-well (the export review's build stage)
 *
 * A two-ink vessel whose Krackle bubbles live on their own clocks: they nucleate, grow, circulate
 * round a central void, crowd and fuse while pressure builds, split on release, and a bud pinches
 * off the void, climbs the neck and bursts at the mouth, throwing the splash. A few inner bubbles
 * carry the cooked skin's diffuse colours (setPalette), so its colours mix through the well.
 *
 * Results perform once and hold: success empties the void into a floating cluster of released
 * bubbles; warning boils over, foam crowning the lip, dripping down the neck and bubbling over
 * the sides; failure cracks the vessel from the void outwards and throws shards.
 *
 * mount(host, {size, kind, tier, state, settled, palette, reducedMotion, fixedFrame, sparse})
 * returns setState ('busy', 'success', 'warning', 'error'), setPalette, setReducedMotion, frames
 * and an idempotent destroy. fixedFrame keeps the artboard still through results, so the well
 * holds its place under something laid over it (released ink spills past the SVG instead).
 * sparse keeps a few large bubbles and drops the small ones, for a well people look at while
 * waiting rather than one that reports a build. There are
 * no API or storage calls. Calm, Off and reduced motion show each state's still pose; settled
 * results, hidden documents and off-screen hosts stop drawing; a refused moment shows the 48px
 * glyph for the state instead.
 */
(function () {
  'use strict';

  var SVG_NS = 'http://www.w3.org/2000/svg';
  var TAU = Math.PI * 2;
  var mounted = typeof WeakMap === 'function' ? new WeakMap() : null;
  var uid = 0;

  function clamp(v, a, b) { return v < a ? a : v > b ? b : v; }
  function lerp(a, b, t) { return a + (b - a) * t; }
  function sstep(e0, e1, x) { var t = clamp((x - e0) / (e1 - e0), 0, 1); return t * t * (3 - 2 * t); }
  function fract(x) { return x - Math.floor(x); }
  function hash(n) { var s = Math.sin(n * 12.9898 + 78.233) * 43758.5453; return s - Math.floor(s); }
  // One decimal is well under a pixel at stage sizes and keeps path strings short.
  function q(v) { return Math.round(v * 10) / 10; }

  // Periodic cubic Hermite curve through [phase, value, tangent?] keys. Catmull-Rom tangents let
  // motion flow through each key instead of stopping on it.
  function periodicCurve(keys) {
    var n = keys.length, P = [], V = [], M = [];
    keys.forEach(function (k) { P.push(k[0]); V.push(k[1]); });
    for (var i = 0; i < n; i++) {
      if (keys[i].length > 2) { M[i] = keys[i][2]; continue; }
      var ip = (i - 1 + n) % n, inx = (i + 1) % n, pp = P[ip], pn = P[inx];
      if (ip > i) pp -= 1;
      if (inx < i) pn += 1;
      M[i] = (V[inx] - V[ip]) / (pn - pp);
    }
    return function (phi) {
      phi = fract(phi);
      var a = n - 1;
      for (var k = 0; k < n; k++) if (P[k] > phi) { a = k - 1; break; }
      if (a < 0) a = n - 1;
      var b = (a + 1) % n, p0 = P[a], p1 = P[b], x = phi;
      if (p1 <= p0) { p1 += 1; if (x < p0) x += 1; }
      var h = p1 - p0, s = (x - p0) / h, s2 = s * s, s3 = s2 * s;
      return (2 * s3 - 3 * s2 + 1) * V[a] + (s3 - 2 * s2 + s) * h * M[a] + (-2 * s3 + 3 * s2) * V[b] + (s3 - s2) * h * M[b];
    };
  }

  function closedPath(X, Y, n) {
    var d = 'M' + q(X[0]) + ' ' + q(Y[0]);
    for (var i = 0; i < n; i++) {
      var i0 = i === 0 ? n - 1 : i - 1, i2 = i + 1 === n ? 0 : i + 1, i3 = i2 + 1 === n ? 0 : i2 + 1;
      d += 'C' + q(X[i] + (X[i2] - X[i0]) / 6) + ' ' + q(Y[i] + (Y[i2] - Y[i0]) / 6) + ' ' +
        q(X[i2] - (X[i3] - X[i]) / 6) + ' ' + q(Y[i2] - (Y[i3] - Y[i]) / 6) + ' ' + q(X[i2]) + ' ' + q(Y[i2]);
    }
    return d + 'Z';
  }
  function ellipsePath(cx, cy, rx, ry, rot) {
    var a = rot * Math.PI / 180, c = Math.cos(a), s = Math.sin(a);
    var x1 = q(cx + rx * c), y1 = q(cy + rx * s), x2 = q(cx - rx * c), y2 = q(cy - rx * s);
    var arc = 'A' + q(rx) + ' ' + q(ry) + ' ' + q(rot) + ' 1 1 ';
    return 'M' + x1 + ' ' + y1 + arc + x2 + ' ' + y2 + arc + x1 + ' ' + y1 + 'Z';
  }
  function circlePath(cx, cy, r) {
    var arc = 'A' + q(r) + ' ' + q(r) + ' 0 1 1 ';
    return 'M' + q(cx - r) + ' ' + q(cy) + arc + q(cx + r) + ' ' + q(cy) + arc + q(cx - r) + ' ' + q(cy) + 'Z';
  }

  // Analytic metaball neck between two circles (Hiroyuki Sato's construction). v is the spread:
  // 0 is a hairline about to snap, ~0.6 a fused pair.
  function metaballPath(r1, r2, x1, y1, x2, y2, v) {
    var t;
    if (r1 < r2) { t = r1; r1 = r2; r2 = t; t = x1; x1 = x2; x2 = t; t = y1; y1 = y2; y2 = t; }
    var d = Math.hypot(x2 - x1, y2 - y1);
    if (v <= 0.005 || r2 < 0.4 || d > r1 + r2 * 2.5 || d <= r1 - r2 + 0.01) return '';
    var u1 = 0, u2 = 0;
    if (d < r1 + r2) {
      u1 = Math.acos(clamp((r1 * r1 + d * d - r2 * r2) / (2 * r1 * d), -1, 1));
      u2 = Math.acos(clamp((r2 * r2 + d * d - r1 * r1) / (2 * r2 * d), -1, 1));
    }
    var ab = Math.atan2(y2 - y1, x2 - x1), spread = Math.acos(clamp((r1 - r2) / d, -1, 1)), H = Math.PI / 2;
    var a1 = ab + u1 + (spread - u1) * v, a2 = ab - u1 - (spread - u1) * v;
    var a3 = ab + Math.PI - u2 - (Math.PI - u2 - spread) * v, a4 = ab - Math.PI + u2 + (Math.PI - u2 - spread) * v;
    var p1x = x1 + Math.cos(a1) * r1, p1y = y1 + Math.sin(a1) * r1, p2x = x1 + Math.cos(a2) * r1, p2y = y1 + Math.sin(a2) * r1;
    var p3x = x2 + Math.cos(a3) * r2, p3y = y2 + Math.sin(a3) * r2, p4x = x2 + Math.cos(a4) * r2, p4y = y2 + Math.sin(a4) * r2;
    var k = Math.min(v * 2.4, Math.hypot(p3x - p1x, p3y - p1y) / (r1 + r2)) * Math.min(1, d * 2 / (r1 + r2));
    var h1 = r1 * k, h2 = r2 * k;
    return 'M' + q(p1x) + ' ' + q(p1y) +
      'C' + q(p1x + Math.cos(a1 - H) * h1) + ' ' + q(p1y + Math.sin(a1 - H) * h1) + ' ' + q(p3x + Math.cos(a3 + H) * h2) + ' ' + q(p3y + Math.sin(a3 + H) * h2) + ' ' + q(p3x) + ' ' + q(p3y) +
      'A' + q(r2) + ' ' + q(r2) + ' 0 ' + (d > r1 ? 1 : 0) + ' 0 ' + q(p4x) + ' ' + q(p4y) +
      'C' + q(p4x + Math.cos(a4 - H) * h2) + ' ' + q(p4y + Math.sin(a4 - H) * h2) + ' ' + q(p2x + Math.cos(a2 + H) * h1) + ' ' + q(p2y + Math.sin(a2 + H) * h1) + ' ' + q(p2x) + ' ' + q(p2y) + 'Z';
  }

  // A bubble breaking the surface: a waisted neck from its crown through the lip into the mouth.
  function surfaceNeckPath(bx, by, br, surfY, k) {
    if (k <= 0.01 || br <= 0.4) return '';
    var a = lerp(0.3, 1.05, k), sa = Math.sin(a), ca = Math.cos(a);
    var p1x = bx - br * sa, p2x = bx + br * sa, py = by - br * ca, w = br * lerp(0.22, 0.8, k);
    var top = surfY - 1.6, mid = lerp(py, top, 0.55), pinch = (1 - k) * 0.35;
    return 'M' + q(p1x) + ' ' + q(py) + 'C' + q(lerp(p1x, bx, pinch)) + ' ' + q(mid) + ' ' + q(bx - w) + ' ' + q(mid) + ' ' + q(bx - w) + ' ' + q(top) +
      'L' + q(bx + w) + ' ' + q(top) + 'C' + q(bx + w) + ' ' + q(mid) + ' ' + q(lerp(p2x, bx, pinch)) + ' ' + q(mid) + ' ' + q(p2x) + ' ' + q(py) + 'Z';
  }

  /* ── pressure cycle: rest → compression → release → settle ── */
  var PERIOD = 3.4;
  var C = {
    press: periodicCurve([[0, 0.03, 0], [0.12, 0.1], [0.27, 0.55], [0.4, 1, 0], [0.47, 0.6], [0.53, 0.05], [0.62, -0.1, 0], [0.76, 0, 0], [0.9, 0.025, 0]]),
    squash: periodicCurve([[0, 0, 0], [0.13, 0.07], [0.28, 0.55], [0.41, 1, 0], [0.5, 0.02], [0.575, -1, 0], [0.67, 0.3, 0], [0.78, -0.1, 0], [0.88, 0.025, 0]]),
    surge: periodicCurve([[0, 0, 0], [0.4, 0, 0], [0.47, 0.45], [0.535, 1, 0], [0.62, 0.45], [0.74, 0.08], [0.86, 0, 0]]),
    flow: periodicCurve([[0, 1], [0.2, 0.88], [0.38, 0.72, 0], [0.53, 2.5, 0], [0.64, 1.7], [0.78, 1.12], [0.92, 1]]),
    sway: periodicCurve([[0, 0, 0], [0.5, 0, 0], [0.6, 0.8, 0], [0.72, -0.45, 0], [0.84, 0.15, 0], [0.94, 0, 0]])
  };
  // Circulation runs on "flow time", the integral of the flow channel: it surges on release
  // without ever jumping.
  var FLOW = (function () {
    var N = 512, tab = new Float64Array(N + 1), acc = 0;
    for (var i = 1; i <= N; i++) { acc += C.flow((i - 0.5) / N) / N; tab[i] = acc; }
    return {tab: tab, total: acc, n: N};
  })();
  function channels(t) {
    var cyc = Math.floor(t / PERIOD), ph = t / PERIOD - cyc, fi = ph * FLOW.n, i0 = Math.floor(fi);
    var ftab = FLOW.tab[i0] + (FLOW.tab[Math.min(FLOW.n, i0 + 1)] - FLOW.tab[i0]) * (fi - i0);
    return {t: t, ph: ph, cyc: cyc, press: C.press(ph), sq: C.squash(ph), sqLag: C.squash(ph - 0.035),
      sqLag2: C.squash(ph - 0.075), surge: Math.max(0, C.surge(ph)), flowRate: C.flow(ph), sway: C.sway(ph),
      ft: PERIOD * (cyc * FLOW.total + ftab), live: true};
  }
  // A sparse well (the first-run page) keeps every other bubble of the inner ring, two neck
  // risers, no secondary pockets and only the large satellites.
  var SPARSE = {ringEvery: 2, risers: 2, micro: 0, satMinR: 6};
  var STILL = {t: 0.9, ph: 0.05, cyc: 0, press: 0, sq: 0, sqLag: 0, sqLag2: 0, surge: 0, flowRate: 1, sway: 0, ft: 0.9, live: false};

  /* ── outcomes, performed from wherever the cook was ──
   * Failure (ruptured): cracks appear, the rim and body break into slumping pieces, red ink
   *   leaks out and pools. Warning (overpressurised): the body swells and wobbles, bubbles
   *   pressurise, an amber bulge strains out of the mouth; it holds in a tense loop and never
   *   breaks. Success (clean release): the bubbles rise and gather, a clean burst leaps from the
   *   mouth and floats away, and the well settles calm.
   * `still` is the pose for Calm/Off/reduced motion and reopened results. Warning loops in Full
   * only, and holds still after `dur` so a dialog left open stops drawing. */
  var OUTCOME = {
    success: {dur: 1.6, still: 1.6, cls: 'am-ink-well-success', sound: 'pop'},
    warning: {dur: 15, still: 0.9, cls: 'am-ink-well-warn', sound: null, loop: 1.25},
    error: {dur: 1.75, still: 1.75, cls: 'am-ink-well-fault', sound: 'splat'}
  };
  var VIEW = [10, 10, 236];
  // The artboard eases out while released ink needs room, so it stays inside the stage and clear
  // of the dialog's heading; success returns to the cooking frame once calm.
  function outcomeView(name, tau) {
    if (name === 'success') return [[-18, -56, 292], sstep(0.22, 0.48, tau) * (1 - sstep(1.25, 1.6, tau))];
    if (name === 'warning') return [[-6, -28, 272], sstep(0, 0.5, tau)];
    return [[-4, 4, 262], sstep(0, 0.4, tau)];
  }
  function easeOut(x) { x = clamp(x, 0, 1); return 1 - Math.pow(1 - x, 3); }
  function jolt(x, at, amp) { x -= at; return x > 0 ? amp * Math.exp(-x * 6) * Math.sin(x * 14) : 0; }
  // The cook coasts to a stop and its pressure relaxes (warning keeps simmering at half speed
  // under rising pressure). `live` false starts from the still pose.
  function outcomeChannels(t0, tau, name, live) {
    var warn = name === 'warning', base = !live ? STILL : channels(t0 + (warn ? 0.5 * tau : 0.3 * (1 - Math.exp(-tau / 0.3))));
    var ch = {};
    for (var key in base) ch[key] = base[key];
    var calm = 1 - sstep(0, 0.4, tau), k = warn ? sstep(0, 0.6, tau) : 0, w = tau * TAU / OUTCOME.warning.loop;
    function shape(x) {
      if (name === 'error') return jolt(x, 0, 0.8) + jolt(x, 0.32, 0.6);       // the crack, then the break
      if (name === 'success') return jolt(x, 0.36, 0.45) + jolt(x, 0.44, -0.6); // a squeeze, then the release
      var kk = sstep(0, 0.6, x), ww = x * TAU / OUTCOME.warning.loop;
      return kk * (0.22 * Math.sin(ww) + 0.08 * Math.sin(ww * 2.3 + 1));         // a slow, tense wobble
    }
    ch.press = lerp(ch.press * calm, 0.9, k); ch.surge *= calm; ch.flowRate = lerp(1, ch.flowRate, calm);
    ch.sway = ch.sway * calm + k * 0.7 * Math.sin(w * 0.8 + 0.5);
    ch.sq = ch.sq * calm + shape(tau); ch.sqLag = ch.sqLag * calm + shape(tau - 0.035); ch.sqLag2 = ch.sqLag2 * calm + shape(tau - 0.075);
    ch.swell = 1 + k * (0.045 + 0.01 * Math.sin(w + 0.6));
    ch.strain = k * (0.7 + 0.3 * Math.sin(w));
    ch.outcome = name; ch.tau = tau; ch.fade = calm; ch.warnK = k; ch.warnW = w;
    return ch;
  }

  /* ── rest geometry on a 256-unit artboard ── */
  var G = {
    cx: 128, baseY: 235.5, height: 186,
    outline: [[130, 52], [161, 57.5], [160, 76], [163, 90], [184, 104], [203, 124], [211, 150], [208, 177],
      [199, 199], [192, 214], [197, 228], [187, 234], [128, 235.5], [70, 234], [61, 228], [66, 214],
      [60, 200], [50, 178], [46.5, 150], [56, 124], [76, 104], [95, 90], [99, 76], [97, 58]],
    rightChain: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
    leftChain: [23, 22, 21, 20, 19, 18, 17, 16, 15, 14, 13],
    bulge: [3, 4, 5, 6, 7, 8, 9, 15, 16, 17, 18, 19, 20, 21],
    eye: {x: 128, y: 148}, capY: 84, neckX: 129.5, riserY: 101,
    rim: {cx: 130, cy: 51.5, rx: 45, ry: 9.6, mrx: 33.5, mry: 5.6, tilt: 2.5},
    // Charge ink: the neck, the rim and a broad disc riding the upper left belly.
    charge: [[18, 26], [150, 24], [153.5, 56], [152.5, 74], [153, 88], [160, 100], [169, 114], [169, 133],
      [161, 152], [146, 169], [121, 181], [95, 182], [71, 175], [53, 164], [40, 156], [18, 152]],
    sats: [
      {x: 62.5, y: 90, rx: 13.5, ry: 12.6, rot: -10, ink: 0, ph: 0.3, f: 0.71, gap: 2.6},
      {x: 48.5, y: 113, rx: 4.2, ry: 4.4, rot: 0, ink: 0, ph: 1.7, f: 0.93, gap: 2.2},
      {x: 195, y: 108, rx: 10.5, ry: 15, rot: -24, ink: 1, ph: 2.2, f: 0.64, gap: 2.6, hl: {dx: 3.8, dy: -3.5, rx: 2.8, ry: 5.4}},
      {x: 49.5, y: 195, rx: 9.6, ry: 12.8, rot: 14, ink: 1, ph: 3.1, f: 0.77, gap: 2.6, hl: {dx: -2.4, dy: -3.6, rx: 2.5, ry: 4.8}},
      {x: 202, y: 200, rx: 9.6, ry: 11.6, rot: -14, ink: 1, ph: 4.4, f: 0.69, gap: 2.6},
      {x: 213, y: 180, rx: 2.9, ry: 2.9, rot: 0, ink: 1, ph: 5, f: 0.88, gap: 2}
    ],
    crown: [
      {dx: -9, vx: -34, h: 26, r: 4.8, ink: 0, p0: 0.598}, {dx: 10, vx: 40, h: 31, r: 5.4, ink: 1, p0: 0.604},
      {dx: -3, vx: -13, h: 39, r: 2.4, ink: 0, p0: 0.612}, {dx: 5, vx: 25, h: 20, r: 2.3, ink: 1, p0: 0.618}
    ]
  };
  // Bubble lanes conform to the cavity: inner ring hugs the void, the outer lane hugs the walls.
  var L = {
    eyeR: 27.5, innerGap: 13.5, outerGap: 6.5, web: 2.6, webPress: 1.2, margin: 3, budR: 8.5,
    fuseP: 0.09, eyeFuseP: 0.12, flatMinR: 2.6, wallBulge: 0.2,
    lanes: [
      {n: 12, psi: 0, jitterP: 0, rMin: 8.6, rMax: 12.2, omega: 0.42, lifeMin: 8, lifeMax: 13, grow: 0.16, mergeP: 0.24, theta0: 0.2, activeMin: 0.92},
      {n: 18, psi: 0.44, jitterP: 0.1, rMin: 5.8, rMax: 9.2, omega: 0.27, lifeMin: 5, lifeMax: 9, grow: 0.2, mergeP: 0.2, theta0: 1.1},
      {n: 25, psi: 0.95, jitterP: 0.06, rMin: 3, rMax: 5.8, omega: 0.17, lifeMin: 3, lifeMax: 6, grow: 0.26, mergeP: 0.12, theta0: 2.3, activeMin: 0.8}
    ],
    risers: {n: 4, rMin: 2.4, rMax: 4.6, pMin: 3, pMax: 4.4, spread: 15},
    micro: {n: 12, neck: 3, rMin: 1.2, rMax: 2.2},
    // Inner-ring slots that carry the skin's colours, spaced round the void.
    tintSlots: [1, 7, 4, 10]
  };
  var WALL_DIST = (function () {
    var pts = G.outline, n = pts.length, PX = [], PY = [];
    function cr(a, b, c, d, u) { var u2 = u * u, u3 = u2 * u; return 0.5 * (2 * b + (-a + c) * u + (2 * a - 5 * b + 4 * c - d) * u2 + (-a + 3 * b - 3 * c + d) * u3); }
    for (var i = 0; i < n; i++) {
      var p0 = pts[(i - 1 + n) % n], p1 = pts[i], p2 = pts[(i + 1) % n], p3 = pts[(i + 2) % n];
      for (var s = 0; s < 8; s++) { PX.push(cr(p0[0], p1[0], p2[0], p3[0], s / 8)); PY.push(Math.max(G.capY, cr(p0[1], p1[1], p2[1], p3[1], s / 8))); }
    }
    var N = 96, raw = new Float64Array(N), out = new Float64Array(N);
    for (var k = 0; k < N; k++) {
      var dx = Math.cos(k / N * TAU), dy = Math.sin(k / N * TAU), best = 200;
      for (var j = 0; j < PX.length; j++) {
        var jn = (j + 1) % PX.length, ax = PX[j] - G.eye.x, ay = PY[j] - G.eye.y, ex = PX[jn] - PX[j], ey = PY[jn] - PY[j];
        var den = dx * ey - dy * ex;
        if (Math.abs(den) < 1e-9) continue;
        var tr = (ax * ey - ay * ex) / den, ss = (ax * dy - ay * dx) / den;
        if (tr > 0 && ss >= 0 && ss <= 1 && tr < best) best = tr;
      }
      raw[k] = best;
    }
    for (k = 0; k < N; k++) { var sum = 0; for (var o = -3; o <= 3; o++) sum += raw[(k + o + N) % N]; out[k] = sum / 7; }
    return out;
  })();
  function wallDistAt(theta) {
    var N = WALL_DIST.length, f = fract(theta / TAU) * N, i = Math.floor(f), t = f - i;
    return WALL_DIST[i % N] * (1 - t) + WALL_DIST[(i + 1) % N] * t;
  }

  // Failure: seven cracks run from the void's centre out past the walls (the last straight up
  // the neck and through the rim). Between them lie the wedges the vessel breaks into: each
  // piece drifts out, the neck and shoulders slump and tip.
  var FRACTURE = (function () {
    var ex = G.eye.x, ey = G.eye.y, cracks = [], wedges = [];
    [-25, 30, 80, 128, 175, 215, 268].forEach(function (deg, i) {
      var a = deg * Math.PI / 180, dx = Math.cos(a), dy = Math.sin(a), pts = [[ex, ey]];
      for (var k = 1; k <= 10; k++) {
        var rr = 170 * k / 10, j = k === 10 ? 0 : (hash(i * 7.3 + k * 1.7) - 0.5) * (k < 2 ? 3 : 10);
        pts.push([ex + dx * rr - dy * j, ey + dy * rr + dx * j]);
      }
      var wall = wallDistAt(a);
      cracks.push({a: a, pts: pts, delay: 0.02 * i, dir: [dx, dy], exit: [ex + dx * wall, ey + dy * wall]});
    });
    cracks.forEach(function (A, i) {
      var B = cracks[(i + 1) % cracks.length], a0 = A.a, a1 = B.a < a0 ? B.a + TAU : B.a, mid = (a0 + a1) / 2;
      var d = 'M' + A.pts.map(function (p) { return q(p[0]) + ' ' + q(p[1]); }).join('L');
      for (var s = 1; s < 4; s++) { var aa = lerp(a0, a1, s / 4); d += 'L' + q(ex + Math.cos(aa) * 260) + ' ' + q(ey + Math.sin(aa) * 260); }
      d += 'L' + B.pts.slice().reverse().map(function (p) { return q(p[0]) + ' ' + q(p[1]); }).join('L') + 'Z';
      var mx = Math.cos(mid), my = Math.sin(mid), up = my < -0.35;
      wedges.push({d: d, mx: mx, my: my, cx: ex + mx * 55, cy: ey + my * 55, delay: 0.3 + 0.025 * i,
        sep: 6 + 5 * hash(i * 3.1), drop: up ? 14 + 8 * hash(i * 1.9) : 0,
        rot: (up ? 16 : 5) * (mx > 0 ? 1 : -1) * (0.6 + 0.4 * hash(i * 5.7))});
    });
    return {cracks: cracks, wedges: wedges};
  })();
  // Red ink leaks from the low cracks [crack, width, delay], runs down to the ground and pools
  // [crack, puddle radius]; drops splash out and land [crack, vx, vy, radius, delay].
  var LEAKS = [[1, 7, 0.52], [3, 8.5, 0.58], [2, 6, 0.66]];
  var POOLS = [[1, 24], [3, 28], [2, 18]];
  var SPLASH = [[0, 48, -150, 3.6, 0.36], [0, 28, -190, 2.4, 0.4], [1, 58, -90, 3, 0.42], [6, 40, -170, 2.8, 0.38],
    [5, -42, -130, 3.2, 0.4], [4, -55, -70, 2.6, 0.46], [3, -25, -60, 2.2, 0.5]];
  // Success: a clean burst. Tendrils leap from the mouth and curl outward [angle from vertical,
  // length, base width, tip radius, start], their tips break into drops, and a spray of small
  // bubbles rides out with them [dx, dy, radius, start]; all of it floats up and dissipates.
  var BURST = [[-62, 48, 9.5, 6, 0.42], [-28, 66, 11.5, 7.2, 0.39], [-2, 80, 12.5, 8, 0.37], [26, 64, 11, 7, 0.4], [60, 50, 9.5, 5.8, 0.43]];
  var SPRAY = [[-22, -40, 3, 0.45], [22, -46, 3.4, 0.48], [-38, -24, 2.4, 0.5], [38, -28, 2.6, 0.47], [6, -64, 2.6, 0.5], [-8, -30, 2, 0.52]];
  // A tapered crack ribbon grown to `g`, sharp at its running tip.
  function ribbon(P, w0, g) {
    if (g <= 0.01) return '';
    var lens = [0], total = 0, i;
    for (i = 1; i < P.length; i++) { total += Math.hypot(P[i][0] - P[i - 1][0], P[i][1] - P[i - 1][1]); lens.push(total); }
    var front = total * g, Q = [P[0]], S = [0];
    for (i = 1; i < P.length; i++) {
      if (lens[i] < front) { Q.push(P[i]); S.push(lens[i]); continue; }
      var f = (front - lens[i - 1]) / (lens[i] - lens[i - 1] || 1);
      Q.push([lerp(P[i - 1][0], P[i][0], f), lerp(P[i - 1][1], P[i][1], f)]); S.push(front);
      break;
    }
    var left = '', right = '';
    for (i = 0; i < Q.length; i++) {
      var a = Q[Math.max(0, i - 1)], c = Q[Math.min(Q.length - 1, i + 1)], tx = c[0] - a[0], ty = c[1] - a[1], tl = Math.hypot(tx, ty) || 1;
      var w = w0 * (1 - 0.75 * S[i] / total) * Math.min(1, (front - S[i]) / 6) / 2, nx = -ty / tl * w, ny = tx / tl * w;
      left += (i ? 'L' : 'M') + q(Q[i][0] + nx) + ' ' + q(Q[i][1] + ny);
      right = 'L' + q(Q[i][0] - nx) + ' ' + q(Q[i][1] - ny) + right;
    }
    return left + right + 'Z';
  }
  // A drip from (x0, y0) hanging to (x1, y1): necks in below its source and hangs a bead.
  // Clockwise, like the circles it overlaps, so the union never cancels.
  function dripPath(x0, y0, x1, y1, width, g) {
    var w = width / 2, my = (y0 + y1) / 2;
    return 'M' + q(x0 - w) + ' ' + q(y0) + 'L' + q(x0 + w) + ' ' + q(y0) + 'Q' + q(x0 + w * 0.62) + ' ' + q(my) + ' ' + q(x1 + w * 0.6) + ' ' + q(y1) +
      'L' + q(x1 - w * 0.6) + ' ' + q(y1) + 'Q' + q(x0 - w * 0.62) + ' ' + q(my) + ' ' + q(x0 - w) + ' ' + q(y0) + 'Z' + circlePath(x1, y1 + w * 0.2, w * (0.78 + 0.22 * g));
  }

  var EYE = 0, RING = 1, RISER = 2, BUD = 3, MICRO = 4, PLANES = 10;

  /* ── the well: geometry for one frame, written into its SVG ── */
  function Well(svg) {
    this.svg = svg;
    this.palette = [];
    var slots = 0;
    L.lanes.forEach(function (lane) { slots += lane.n; });
    this.slotCount = slots;
    this.bodies = [];
    for (var i = 0; i < 1 + slots + L.risers.n + L.micro.n + 1; i++) {
      this.bodies.push({kind: 0, id: 0, x: 0, y: 0, r: 0, rc: 0, m: 1, a: 1, b: 0, c: 0, d: 1, w2: 0, w3: 0, wp: 0, ax: 0, ay: 0,
        partner: -1, mergeK: 0, noCollide: -1, top: true, low: false, lane: 0, tint: -1, pop: 0, neck: 0, wj: 0, out: false,
        np: 0, pnx: new Float64Array(PLANES), pny: new Float64Array(PLANES), ps: new Float64Array(PLANES)});
    }
    var f = function () { return new Float64Array(slots); };
    this.slot = {x: f(), y: f(), r: f(), rFull: f(), th: f(), m: f(), extra: f(), tail: f(), nx: f(), ny: f(), env: f(),
      alive: new Uint8Array(slots), body: new Int32Array(slots), lane: new Int32Array(slots), idx: new Int32Array(slots), tint: new Int8Array(slots)};
    var k = 0, self = this;
    L.lanes.forEach(function (lane, li) { for (var s = 0; s < lane.n; s++, k++) { self.slot.lane[k] = li; self.slot.idx[k] = s; } });
    this.tintOrder = new Int8Array(slots).fill(-1);
    L.tintSlots.forEach(function (s, order) { self.tintOrder[s] = order; });
    var n = G.outline.length;
    this.OX = new Float64Array(n); this.OY = new Float64Array(n);
    this.rcX = new Float64Array(G.rightChain.length); this.rcY = new Float64Array(G.rightChain.length);
    this.lcX = new Float64Array(G.leftChain.length); this.lcY = new Float64Array(G.leftChain.length);
    this.PX = new Float64Array(32); this.PY = new Float64Array(32);
    this.CX = new Float64Array(G.charge.length); this.CY = new Float64Array(G.charge.length);
    // Collision displacement carried between frames, indexed by body id.
    this.offX = new Float64Array(1000); this.offY = new Float64Array(1000); this.seen = new Int32Array(1000);
    this.frameNo = 0; this.prevT = null;
    this.build();
  }

  Well.prototype.build = function () {
    var svg = this.svg, id = 'am-ink-well-' + (++uid);
    function mk(tag, attrs, parent) {
      var el = document.createElementNS(SVG_NS, tag);
      for (var k in attrs) el.setAttribute(k, attrs[k]);
      (parent || svg).appendChild(el);
      return el;
    }
    var defs = mk('defs', {});
    this.clipBody = mk('path', {}, mk('clipPath', {id: id + '-body'}, defs));
    var cpInk = mk('clipPath', {id: id + '-ink'}, defs);
    this.clipInkBody = mk('path', {}, cpInk);
    this.clipInkRim = mk('path', {}, cpInk);
    this.clipGap = mk('path', {'clip-rule': 'evenodd'}, mk('clipPath', {id: id + '-gap'}, defs));
    // Rift body, charge ink, rim, then the hole layer (mouth + bubbles) clipped to body ∪ rim.
    // Satellites knock the vessel out around themselves.
    var main = mk('g', {id: id + '-vessel', 'clip-path': 'url(#' + id + '-gap)'});
    this.id = id; this.defs = defs; this.main = main; this.pieces = null;
    this.elBody = mk('path', {class: 'am-ink-well-rift'}, main);
    this.elCharge = mk('path', {class: 'am-ink-well-charge', 'clip-path': 'url(#' + id + '-body)'}, main);
    this.elRimRift = mk('path', {class: 'am-ink-well-rift'}, main);
    this.elRim = mk('path', {class: 'am-ink-well-charge'}, main);
    this.ink = mk('g', {'clip-path': 'url(#' + id + '-ink)'}, main);
    this.elHoles = mk('path', {class: 'am-ink-well-hole'}, this.ink);
    this.elNecks = mk('path', {class: 'am-ink-well-hole'}, this.ink);
    // Outcome layers: bubbles that took the outcome ink (and their necks), the skin tints,
    // then cracks over all.
    this.elOutIn = mk('path', {}, this.ink);
    this.elOutNecksIn = mk('path', {}, this.ink);
    this.tintGroup = mk('g', {}, this.ink);
    this.elCracks = mk('path', {class: 'am-ink-well-hole'}, this.ink);
    this.elTints = [];
    this.elSatRift = mk('path', {class: 'am-ink-well-rift'});
    this.elSatCharge = mk('path', {class: 'am-ink-well-charge'});
    this.elDropRift = mk('path', {class: 'am-ink-well-rift'});
    this.elDropCharge = mk('path', {class: 'am-ink-well-charge'});
    // Released ink, bulges, leaks and puddles sit over everything (necks apart, so their
    // winding never cancels a circle).
    this.elOutNecks = mk('path', {});
    this.elOutOver = mk('path', {});
    this.outClass = ''; this.viewBox = '';
  };

  // Failure draws the vessel as wedge pieces: <use> copies of it, each clipped to one wedge,
  // that can drift apart. The vessel itself waits in <defs> meanwhile.
  Well.prototype.shatter = function (on) {
    var self = this, svg = this.svg;
    if (on && !this.pieces) {
      if (!this.wedgeClips) {
        this.wedgeClips = FRACTURE.wedges.map(function (w, i) {
          var cp = document.createElementNS(SVG_NS, 'clipPath'), p = document.createElementNS(SVG_NS, 'path');
          cp.setAttribute('id', self.id + '-piece-' + i); p.setAttribute('d', w.d);
          cp.appendChild(p); self.defs.appendChild(cp);
          return cp;
        });
      }
      this.defs.appendChild(this.main);
      this.pieces = FRACTURE.wedges.map(function (w, i) {
        var use = document.createElementNS(SVG_NS, 'use');
        use.setAttribute('href', '#' + self.id + '-vessel');
        use.setAttributeNS('http://www.w3.org/1999/xlink', 'xlink:href', '#' + self.id + '-vessel');
        use.setAttribute('clip-path', 'url(#' + self.id + '-piece-' + i + ')');
        svg.insertBefore(use, self.elSatRift);
        return use;
      });
    } else if (!on && this.pieces) {
      this.pieces.forEach(function (use) { use.remove(); });
      this.pieces = null;
      svg.insertBefore(this.main, this.elSatRift);
    }
  };

  Well.prototype.setPalette = function (colours) {
    var valid = (Array.isArray(colours) ? colours : []).filter(function (c) { return /^#[0-9a-f]{6}$/i.test(c); }).slice(0, 4);
    this.palette = valid;
    while (this.elTints.length > valid.length) this.elTints.pop().remove();
    while (this.elTints.length < valid.length) {
      var el = document.createElementNS(SVG_NS, 'path');
      el.setAttribute('class', 'am-ink-well-tint');
      this.tintGroup.appendChild(el);
      this.elTints.push(el);
    }
    this.elTints.forEach(function (el, i) { el.style.fill = valid[i]; });
    // One colour shows on two bubbles, two on three, three or four on four: a few, never a crowd.
    this.tintCount = valid.length ? Math.min(L.tintSlots.length, valid.length + 1) : 0;
  };

  // Squash/stretch around the base, with the top lagging so the motion travels upward.
  Well.prototype.deform = function (ch, x, y, lagged) {
    var hn = clamp((G.baseY - y) / G.height, 0, 1.25);
    var sq = lerp(lagged ? ch.sqLag : ch.sq, lagged ? ch.sqLag2 : ch.sqLag, sstep(0.2, 1, hn));
    var w = 0.3 + 0.7 * Math.exp(-Math.pow((hn - 0.42) / 0.27, 2));
    var swell = ch.swell || 1;
    this._x = G.cx + (x - G.cx) * (1 + 0.038 * sq * w) * swell + ch.sway * 2 * hn * hn;
    this._y = G.baseY - (G.baseY - y) * (1 - (sq > 0 ? 0.036 : 0.04) * sq) * (1 + (swell - 1) * 0.5);
  };

  Well.prototype.wallAt = function (cx, cy, y) {
    var n = cy.length;
    if (y <= cy[0]) return cx[0];
    for (var i = 1; i < n; i++) if (y <= cy[i]) return cx[i - 1] + (cx[i] - cx[i - 1]) * (y - cy[i - 1]) / (cy[i] - cy[i - 1] || 1);
    return cx[n - 1];
  };

  Well.prototype.constrain = function (b, web) {
    var R = b.rc, m = Math.max(L.margin, web), lo = -1e9, hi = 1e9;
    for (var k = -1; k <= 1; k++) {
      lo = Math.max(lo, this.wallAt(this.lcX, this.lcY, b.y + k * 0.6 * R));
      hi = Math.min(hi, this.wallAt(this.rcX, this.rcY, b.y + k * 0.6 * R));
    }
    lo += R + m; hi -= R + m;
    if (lo > hi) b.x = (lo + hi) / 2; else b.x = clamp(b.x, lo, hi);
    if (b.y > this.bottomY - R - m) b.y = this.bottomY - R - m;
    if (b.top && b.y < this.lipBottom + R + m * 0.8) b.y = this.lipBottom + R + m * 0.8;
  };

  // Stretch e1/e2 along `ang`, then a vertical lift (release) and squash (pressure).
  Well.prototype.shapeOf = function (b, ang, e1, e2, lift, press) {
    var c = Math.cos(ang), s = Math.sin(ang), off = c * s * (e1 - e2);
    var vx = (1 / Math.sqrt(lift)) * (1 + 0.035 * press), vy = lift * (1 - 0.05 * press);
    b.a = (c * c * e1 + s * s * e2) * vx; b.b = off * vx; b.c = off * vy; b.d = (s * s * e1 + c * c * e2) * vy;
  };

  Well.prototype.reach = function (b, dx, dy) {
    var l = Math.hypot(dx, dy) || 1, ux = dx / l, uy = dy / l;
    return b.r * Math.hypot(b.a * ux + b.c * uy, b.b * ux + b.d * uy);
  };

  Well.prototype.shape = function (b, web) {
    if (b.r < 0.45) return '';
    if (b.kind !== EYE && b.r < L.flatMinR && b.a === 1 && b.d === 1) return circlePath(b.x, b.y, b.r);
    var K = b.kind === EYE ? (b.wj ? 30 : 22) : b.r < 6 ? 8 : b.r < 10 ? 10 : 13, PX = this.PX, PY = this.PY;
    var m = Math.max(L.margin, web) * 0.5;
    var left = Math.max(this.wallAt(this.lcX, this.lcY, b.y - b.rc * 0.5), this.wallAt(this.lcX, this.lcY, b.y + b.rc * 0.5));
    var right = Math.min(this.wallAt(this.rcX, this.rcY, b.y - b.rc * 0.5), this.wallAt(this.rcX, this.rcY, b.y + b.rc * 0.5));
    var dl = b.x - left - m, dr = right - b.x - m, db = this.bottomY - b.y - m, dt = b.top ? b.y - this.lipBottom - m : 1e9;
    var flat = b.r >= L.flatMinR;
    for (var k = 0; k < K; k++) {
      // wj tears the void's edge when the well fails.
      var al = k / K * TAU, wob = 1 + b.w2 * Math.cos(2 * al + b.wp) + b.w3 * Math.cos(3 * al - b.wp * 1.3) +
        b.wj * (0.7 * Math.cos(7 * al + 0.6) + 0.5 * Math.cos(11 * al + 2.1));
      var cx = Math.cos(al) * b.r * wob, cy = Math.sin(al) * b.r * wob;
      var px = b.a * cx + b.b * cy, py = b.c * cx + b.d * cy, len = Math.hypot(px, py) || 1e-4, ux = px / len, uy = py / len;
      // Contact flattening: crowded bubbles press flat faces against each other and the walls.
      if (flat) for (var p = 0; p < b.np; p++) { var cth = ux * b.pnx[p] + uy * b.pny[p]; if (cth > 0.01) len = Math.min(len, b.ps[p] / cth); }
      if (ux < -0.01) len = Math.min(len, dl / -ux);
      if (ux > 0.01) len = Math.min(len, dr / ux);
      if (uy > 0.01) len = Math.min(len, db / uy);
      if (uy < -0.01) len = Math.min(len, dt / -uy);
      len = Math.max(len, b.r * 0.38);
      PX[k] = b.x + ux * len; PY[k] = b.y + uy * len;
    }
    return closedPath(PX, PY, K);
  };

  Well.prototype.render = function (ch) {
    var self = this, still = !ch.live, t = ch.t, ph = ch.ph, press = ch.press, surge = ch.surge;
    var name = ch.outcome || '', out = name ? OUTCOME[name] : null, tau = ch.tau || 0, fade = out ? ch.fade : 1;
    var pressEnv = sstep(0.3, 0.9, press), web = lerp(L.web, L.webPress, pressEnv);
    var OX = this.OX, OY = this.OY, n = G.outline.length, i, j, b, s;
    for (i = 0; i < n; i++) { this.deform(ch, G.outline[i][0], G.outline[i][1], false); OX[i] = this._x; OY[i] = this._y; }
    G.rightChain.forEach(function (idx, k) { self.rcX[k] = OX[idx]; self.rcY[k] = OY[idx]; });
    G.leftChain.forEach(function (idx, k) { self.lcX[k] = OX[idx]; self.lcY[k] = OY[idx]; });
    this.bottomY = OY[12] - 1.5;

    this.deform(ch, G.rim.cx, G.rim.cy, false);
    // An overpressurised rim stretches and strains.
    var strain = ch.strain || 0;
    var rimX = this._x, rimY = this._y - surge * 1.2, tilt = G.rim.tilt + ch.sway * 2.6 + strain * 1.6 * Math.sin((ch.warnW || 0) * 1.3);
    var rimRx = G.rim.rx * (1 + 0.012 * ch.sq + 0.05 * strain);
    this.lipBottom = rimY + G.rim.ry * 0.95;
    var mouthX = rimX - 0.5, mouthY = rimY - 1.2;

    /* bubbles */
    var B = this.bodies, nb = 0, ex0 = G.eye.x, ey0 = G.eye.y, tints = this.tintCount || 0, palette = this.palette;
    function add(kind, id) {
      var o = B[nb++];
      o.kind = kind; o.id = id; o.partner = -1; o.noCollide = -1; o.top = true; o.np = 0; o.tint = -1; o.pop = 0; o.neck = 0; o.wj = 0; o.out = false;
      o.a = 1; o.b = 0; o.c = 0; o.d = 1; o.w2 = 0; o.w3 = 0; o.wp = 0;
      return o;
    }

    // The void lends area to the bud on release and refills while the vessel settles.
    var budOn = !still, def = budOn ? sstep(0.405, 0.53, ph) * (1 - sstep(0.6, 0.97, ph)) : 0;
    var eyeR = Math.sqrt(Math.max(1, L.eyeR * L.eyeR - 0.75 * L.budR * L.budR * def)), ring = 0;
    // Success empties the void into the released bubbles; the rest of the field lifts a little.
    // Success: bubbles rise and gather under the neck, then settle back a little, calm. Warning:
    // the pressurised field lifts and its bubbles swell.
    var gather = name === 'success' ? sstep(0, 0.5, tau) * (1 - 0.7 * sstep(0.55, 1.3, tau)) : 0;
    var climb = 16 * gather + 4 * (ch.warnK || 0), swellR = 1 + 0.2 * (ch.warnK || 0);
    if (name === 'success') eyeR *= lerp(1, 0.9, sstep(0.05, 0.6, tau));
    if (budOn) { var tau0 = (ph - 0.53) * PERIOD; if (tau0 > 0 && tau0 < 1.8) ring = 0.07 * Math.exp(-tau0 * 2.8) * Math.sin(tau0 * 12); }
    var eye = add(EYE, 0);
    this.deform(ch, ex0 + 1.1 * Math.sin(0.83 * t), ey0 + 0.9 * Math.sin(0.61 * t + 1.3) + 4 * press - 3 * surge, false);
    eye.x = this._x; eye.y = this._y; eye.r = eyeR; eye.m = 6; eye.top = false;
    eye.a = 1 + 0.06 * press - 0.035 * surge - ring; eye.d = 1 - 0.07 * press + 0.045 * surge + ring;
    eye.w2 = 0.02 + Math.abs(ring) * 0.4; eye.w3 = 0.012; eye.wp = 0.45 * t;
    if (name === 'error') eye.wj = 0.09 * sstep(0, 0.18, tau);

    // Ring slots: each runs its own life (nucleate, grow, then dissolve or merge into the bubble
    // ahead), on lanes that rotate at different rates, so nothing moves as one rigid group.
    var SL = this.slot;
    for (s = 0; s < this.slotCount; s++) {
      var lane = L.lanes[SL.lane[s]], si = SL.idx[s], id = 100 + s;
      var life = lerp(lane.lifeMin, lane.lifeMax, hash(id * 3.17 + 0.5)), off = hash(id * 7.31 + 1.9) * life;
      var lt = (t + off) / life, k = Math.floor(lt), u = lt - k;
      if (still) { k = 0; u = 0.4; }
      var hk = hash(id * 13.37 + k * 1.618 + 0.3);
      var order = SL.lane[s] === 0 ? this.tintOrder[si] : -1;
      SL.tint[s] = order >= 0 && order < tints ? (order + k) % palette.length : -1;
      var tinted = SL.tint[s] >= 0 || (SL.lane[s] === 0 && this.tintOrder[(si + 1) % lane.n] >= 0 && this.tintOrder[(si + 1) % lane.n] < tints);
      var isMerge = !still && !tinted && hash(id * 2.71 + k * 4.13 + 0.7) < lane.mergeP;
      var active = isMerge ? 0.72 : lerp(lane.activeMin || 0.88, 0.97, hash(id * 5.13 + k * 0.77));
      var step = TAU / lane.n;
      var th = lane.theta0 + si * step + (hk - 0.5) * 0.35 * step + lane.omega * ch.ft + 0.1 * Math.sin(0.31 * t + id * 1.3) * step;
      var span = Math.max(0, wallDistAt(th) - L.eyeR - L.innerGap - L.outerGap);
      var psi = clamp(lane.psi + (hash(id * 9.1 + k * 2.3) - 0.5) * lane.jitterP + (lane.psi > 0 ? 0.035 * Math.sin(0.43 * t + id * 1.7) : 0), 0, 1);
      // Pressure gathers the crowd in toward the void and down into the base.
      var R = (L.eyeR + L.innerGap + span * psi + (lane.psi === 0 ? 0.9 * Math.sin(0.5 * t + id) : 0)) * (1 - 0.085 * press);
      SL.x[s] = ex0 + Math.cos(th) * R * (1 - 0.18 * gather); SL.y[s] = ey0 + Math.sin(th) * R + 7 * press - 3 * surge - climb; SL.th[s] = th;
      // Nominal slot position (no per-life jitter): a continuous target for merges.
      var thN = lane.theta0 + si * step + lane.omega * ch.ft;
      var RN = (L.eyeR + L.innerGap + Math.max(0, wallDistAt(thN) - L.eyeR - L.innerGap - L.outerGap) * lane.psi) * (1 - 0.085 * press);
      SL.nx[s] = ex0 + Math.cos(thN) * RN * (1 - 0.18 * gather); SL.ny[s] = ey0 + Math.sin(thN) * RN + 7 * press - 3 * surge - climb;
      // Outer lanes thin out where the cavity narrows under the neck.
      var space = lane.psi === 0 ? 1 : lerp(0.2, 1, sstep(12, 36, span));
      var rFull = lerp(lane.rMin, lane.rMax, hk) * space * (1 + 0.045 * Math.sin(t * (0.9 + hk * 0.8) + id * 2.1)) * (1 + 0.06 * press) * swellR;
      SL.extra[s] = 0; SL.m[s] = 0; SL.tail[s] = 0; SL.env[s] = 0;
      if (this.sparse && (SL.lane[s] !== 0 || si % SPARSE.ringEvery)) { SL.alive[s] = 0; SL.r[s] = 0; continue; }
      if (u >= active) {
        SL.alive[s] = 0; SL.r[s] = 0;
        // A merged bubble's receiver keeps the absorbed volume a while, then relaxes.
        if (isMerge) { SL.tail[s] = 1 - sstep(active, 1, u); SL.rFull[s] = rFull; }
        continue;
      }
      var ul = u / active, g = sstep(0, lane.grow, ul);
      g = 1 - (1 - g) * (1 - g);
      SL.alive[s] = 1;
      if (isMerge) {
        SL.m[s] = sstep(0.62, 1, ul); SL.env[s] = g; SL.rFull[s] = rFull * g; SL.r[s] = rFull * g * Math.sqrt(1 - SL.m[s]);
      } else {
        SL.env[s] = g * (1 - sstep(0.82, 1, ul)); SL.r[s] = rFull * SL.env[s]; SL.rFull[s] = SL.r[s];
      }
    }
    // Merges drift into the bubble ahead and hand over area, scaled by the receiver's own life.
    var start = 0, li, ln, p;
    for (li = 0; li < L.lanes.length; li++) {
      ln = L.lanes[li].n;
      for (i = 0; i < ln; i++) {
        s = start + i; p = start + (i + 1) % ln;
        if (SL.alive[s] && SL.m[s] > 0) {
          SL.x[s] = lerp(SL.x[s], SL.nx[p], 0.8 * SL.m[s]); SL.y[s] = lerp(SL.y[s], SL.ny[p], 0.8 * SL.m[s]);
          SL.extra[p] += (SL.rFull[s] * SL.rFull[s] - SL.r[s] * SL.r[s]) * SL.env[p];
        } else if (!SL.alive[s] && SL.tail[s] > 0) SL.extra[p] += SL.rFull[s] * SL.rFull[s] * SL.tail[s] * SL.env[p];
      }
      start += ln;
    }
    for (s = 0; s < this.slotCount; s++) {
      SL.body[s] = -1;
      if (!SL.alive[s]) continue;
      var r = Math.sqrt(SL.r[s] * SL.r[s] + SL.extra[s]);
      if (r < 0.3) continue;
      b = add(RING, 100 + s);
      this.deform(ch, SL.x[s], SL.y[s], false);
      b.x = this._x; b.y = this._y; b.r = r; b.m = 1; b.lane = SL.lane[s]; b.tint = SL.tint[s];
      b.low = Math.sin(SL.th[s]) > -0.05;
      var hb = hash(b.id * 3.7);
      b.w2 = 0.025 + 0.035 * hb; b.w3 = 0.015 * hash(b.id * 1.3); b.wp = t * (0.5 + hb * 0.6) + b.id;
      // Stretch along the circulation, and upward while the vessel releases.
      var e = 1.02 + 0.035 * (ch.flowRate - 1);
      this.shapeOf(b, SL.th[s] + Math.PI / 2, e, 1 / e, 1 + 0.15 * surge * (0.5 + 0.5 * sstep(160, 100, b.y)), press);
      SL.body[s] = nb - 1;
    }
    start = 0;
    for (li = 0; li < L.lanes.length; li++) {
      ln = L.lanes[li].n;
      for (i = 0; i < ln; i++) {
        s = start + i; p = start + (i + 1) % ln;
        if (SL.m[s] > 0 && SL.body[s] >= 0 && SL.body[p] >= 0) { B[SL.body[s]].partner = SL.body[p]; B[SL.body[s]].mergeK = SL.m[s]; }
      }
      start += ln;
    }

    // Neck risers expand as they climb, then break through the lip into the mouth. They run on
    // flow time, so the release sends them racing up.
    var popSum = 0, RZ = L.risers;
    for (i = 0; i < (this.sparse ? SPARSE.risers : RZ.n); i++) {
      var rid = 500 + i, P = lerp(RZ.pMin, RZ.pMax, hash(rid * 3.3)), rlt = (ch.ft + hash(rid * 5.9) * P) / P, ru = rlt - Math.floor(rlt);
      if (still) ru = (i + 0.5) / RZ.n * 0.8;
      var rh = hash(rid * 7.7 + Math.floor(rlt) * 1.3), rise = clamp(ru / 0.84, 0, 1), pop = ru > 0.84 ? (ru - 0.84) / 0.16 : 0;
      var rr = lerp(RZ.rMin, RZ.rMax, rh) * sstep(0, 0.22, ru) * (0.85 + 0.15 * rise) * (1 - sstep(0.25, 1, pop));
      if (rr < 0.3) continue;
      b = add(RISER, rid);
      this.deform(ch, G.neckX + (rh - 0.5) * 2 * RZ.spread * (1 - 0.55 * rise) + 2.2 * Math.sin(rise * TAU * 1.2 + rh * 6), G.riserY, false);
      b.x = this._x; b.y = lerp(this._y, this.lipBottom + rr * 0.95 + 0.5, Math.pow(rise, 1.35));
      b.r = rr; b.m = 0.8; b.top = false; b.w2 = 0.03; b.wp = t * 0.9 + rid;
      var lift = 1 + 0.1 * sstep(0, 0.5, rise) + 0.25 * surge;
      b.a = 1 / Math.sqrt(lift); b.d = lift;
      b.pop = sstep(0, 0.3, pop) * (1 - sstep(0.7, 1, pop)); popSum += b.pop;
    }

    // Secondary bubbling: tiny pockets that open in the webs and fade.
    var MZ = L.micro;
    for (i = 0; i < (this.sparse ? SPARSE.micro : MZ.n); i++) {
      var mid = 700 + i, MP = lerp(1.6, 3, hash(mid * 1.7)), mlt = (t + hash(mid * 4.1) * MP) / MP, mk = Math.floor(mlt), mu = still ? 0.5 : mlt - mk;
      var h1 = hash(mid * 3.1 + mk * 2.9), h2 = hash(mid * 8.3 + mk * 1.1);
      var mr = lerp(MZ.rMin, MZ.rMax, hash(mid + mk * 0.37)) * sstep(0, 0.25, mu) * (1 - sstep(0.7, 1, mu)) * (1 + 0.5 * surge);
      if (mr < 0.35) continue;
      var mx, my;
      if (i < MZ.neck) { mx = G.neckX + (h1 - 0.5) * 34; my = lerp(96, 70, h2) - 6 * mu; }
      else {
        var mth = h1 * TAU + 0.18 * ch.ft, MR = L.eyeR + 5 + Math.max(0, wallDistAt(mth) - L.eyeR - 9) * lerp(0.08, 1, h2);
        mx = ex0 + Math.cos(mth) * MR; my = ey0 + Math.sin(mth) * MR - 4 * mu;
      }
      b = add(MICRO, mid);
      this.deform(ch, mx, my, false);
      b.x = this._x; b.y = this._y; b.r = mr; b.m = 0.5;
    }

    // The bud pinches off the top of the void, shoulders up the neck and bursts into the mouth,
    // which throws the splash.
    var bud = null;
    if (budOn && ph > 0.4 && ph < 0.69) {
      var be = sstep(0.4, 0.49, ph), detach = sstep(0.485, 0.53, ph), brise = sstep(0.515, 0.6, ph), bpop = clamp((ph - 0.6) / 0.085, 0, 1);
      var rb = L.budR * Math.sqrt(be) * (1 - sstep(0.25, 1, bpop)) * fade;
      if (rb > 0.3) {
        bud = add(BUD, 900);
        var ang = -Math.PI / 2 + 0.12, dist = eyeR * eye.d * 0.98 + L.budR * lerp(-0.45, 0.62, be) + detach * (L.budR * 0.55 + 3.5);
        bud.x = lerp(eye.x + Math.cos(ang) * dist, mouthX, brise);
        bud.y = lerp(eye.y + Math.sin(ang) * dist, this.lipBottom + rb * 0.95 + 0.6, brise);
        bud.r = rb; bud.m = 4; bud.top = false; bud.w2 = 0.03; bud.wp = t;
        var bs = 1 + 0.32 * Math.sin(Math.PI * brise);
        bud.a = 1 / Math.sqrt(bs); bud.d = bs;
        bud.neck = 0.62 * (1 - detach) * sstep(0, 0.25, be);
        bud.pop = sstep(0, 0.3, bpop) * (1 - sstep(0.7, 1, bpop)); popSum += bud.pop * 1.5;
        if (detach < 1) bud.noCollide = 0;
      }
    }

    // Collision radii, and last frame's displacement decaying back toward each bubble's own
    // path: crowded bubbles slide round each other instead of flipping sides.
    var dtT = this.prevT === null ? -1 : t - this.prevT, coherent = !still && dtT >= 0 && dtT < 0.12;
    var decay = coherent ? Math.exp(-dtT / 0.4) : 0, fno = ++this.frameNo;
    for (i = 0; i < nb; i++) {
      b = B[i];
      b.rc = b.r * Math.max(Math.hypot(b.a, b.c), Math.hypot(b.b, b.d)) * 0.92;
      b.m *= b.r * b.r; b.ax = b.x; b.ay = b.y;
      if (coherent && this.seen[b.id] === fno - 1) { b.x += this.offX[b.id] * decay; b.y += this.offY[b.id] * decay; }
    }
    this.prevT = still ? null : t;

    /* relaxation: keep webs between bubbles; pressure presses a few pairs together */
    // Pressure keeps fusing bubbles in the overpressurised well, more than while cooking.
    var fuseOn = !still && (!out || name === 'warning'), fuseMore = name === 'warning' ? 2.5 : 1;
    function gate(bi, bj) {
      if (!fuseOn || pressEnv <= 0 || bi.tint >= 0 || bj.tint >= 0) return 0;
      var pr = 0;
      if (bi.kind === RING && bj.kind === RING) { if (bi.low && bj.low) pr = L.fuseP; }
      else if ((bi.kind === EYE && bj.kind === RING && bj.lane === 0 && bj.low) || (bj.kind === EYE && bi.kind === RING && bi.lane === 0 && bi.low)) pr = L.eyeFuseP;
      return pr > 0 && hash(bi.id * 0.731 + bj.id * 1.377 + ch.cyc * 7.17) < pr * fuseMore ? pressEnv : 0;
    }
    function ignored(a, c, ba, bc) { return ba.partner === c || bc.partner === a || ba.noCollide === c || bc.noCollide === a; }
    var iterations = coherent ? 3 : 10, bi, bj, dx, dy, d2, d, nx, ny, wi, minD, pe;
    for (var it = 0; it < iterations; it++) {
      for (i = 0; i < nb; i++) {
        bi = B[i];
        for (j = i + 1; j < nb; j++) {
          bj = B[j]; dx = bj.x - bi.x; dy = bj.y - bi.y; d2 = dx * dx + dy * dy;
          var reachD = bi.rc + bj.rc + web * 3;
          if (d2 > reachD * reachD || ignored(i, j, bi, bj)) continue;
          minD = bi.rc + bj.rc + web; pe = gate(bi, bj); d = Math.sqrt(d2) || 1e-4;
          if (pe > 0) {
            var target = minD - pe * (web + 0.32 * Math.min(bi.rc, bj.rc));
            if (d > target) {
              var pull = (d - target) * 0.3 * pe; nx = dx / d; ny = dy / d; wi = bj.m / (bi.m + bj.m);
              bi.x += nx * pull * wi; bi.y += ny * pull * wi; bj.x -= nx * pull * (1 - wi); bj.y -= ny * pull * (1 - wi);
              continue;
            }
            minD = target;
          }
          if (d >= minD) continue;
          if (d2 < 1e-6) { var ra = hash(bi.id + bj.id) * TAU; nx = Math.cos(ra); ny = Math.sin(ra); } else { nx = dx / d; ny = dy / d; }
          var ov = (minD - d) * 0.6; wi = bj.m / (bi.m + bj.m);
          bi.x -= nx * ov * wi; bi.y -= ny * ov * wi; bj.x += nx * ov * (1 - wi); bj.y += ny * ov * (1 - wi);
        }
      }
      for (i = 0; i < nb; i++) this.constrain(B[i], web);
    }
    // Collision speed limit: a push moves a bubble at most ~110 units/s beyond its own path,
    // so a big shove plays out over frames instead of a hop.
    var lim = 110 * Math.max(dtT, 1 / 120);
    for (i = 0; i < nb; i++) {
      b = B[i];
      if (coherent && this.seen[b.id] === fno - 1) {
        var px0 = this.offX[b.id] * decay, py0 = this.offY[b.id] * decay, ddx = b.x - b.ax - px0, ddy = b.y - b.ay - py0, dl = Math.hypot(ddx, ddy);
        if (dl > lim) { b.x = b.ax + px0 + ddx * lim / dl; b.y = b.ay + py0 + ddy * lim / dl; }
      }
      this.offX[b.id] = b.x - b.ax; this.offY[b.id] = b.y - b.ay; this.seen[b.id] = fno;
    }

    // An outcome washes out from the void: each bubble takes the outcome ink with a small pop.
    // The failed void stays a hole; skin tints keep their colours.
    if (out) for (i = 0; i < nb; i++) {
      b = B[i];
      if (b.tint >= 0 || (b.kind === EYE && name === 'error')) continue;
      var flip = b.kind === EYE ? 0.02 : 0.03 + 0.0024 * Math.hypot(b.x - eye.x, b.y - eye.y);
      if (tau < flip) continue;
      b.out = true;
      b.r *= 1 + 0.16 * Math.sin(Math.PI * clamp((tau - flip) / 0.16, 0, 1));
    }

    /* necks and flattening planes */
    var necks = [], necksOut = [], webFlat = web * 0.85;
    for (i = 0; i < nb; i++) {
      bi = B[i];
      for (j = i + 1; j < nb; j++) {
        bj = B[j]; dx = bj.x - bi.x; dy = bj.y - bi.y; d2 = dx * dx + dy * dy;
        var reach2 = bi.rc + bj.rc + web * 2;
        if (d2 > reach2 * reach2) continue;
        d = Math.sqrt(d2) || 1e-4;
        if (bi.partner === j || bj.partner === i) {
          if (!out) necks.push(metaballPath(bi.r, bj.r, bi.x, bi.y, bj.x, bj.y, 0.55 * sstep(0, 0.3, bi.partner === j ? bi.mergeK : bj.mergeK)));
          continue;
        }
        if (bi.noCollide === j || bj.noCollide === i) continue;
        pe = gate(bi, bj);
        if (pe > 0.02) {
          var v = 0.58 * pe * sstep(1.6 * web, -0.1 * Math.min(bi.rc, bj.rc), d - bi.rc - bj.rc);
          if (v > 0.01) { (bi.out && bj.out ? necksOut : necks).push(metaballPath(this.reach(bi, dx, dy), this.reach(bj, -dx, -dy), bi.x, bi.y, bj.x, bj.y, v)); continue; }
        }
        if (d >= bi.rc + bj.rc + webFlat) continue;
        var sI = (d2 + bi.rc * bi.rc - bj.rc * bj.rc) / (2 * d);
        nx = dx / d; ny = dy / d;
        if (bi.np < PLANES) { bi.pnx[bi.np] = nx; bi.pny[bi.np] = ny; bi.ps[bi.np++] = sI - webFlat / 2; }
        if (bj.np < PLANES) { bj.pnx[bj.np] = -nx; bj.pny[bj.np] = -ny; bj.ps[bj.np++] = d - sI - webFlat / 2; }
      }
    }
    if (bud && !out && bud.neck > 0.005) necks.push(metaballPath(this.reach(eye, bud.x - eye.x, bud.y - eye.y), bud.r, eye.x, eye.y, bud.x, bud.y, bud.neck));

    // The mouth swells a touch when a bubble bursts into it.
    var mouthRx = G.rim.mrx * (1 + 0.012 * ch.sq + 0.05 * strain) + Math.min(1.6, popSum * 0.8), mouthRy = G.rim.mry + Math.min(1.4, popSum * 0.7);
    var tan = Math.tan(tilt * Math.PI / 180);
    for (i = 0; i < nb; i++) {
      b = B[i];
      if (b.pop > 0.01 && !b.out) {
        var dm = (b.x - mouthX) / mouthRx;
        necks.push(surfaceNeckPath(b.x, b.y, b.r * b.a, mouthY + mouthRy * Math.sqrt(Math.max(0, 1 - dm * dm)) + (b.x - mouthX) * tan, b.pop));
      }
    }
    var holes = ellipsePath(mouthX, mouthY, mouthRx, mouthRy, tilt), tinted = this.elTints.map(function () { return ''; }), outIn = '';
    for (i = 0; i < nb; i++) {
      b = B[i];
      if (b.tint >= 0 && b.tint < tinted.length) tinted[b.tint] += this.shape(b, web);
      else if (b.out) outIn += this.shape(b, web);
      else holes += this.shape(b, web);
    }

    /* the walls answer the bubbles crowding them */
    for (var bk = 0; bk < G.bulge.length; bk++) {
      var kk = G.bulge[bk], kp = (kk - 1 + n) % n, kn = (kk + 1) % n, tx = OX[kn] - OX[kp], ty = OY[kn] - OY[kp], tl = Math.hypot(tx, ty) || 1, push = 0;
      for (i = 0; i < nb; i++) {
        var gap = Math.hypot(B[i].x - OX[kk], B[i].y - OY[kk]) - B[i].rc;
        if (gap < 11) push += sstep(11, 1.5, gap) * B[i].rc * L.wallBulge * 0.5;
      }
      push = Math.min(1.8, push); OX[kk] += ty / tl * push; OY[kk] += -tx / tl * push;
    }
    var bodyD = closedPath(OX, OY, n), rimD = ellipsePath(rimX, rimY, rimRx, G.rim.ry, tilt);

    /* charge ink: sloshes, ripples and lifts on release */
    var CX = this.CX, CY = this.CY, nc = G.charge.length, slosh = 0.045 * Math.sin(0.45 * ch.ft) + 0.07 * ch.sway, cs = Math.cos(slosh), sn = Math.sin(slosh);
    for (i = 0; i < nc; i++) {
      var x = G.charge[i][0], y = G.charge[i][1];
      if (i >= 5 && i <= 14) {
        var ox = x - ex0, oy = y - ey0;
        x = ex0 + ox * cs - oy * sn; y = ey0 + ox * sn + oy * cs;
        var dlen = Math.hypot(x - ex0, y - ey0) || 1, rip = 1.3 * Math.sin(1.15 * t + i * 0.8) + 0.9 * Math.sin(0.7 * t - i * 1.3);
        x += (x - ex0) / dlen * rip; y += (y - ey0) / dlen * rip + 4 * press - 6 * surge;
      }
      this.deform(ch, x, y, false); CX[i] = this._x; CY[i] = this._y;
    }

    /* satellites and their knockout gaps */
    var sat = ['', ''], gapD = 'M-60 -60H316V316H-60Z';
    G.sats.forEach(function (st) {
      if (self.sparse && st.rx < SPARSE.satMinR) return;
      var sdx = st.x - 128, sdy = st.y - 150, sl = Math.hypot(sdx, sdy) || 1, out = 2.2 * press - 1.2 * surge;
      self.deform(ch, st.x + sdx / sl * out + 0.7 * Math.sin(t * TAU * st.f * 0.5 + st.ph), st.y + sdy / sl * out + 0.8 * Math.sin(t * TAU * st.f * 0.42 + st.ph * 1.7), true);
      var sc = 1 + 0.07 * press - 0.035 * surge + 0.03 * Math.sin(t * 1.7 + st.ph), br = 0.035 * Math.sin(t * 1.3 + st.ph * 2.3);
      var rx = st.rx * sc * (1 + br), ry = st.ry * sc * (1 - br), rot = st.rot + 4 * Math.sin(t * 0.7 + st.ph), sx = self._x, sy = self._y;
      sat[st.ink] += ellipsePath(sx, sy, rx, ry, rot);
      if (st.hl) {
        var a = rot * Math.PI / 180;
        sat[0] += ellipsePath(sx + st.hl.dx * Math.cos(a) - st.hl.dy * Math.sin(a), sy + st.hl.dx * Math.sin(a) + st.hl.dy * Math.cos(a), st.hl.rx * sc, st.hl.ry * sc, rot);
      }
      gapD += ellipsePath(sx, sy, rx + st.gap, ry + st.gap, rot);
    });

    /* crown splash, thrown by the bud's burst */
    var drops = ['', ''], GRAV = 560;
    if (!still) G.crown.forEach(function (c) {
      var tau = (ph - c.p0) * PERIOD, V = Math.sqrt(2 * GRAV * c.h), tf = 2 * V / GRAV;
      if (tau <= 0 || tau >= tf) return;
      var dr = c.r * sstep(0, 0.07, tau) * (1 - sstep(tf - 0.12, tf, tau)) * fade;
      if (dr < 0.3) return;
      var vy = -(V - GRAV * tau), el = 1 + Math.min(0.75, Math.hypot(c.vx, vy) / 300) * 0.55;
      drops[c.ink] += ellipsePath(mouthX + c.dx * 0.5 + c.vx * tau, mouthY - (V * tau - 0.5 * GRAV * tau * tau), dr * el, dr / Math.sqrt(el), Math.atan2(vy, c.vx) * 180 / Math.PI);
    });

    /* outcome geometry (ribbons and necks go to their own path, so winding never cancels) */
    var over = '', overNecks = '', cracks = '';
    if (name === 'success') {
      // The mouth brims, five tendrils leap and curl outward and their tips break into drops; the
      // drops and a spray of small bubbles float up and dissipate, and the mouth drains calm.
      var brim = sstep(0.32, 0.42, tau) * (1 - sstep(0.75, 1, tau));
      if (brim > 0.01) over += ellipsePath(mouthX, mouthY, mouthRx * 0.92 * brim, mouthRy * 0.9 * brim + 0.01, tilt);
      BURST.forEach(function (bt) {
        var a = bt[0] * Math.PI / 180, sa = Math.sin(a), ca = Math.cos(a), brk = bt[4] + 0.28;
        var grow = easeOut((tau - bt[4]) / 0.18), back = sstep(brk, brk + 0.26, tau), len = bt[1] * grow * (1 - back);
        var bx = mouthX + sa * mouthRx * 0.35, by = mouthY;
        function at(Lt, s) {
          var ex = bx + sa * Lt * 1.05, ey = by - ca * Lt * 0.9, cx = bx + sa * Lt * 0.15, cy = by - Lt * 0.6, u = 1 - s;
          return [u * u * bx + 2 * u * s * cx + s * s * ex, u * u * by + 2 * u * s * cy + s * s * ey];
        }
        if (len > 1) {
          var pts = [];
          for (var s = 0; s <= 6; s++) pts.push(at(len, s / 6));
          overNecks += ribbon(pts, bt[2] * (1 - 0.4 * back), 1);
          if (tau < brk) { var tip = at(len, 1); over += circlePath(tip[0], tip[1], bt[3] * grow); }
        }
        if (tau >= brk) {
          var tip0 = at(bt[1], 1), dt = tau - brk, drift = easeOut(dt / 0.7), r = bt[3] * (1 - sstep(0.25, 0.6, dt));
          if (r > 0.3) over += circlePath(tip0[0] + sa * 26 * drift, tip0[1] - 10 * drift - 10 * dt, r);
        }
      });
      SPRAY.forEach(function (sp, k) {
        var dt = tau - sp[3], p = easeOut(dt / 0.6), r = sp[2] * sstep(0, 0.1, dt) * (1 - sstep(0.4, 0.75, dt));
        if (dt > 0 && r > 0.3) over += circlePath(mouthX + sp[0] * p + 1.4 * Math.sin(dt * 8 + k), mouthY + sp[1] * p - 8 * Math.max(0, dt - 0.4), r);
      });
    } else if (name === 'warning') {
      // The pressurised ink brims in the mouth and an amber bulge strains up out of it, pulsing in
      // a tense loop and now and then spitting a drop that falls back. It never bursts.
      var wk = ch.warnK, ww = ch.warnW;
      if (wk > 0.01) {
        var sr = mouthRy * 2 * wk, bx = mouthX + 1.8 * Math.sin(ww * 0.9), br = 9 + 12 * wk + 1.5 * wk * Math.sin(ww + 0.8);
        var by = mouthY - (8 + 20 * wk + 3 * wk * Math.sin(ww)), tr = br * 0.5 * wk;
        var tx = bx + 2.5 * Math.sin(ww * 1.7), ty = by - br * (1.05 + 0.12 * (1 + Math.sin(ww * 1.3)));
        over += ellipsePath(mouthX, mouthY, mouthRx * 0.92 * wk, mouthRy * 0.9 * wk + 0.01, tilt) + circlePath(mouthX, mouthY + 1, sr) +
          circlePath(bx, by, br) + circlePath(tx, ty, tr);
        overNecks += metaballPath(sr, br, mouthX, mouthY + 1, bx, by, 0.7) + metaballPath(br, tr, bx, by, tx, ty, 0.6);
        // Spits: three a cycle on short arcs, falling back onto the shoulders. The previous
        // cycle's drops finish their flight.
        var LOOP = OUTCOME.warning.loop, cyc = Math.floor(tau / LOOP);
        for (var c = cyc - 1; c <= cyc; c++) [[-1, 0.08], [1, 0.34], [-1, 0.62]].forEach(function (sp, j) {
          var h = hash(c * 3.1 + j * 7.7), dt = tau - (c + sp[1]) * LOOP, V = 70 + 40 * h, tf = (V + Math.sqrt(V * V + 2 * 420 * 28)) / 420;
          if (c < 0 || tau < 0.6 || dt <= 0 || dt >= tf) return;
          var r = (2.2 + 1.8 * hash(c * 5.3 + j)) * sstep(0, 0.05, dt) * (1 - sstep(tf - 0.08, tf, dt));
          over += circlePath(bx + sp[0] * (br * 0.8 + (22 + 18 * h) * dt), by - br * 0.2 - (V * dt - 210 * dt * dt), r);
        });
      }
    } else if (name === 'error') {
      // Subtle cracks first, widening as the rim and body break.
      var widen = lerp(0.45, 1, sstep(0.26, 0.45, tau)), ground = G.baseY + 1.2;
      FRACTURE.cracks.forEach(function (c) {
        cracks += ribbon(c.pts.map(function (p) { self.deform(ch, p[0], p[1], false); return [self._x, self._y]; }), 3.4 * widen, easeOut((tau - c.delay) / 0.26));
      });
      // Red ink leaks from the low cracks, runs down to the ground and pools.
      POOLS.forEach(function (pl, k) {
        var c = FRACTURE.cracks[pl[0]], g = easeOut((tau - LEAKS[k][2] - 0.25) / 0.7);
        if (g > 0.01) {
          self.deform(ch, c.exit[0], ground, false);
          var px = self._x + c.dir[0] * 6, ry = 4.6 * Math.min(1, g * 2);
          over += ellipsePath(px, ground + 2, pl[1] * g, ry, 0) + ellipsePath(px + pl[1] * 0.4 * g, ground + 2.8, pl[1] * 0.45 * g, ry * 0.9, 0);
        }
      });
      LEAKS.forEach(function (lk) {
        var c = FRACTURE.cracks[lk[0]], g = easeOut((tau - lk[2]) / 0.4);
        if (g <= 0.01) return;
        self.deform(ch, c.exit[0], c.exit[1], false);
        over += dripPath(self._x, self._y, self._x + c.dir[0] * 4 * g, lerp(self._y, ground, g), lk[1], g);
      });
      // Drops splash out of the cracks and flatten where they land.
      SPLASH.forEach(function (sp) {
        var c = FRACTURE.cracks[sp[0]], dt = tau - sp[4];
        if (dt <= 0) return;
        self.deform(ch, c.exit[0], c.exit[1], false);
        var x0 = self._x, y0 = self._y, vy = sp[2], land = (-vy + Math.sqrt(vy * vy + 2 * 560 * Math.max(0, ground - y0))) / 560, r = sp[3] * sstep(0, 0.05, dt);
        if (dt < land) over += circlePath(x0 + sp[1] * dt, y0 + vy * dt + 280 * dt * dt, r);
        else { var sk = easeOut((dt - land) / 0.12); over += ellipsePath(x0 + sp[1] * land, ground + 1, r * (1 + 0.8 * sk), r * (1 - 0.6 * sk) + 0.01, 0); }
      });
    }
    // Failure breaks the vessel into its wedges, which drift apart while the neck and shoulders
    // slump and tip.
    this.shatter(name === 'error' && tau >= 0.28);
    if (this.pieces) FRACTURE.wedges.forEach(function (w, k) {
      var p = easeOut((tau - w.delay) / 0.45), dx = w.mx * w.sep * p, dy = (w.my > 0.3 ? 0 : w.my * w.sep * p) + w.drop * p * p;
      self.pieces[k].setAttribute('transform', 'translate(' + q(dx) + ' ' + q(dy) + ') rotate(' + q(w.rot * p) + ' ' + q(w.cx) + ' ' + q(w.cy) + ')');
    });
    if (out && this.outClass !== out.cls) {
      this.outClass = out.cls;
      [this.elOutIn, this.elOutNecksIn, this.elOutNecks, this.elOutOver].forEach(function (el) { el.setAttribute('class', out.cls); });
    }
    var vv = out && !this.fixedFrame ? outcomeView(name, tau) : [VIEW, 0], vk = vv[1], view = vv[0], vs = q(lerp(VIEW[2], view[2], vk));
    var vb = q(lerp(VIEW[0], view[0], vk)) + ' ' + q(lerp(VIEW[1], view[1], vk)) + ' ' + vs + ' ' + vs;
    if (vb !== this.viewBox) { this.viewBox = vb; this.svg.setAttribute('viewBox', vb); }
    this.elOutIn.setAttribute('d', outIn); this.elOutNecksIn.setAttribute('d', necksOut.join('')); this.elCracks.setAttribute('d', cracks);
    this.elOutNecks.setAttribute('d', overNecks); this.elOutOver.setAttribute('d', over);

    this.elBody.setAttribute('d', bodyD); this.clipBody.setAttribute('d', bodyD);
    this.clipInkBody.setAttribute('d', bodyD); this.clipInkRim.setAttribute('d', rimD);
    this.clipGap.setAttribute('d', gapD);
    this.elCharge.setAttribute('d', closedPath(CX, CY, nc));
    this.elRimRift.setAttribute('d', ellipsePath(rimX + 3.2, rimY + 0.9, rimRx, G.rim.ry, tilt));
    this.elRim.setAttribute('d', rimD);
    this.elHoles.setAttribute('d', holes); this.elNecks.setAttribute('d', necks.join(''));
    this.elTints.forEach(function (el, k) { el.setAttribute('d', tinted[k]); });
    this.elSatRift.setAttribute('d', sat[1]); this.elSatCharge.setAttribute('d', sat[0]);
    this.elDropRift.setAttribute('d', drops[1]); this.elDropCharge.setAttribute('d', drops[0]);
  };

  /* ── lifecycle ── */
  function mount(host, options) {
    if (!host || host.nodeType !== 1) throw new Error('AtelierMotion.inkWell.mount requires a DOM host.');
    var prior = mounted ? mounted.get(host) : null;
    if (prior) prior.destroy();
    if (host.childNodes.length) throw new Error('Ink-well needs an empty host.');
    var opts = options || {};
    var size = clamp(Number(opts.size) || 216, 96, 480);
    var svg = document.createElementNS(SVG_NS, 'svg');
    if (!svg || typeof svg.setAttribute !== 'function') throw new Error('SVG unavailable');
    svg.setAttribute('class', 'am-ink-well');
    svg.setAttribute('viewBox', '10 10 236 236');
    svg.setAttribute('width', String(size)); svg.setAttribute('height', String(size));
    svg.setAttribute('aria-hidden', 'true'); svg.setAttribute('focusable', 'false');
    svg.style.width = svg.style.height = size + 'px';
    host.appendChild(svg);
    var well = new Well(svg);
    well.fixedFrame = !!opts.fixedFrame;
    well.sparse = !!opts.sparse;
    well.setPalette(opts.palette);

    var reducedPref = opts.reducedMotion === 'reduce' ? 'reduce' : 'system', mql = null;
    try { mql = (window.AtelierMotionPolicy && window.AtelierMotionPolicy.query()) || window.matchMedia('(prefers-reduced-motion: reduce)'); } catch (_) {}
    function reduced() { return reducedPref === 'reduce' || Boolean(mql && mql.matches) || document.documentElement.dataset.motion === 'reduce' || window.AtelierMotionPolicy?.allows(2) === false; }

    var t = 0, raf = 0, last = 0, frames = 0, sleeping = true, destroyed = false, onScreen = true, io = null;
    var releaseMoment = null, microMode = false, microHost = null, micro = null;
    // An outcome performs once (tau runs to its duration) and then holds; `settled` outcomes
    // never draw again. A result mounted directly starts from the still pose, or settled.
    var state = OUTCOME[opts.state] ? opts.state : 'busy', t0 = 0, tau = 0, live = false;
    var settled = state !== 'busy' && !!opts.settled;
    function release() { if (releaseMoment) releaseMoment(); releaseMoment = null; }
    function clearMicro() { micro?.destroy(); micro = null; microHost?.remove(); microHost = null; microMode = false; svg.style.display = ''; host.removeAttribute('data-am-micro'); }
    // The large formation needs the screen's one moment; refused, it shows the busy glyph.
    function ownership() {
      if (reduced()) { release(); clearMicro(); return; }
      if (!releaseMoment) releaseMoment = window.AtelierMotion.moment?.claim(opts.kind || 'formation', opts.tier || 2) || null;
      if (releaseMoment || !window.AtelierMotion.moment) { clearMicro(); return; }
      microMode = true; svg.style.display = 'none'; host.setAttribute('data-am-micro', 'true');
      if (!microHost) {
        microHost = document.createElement('span'); microHost.className = 'am-stage-micro'; host.append(microHost);
        try { micro = window.AtelierMotion.krackleGlyph.mount(microHost, {state: state}); } catch (_) {}
      }
    }
    function draw() {
      if (state === 'busy') well.render(reduced() ? STILL : channels(t));
      else {
        // A performed result redraws where it stopped; reduced motion and reopened results
        // show the outcome's still pose.
        var still = reduced() || (settled && !live);
        well.render(outcomeChannels(t0, still ? OUTCOME[state].still : tau, state, live && !still));
      }
      frames++;
    }
    function sleep() {
      release(); sleeping = true; host.setAttribute('data-am-sleeping', 'true');
      if (raf) cancelAnimationFrame(raf);
      raf = 0; last = 0;
    }
    function frame(now) {
      raf = 0;
      if (destroyed) return;
      var dt = last ? Math.min((now - last) / 1000, 1 / 30) : 1 / 60;
      last = now;
      if (state === 'busy') t += dt;
      else if ((tau += dt) >= OUTCOME[state].dur) { tau = OUTCOME[state].dur; draw(); settled = true; sleep(); return; }
      draw();
      if (document.hidden || !onScreen || reduced()) { sleep(); return; }
      raf = requestAnimationFrame(frame);
    }
    function wake() {
      if (destroyed) return;
      host.setAttribute('data-am-reduced', String(reduced()));
      if (settled || document.hidden || !onScreen) { sleep(); return; }
      ownership();
      if (microMode) { sleep(); return; }
      if (reduced()) { if (state !== 'busy') settled = true; draw(); sleep(); return; }
      sleeping = false; host.setAttribute('data-am-sleeping', 'false');
      if (!raf) raf = requestAnimationFrame(frame);
    }
    function onEnvironment() { if (!destroyed) wake(); }
    if (mql && typeof mql.addEventListener === 'function') mql.addEventListener('change', onEnvironment);
    document.addEventListener('visibilitychange', onEnvironment);
    window.addEventListener('atelier:inks', onEnvironment);
    // A well in a hidden dialog never draws; showing the dialog resumes it where it was.
    if (typeof IntersectionObserver === 'function') {
      io = new IntersectionObserver(function (entries) {
        onScreen = entries[entries.length - 1].isIntersecting;
        if (onScreen) onEnvironment(); else sleep();
      });
      io.observe(host);
    }

    host.setAttribute('data-atelier-motion', 'ink-well');
    host.setAttribute('data-am-state', state);
    host.setAttribute('data-am-sleeping', 'true');
    var handle = {
      // Results interrupt at once and perform from wherever the cook is; busy after a result
      // (a retry) starts cooking again.
      setState: function (next) {
        if (destroyed || next === state || !(next === 'busy' || OUTCOME[next])) return;
        var wasBusy = state === 'busy';
        state = next; tau = 0; settled = false; t0 = t; live = next !== 'busy' && wasBusy && !reduced();
        host.setAttribute('data-am-state', next);
        micro?.setState(next);
        if (sleeping) draw();
        wake();
        var sound = OUTCOME[next] && OUTCOME[next].sound;
        if (sound && !sleeping && !microMode && releaseMoment && window.AtelierMotionPolicy?.allows(3)) window.AtelierFoley?.play(sound);
      },
      setPalette: function (colours) { if (destroyed) return; well.setPalette(colours); if (sleeping) draw(); },
      setReducedMotion: function (mode) { if (destroyed) return; reducedPref = mode === 'reduce' ? 'reduce' : 'system'; onEnvironment(); },
      frames: function () { return frames; },
      destroy: function () {
        if (destroyed) return;
        destroyed = true;
        sleep(); clearMicro();
        if (io) io.disconnect();
        if (mql && typeof mql.removeEventListener === 'function') mql.removeEventListener('change', onEnvironment);
        document.removeEventListener('visibilitychange', onEnvironment);
        window.removeEventListener('atelier:inks', onEnvironment);
        if (svg.parentNode === host) host.removeChild(svg);
        ['data-atelier-motion', 'data-am-state', 'data-am-reduced', 'data-am-sleeping'].forEach(function (name) { host.removeAttribute(name); });
        if (mounted && mounted.get(host) === handle) mounted.delete(host);
      }
    };
    if (mounted) mounted.set(host, handle);
    draw();
    wake();
    return handle;
  }

  window.AtelierMotion = window.AtelierMotion || {};
  window.AtelierMotion.inkWell = {mount: mount};
})();
