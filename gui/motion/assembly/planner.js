/*
 * Atelier motion system: collision and path planning (SPEC section 4.1).
 * Pieces travel one at a time along a curve that keeps the halo's width from the others, so
 * nothing passes through anything. Contact a pose is built on (the disc in the A's bites, the X's
 * crossing) is allowed only at the very end of a path; contact the start was built on, only at
 * the very start. Nothing here touches the page. Load after pieces.js.
 */
(() => {
  'use strict';
  const assembly = window.AtelierMotion.assembly;
  const {BRAND, BRAND_SMALL, VB, G, IDS, lerp, lerpObj, clone, quadOf, ringOf} = assembly.pieces;

  // ---------- outlines ----------
  const segDist = (p, a, b) => {
    const dx = b[0] - a[0], dy = b[1] - a[1], l = dx * dx + dy * dy;
    let t = l ? ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l : 0;
    t = Math.max(0, Math.min(1, t));
    return Math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy);
  };
  // A coarse outline, within tol of the true one, to rule out far pieces: planning runs thousands of these.
  function hullOf(P, tol = 1.5) {
    const mid = P.length >> 1, keep = new Set([0, mid, P.length - 1]);
    const go = (a, b) => {
      let m = 0, k = -1;
      for (let i = a + 1; i < b; i++) { const d = segDist(P[i], P[a], P[b]); if (d > m) { m = d; k = i; } }
      if (m > tol) { keep.add(k); go(a, k); go(k, b); }
    };
    go(0, mid); go(mid, P.length - 1);
    return P.filter((_, i) => keep.has(i));
  }
  let hulls = null;
  function coarse() {
    if (hulls) return hulls;
    const blue = hullOf(BRAND.tile), teal = hullOf(BRAND.mesh), sets = {blue, teal};
    // How far the coarse outline can sit inside the true one, either side, at full size.
    const slack = 2 * Math.max(...['blue', 'teal'].map(id => {
      const H = sets[id], F = id === 'blue' ? BRAND.tile : BRAND.mesh;
      return Math.max(...F.map(p => {
        let m = 1e9;
        for (let i = 0; i < H.length; i++) m = Math.min(m, segDist(p, H[i], H[(i + 1) % H.length]));
        return m;
      }));
    }));
    hulls = {blue, teal, slack, small: {blue: hullOf(BRAND_SMALL.tile), teal: hullOf(BRAND_SMALL.mesh)}};
    return hulls;
  }
  function place(pts, o) {
    const c = Math.cos(o.rot * Math.PI / 180), s = Math.sin(o.rot * Math.PI / 180), sc = o.s || 1, out = [];
    for (const [x, y] of pts) out.push([o.x + (x * c - y * s) * sc, o.y + (x * s + y * c) * sc]);
    return out;
  }
  function polyOf(id, o) {
    let pts;
    if ((o.m ?? 0) >= .5) {
      const brand = o.small ? BRAND_SMALL : BRAND, bw = id === 'blue' ? brand.tw : brand.mw, sx = o.w / bw, sy = o.h / brand.h;
      pts = (o.small ? coarse().small : coarse())[id].map(([x, y]) => [x * sx, y * sy]);
    } else pts = quadOf(id, o);
    return place(pts, o);
  }
  function inside(p, poly) {
    let c = false;
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const a = poly[i], b = poly[j];
      if ((a[1] > p[1]) !== (b[1] > p[1]) && p[0] < (b[0] - a[0]) * (p[1] - a[1]) / (b[1] - a[1]) + a[0]) c = !c;
    }
    return c;
  }
  function segX(a, b, c, d) {
    const o = (p, q, r) => Math.sign((q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0]));
    return o(a, b, c) !== o(a, b, d) && o(c, d, a) !== o(c, d, b);
  }
  function polyDist(A, B) {
    // far apart: the gap between bounding boxes is enough, and planning runs thousands of these
    let ax0 = 1e9, ay0 = 1e9, ax1 = -1e9, ay1 = -1e9, bx0 = 1e9, by0 = 1e9, bx1 = -1e9, by1 = -1e9;
    for (const [x, y] of A) { if (x < ax0) ax0 = x; if (x > ax1) ax1 = x; if (y < ay0) ay0 = y; if (y > ay1) ay1 = y; }
    for (const [x, y] of B) { if (x < bx0) bx0 = x; if (x > bx1) bx1 = x; if (y < by0) by0 = y; if (y > by1) by1 = y; }
    const sep = Math.max(ax0 - bx1, bx0 - ax1, ay0 - by1, by0 - ay1);
    if (sep > 30) return sep;
    if (A.some(p => inside(p, B)) || B.some(p => inside(p, A))) return -1;
    let m = 1e9;
    for (const [P, Q] of [[A, B], [B, A]]) for (const p of P) for (let i = 0; i < Q.length; i++) m = Math.min(m, segDist(p, Q[i], Q[(i + 1) % Q.length]));
    // edge crossings without contained vertices
    for (let i = 0; i < A.length; i++) for (let j = 0; j < B.length; j++) if (segX(A[i], A[(i + 1) % A.length], B[j], B[(j + 1) % B.length])) return -1;
    return m;
  }
  // The coarse outline cuts across rounded corners, so it only ever rules out pieces that are clearly
  // far apart. Anything near is measured on the outline actually drawn, or a halo could bite into a neighbour.
  const TRUE_CACHE = new WeakMap();
  function outline(id, o) {
    const hit = TRUE_CACHE.get(o);
    if (hit && hit.x === o.x && hit.y === o.y && hit.rot === o.rot && hit.s === o.s) return hit.pts;
    const pts = place(ringOf(id, o), o);
    TRUE_CACHE.set(o, {x: o.x, y: o.y, rot: o.rot, s: o.s, pts});
    return pts;
  }
  function discGap(d, poly) {
    const c = [d.x, d.y], r = d.r * (d.s || 1);
    if (inside(c, poly)) return -1;
    let m = 1e9;
    for (let k = 0; k < poly.length; k++) m = Math.min(m, segDist(c, poly[k], poly[(k + 1) % poly.length]));
    return m - r;
  }
  // Exact distance between two drawn outlines, looking only at the stretches within lim of each other.
  function nearDist(A, B, lim) {
    const box = P => {
      let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
      for (const [x, y] of P) { if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
      return [x0 - lim, y0 - lim, x1 + lim, y1 + lim];
    };
    const ba = box(A), bb = box(B);
    const near = (P, b) => {
      const o = [];
      for (let i = 0; i < P.length; i++) { const [x, y] = P[i]; if (x > b[0] && x < b[2] && y > b[1] && y < b[3]) o.push(i); }
      return o;
    };
    const ia = near(A, bb), ib = near(B, ba);
    if (ia.some(i => inside(A[i], B)) || ib.some(i => inside(B[i], A))) return -1;
    let m = lim;
    const nl = A.length, ml = B.length;
    for (const i of ia) {
      const a0 = A[i], a1 = A[(i + 1) % nl], a9 = A[(i - 1 + nl) % nl];
      for (const j of ib) {
        const b0 = B[j], b1 = B[(j + 1) % ml], b9 = B[(j - 1 + ml) % ml];
        const d = Math.min(segDist(a0, b0, b1), segDist(a0, b9, b0), segDist(b0, a0, a1), segDist(b0, a9, a0));
        if (d < m) m = d;
        if (segX(a0, a1, b0, b1)) return -1;
      }
    }
    return m;
  }
  // Clearance between two pieces (negative: overlapping).
  function gap(pose, i, j) {
    if (j === 'disc') [i, j] = [j, i];
    const {slack} = coarse();
    if (i === 'disc') {
      const far = discGap(pose.disc, polyOf(j, pose[j]));
      return far > G + slack ? far : discGap(pose.disc, outline(j, pose[j]));
    }
    const far = polyDist(polyOf(i, pose[i]), polyOf(j, pose[j]));
    return far < 0 || far > G + slack ? far : nearDist(outline(i, pose[i]), outline(j, pose[j]), G + slack + 24);
  }
  // For costing paths: exact only where it decides whether a sample is charged.
  function gapPath(pose, i, j) {
    if (i === 'disc' || j === 'disc') return gap(pose, i, j);
    const far = polyDist(polyOf(i, pose[i]), polyOf(j, pose[j])), {slack} = coarse();
    return Math.abs(far - (G - 1)) > slack ? far : nearDist(outline(i, pose[i]), outline(j, pose[j]), G + slack + 24);
  }
  const lerpPose = (a, b, t) => ({blue: lerpObj(a.blue, b.blue, t), teal: lerpObj(a.teal, b.teal, t), disc: lerpObj(a.disc, b.disc, t)});

  // ---------- paths ----------
  const CEN = [240, 200];
  function curvePt(path, u) {
    const S = [path.a.x, path.a.y], T = [path.b.x, path.b.y], c = path.c, m = 1 - u;
    if (!c.length) return [lerp(S[0], T[0], u), lerp(S[1], T[1], u)];
    if (c.length === 1) return [0, 1].map(k => m * m * S[k] + 2 * m * u * c[0][k] + u * u * T[k]);
    return [0, 1].map(k => m * m * m * S[k] + 3 * m * m * u * c[0][k] + 3 * m * u * u * c[1][k] + u * u * u * T[k]);
  }
  function pieceAt(path, u) {
    const o = lerpObj(path.a, path.b, u), q = curvePt(path, u);
    o.x = q[0]; o.y = q[1];
    return o;
  }
  function pathLen(path) {
    let L = 0, p = curvePt(path, 0);
    for (let k = 1; k <= 16; k++) { const q = curvePt(path, k / 16); L += Math.hypot(q[0] - p[0], q[1] - p[1]); p = q; }
    return L;
  }
  // Cost of a path: its length, plus a heavy charge for every bit of undesigned overlap along the way.
  // Layer order is fixed, so an unavoidable crossing just reads as one piece passing in front of another.
  function pathCost(state, id, path, allowStart, allowEnd, limit = Infinity) {
    const tmp = {...state}, len = pathLen(path);
    let over = 0;
    if (len >= limit) return {over, cost: Infinity};
    for (let k = 1; k <= 24; k++) {
      const u = k / 24;
      tmp[id] = pieceAt(path, u);
      const pc = tmp[id], ext = id === 'disc' ? [[pc.x - pc.r, pc.y - pc.r], [pc.x + pc.r, pc.y + pc.r]] : polyOf(id, pc);
      let outby = 0;
      for (const [x, y] of ext) outby = Math.max(outby, -x, -y, x - VB.w, y - VB.h);
      if (outby > 0) over += Math.min(60, outby);
      for (const o of IDS) {
        if (o === id) continue;
        if (allowStart.has(o) && u < .7) continue;
        if (allowEnd.has(o) && u > .3) continue;
        const g = gapPath(tmp, id, o);
        if (g < G - 1) {
          over += Math.min(60, G - g);
          if (len + over * 12 >= limit) return {over, cost: Infinity};
        }
      }
    }
    return {over, cost: len + over * 12};
  }
  const differs = (p, q) => Object.keys(q).some(k => typeof q[k] === 'number' && Math.abs((p[k] ?? q[k]) - q[k]) > .01);
  const perms = a => (a.length < 2 ? [a] : a.flatMap((x, i) => perms([...a.slice(0, i), ...a.slice(i + 1)]).map(p => [x, ...p])));
  // Planning yields between candidates, so a live plan can be spread over several slices of main-thread time.
  function* planPiece(state, id, target, final, initial) {
    const a = state[id], b = target, end = {...state, [id]: b};
    const allowStart = new Set(IDS.filter(o => o !== id && gap(state, id, o) < G - 1 && !differs(state[o], initial[o]) && gap(initial, id, o) < G - 1));
    const allowEnd = new Set(IDS.filter(o => o !== id && gap(end, id, o) < G - 1 && !differs(state[o], final[o])));
    const S = [a.x, a.y], T = [b.x, b.y], M = [(S[0] + T[0]) / 2, (S[1] + T[1]) / 2];
    let n = [S[1] - T[1], T[0] - S[0]];
    const nl = Math.hypot(...n) || 1;
    n = [n[0] / nl, n[1] / nl];
    const out = (Q, k) => { const v = [Q[0] - CEN[0], Q[1] - CEN[1]], l = Math.hypot(...v) || 1; return [Q[0] + v[0] / l * k, Q[1] + v[1] / l * k]; };
    const cands = [[]];
    for (const d of [60, 120, 180]) for (const sg of [1, -1]) cands.push([[M[0] + n[0] * d * sg, M[1] + n[1] * d * sg]]);
    for (const k of [100, 170]) cands.push([out(S, k), out(T, k)]);
    for (let i = 0; i < 12; i++) { const ang = i * Math.PI / 6; cands.push([[CEN[0] + Math.cos(ang) * 210, CEN[1] + Math.sin(ang) * 180]]); }
    const P3 = (f, d) => [S[0] + (T[0] - S[0]) * f + n[0] * d, S[1] + (T[1] - S[1]) * f + n[1] * d];
    for (const d of [90, 150, 210]) for (const sg of [1, -1]) cands.push([P3(.25, d * sg), P3(.75, d * sg)]);
    for (const d of [120, 200]) for (const sg of [1, -1]) cands.push([P3(0, d * sg), P3(1, d * sg)]);
    let best = null;
    for (const c of cands) {
      const path = {a, b, c}, r = pathCost(state, id, path, allowStart, allowEnd, best ? best.cost : Infinity);
      if (!best || r.cost < best.cost) best = {path, ...r};
      yield best;
    }
    return best;
  }
  // Every order of moving the pieces is tried; the preferred order is favoured.
  function* planSteps(from, to, prefer = IDS, progress = {}) {
    const movers = prefer.filter(id => differs(from[id], to[id]));
    let best = null, oi = 0;
    orders: for (const order of perms(movers)) {
      const st = clone(from), steps = [];
      let cost = oi++ ? 40 : 0, over = 0;
      for (const id of order) {
        if (best && cost >= best.cost) continue orders;
        const r = yield* planPiece(st, id, to[id], to, from);
        steps.push({id, path: r.path});
        cost += r.cost; over += r.over;
        st[id] = {...to[id]};
      }
      if (!best || cost < best.cost) progress.best = best = {steps, cost, over};
    }
    return best || {steps: [], cost: 0, over: 0};
  }
  function planSequence(from, to, prefer = IDS, stats = false) {
    const walk = planSteps(from, to, prefer);
    let step = walk.next();
    while (!step.done) step = walk.next();
    return stats ? step.value : step.value.steps;
  }
  // Can everything move at once without touching?
  function simulClear(from, to) {
    const pairs = [['blue', 'teal'], ['blue', 'disc'], ['teal', 'disc']].filter(([i, j]) => gap(from, i, j) >= G - 1 && gap(to, i, j) >= G - 1);
    for (let k = 1; k < 20; k++) {
      const p = lerpPose(from, to, k / 20);
      if (pairs.some(([i, j]) => gap(p, i, j) < G - 1)) return false;
    }
    return true;
  }
  const extent = (id, piece) => (id === 'disc' ? [[piece.x - piece.r, piece.y - piece.r], [piece.x + piece.r, piece.y + piece.r]] : polyOf(id, piece));
  const offCanvas = (pts, m) => pts.some(([x, y]) => x < m || x > VB.w - m || y < m || y > VB.h - m);
  // Come apart: every piece slides straight out from the middle, away from the others, until it
  // nears the edge. Moving apart along those lines can't collide.
  function spreadFor(a, state, open) {
    const q = clone(state), m = 8;
    let cx = 0, cy = 0;
    IDS.forEach(id => { cx += state[id].x; cy += state[id].y; });
    cx /= 3; cy /= 3;
    for (const id of IDS) {
      let v = [state[id].x - cx, state[id].y - cy];
      const l = Math.hypot(...v);
      v = l < 1 ? [0, -1] : [v[0] / l, v[1] / l];
      if (open && id === 'disc') v = [.45, .89];
      const piece = {...state[id]};
      let ok = 0;
      for (let t = 0; t < 300; t += 4) {
        piece.x = state[id].x + v[0] * t; piece.y = state[id].y + v[1] * t;
        if (offCanvas(extent(id, piece), m)) break;
        ok = t;
      }
      piece.x = state[id].x + v[0] * Math.min(ok, 140); piece.y = state[id].y + v[1] * Math.min(ok, 140);
      q[id] = piece;
    }
    return q;
  }
  // Each piece that will dock next swings round to the side it docks from, keeping clear of everything
  // that's still standing where it is.
  function slotsFor(a, state) {
    const q = clone(state), m = 8, anchor = a.order[0], fixed = a.fixed || [];
    for (const id of fixed) q[id] = {...a.contact[id]}; // these go straight to where they'll wait
    const movers = a.order.slice(1).filter(id => !fixed.includes(id)).sort((x, y) => (x === 'disc' ? -1 : y === 'disc' ? 1 : 0));
    const sep = (id, piece, oid, op) => gap({[id]: piece, [oid]: op}, id, oid);
    for (const id of movers) {
      const hard = [[anchor, state[anchor]]], soft = [[anchor, a.contact[anchor]]];
      for (const o of [...movers, ...fixed]) if (o !== id) { hard.push([o, q[o]]); soft.push([o, a.contact[o]]); }
      const clr = (L, piece) => L.reduce((s, [oid, op]) => s + Math.min(sep(id, piece, oid, op), G + 4), 0);
      const pref = Math.atan2(a.dirs[id][1], a.dirs[id][0]);
      let best = null;
      for (const off of [0, .3, -.3, .6, -.6, .9, -.9, 1.2, -1.2, 1.6, -1.6, 2, -2, 2.5, -2.5, 3.14]) {
        const ang = pref + off, piece = {...a.contact[id]};
        let ok = 0;
        for (let t = 0; t < 400; t += 6) {
          piece.x = CEN[0] + Math.cos(ang) * t; piece.y = CEN[1] + Math.sin(ang) * t;
          if (offCanvas(extent(id, piece), m)) break;
          ok = t;
        }
        piece.x = CEN[0] + Math.cos(ang) * ok; piece.y = CEN[1] + Math.sin(ang) * ok;
        const score = clr(hard, piece) + .5 * clr(soft, piece) - Math.abs(off) * 2;
        if (!best || score > best.score) best = {piece, score};
      }
      q[id] = best.piece;
    }
    return q;
  }
  const seated = p => (p.teal.m ?? 0) >= .5 && gap(p, 'teal', 'disc') < G + 6 && gap(p, 'blue', 'disc') < G + 6;

  // ---------- routes: planned ahead at idle, or live on a budget ----------
  // A route is the same whoever asks, so every glyph shares them.
  const ROUTES = new Map(), ROUTE_LIMIT = 512;
  const SLICE_MS = 6, BUDGET_MS = 400;
  const stats = {hits: 0, live: 0, overBudget: 0, longestSlice: 0, planned: 0};
  const n2 = v => (v ?? 0).toFixed(2);
  const pieceKey = o => [n2(o.x), n2(o.y), n2(o.rot), n2(o.w ?? o.r), n2(o.h), n2(o.m), n2(o.k), n2(o.taper ?? o.dx)].join();
  const routeKey = (from, to, prefer) => IDS.map(id => pieceKey(from[id]) + '>' + pieceKey(to[id])).join('|') + '|' + prefer.join();
  function remember(key, steps) {
    if (ROUTES.size >= ROUTE_LIMIT) ROUTES.delete(ROUTES.keys().next().value);
    ROUTES.set(key, steps);
    return steps;
  }
  // Moved straight, in the preferred order, when a plan runs out of time. The fixed layer order means
  // a crossing can only read as one piece passing in front of another.
  const straight = (from, to, prefer) => prefer.filter(id => differs(from[id], to[id])).map(id => ({id, path: {a: from[id], b: to[id], c: []}}));
  // A planned route, or null if it would have to be worked out.
  function known(from, to, prefer = IDS) {
    const hit = ROUTES.get(routeKey(from, to, prefer));
    if (hit) stats.hits++;
    return hit || null;
  }
  // Plans in slices of a few milliseconds, so the page keeps running; a plan took up to 146 ms on one thread.
  function planLive(from, to, prefer = IDS) {
    const key = routeKey(from, to, prefer), progress = {}, walk = planSteps(clone(from), to, prefer, progress), began = performance.now();
    stats.live++;
    return new Promise(resolve => {
      const slice = () => {
        const start = performance.now(), end = start + SLICE_MS;
        let step = walk.next();
        while (!step.done && performance.now() < end) step = walk.next();
        stats.longestSlice = Math.max(stats.longestSlice, performance.now() - start);
        if (step.done) resolve(remember(key, step.value.steps));
        else if (performance.now() - began > BUDGET_MS) { stats.overBudget++; resolve(progress.best ? progress.best.steps : straight(from, to, prefer)); }
        else setTimeout(slice, 0);
      };
      slice();
    });
  }
  // The moves an assembly makes from a starting pose, in order (SPEC section 4.1).
  function* assemblyRoutes(a, target, from) {
    const {standOff} = assembly.pieces, open = seated(from);
    let cur = from;
    if (open) { const s = standOff(cur); yield [cur, s, ['teal']]; cur = s; }
    const sp = spreadFor(a, cur, open);
    if (!simulClear(cur, sp)) yield [cur, sp, IDS];
    const sl = slotsFor(a, sp);
    yield [sp, sl, a.order.slice(1)];
    yield [sl, target, a.order];
  }
  // Everything the working loop and the outcomes go through from a pose they're designed to rest in.
  function* commonRoutes() {
    const {fits, rest, POSES, OUT, STRAIGHT, standOff, logoStart, clone: copy} = assembly.pieces, F = fits(), W = POSES.warning, M = POSES.master;
    const X = copy(POSES.error);
    X.blue.rot -= 6; X.teal.rot += 6;
    for (const a of F) {
      for (const b of F) {
        if (a === b) continue;
        if (STRAIGHT.has(a.name) && STRAIGHT.has(b.name)) yield [a.contact, b.approach, b.order];
        else yield* assemblyRoutes(b, b.approach, a.contact);
      }
    }
    const wait = standOff(M), starts = [...F.flatMap(a => [a.contact, a.tap, a.approach]), rest(), M];
    for (const from of starts) {
      yield* assemblyRoutes({...OUT.warning, contact: W}, W, from);
      yield* assemblyRoutes({...OUT.error, contact: X}, X, from);
    }
    yield* assemblyRoutes({...OUT.master, contact: wait, fixed: ['teal']}, wait, rest());
    yield [wait, M, ['teal']];
    // The logo's entrance.
    const start = logoStart(), waiting = {blue: M.blue, teal: wait.teal, disc: start.disc};
    yield [start, waiting, ['blue', 'teal']];
    yield [waiting, M, ['disc', 'teal']];
  }
  let idle = null;
  const later = fn => (window.requestIdleCallback ? window.requestIdleCallback(fn) : setTimeout(() => fn({timeRemaining: () => 8}), 200));
  // After start-up, in idle time only. It stops as soon as the page has something better to do.
  function precompute() {
    if (idle || window.AtelierMotionPolicy?.mode() === 'off') return;
    idle = {routes: commonRoutes(), walk: null, key: null};
    const run = deadline => {
      while (deadline.timeRemaining() > 1) {
        if (!idle.walk) {
          const next = idle.routes.next();
          if (next.done) { idle.done = true; return; }
          const [from, to, prefer] = next.value;
          idle.key = routeKey(from, to, prefer);
          if (ROUTES.has(idle.key)) continue;
          idle.walk = planSteps(clone(from), to, prefer);
        }
        const step = idle.walk.next();
        if (step.done) { remember(idle.key, step.value.steps); stats.planned++; idle.walk = null; }
      }
      later(run);
    };
    later(run);
  }
  if (document.readyState === 'complete') later(precompute);
  else window.addEventListener('load', () => later(precompute), {once: true});

  assembly.planner = Object.freeze({
    outline, polyOf, gap, lerpPose, curvePt, pieceAt, pathLen, planSteps, planSequence, simulClear, spreadFor, slotsFor, seated,
    known, planLive, precompute, stats, commonRoutes, idleDone: () => Boolean(idle && idle.done), clearRoutes: () => ROUTES.clear(),
  });
})();
