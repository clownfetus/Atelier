// Every counted progress bar is the material disc rolling its fill forward (SPEC section 4.10).
// The bar's own element stays as it is and keeps the value: a <progress> keeps its value and role, and a
// fill keeps its width or --progress. The disc is drawn over it, and only ever goes where the count is.
// Uncounted work never gets a bar; it is the working glyph.
(() => {
  'use strict';
  const NS = 'http://www.w3.org/2000/svg';
  const SELECTOR = 'progress, .progress-bar-bg, .shader-bar, .activity-ring:not(.indeterminate)';
  const SHINE_AT = 25; // degrees: where the shine sits at the start of the bar
  const live = new Map();
  const carried = new WeakMap(); // an Activity ring's button → the last ring, so a refreshed ring carries on

  // The glyph's own curves (SPEC section 4.9).
  function bez(x1, y1, x2, y2) {
    const cx = 3 * x1, bx = 3 * (x2 - x1) - cx, ax = 1 - cx - bx, cy = 3 * y1, by = 3 * (y2 - y1) - cy, ay = 1 - cy - by;
    const X = t => ((ax * t + bx) * t + cx) * t, Y = t => ((ay * t + by) * t + cy) * t, dX = t => (3 * ax * t + 2 * bx) * t + cx;
    return x => {
      if (x <= 0) return 0;
      if (x >= 1) return 1;
      let t = x;
      for (let i = 0; i < 8; i++) { const e = X(t) - x, d = dX(t); if (Math.abs(e) < 1e-5 || !d) break; t -= e / d; }
      return Y(Math.max(0, Math.min(1, t)));
    };
  }
  const MOVE = bez(.65, 0, .35, 1), PUNCH_BACK = bez(.3, 1.6, .5, 1);
  const PEAK = (() => { let m = 0; for (let i = 1; i <= 400; i++) m = Math.max(m, (MOVE(i / 400) - MOVE((i - 1) / 400)) * 400); return m; })();
  const slope = r => { const a = Math.max(0, r - .005), b = Math.min(1, r + .005); return (MOVE(b) - MOVE(a)) / (b - a); };
  const clamp01 = v => Math.max(0, Math.min(1, v));
  const lerp = (a, b, t) => a + (b - a) * t;
  const travel = px => Math.max(300, Math.min(640, 220 + Math.abs(px) * .95));
  const f = v => (+v).toFixed(2);
  const mk = (tag, attrs, parent) => {
    const el = document.createElementNS(NS, tag);
    for (const k in attrs) el.setAttribute(k, attrs[k]);
    if (parent) parent.append(el);
    return el;
  };
  const mode = () => {
    const policy = window.AtelierMotionPolicy;
    if (policy?.mode) return policy.mode();
    return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'off' : 'full';
  };

  // What the bar's own element says, 0 to 1, or null when there's nothing to count.
  function valueOf(el) {
    if (el.tagName === 'PROGRESS') return el.hasAttribute('value') && el.max > 0 ? clamp01(el.value / el.max) : null;
    if (el.classList.contains('activity-ring')) return clamp01((parseFloat(el.style.getPropertyValue('--job-progress')) || 0) / 100);
    const fill = el.firstElementChild;
    if (!fill || fill.namespaceURI === NS) return null;
    const scaled = fill.style.getPropertyValue('--progress');
    if (scaled !== '') return clamp01(parseFloat(scaled) || 0);
    return clamp01((parseFloat(fill.style.width) || 0) / 100);
  }
  // The halo is the colour of whatever is behind the bar.
  function surfaceOf(el) {
    for (let node = el.parentElement; node; node = node.parentElement) {
      const c = getComputedStyle(node).backgroundColor;
      if (c && c !== 'transparent' && !/rgba\(.*,\s*0\)$/.test(c)) return c;
    }
    return getComputedStyle(document.body).backgroundColor || 'transparent';
  }

  // One clock for every bar, running only while something moves.
  const clock = (() => {
    const busy = new Set();
    let handle = 0, last = 0;
    const frame = stamp => {
      handle = 0;
      const dt = Math.max(0, Math.min(64, stamp - last));
      last = stamp;
      for (const bar of [...busy]) if (!bar.tick(dt)) busy.delete(bar);
      if (busy.size) handle = requestAnimationFrame(frame);
    };
    return {
      add(bar) { busy.add(bar); if (!handle) { last = performance.now(); handle = requestAnimationFrame(frame); } },
      remove(bar) { busy.delete(bar); },
    };
  })();

  class Roller {
    constructor(el) {
      this.el = el;
      this.tweens = [];
      this.p = 0;        // where the disc is, 0 to 1
      this.target = 0;
      this.moving = false;
      this.sx = this.sy = 1;
      el.classList.add('has-disc');
      this.watch = new MutationObserver(() => this.update());
      this.watch.observe(el, {attributes: true, subtree: true, attributeFilter: ['value', 'max', 'style']});
      this.button = el.closest('button');
      this.refresh = () => { this.halo = surfaceOf(this.el); this.draw(); };
      this.button?.addEventListener('pointerenter', this.refresh);
      this.button?.addEventListener('pointerleave', this.refresh);
    }
    animate(ms, ease, fn) {
      return new Promise(done => { this.tweens.push({t: 0, ms, ease, fn, done}); clock.add(this); });
    }
    tick(dt) {
      for (const w of [...this.tweens]) {
        w.t += dt;
        const r = Math.min(1, w.t / w.ms);
        w.fn(w.ease(r), r);
        if (r >= 1) { this.tweens.splice(this.tweens.indexOf(w), 1); w.done(); }
      }
      this.draw();
      return this.tweens.length > 0;
    }
    update() {
      const v = valueOf(this.el);
      this.shown = v !== null;
      if (v === null) { this.draw(); return; }
      // A new count starting again goes straight back: the disc never rolls backwards.
      if (v < this.p - 1e-4 && !this.moving) { this.p = v; this.target = v; this.draw(); return; }
      this.target = v;
      if (!this.moving) this.roll();
    }
    // Each roll goes to the latest count and lands (640 ms at most) before the next one starts.
    async roll() {
      while (this.target > this.p + 1e-4 && this.el.isConnected) {
        const from = this.p, to = this.target, px = this.span(to - from), how = mode();
        // Off, a tiny step, or a bar not laid out yet (a closed dialog): it takes the count at once.
        if (how === 'off' || !this.ready() || !(Math.abs(px) >= .3)) { this.p = to; this.draw(); continue; }
        this.moving = true;
        const k = how === 'full' && this.stretches ? Math.min(1, Math.abs(px) / (4 * this.r)) : 0;
        await this.animate(travel(px), x => x, (_, r) => {
          this.p = lerp(from, to, MOVE(r));
          this.sx = 1 + .16 * k * slope(r) / PEAK;
          this.sy = 1 / this.sx;
        });
        this.p = to; this.sx = this.sy = 1;
        // The squash runs on after the landing; the next roll doesn't wait for it.
        if (k) this.animate(300, PUNCH_BACK, e => { this.sx = 1 - .12 * k * (1 - e); this.sy = 1 + .12 * k * (1 - e); });
      }
      this.moving = false;
      if (this.target < this.p - 1e-4) this.update();
    }
    destroy() {
      clock.remove(this);
      this.watch.disconnect();
      this.resize?.disconnect();
      this.button?.removeEventListener('pointerenter', this.refresh);
      this.button?.removeEventListener('pointerleave', this.refresh);
      this.svg.remove();
      this.el.classList.remove('has-disc');
    }
  }

  // A straight bar: the 8 px update and shader bars, and the 3 px startup bar.
  class Bar extends Roller {
    constructor(el) {
      super(el);
      this.stretches = true;
      this.native = el.tagName === 'PROGRESS';
      const svg = this.svg = mk('svg', {class: 'progress-disc', 'aria-hidden': 'true', focusable: 'false'});
      this.fill = mk('rect', {x: 0, class: 'progress-disc-fill'}, svg);
      const id = `progress-disc-${Math.random().toString(36).slice(2, 9)}`;
      this.clip = mk('circle', {cx: 0, cy: 0}, mk('clipPath', {id}, mk('defs', {}, svg)));
      this.group = mk('g', {}, svg);
      this.disc = mk('circle', {cx: 0, cy: 0, class: 'progress-disc-piece'}, this.group);
      this.turn = mk('g', {}, mk('g', {'clip-path': `url(#${id})`}, this.group));
      this.shine = mk('rect', {class: 'progress-disc-shine'}, this.turn);
      if (this.native) el.after(svg); else el.append(svg);
      // The startup bar moves when the splash around it changes, so its parent is watched too.
      this.resize = new ResizeObserver(() => this.layout());
      this.resize.observe(el);
      if (this.native && el.parentElement) this.resize.observe(el.parentElement);
      this.layout();
      const v = valueOf(el);
      this.shown = v !== null;
      this.p = this.target = 0;
      this.update();
    }
    ready() { return this.W > 0 && this.h > 0 && this.r > 0; }
    span(dp) { return this.ready() ? dp * Math.max(0, this.W - 2 * this.r) : 0; }
    layout() {
      const W = this.el.offsetWidth, h = this.el.offsetHeight;
      this.W = W; this.h = h;
      if (!W || !h) { this.draw(); return; }
      const r = this.r = Math.max(3.6, h * .8), g = this.g = Math.max(1.4, h * .28), H = this.H = 2 * (r + g);
      const svg = this.svg, rx = Math.min(2, h / 2);
      svg.setAttribute('viewBox', `0 0 ${f(W)} ${f(H)}`);
      svg.setAttribute('width', f(W));
      svg.setAttribute('height', f(H));
      for (const [k, v] of Object.entries({y: (H - h) / 2, height: h, rx})) this.fill.setAttribute(k, f(v));
      this.clip.setAttribute('r', f(r));
      this.disc.setAttribute('r', f(r));
      this.disc.setAttribute('stroke-width', f(2 * g));
      for (const [k, v] of Object.entries({x: -r * .28, y: -r * 1.2, width: r * .46, height: r * 2.4})) this.shine.setAttribute(k, f(v));
      this.halo = surfaceOf(this.el);
      this.draw();
    }
    draw() {
      const visible = this.shown && this.W > 0 && this.h > 0 && this.el.isConnected;
      this.svg.style.display = visible ? '' : 'none';
      if (!visible) return;
      this.svg.style.left = `${this.native ? this.el.offsetLeft : 0}px`;
      this.svg.style.top = `${(this.native ? this.el.offsetTop : 0) + (this.h - this.H) / 2}px`;
      const cx = this.r + this.span(this.p);
      this.fill.setAttribute('width', f(cx));
      this.disc.style.stroke = this.halo;
      this.group.setAttribute('transform', `translate(${f(cx)} ${f(this.H / 2)})${this.sx === 1 ? '' : ` scale(${this.sx.toFixed(3)} ${this.sy.toFixed(3)})`}`);
      this.turn.setAttribute('transform', `rotate(${f(SHINE_AT + (cx - this.r) / this.r * 180 / Math.PI)})`);
    }
  }

  // The 16 px Activity ring: the disc rolls round it. A refreshed ring carries on from where the last one was.
  const R = 5.6, TOP = -Math.PI / 2, TAU = 2 * Math.PI;
  class Ring extends Roller {
    constructor(el) {
      super(el);
      this.stretches = false;
      this.r = 2.5;
      const svg = this.svg = mk('svg', {class: 'progress-disc progress-disc-ring', viewBox: '0 0 16 16', 'aria-hidden': 'true', focusable: 'false'});
      mk('circle', {cx: 8, cy: 8, r: R, class: 'progress-disc-track'}, svg);
      this.arc = mk('path', {class: 'progress-disc-arc'}, svg);
      this.disc = mk('circle', {r: this.r, class: 'progress-disc-piece', 'stroke-width': 1.8}, svg);
      el.append(svg);
      const before = this.button && carried.get(this.button);
      this.p = this.target = before && !before.el.isConnected ? before.p : 0;
      if (this.button) carried.set(this.button, this);
      this.shown = true;
      this.halo = surfaceOf(el);
      this.update();
    }
    ready() { return true; }
    span(dp) { return dp * TAU * R * 4; }
    layout() {}
    draw() {
      const a = TOP + this.p * TAU, end = Math.min(a, TOP + TAU - .001);
      const at = t => `${f(8 + R * Math.cos(t))} ${f(8 + R * Math.sin(t))}`;
      this.arc.setAttribute('d', this.p > .001 ? `M ${at(TOP)} A ${R} ${R} 0 ${end - TOP > Math.PI ? 1 : 0} 1 ${at(end)}` : '');
      this.disc.setAttribute('cx', f(8 + R * Math.cos(a)));
      this.disc.setAttribute('cy', f(8 + R * Math.sin(a)));
      this.disc.style.stroke = this.halo;
    }
  }

  function attach(el) {
    if (live.has(el) || !el.isConnected) return live.get(el) || null;
    try {
      const roller = el.classList.contains('activity-ring') ? new Ring(el) : new Bar(el);
      live.set(el, roller);
      return roller;
    } catch (error) {
      console.warn('Progress disc unavailable', error);
      return null;
    }
  }
  function scan(node) {
    if (node.nodeType !== 1) return;
    if (node.matches(SELECTOR)) attach(node);
    for (const el of node.querySelectorAll(SELECTOR)) attach(el);
  }
  new MutationObserver(records => {
    for (const record of records) for (const node of record.addedNodes) scan(node);
    for (const [el, roller] of live) if (!el.isConnected) { live.delete(el); roller.destroy(); }
  }).observe(document.documentElement, {childList: true, subtree: true});
  // A theme change repaints the halo in the new surface colour.
  new MutationObserver(() => { for (const roller of live.values()) roller.refresh(); })
    .observe(document.documentElement, {attributes: true, attributeFilter: ['class', 'data-theme', 'style']});
  scan(document.documentElement);

  window.AtelierMotion = window.AtelierMotion || {};
  window.AtelierMotion.progressDisc = Object.freeze({attach, of: el => live.get(el) || null});
})();
