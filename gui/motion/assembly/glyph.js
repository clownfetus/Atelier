/*
 * Atelier motion system: the SVG renderer. Fixed layer order: tile, mesh, disc. Nothing ever
 * re-stacks, so nothing can flicker. Each write is skipped when its value hasn't changed, and path
 * strings are only rebuilt when a piece's shape changes, so most frames only move pieces.
 * The loaders' overlays and the ripple are built the first time they're needed. Load after engine.js.
 */
(() => {
  'use strict';
  const assembly = window.AtelierMotion.assembly;
  const {VB, G, IDS, STATUS, SHINE, shapeKey, piecePath} = assembly.pieces;
  const NS = 'http://www.w3.org/2000/svg';
  const BAND_EDGES = [0, .171, .378, .585, .792, 1];
  let UID = 0;

  function mk(name, attrs, parent, cls) {
    const el = document.createElementNS(NS, name);
    for (const k in attrs) el.setAttribute(k, attrs[k]);
    if (cls) el.setAttribute('class', cls);
    if (parent) parent.appendChild(el);
    return el;
  }
  const f = v => v.toFixed(2);
  const rgb = c => `rgb(${c[0]},${c[1]},${c[2]})`;
  function parseColour(text, fallback) {
    const t = (text || '').trim();
    let m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(t);
    if (m) return [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)];
    m = /^rgba?\(\s*(\d+)[ ,]+(\d+)[ ,]+(\d+)/i.exec(t);
    return m ? [+m[1], +m[2], +m[3]] : fallback;
  }

  function createView(host) {
    const svg = mk('svg', {viewBox: `0 0 ${VB.w} ${VB.h}`, 'aria-hidden': 'true', focusable: 'false'});
    const g = mk('g', {}, svg), defs = mk('defs', {}, svg);
    const parts = {};
    for (const id of IDS) {
      const el = mk(id === 'disc' ? 'circle' : 'path', id === 'disc' ? {cx: 0, cy: 0} : {}, g, 'glyph-piece');
      el.dataset.piece = id;
      parts[id] = {el};
    }
    host.appendChild(svg);

    let ring = null, bands = null, cuts = null, shine = null;
    let lastPunch = 1, lastBox = '', lastOpacity = 1;

    function drawRing(fx) {
      if (!ring && !fx.ringOp) return;
      if (!ring) { ring = mk('circle', {fill: 'none'}); g.insertBefore(ring, g.firstChild); }
      const d = parts.disc;
      ring.setAttribute('cx', d.x); ring.setAttribute('cy', d.y);
      ring.setAttribute('r', f(Math.max(0, fx.ringR)));
      ring.setAttribute('stroke-width', f(Math.max(0, fx.ringW)));
      ring.style.stroke = rgb(fx.ringC);
      ring.style.opacity = fx.ringOp.toFixed(3);
    }
    function drawShape(id, o) {
      const part = parts[id], key = shapeKey(id, o);
      if (key !== part.key) {
        part.key = key;
        part.d = piecePath(id, o, key);
        part.el.setAttribute('d', part.d);
      }
      if (o.x !== part.x || o.y !== part.y || o.rot !== part.rot) {
        part.x = o.x; part.y = o.y; part.rot = o.rot;
        part.el.setAttribute('transform', `translate(${f(o.x)} ${f(o.y)}) rotate(${f(o.rot)})`);
      }
    }
    function drawDisc(d, fx) {
      const part = parts.disc;
      if (d.r !== part.r) { part.r = d.r; part.el.setAttribute('r', f(d.r)); }
      if (d.x !== part.x || d.y !== part.y || fx.dsx !== part.dsx || fx.dsy !== part.dsy) {
        part.x = d.x; part.y = d.y; part.dsx = fx.dsx; part.dsy = fx.dsy;
        part.el.setAttribute('transform', fx.dsx === 1 && fx.dsy === 1 ? `translate(${f(d.x)} ${f(d.y)})` : `translate(${f(d.x)} ${f(d.y)}) scale(${fx.dsx.toFixed(3)} ${fx.dsy.toFixed(3)})`);
      }
    }
    function drawColours(cols) {
      for (const id of IDS) {
        const part = parts[id], c = cols[id];
        if (part.c !== c && (!part.c || part.c[0] !== c[0] || part.c[1] !== c[1] || part.c[2] !== c[2])) part.el.style.fill = rgb(c);
        part.c = c;
      }
    }
    function makeBands() {
      const u = ++UID, group = mk('g', {display: 'none'});
      g.insertBefore(group, parts.teal.el);
      const list = [];
      for (let i = 0; i < BAND_EDGES.length - 1; i++) {
        const clip = mk('clipPath', {id: `glyph-band-${u}-${i}`}, defs), rect = mk('rect', {}, clip);
        const outer = mk('g', {}, group), inner = mk('g', {'clip-path': `url(#glyph-band-${u}-${i})`}, outer);
        list.push({rect, outer, path: mk('path', {}, inner, 'glyph-piece')});
      }
      return {group, list};
    }
    function makeCuts() {
      const u = ++UID, clip = mk('clipPath', {id: `glyph-cuts-${u}`}, defs), shape = mk('path', {}, clip);
      const group = mk('g', {'clip-path': `url(#glyph-cuts-${u})`, display: 'none'});
      g.insertBefore(group, parts.disc.el);
      const lines = [];
      for (let i = 0; i < 4; i++) lines.push(mk('line', {}, group, 'glyph-cut'));
      return {shape, group, lines};
    }
    function makeShine() {
      const u = ++UID, clip = mk('clipPath', {id: `glyph-shine-${u}`}, defs), circle = mk('circle', {cx: 0, cy: 0}, clip);
      const group = mk('g', {'clip-path': `url(#glyph-shine-${u})`, display: 'none'}, g), turn = mk('g', {}, group);
      const wide = mk('rect', {}, turn), thin = mk('rect', {}, turn);
      wide.style.fill = rgb(SHINE); thin.style.fill = rgb(SHINE);
      return {circle, group, turn, wide, thin};
    }
    function drawLoad(pose, load) {
      const b = pose.blue, t = pose.teal, d = pose.disc, kind = load && load.kind;
      parts.blue.el.style.display = kind === 'texture' ? 'none' : '';
      if (kind === 'texture') {
        bands ||= makeBands();
        bands.group.removeAttribute('display');
        const H = b.h, half = load.gap / 2, shape = parts.blue.d;
        bands.list.forEach((band, i) => {
          const top = -H / 2 + BAND_EDGES[i] * H, slice = (BAND_EDGES[i + 1] - BAND_EDGES[i]) * H;
          band.rect.setAttribute('x', f(-b.w * 1.2)); band.rect.setAttribute('width', f(b.w * 2.4));
          band.rect.setAttribute('y', f(top + (i ? half : -40)));
          band.rect.setAttribute('height', f(slice - (i ? half : -40) - (i < BAND_EDGES.length - 2 ? half : -40)));
          band.outer.setAttribute('transform', `translate(${f(b.x + load.off[i])} ${f(b.y)}) rotate(${f(b.rot)})`);
          if (band.d !== shape) { band.d = shape; band.path.setAttribute('d', shape); }
          band.path.style.fill = rgb(load.tone[i]);
        });
      } else if (bands) bands.group.setAttribute('display', 'none');
      if (kind === 'mesh') {
        cuts ||= makeCuts();
        cuts.group.removeAttribute('display');
        cuts.group.setAttribute('transform', `translate(${f(t.x)} ${f(t.y)}) rotate(${f(t.rot)})`);
        cuts.shape.setAttribute('d', parts.teal.d);
        cuts.lines.forEach((line, i) => {
          const c = load.lines[i];
          if (!c || load.w <= .05) { line.setAttribute('display', 'none'); return; }
          line.removeAttribute('display');
          line.setAttribute('x1', f((c[0] - .5) * t.w)); line.setAttribute('y1', f((c[1] - .5) * t.h));
          line.setAttribute('x2', f((c[2] - .5) * t.w)); line.setAttribute('y2', f((c[3] - .5) * t.h));
          line.setAttribute('stroke-width', f(load.w));
        });
      } else if (cuts) cuts.group.setAttribute('display', 'none');
      if (kind === 'material') {
        shine ||= makeShine();
        shine.group.removeAttribute('display');
        shine.group.setAttribute('transform', `translate(${f(d.x)} ${f(d.y)})`);
        shine.circle.setAttribute('r', f(d.r));
        shine.turn.setAttribute('transform', `rotate(${f(load.ang)})`);
        const w = d.r * .56, w2 = d.r * .16, x = load.at * d.r;
        shine.wide.setAttribute('x', f(x - w / 2)); shine.wide.setAttribute('y', f(-d.r * 1.3));
        shine.wide.setAttribute('width', f(w)); shine.wide.setAttribute('height', f(d.r * 2.6));
        shine.thin.setAttribute('x', f(x + w / 2 + d.r * .14)); shine.thin.setAttribute('y', f(-d.r * 1.3));
        shine.thin.setAttribute('width', f(w2)); shine.thin.setAttribute('height', f(d.r * 2.6));
      } else if (shine) shine.group.setAttribute('display', 'none');
    }

    return {
      svg,
      // Status colours follow the theme's lightness, so they're read from the surface each time.
      status() {
        const style = getComputedStyle(host);
        return {
          complete: parseColour(style.getPropertyValue('--status-complete'), STATUS.complete),
          warning: parseColour(style.getPropertyValue('--status-warning'), STATUS.warning),
          error: parseColour(style.getPropertyValue('--status-error'), STATUS.error),
        };
      },
      render(engine) {
        const {cur, cols, fx, load, box} = engine, opacity = engine.opacity ?? 1;
        if (box) {
          const text = `${f(box[0])} ${f(box[1])} ${f(box[2])} ${f(box[3])}`;
          if (text !== lastBox) { lastBox = text; svg.setAttribute('viewBox', text); }
        }
        if (fx.punch !== lastPunch) {
          lastPunch = fx.punch;
          if (fx.punch === 1) g.removeAttribute('transform');
          else g.setAttribute('transform', `translate(240 200) scale(${fx.punch.toFixed(4)}) translate(-240 -200)`);
        }
        drawShape('blue', cur.blue);
        drawShape('teal', cur.teal);
        drawDisc(cur.disc, fx);
        drawColours(cols);
        drawRing(fx);
        drawLoad(cur, load);
        if (opacity !== lastOpacity) { lastOpacity = opacity; svg.style.opacity = opacity === 1 ? '' : opacity.toFixed(3); }
      },
    };
  }

  // ---------- the public glyph ----------
  const STATES = new Set(['busy', 'info', 'success', 'warning', 'error']);
  const ASSETS = new Set(['mesh', 'texture', 'material']);
  const mounted = new WeakMap();
  const motion = window.AtelierMotion;

  // mount(host, {state, asset?, size?, reducedMotion?, surface?})
  //   state: busy, info, success, warning or error. Defaults to info.
  //   asset: mesh, texture or material, only with busy, and only when the surface truly knows it.
  //   size: the host's height in pixels, if the host doesn't set its own.
  //   surface: the colour behind the glyph, if it isn't the page background (a CSS colour or var()).
  // Success forms the A, so call it only for a real succeeded result (SPEC invariant 5).
  function mount(host, options) {
    if (!host || host.nodeType !== 1) throw new Error('AtelierMotion.glyph.mount requires a DOM host.');
    mounted.get(host)?.destroy();
    if (host.childNodes.length) throw new Error('The glyph needs an empty host.');
    const opts = options || {};
    const assetFor = (state, wanted) => (state === 'busy' && ASSETS.has(wanted) ? wanted : null);
    let state = STATES.has(opts.state) ? opts.state : 'info';
    let asset = assetFor(state, opts.asset);
    let destroyed = false;

    host.setAttribute('data-atelier-motion', 'glyph');
    host.classList.add('atelier-glyph');
    if (opts.surface) host.style.setProperty('--glyph-halo', opts.surface);
    if (opts.size) { host.style.height = `${opts.size}px`; host.style.width = `${opts.size * VB.w / VB.h}px`; }
    const sync = () => {
      host.setAttribute('data-glyph-state', state);
      if (asset) host.setAttribute('data-glyph-asset', asset);
      else host.removeAttribute('data-glyph-asset');
    };
    sync();
    const engine = new assembly.Engine(createView(host));
    engine.run(state, asset);

    const handle = {
      // A busy state that follows the same busy state carries on, and a result doesn't animate twice.
      set(next, nextOptions) {
        if (destroyed || !STATES.has(next)) return handle;
        const nextAsset = assetFor(next, nextOptions && nextOptions.asset);
        if (next === state && nextAsset === asset) return handle;
        state = next;
        asset = nextAsset;
        sync();
        engine.run(state, asset);
        return handle;
      },
      replay() {
        if (!destroyed) engine.run(state, asset);
        return handle;
      },
      destroy() {
        if (destroyed) return;
        destroyed = true;
        engine.destroy();
        mounted.delete(host);
        host.replaceChildren();
        host.classList.remove('atelier-glyph');
        for (const name of ['data-atelier-motion', 'data-glyph-state', 'data-glyph-asset']) host.removeAttribute(name);
        if (opts.surface) host.style.removeProperty('--glyph-halo');
        if (opts.size) { host.style.height = ''; host.style.width = ''; }
      },
      get state() { return state; },
    };
    if (window.__ATELIER_GLYPH_TEST__) handle.engine = engine;
    mounted.set(host, handle);
    return handle;
  }

  assembly.createView = createView;
  motion.glyph = Object.freeze({mount});
})();
