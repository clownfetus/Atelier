/*
 * Atelier — Krackle stage (particle formations, plain Canvas 2D)
 * Classic-script IIFE adding window.AtelierMotion.krackleStage.
 * The full Krackle language for real work, ported from the living-krackle prototype
 * without p5.js: every job starts as a drop of ink that splashes and is drawn out
 * into a charging ring of comic-sized dots; a result pops into a starburst, cracks
 * the ring so a chunk falls out, or squeezes and bursts into a knocked-out splat.
 * States: idle, busy, success, warning, error. Settled results stop drawing; only
 * busy keeps the frame loop alive. Reduced motion jumps straight to each formation.
 * Hidden documents pause. mount() throws when canvas is unavailable, so callers keep
 * their existing static progress UI as the fallback.
 */
(function () {
  'use strict';

  var STATES = new Set(['idle', 'busy', 'success', 'warning', 'error']);
  var TAU = Math.PI * 2;
  var DROP_T = 0.42, DROP_DUR = 1.05, PUDDLE = 118;
  var SETTLE = {success: 1.5, warning: 1.5, error: 3.3};
  var CODE = {drop: 5, busy: 11, success: 23, warning: 37, error: 53};
  var DIZZY_C = [0, -262, 70, 20];
  var K_CHARGE = 0, K_RIFT = 1, K_SUCCESS = 2, K_WARN = 3, K_FAULT = 4;
  var R_SHAPE = 0, R_DUST = 1, R_SPLASH = 2, R_CHUNK = 3, R_DIZZY = 4;
  var SVG_NS = 'http://www.w3.org/2000/svg';
  var mounted = typeof WeakMap === 'function' ? new WeakMap() : null;
  var uid = 0;

  // ── small maths ──
  function mulberry32(a) {
    return function () {
      a |= 0; a = a + 0x6D2B79F5 | 0;
      var t = Math.imul(a ^ a >>> 15, 1 | a);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };
  }
  function clamp01(v) { return Math.max(0, Math.min(1, v)); }
  function span(t, a, b) { return clamp01((t - a) / (b - a)); }
  function smooth(e0, e1, x) { var t = clamp01((x - e0) / (e1 - e0)); return t * t * (3 - 2 * t); }
  function easeOutBack(u) { var c1 = 1.70158, c3 = c1 + 1; return 1 + c3 * Math.pow(u - 1, 3) + c1 * Math.pow(u - 1, 2); }
  function easeOutCubic(u) { return 1 - Math.pow(1 - u, 3); }
  function easeOutBounce(u) {
    var n = 7.5625, d = 2.75;
    if (u < 1 / d) return n * u * u;
    if (u < 2 / d) { u -= 1.5 / d; return n * u * u + 0.75; }
    if (u < 2.5 / d) { u -= 2.25 / d; return n * u * u + 0.9375; }
    u -= 2.625 / d; return n * u * u + 0.984375;
  }
  function distSeg(px, py, ax, ay, bx, by) {
    var dx = bx - ax, dy = by - ay;
    var t = clamp01(((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy));
    return Math.hypot(px - ax - t * dx, py - ay - t * dy);
  }
  function polySD(px, py, pts) {
    var d = Infinity, inside = false;
    for (var i = 0, j = pts.length - 1; i < pts.length; j = i++) {
      var xi = pts[i][0], yi = pts[i][1], xj = pts[j][0], yj = pts[j][1];
      d = Math.min(d, distSeg(px, py, xi, yi, xj, yj));
      if ((yi > py) !== (yj > py) && px < (xj - xi) * (py - yi) / (yj - yi) + xi) inside = !inside;
    }
    return inside ? -d : d;
  }

  // ── the shared screen: every formation samples one 45° lattice ──
  function lattice(x0, y0, x1, y1, P, fn) {
    var c = Math.SQRT1_2, out = [];
    var us = [(x0 + y0) * c, (x1 + y0) * c, (x0 + y1) * c, (x1 + y1) * c];
    var vs = [(y0 - x0) * c, (y0 - x1) * c, (y1 - x0) * c, (y1 - x1) * c];
    var i0 = Math.floor(Math.min.apply(null, us) / P), i1 = Math.ceil(Math.max.apply(null, us) / P);
    var j0 = Math.floor(Math.min.apply(null, vs) / P), j1 = Math.ceil(Math.max.apply(null, vs) / P);
    for (var i = i0; i <= i1; i++) for (var j = j0; j <= j1; j++) {
      var u = i * P, v = j * P, x = (u - v) * c, y = (u + v) * c;
      if (x < x0 || x > x1 || y < y0 || y > y1) continue;
      var t = fn(x, y); if (t) out.push(t);
    }
    return out;
  }

  // ── formations: none of them draws a symbol ──
  function fRing(P) {
    var r1 = 180, r2 = 250;
    return lattice(-r2 - P, -r2 - P, r2 + P, r2 + P, P, function (x, y) {
      var d = Math.hypot(x, y), dens = smooth(-P * 0.5, P * 1.4, Math.min(d - r1, r2 - d));
      return dens < 0.04 ? null : {x: x, y: y, r: P * 0.5 * Math.sqrt(dens) * 0.92, k: K_CHARGE, m: 0};
    });
  }
  function fMask(P,mask) {
    return lattice(-240,-240,240,240,P,function(x,y){
      var px=Math.min(mask.width-1,Math.max(0,Math.round((x+240)/480*(mask.width-1))));
      var py=Math.min(mask.height-1,Math.max(0,Math.round((y+240)/480*(mask.height-1))));
      return mask.data[(py*mask.width+px)*4+3]>128?{x:x,y:y,r:P*.5,k:K_CHARGE,m:0}:null;
    });
  }
  function fBurst(P, rnd) {
    var S = 205, n = 10 + Math.floor(rnd() * 3), ph = rnd() * TAU, pts = [];
    for (var k = 0; k < n * 2; k++) {
      var a = ph + k * Math.PI / n + (rnd() - 0.5) * 0.12;
      var r = (k % 2 === 0 ? 1.0 + rnd() * 0.2 : 0.5 + rnd() * 0.06) * S;
      pts.push([Math.cos(a) * r, Math.sin(a) * r]);
    }
    var E = S * 1.25;
    return lattice(-E, -E, E, E, P, function (x, y) {
      var dens = smooth(P * 0.55, -P * 1.0, polySD(x, y, pts));
      return dens < 0.04 ? null : {x: x, y: y, r: P * 0.58 * Math.sqrt(dens), k: K_SUCCESS, m: 0};
    });
  }
  function fCracked(P, rnd) {
    var r1 = 176, r2 = 246, gap = 0.32 * Math.PI + (rnd() - 0.5) * 0.3, half = 0.36;
    function angDist(a) { return Math.abs(((((a - gap) % TAU) + TAU + Math.PI) % TAU) - Math.PI); }
    var out = lattice(-r2 - P, -r2 - P, r2 + P, r2 + P, P, function (x, y) {
      var d = Math.hypot(x, y);
      var dens = smooth(-P * 0.5, P * 1.4, Math.min(d - r1, r2 - d)) * smooth(half, half + 0.16, angDist(Math.atan2(y, x)));
      return dens < 0.04 ? null : {x: x, y: y, r: P * 0.5 * Math.sqrt(dens) * 0.95, k: K_WARN, m: 0};
    });
    var gx = Math.cos(gap) * (r1 + r2) / 2, gy = Math.sin(gap) * (r1 + r2) / 2;
    var fx = gx + 46, fy = r2 + 36, cr = 44;
    lattice(fx - cr - P, fy - cr - P, fx + cr + P, fy + cr + P, P, function (x, y) {
      var dens = smooth(cr + P * 0.4, cr - P * 1.0, Math.hypot(x - fx, (y - fy) * 1.25));
      if (dens >= 0.04) out.push({x: x, y: y, r: P * 0.55 * Math.sqrt(dens), k: K_WARN, m: 0, role: R_CHUNK, dx: gx - fx, dy: gy - fy});
      return null;
    });
    return out;
  }
  function fSplat(P, rnd) {
    var R0 = 158, cy0 = -24;
    var harm = [3, 4, 5, 7].map(function (k) { return [k, 0.04 + rnd() * 0.07, rnd() * TAU]; });
    function clearSky() { var a; do { a = rnd() * TAU; } while (Math.abs(((a + Math.PI / 2 + Math.PI) % TAU) - Math.PI) < 0.6); return a; }
    var spikes = [], sats = [], k;
    for (k = 6 + Math.floor(rnd() * 3); k > 0; k--) spikes.push({a: clearSky(), L: R0 * (0.3 + rnd() * 0.45), w: R0 * (0.11 + rnd() * 0.06)});
    for (k = 6 + Math.floor(rnd() * 4); k > 0; k--) {
      var sa = clearSky(), sd = R0 * (1.4 + rnd() * 0.55);
      sats.push([Math.cos(sa) * sd, cy0 + Math.sin(sa) * sd * 0.85, 12 + rnd() * 14]);
    }
    var side = rnd() < 0.5 ? -1 : 1;
    var drips = [{x: side * R0 * (0.18 + rnd() * 0.15), len: R0 * (0.6 + rnd() * 0.3)},
                 {x: -side * R0 * (0.42 + rnd() * 0.12), len: R0 * (0.3 + rnd() * 0.2)}];
    var E = R0 * 2.4;
    var out = lattice(-E, cy0 - E, E, cy0 + E, P, function (x, y) {
      var yy = y - cy0, d = Math.hypot(x, yy), th = Math.atan2(yy, x), rt = R0, i, q;
      for (i = 0; i < harm.length; i++) rt += R0 * harm[i][1] * Math.sin(harm[i][0] * th + harm[i][2]);
      var sdv = d - rt;
      for (i = 0; i < spikes.length; i++) for (q = 0; q <= 3; q++) {
        var f = q / 3, cd = R0 * 0.8 + spikes[i].L * f, cr = spikes[i].w * (1 - 0.3 * f) * (q === 3 ? 1.3 : 1);
        sdv = Math.min(sdv, Math.hypot(x - Math.cos(spikes[i].a) * cd, yy - Math.sin(spikes[i].a) * cd) - cr);
      }
      for (i = 0; i < drips.length; i++) {
        var top = Math.sqrt(Math.max(0, R0 * R0 * 0.8 - drips[i].x * drips[i].x)) * 0.9;
        sdv = Math.min(sdv, distSeg(x, yy, drips[i].x, top, drips[i].x, top + drips[i].len) - R0 * 0.075,
          Math.hypot(x - drips[i].x, yy - top - drips[i].len) - R0 * 0.13);
      }
      for (i = 0; i < sats.length; i++) sdv = Math.min(sdv, Math.hypot(x - sats[i][0], y - sats[i][1]) - sats[i][2]);
      var dens = smooth(P * 0.5, -P * 0.9, sdv);
      return dens < 0.04 ? null : {x: x, y: y, r: P * 0.8 * Math.sqrt(dens), k: K_FAULT, m: 1};
    });
    sats.forEach(function (s) { out.push({x: s[0], y: s[1], r: Math.max(P * 0.6, s[2] * 0.85), k: K_FAULT, m: 1}); });
    return out;
  }

  function parseColour(ctx, value, fallback) {
    ctx.fillStyle = fallback;
    if (value) ctx.fillStyle = value.trim();
    var c = ctx.fillStyle;
    if (c.charAt(0) === '#') {
      var n = parseInt(c.slice(1), 16);
      return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
    }
    var m = c.match(/[\d.]+/g) || [0, 0, 0];
    return [Number(m[0]), Number(m[1]), Number(m[2])];
  }

  function mount(host, options) {
    if (!host || host.nodeType !== 1) throw new Error('AtelierMotion.krackleStage.mount requires a DOM host.');
    var prior = mounted ? mounted.get(host) : null;
    if (prior) prior.destroy();
    if (host.childNodes.length) throw new Error('Krackle stage needs an empty host.');
    var opts = options || {};
    var size = Math.max(96, Math.min(480, Number(opts.size) || 200));
    var canvas = document.createElement('canvas');
    var ctx = canvas.getContext && canvas.getContext('2d');
    if (!ctx) throw new Error('Canvas 2D unavailable');

    var dpr = Math.min(2, window.devicePixelRatio || 1);
    var k = size / 700;                 // logical formation units to CSS pixels (±350 fits)
    var P = Math.max(16, 8 / k);         // pitch: dots stay comic-sized on screen
    var gooCanvas = document.createElement('canvas');
    var gooCtx = gooCanvas.getContext('2d');
    canvas.width = gooCanvas.width = Math.round(size * dpr);
    canvas.height = gooCanvas.height = Math.round(size * dpr);
    canvas.style.width = canvas.style.height = size + 'px';
    canvas.className = 'am-krackle-stage-canvas';
    canvas.setAttribute('aria-hidden', 'true');

    var filterId = 'am-krackle-goo-' + (++uid);
    var filterSvg = document.createElementNS(SVG_NS, 'svg');
    filterSvg.setAttribute('class', 'am-krackle-stage-filter');
    filterSvg.setAttribute('width', '0'); filterSvg.setAttribute('height', '0'); filterSvg.setAttribute('aria-hidden', 'true');
    filterSvg.innerHTML = '<filter id="' + filterId + '" color-interpolation-filters="sRGB"><feGaussianBlur stdDeviation="' +
      (11 * k * dpr).toFixed(2) + '" result="b"/><feColorMatrix in="b" mode="matrix" values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 22 -9"/></filter>';
    host.appendChild(filterSvg);
    host.appendChild(canvas);
    var gooOk = typeof ctx.filter === 'string';
    var gooSlow = 0, gooFrames = 0;

    var state = STATES.has(opts.state) ? opts.state : 'idle';
    var reducedPref = opts.reducedMotion === 'reduce' ? 'reduce' : 'system';
    var mql = null;
    try { mql = (window.AtelierMotionPolicy && window.AtelierMotionPolicy.query()) || window.matchMedia('(prefers-reduced-motion: reduce)'); } catch (_) {}
    function reduced() { return reducedPref === 'reduce' || Boolean(mql && mql.matches) || document.documentElement.dataset.motion === 'reduce' || window.AtelierMotionPolicy?.allows(2)===false || microMode; }
    var releaseMoment=null,microMode=false,microHost=null,micro=null;
    function release() {if(releaseMoment)releaseMoment();releaseMoment=null;}
    function clearMicro() {micro?.destroy();micro=null;microHost?.remove();microHost=null;microMode=false;canvas.style.display='';host.removeAttribute('data-am-micro');}
    function ownership() {
      if(reducedPref==='reduce'||window.AtelierMotionPolicy?.allows(2)===false){release();clearMicro();return;}
      if(!releaseMoment)releaseMoment=window.AtelierMotion.moment?.claim(opts.kind||'formation',opts.tier||2)||null;
      if(releaseMoment){clearMicro();return;}
      microMode=true;canvas.style.display='none';host.setAttribute('data-am-micro','true');
      if(!microHost){microHost=document.createElement('span');microHost.className='am-stage-micro';host.append(microHost);try{micro=window.AtelierMotion.krackleGlyph.mount(microHost,{state:state==='idle'?'info':state});}catch(_){}}
      micro?.setState(state==='idle'?'info':state);
    }

    // ── dot pool ──
    var rndSeed = 12345 + uid * 101, results = 0;
    var sample = [fRing(P), fBurst(P, mulberry32(1)), fCracked(P, mulberry32(2)), fSplat(P, mulberry32(3))];
    if(opts.mask)sample.push(fMask(P,opts.mask));
    var POOL = Math.max.apply(null, sample.map(function (f) { return f.length; })) + 60;
    function F() { return new Float32Array(POOL); }
    var X = F(), Y = F(), VX = F(), VY = F(), R = F(), TX = F(), TY = F(), TR = F(), PA = F(), PR = F(), BASE = F(), DELAY = F();
    var AL = F(), TAL = F(), M = F(), TM = F(), COLT = F(), WAVE = F(), KICK = F(), DX = F(), DY = F(), SF = F(), SH = F();
    var KFROM = new Uint8Array(POOL), KTO = new Uint8Array(POOL), ROLE = new Uint8Array(POOL), SPECK = new Uint8Array(POOL), DEPTH = new Uint8Array(POOL);
    var kr = mulberry32(rndSeed);
    for (var i0 = 0; i0 < POOL; i0++) { SF[i0] = 0.55 + 1.55 * Math.pow(kr(), 2.2); SPECK[i0] = kr() < 0.32 ? 1 : 0; M[i0] = 1; COLT[i0] = 1; }

    var form = 'idle', formStart = 0, clock = 0, carryHead = 0, kicked = false, fromInk = false;
    var progress=0;
    var inks = [], hole = [18, 18, 22], successHole=[18,18,22], glint = [238,229,207];
    var raf = 0, last = 0, sleeping = true, destroyed = false, frames = 0;

    function readInks() {
      var cs = getComputedStyle(host);
      inks = [
        parseColour(ctx, cs.getPropertyValue('--krackle-charge'), '#37639d'),
        parseColour(ctx, cs.getPropertyValue('--krackle-rift'), '#665b8a'),
        parseColour(ctx, cs.getPropertyValue('--krackle-success'), '#3e6d4a'),
        parseColour(ctx, cs.getPropertyValue('--krackle-warn'), '#786020'),
        parseColour(ctx, cs.getPropertyValue('--krackle-fault'), '#ad3032')
      ];
      hole = parseColour(ctx, cs.getPropertyValue('--krackle-hole'), '#121216');
      successHole = parseColour(ctx, cs.getPropertyValue('--krackle-success-hole'), '#121216');
    }

    function headAngle(tau) { return carryHead + tau * 0.7 * TAU; }
    function waveAt(a, head) {
      var dlt = (((head - a) % TAU) + TAU) % TAU, tr = 0.45 * TAU;
      if (dlt < tr) return Math.pow(1 - dlt / tr, 1.6);
      if (dlt > TAU - 0.2) return (dlt - (TAU - 0.2)) / 0.2 * 0.55;
      return 0;
    }

    function enterDrop(rnd) {
      for (var i = 0; i < POOL; i++) {
        var splash = i % 24 === 0;
        var a = rnd() * TAU, d = splash ? PUDDLE * (1.25 + rnd() * 0.75) : Math.sqrt(rnd()) * PUDDLE;
        TX[i] = Math.cos(a) * d; TY[i] = Math.sin(a) * d * 0.92;
        TR[i] = BASE[i] = splash ? P * (0.45 + rnd() * 0.35) : P * 0.95;
        PA[i] = a; PR[i] = d; ROLE[i] = splash ? R_SPLASH : R_SHAPE; TAL[i] = 1; TM[i] = 1; KICK[i] = 0.7 + rnd() * 0.6;
        KFROM[i] = COLT[i] >= 0.5 ? KTO[i] : KFROM[i]; KTO[i] = K_CHARGE; COLT[i] = 0;
        DELAY[i] = DROP_T + (splash ? 0 : d / PUDDLE * 0.05);
        if (AL[i] < 0.05 || R[i] < 0.3) { X[i] = Y[i] = VX[i] = VY[i] = 0; R[i] = 0; M[i] = 1; AL[i] = 1; }
      }
    }

    function enterForm(name) {
      if (name === 'drop' && reduced()) name = 'busy';
      if (form === 'busy') carryHead = headAngle(clock - formStart);
      fromInk = form === 'drop' && name === 'busy';
      form = name; formStart = clock; kicked = false;
      var rnd = mulberry32(rndSeed + CODE[name] + 1 + results * 977);
      if (name === 'drop') { enterDrop(rnd); return; }
      var shape = name === 'busy' ? (opts.mask?fMask(P,opts.mask):fRing(P)) : name === 'success' ? fBurst(P, rnd) : name === 'warning' ? fCracked(P, rnd) : fSplat(P, rnd);
      if (shape.length > POOL - 4) { shape.sort(function (a, b) { return b.r - a.r; }); shape.length = POOL - 4; }
      var solid = {}, Q = Math.SQRT1_2 / P;
      function cell(t) { return [Math.round((t.x + t.y) * Q), Math.round((t.y - t.x) * Q)]; }
      shape.forEach(function (t) { if (t.r > P * 0.15) { var c = cell(t); solid[c[0] + ',' + c[1]] = 1; } });
      // Lattice steps to the nearest gap: bubbles may only sit this far inside the silhouette.
      function depthOf(t) {
        var c = cell(t);
        for (var d = 1; d <= 3; d++) for (var a = -d; a <= d; a++) for (var b = -d; b <= d; b++) {
          if (Math.abs(a) + Math.abs(b) === d && !solid[(c[0] + a) + ',' + (c[1] + b)]) return d - 1;
        }
        return 3;
      }
      var targets = shape.map(function (t) { return {x: t.x, y: t.y, r: t.r, k: t.k, m: t.m, role: t.role || R_SHAPE, dx: t.dx || 0, dy: t.dy || 0, al: 1, depth: depthOf(t)}; });
      var visible = name === 'busy' || name === 'success' ? 6 : 0, n = 0, dizzy = 0;
      for (var i = shape.length; i < POOL; i++, n++) {
        if (name === 'error' && dizzy < 3) {
          targets.push({x: DIZZY_C[0], y: DIZZY_C[1], r: P * 0.8, k: K_FAULT, m: 0, role: R_DIZZY, dz: dizzy++, al: 1});
        } else if (n < visible) {
          var a = rnd() * TAU, d = 280 + rnd() * 55;
          targets.push({x: Math.cos(a) * d, y: Math.sin(a) * d, r: P * (0.24 + rnd() * 0.16), k: name === 'success' ? K_SUCCESS : K_RIFT, m: 0, role: R_DUST, al: 1});
        } else {
          var t0 = shape[Math.floor(rnd() * shape.length)] || {x: 0, y: 0, k: K_CHARGE};
          targets.push({x: t0.x, y: t0.y, r: 0, k: t0.k, m: 0, role: R_DUST, al: 0});
        }
      }
      var jit = mulberry32(rndSeed * 13 + CODE[name]), J = 0.38 * P;
      targets.sort(function (a, b) { return Math.atan2(a.y, a.x) - Math.atan2(b.y, b.x); });
      var order = [];
      for (var o = 0; o < POOL; o++) order.push(o);
      order.sort(function (a, b) { return Math.atan2(Y[a], X[a]) - Math.atan2(Y[b], X[b]); });
      var rm = reduced();
      order.forEach(function (i, j) {
        var t = targets[j];
        if (t.role === R_SHAPE || t.role === R_CHUNK) { t.x += (jit() - 0.5) * 2 * J; t.y += (jit() - 0.5) * 2 * J; }
        TX[i] = t.x; TY[i] = t.y; TR[i] = t.r; BASE[i] = t.r;
        PA[i] = t.role === R_DIZZY ? t.dz * TAU / 3 : Math.atan2(t.y, t.x); PR[i] = Math.hypot(t.x, t.y);
        ROLE[i] = t.role; DX[i] = t.dx || 0; DY[i] = t.dy || 0; TAL[i] = t.al; TM[i] = t.m; KICK[i] = 0.7 + rnd() * 0.6; DEPTH[i] = t.depth || 0;
        KFROM[i] = COLT[i] >= 0.5 ? KTO[i] : KFROM[i]; KTO[i] = t.k; COLT[i] = 0;
        var dist = Math.hypot(t.x, t.y);
        if (name === 'busy' && fromInk) DELAY[i] = 0.04 + (1 - clamp01(Math.hypot(X[i], Y[i]) / PUDDLE)) * 0.34;
        else if (name === 'busy') DELAY[i] = 0.1 * ((PA[i] + Math.PI) / TAU);
        else if (name === 'success') DELAY[i] = 0.18 + rnd() * 0.05 + dist / 400 * 0.06;
        else if (name === 'warning') DELAY[i] = t.role === R_CHUNK ? 0.1 : 0.08 + clamp01((t.y + 200) / 600) * 0.12;
        else DELAY[i] = t.role === R_DIZZY ? 0.5 : rnd() * 0.04;
        if (rm) { X[i] = t.x; Y[i] = t.y; R[i] = t.r; VX[i] = VY[i] = 0; AL[i] = t.al; M[i] = t.m; COLT[i] = 1; }
      });
      compose(name, rnd);
    }

    // Graphic hierarchy: energy defines the silhouette, bubbles only texture it. Each
    // result places a few deliberate dark masses deep inside the shape on the shadow
    // side (overlapping bubbles that merge), scatters a sparse fringe of single bubbles,
    // and leaves the rest as clean energy. Only dots at least one lattice step inside
    // the shape (DEPTH) may carry a bubble, so edges never perforate. SH is per dot:
    // 0 none, (0, 0.75) a single bubble, >= 0.75 part of a mass.
    var MASSES = {busy: [], success: [1.3], warning: [1.5], error: [2.7, 1.7]};
    var SPARSE = {busy: 0.3, success: 0.05, warning: 0.1, error: 0.12};
    function compose(name, rnd) {
      var extent = name === 'error' ? 250 : name === 'success' ? 205 : 248;
      var maxBase = 0, i, j, cand = [];
      for (i = 0; i < POOL; i++) if (ROLE[i] === R_SHAPE || ROLE[i] === R_CHUNK) maxBase = Math.max(maxBase, BASE[i]);
      for (i = 0; i < POOL; i++) {
        SH[i] = 0;
        if ((ROLE[i] === R_SHAPE || ROLE[i] === R_CHUNK) && BASE[i] >= maxBase * 0.5 && DEPTH[i] >= 1) cand.push(i);
      }
      function shadow(i) { return (TX[i] * 0.6 + TY[i] * 0.8) / extent + (ROLE[i] === R_CHUNK && name === 'warning' ? 2 : 0); }
      var centres = [];
      (MASSES[name] || []).forEach(function (mr, n) {
        var best = -1, score = -1e9;
        cand.forEach(function (c) {
          if (DEPTH[c] < (mr > 2 ? 2 : 1)) return;
          var sc = shadow(c) + (rnd() - 0.5) * 0.35;
          for (var q = 0; q < centres.length; q++) if (Math.hypot(TX[c] - centres[q].x, TY[c] - centres[q].y) < (centres[q].r + mr * P) * 1.1) sc -= 9;
          if (sc > score) { score = sc; best = c; }
        });
        if (best >= 0) centres.push({x: TX[best], y: TY[best], r: mr * P});
      });
      cand.forEach(function (c) {
        var m = 0;
        for (j = 0; j < centres.length; j++) m = Math.max(m, 1 - Math.hypot(TX[c] - centres[j].x, TY[c] - centres[j].y) / centres[j].r);
        if (m > 0) SH[c] = 0.75 + 0.25 * m;
        else if (shadow(c) > -0.1 && rnd() < (SPARSE[name] || 0)) SH[c] = 0.3 + 0.4 * rnd();
      });
    }

    function flowX(x, y, t) { return Math.sin(y * 0.013 + t * 1.7) + 0.6 * Math.sin((x + y) * 0.009 - t * 1.1); }
    function flowY(x, y, t) { return Math.cos(x * 0.012 - t * 1.4) - 0.6 * Math.sin((x - y) * 0.0085 + t * 0.9); }

    function update(dt) {
      var tau = clock - formStart, busy = form === 'busy', rm = reduced();
      var K = 90, C = 2 * 0.6 * Math.sqrt(K), A = 900 * Math.sqrt(P / 9);
      var head = headAngle(tau);
      var stamp = form === 'warning' && !rm ? 1 + 0.12 * (1 - easeOutBack(span(tau, 0.08, 0.42))) : 1;
      var squeeze = form === 'error' && tau < 0.16 && !rm;
      var fall = rm ? 1 : easeOutBounce(span(tau, 0.3, 0.95));
      var i;
      if (!kicked && !rm) {
        if (form === 'drop' && tau >= DROP_T) {
          kicked = true;
          for (i = 0; i < POOL; i++) {
            var a0 = PA[i];
            if (ROLE[i] === R_SPLASH) { var sp = 420 + 340 * KICK[i]; VX[i] = Math.cos(a0) * sp * 0.8; VY[i] = -Math.abs(Math.sin(a0)) * sp - 220; }
            else { var sp2 = 240 * KICK[i]; VX[i] += Math.cos(a0) * sp2; VY[i] += Math.sin(a0) * sp2 * 0.6; }
          }
        } else if (form === 'success' && tau >= 0.18) {
          kicked = true;
          for (i = 0; i < POOL; i++) { var a1 = Math.atan2(Y[i], X[i]), sp3 = 240 + 260 * KICK[i]; VX[i] += Math.cos(a1) * sp3; VY[i] += Math.sin(a1) * sp3; }
        } else if (form === 'error' && tau >= 0.16) {
          kicked = true;
          for (i = 0; i < POOL; i++) {
            if (ROLE[i] === R_DIZZY) continue;
            var a2 = Math.atan2(TY[i], TX[i]), sp4 = (ROLE[i] === R_SHAPE ? 420 : 700) * KICK[i];
            VX[i] += Math.cos(a2) * sp4; VY[i] += Math.sin(a2) * sp4;
          }
        }
      }
      for (i = 0; i < POOL; i++) {
        var tx = TX[i], ty = TY[i], tr = TR[i];
        WAVE[i] = 0;
        if (busy) {
          var shape = ROLE[i] === R_SHAPE, tt = rm ? 0 : tau;
          var a = PA[i] + (shape ? 0.22 : 0.12) * tt;
          var w = waveAt(a, rm ? 0.9 : head);
          var pr = PR[i] + (shape ? 5 * Math.sin(3 * a - tt * 2.2) + 3 * Math.sin(5 * a + tt * 1.3) : 0);
          tx = Math.cos(a) * pr; ty = Math.sin(a) * pr;
          tr = shape ? Math.min(P * 0.64, BASE[i] * (0.42 + 1.05 * w)) : BASE[i] * (1 + 1.2 * w);
          WAVE[i] = w;
        } else if (form === 'success' && tau < 0.18 && ROLE[i] === R_SHAPE) {
          tr *= 1.25;
        } else if (form === 'warning') {
          if (ROLE[i] === R_CHUNK) { tx += DX[i] * (1 - fall); ty += DY[i] * (1 - fall); }
          else if (ROLE[i] === R_SHAPE) { tx *= stamp; ty *= stamp; }
        } else if (form === 'error') {
          if (ROLE[i] === R_DIZZY) {
            var t2 = Math.max(0, tau - 0.55), ad = PA[i] + (rm ? 6 : 9 * (1 - Math.exp(-t2 * 1.1)));
            tx = DIZZY_C[0] + Math.cos(ad) * DIZZY_C[2]; ty = DIZZY_C[1] + Math.sin(ad) * DIZZY_C[3];
            tr = TR[i] * (0.8 + 0.25 * Math.sin(ad));
          } else if (squeeze) { tx *= 0.08; ty *= 0.08; tr *= 0.55; }
        }
        if (rm) { X[i] = tx; Y[i] = ty; R[i] = tr; AL[i] = TAL[i]; M[i] = TM[i]; COLT[i] = 1; VX[i] = VY[i] = 0; continue; }
        COLT[i] = Math.min(1, COLT[i] + dt * 3.2);
        var local = tau - DELAY[i];
        if (local >= 0) {
          var fade = (Math.exp(-local * 2.4) + (busy ? 0.07 : 0)) * (form === 'drop' ? 0.35 : 1);
          var stiff = ROLE[i] === R_DIZZY ? 2.2 : 1;
          VX[i] += (K * stiff * (tx - X[i]) - C * Math.sqrt(stiff) * VX[i] + flowX(X[i], Y[i], clock) * A * fade) * dt;
          VY[i] += (K * stiff * (ty - Y[i]) - C * Math.sqrt(stiff) * VY[i] + flowY(X[i], Y[i], clock) * A * fade) * dt;
        } else { var damp = Math.exp(-3 * dt); VX[i] *= damp; VY[i] *= damp; }
        X[i] += VX[i] * dt; Y[i] += VY[i] * dt;
        if (local < 0) { if (form === 'success' && ROLE[i] === R_SHAPE) R[i] += (tr - R[i]) * Math.min(1, dt * 11); continue; }
        var near = clamp01(1 - Math.hypot(tx - X[i], ty - Y[i]) / 90);
        var arrive = form === 'drop' ? 0.65 + 0.35 * near : 0.62 + 0.38 * near;
        R[i] += (tr * arrive - R[i]) * Math.min(1, dt * 11);
        AL[i] += (TAL[i] - AL[i]) * Math.min(1, dt * 5);
        M[i] += (TM[i] - M[i]) * Math.min(1, dt * (TM[i] > M[i] ? 4 : (fromInk ? 5 : 8)));
      }
    }

    function inkOf(i) {
      if(opts.mask&&form==='busy'&&TY[i]<240-480*progress)return '68,72,80';
      var a = inks[KFROM[i]], b = inks[KTO[i]], t = COLT[i], w = 0;
      var r = a[0] + (b[0] - a[0]) * t, g = a[1] + (b[1] - a[1]) * t, bl = a[2] + (b[2] - a[2]) * t;
      if (w > 0) { r += (glint[0] - r) * w; g += (glint[1] - g) * w; bl += (glint[2] - bl) * w; }
      return ((r | 0) & ~3) + ',' + ((g | 0) & ~3) + ',' + ((bl | 0) & ~3);
    }

    function addCircle(map, key, x, y, r) {
      var p = map[key]; if (!p) { p = map[key] = new Path2D(); }
      p.moveTo(x + r, y); p.arc(x, y, r, 0, TAU);
    }

    function render() {
      var tau = clock - formStart, halo = P * 0.45, S = size * dpr;
      var scale = k * dpr;
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.clearRect(0, 0, S, S);
      if (form === 'idle') return;
      var energy = {}, loose = {}, black = new Path2D(), specks = new Path2D(), anyEnergy = false;
      function bubble(x, y, r, i) {
        if (r < 1.6 / scale) return;
        black.moveTo(x + r, y); black.arc(x, y, r, 0, TAU);
        if (SPECK[i] && r > P * 0.55) { var sr = Math.max(1 / scale, r * 0.22); specks.moveTo(x - r * 0.36 + sr, y - r * 0.38); specks.arc(x - r * 0.36, y - r * 0.38, sr, 0, TAU); }
      }
      function minB(i) { return Math.max(P * 0.2 * SF[i], 2.4 / scale); }
      for (var i = 0; i < POOL; i++) {
        if (R[i] < 0.3 || AL[i] < 0.02) continue;
        var key = inkOf(i), rb = R[i] * SF[i], kk = KTO[i];
        if (ROLE[i] === R_DUST || ROLE[i] === R_DIZZY) {
          var rr = ROLE[i] === R_DIZZY ? R[i] : rb;
          addCircle(loose, key, X[i], Y[i], Math.max(2.4 / scale, rr * 1.15 + halo * 0.45));
          bubble(X[i], Y[i], Math.max(2 / scale, rr * 0.72), i);
        } else if (form === 'drop') {
          addCircle(energy, key, X[i], Y[i], R[i] + halo * 0.65); anyEnergy = true;
          if (i % 9 === 0) bubble(X[i], Y[i], P * 0.34 * SF[i], i);
        } else {
          addCircle(energy, key, X[i], Y[i], (M[i] >= 0.5 ? R[i] + halo * 0.65 : rb + halo * 0.8)); anyEnergy = true;
          // The charge crest swells and catches crisp Paper highlights, never an airbrushed glow.
          if (WAVE[i] > 0.6 && i % 3 === 0) { var hr = Math.max(1.4 / scale, R[i] * 0.38); specks.moveTo(X[i] - R[i] * 0.35 + hr, Y[i] - R[i] * 0.4); specks.arc(X[i] - R[i] * 0.35, Y[i] - R[i] * 0.4, hr, 0, TAU); }
          if (!SH[i]) continue;
          // Bubbles grow in with their dot; a mass's bubbles overlap past the dot spacing.
          var grow = Math.min(1.1, Math.max(0.5, R[i] / Math.max(1e-3, BASE[i])));
          var rb2 = SH[i] >= 0.75 ? P * (0.62 + 2 * (SH[i] - 0.75)) : P * (0.34 + 0.18 * SH[i] + 0.08 * SF[i]);
          bubble(X[i], Y[i], Math.min(P * (0.55 + 0.85 * (DEPTH[i] - 1)), rb2 * grow), i);
        }
      }
      if (form === 'drop' && !reduced() && tau < DROP_T + 0.3) {
        var ckey = inks[K_CHARGE].join(',');
        var blob = function (x, y, r) { addCircle(energy, ckey, x, y, r + 6); anyEnergy = true; black.moveTo(x + r * 0.45, y); black.arc(x, y, r * 0.45, 0, TAU); };
        if (tau < DROP_T) {
          var u = tau / DROP_T, yy = -620 + 620 * u * u, st = 1 + 0.8 * u, dy = 0;
          for (var q = 0; q < 10; q++) { var r = 30 * Math.pow(1 - q / 10, 1.45); blob(0, yy - dy, Math.max(1.6, r)); dy += Math.max(2.5, r * 0.55) * st; }
        } else {
          var g = easeOutCubic(span(tau, DROP_T, DROP_T + 0.12)), fd = 1 - span(tau, DROP_T + 0.1, DROP_T + 0.3), rr2 = (30 + 70 * g) * fd;
          if (rr2 > 1) for (var q2 = -2; q2 <= 2; q2++) blob(q2 * rr2 * 0.45, 0, rr2 * (1 - Math.abs(q2) * 0.22));
        }
      }
      ctx.setTransform(scale, 0, 0, scale, S / 2, S / 2);
      // A success sends a ripple out through the stage.
      if (form === 'success' && !reduced() && tau > 0.18 && tau < 1.2) {
        var rad = 160 + 900 * (tau - 0.18), amp = 1 - span(tau, 0.3, 1.15);
        ctx.fillStyle = 'rgba(' + inks[K_SUCCESS].join(',') + ',' + (0.7 * amp).toFixed(3) + ')';
        ctx.beginPath();
        for (var rp = 0; rp < 40; rp++) { var ra = rp / 40 * TAU, rx = Math.cos(ra) * rad, ry = Math.sin(ra) * rad, rs = (3 + 4 * amp) / k; ctx.moveTo(rx + rs, ry); ctx.arc(rx, ry, rs, 0, TAU); }
        ctx.fill();
      }
      for (var lk in loose) { ctx.fillStyle = 'rgb(' + lk + ')'; ctx.fill(loose[lk]); }
      if (anyEnergy) {
        if (gooOk) {
          gooCtx.setTransform(1, 0, 0, 1, 0, 0);
          gooCtx.clearRect(0, 0, S, S);
          gooCtx.setTransform(scale, 0, 0, scale, S / 2, S / 2);
          for (var ek in energy) { gooCtx.fillStyle = 'rgb(' + ek + ')'; gooCtx.fill(energy[ek]); }
          var t0 = performance.now();
          ctx.save();
          ctx.setTransform(1, 0, 0, 1, 0, 0);
          ctx.filter = 'url(#' + filterId + ')';
          ctx.drawImage(gooCanvas, 0, 0);
          ctx.restore();
          gooSlow = gooSlow * 0.8 + (performance.now() - t0) * 0.2;
          if (++gooFrames > 8 && gooSlow > 12) gooOk = false;
        } else {
          for (var fk in energy) { ctx.fillStyle = 'rgb(' + fk + ')'; ctx.fill(energy[fk]); }
        }
      }
      ctx.fillStyle = 'rgb(' + (form==='success'?successHole:hole).join(',') + ')'; ctx.fill(black);
      ctx.fillStyle = 'rgba(' + glint.join(',') + ',0.9)'; ctx.fill(specks);
    }

    function settled(tau) {
      if (form === 'busy' || form === 'drop') return false;
      if (reduced()) return true;
      if (tau <= (SETTLE[form] || 0)) return false;
      var v = 0;
      for (var i = 0; i < POOL; i++) v = Math.max(v, Math.abs(VX[i]) + Math.abs(VY[i]));
      return v < 6;
    }

    function frame(now) {
      raf = 0;
      if (destroyed) return;
      var dt = last ? Math.min((now - last) / 1000, 1 / 30) : 1 / 60;
      last = now;
      clock += dt;
      var tau = clock - formStart;
      if (form === 'drop' && tau > DROP_DUR) enterForm('busy');
      update(dt);
      render();
      frames++;
      if (settled(clock - formStart) || document.hidden || !onScreen) { sleep(); return; }
      raf = requestAnimationFrame(frame);
    }

    function sleep() {
      release();
      sleeping = true;
      host.setAttribute('data-am-sleeping', 'true');
      if (raf) cancelAnimationFrame(raf);
      raf = 0; last = 0;
    }

    function wake() {
      if (destroyed || form === 'idle') return;
      if(document.hidden||!onScreen){sleep();return;}
      ownership();
      if(microMode){sleep();return;}
      sleeping = false;
      host.setAttribute('data-am-sleeping', 'false');
      if (reduced()) {
        update(0); render(); frames++;
        if (form === 'drop') enterForm('busy');
        update(0); render();
        sleep();
        return;
      }
      if (!raf && !document.hidden && onScreen) raf = requestAnimationFrame(frame);
    }

    function apply(next) {
      readInks();
      if (next === 'idle') { form = 'idle'; clearMicro(); render(); sleep(); return; }
      if(next==='busy')microMode=false;
      // Busy after busy (a quick check running straight into a build) keeps the
      // current performance; only a fresh start drops new ink.
      if (next === 'busy') { if (form !== 'busy' && form !== 'drop') enterForm('drop'); }
      else { results++; enterForm(next); }
      wake();
    }

    function onEnvironment() {
      if (destroyed) return;
      readInks();
      host.setAttribute('data-am-reduced', String(reduced()));
      if (document.hidden) { sleep(); return; }
      if (form !== 'idle' && (form === 'busy' || form === 'drop' || !settled(clock - formStart))) wake();
      else { readInks(); render(); }
    }
    if (mql && typeof mql.addEventListener === 'function') mql.addEventListener('change', onEnvironment);
    document.addEventListener('visibilitychange', onEnvironment);
    window.addEventListener('atelier:inks',onEnvironment);
    // A stage in a hidden dialog never draws; showing the dialog resumes it.
    var onScreen = true, io = null;
    if (typeof IntersectionObserver === 'function') {
      io = new IntersectionObserver(function (entries) {
        onScreen = entries[entries.length - 1].isIntersecting;
        if (onScreen) onEnvironment(); else sleep();
      });
      io.observe(host);
    }

    host.setAttribute('data-atelier-motion', 'krackle-stage');
    host.setAttribute('data-am-state', state);
    host.setAttribute('data-am-reduced', String(reduced()));
    host.setAttribute('data-am-sleeping', 'true');

    var handle = {
      setProgress: function(value) {progress=clamp01(Number(value)||0);if(form==='busy'&&sleeping)render();},
      setState: function (next) {
        if (destroyed || !STATES.has(next) || next === state) return;
        state = next;
        host.setAttribute('data-am-state', state);
        apply(next);
      },
      replay: function () { if (!destroyed && state !== 'idle' && state !== 'busy') apply(state); },
      setReducedMotion: function (mode) {
        if (destroyed) return;
        reducedPref = mode === 'reduce' ? 'reduce' : 'system';
        onEnvironment();
      },
      frames: function () { return frames; },
      destroy: function () {
        if (destroyed) return;
        destroyed = true;
        sleep();
        clearMicro();
        if (io) io.disconnect();
        if (mql && typeof mql.removeEventListener === 'function') mql.removeEventListener('change', onEnvironment);
        document.removeEventListener('visibilitychange', onEnvironment);
        window.removeEventListener('atelier:inks',onEnvironment);
        if (canvas.parentNode === host) host.removeChild(canvas);
        if (filterSvg.parentNode === host) host.removeChild(filterSvg);
        ['data-atelier-motion', 'data-am-state', 'data-am-reduced', 'data-am-sleeping'].forEach(function (name) { host.removeAttribute(name); });
        if (mounted && mounted.get(host) === handle) mounted.delete(host);
      }
    };
    if (mounted) mounted.set(host, handle);
    if (state !== 'idle') apply(state);
    return handle;
  }

  window.AtelierMotion = window.AtelierMotion || {};
  window.AtelierMotion.krackleStage = {mount: mount};
})();
