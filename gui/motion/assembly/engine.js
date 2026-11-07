/*
 * Atelier motion system: the state machine (SPEC section 4).
 * One engine per glyph, all on one shared animation-frame clock. An engine only asks for frames
 * while it has something to animate, so a settled glyph costs nothing. Moves land: once a piece
 * has started travelling it finishes, and a new state waits for it. Load after planner.js.
 */
(() => {
  'use strict';
  const assembly = window.AtelierMotion.assembly;
  const {CAT, PLATES, G, IDS, E, POSES, OUT, WREST, STRAIGHT, CONFIGS, PATTERNS, clone, mixC, all, warningPose, standOff, nudge, fits, rest, atRest, raised} = assembly.pieces;
  const {lerpPose, pieceAt, pathLen, planSequence, simulClear, spreadFor, slotsFor, seated} = assembly.planner;

  // One clock for every glyph: 30 glyphs share one frame callback. Time stops when no glyph needs it,
  // and a long gap (a hidden window) moves it on by at most a quarter of a second.
  const clock = (() => {
    const live = new Set();
    let handle = 0, last = 0, time = 0;
    const frame = stamp => {
      handle = 0;
      time += Math.max(0, Math.min(250, stamp - last));
      last = stamp;
      for (const engine of [...live]) engine.tick(time);
      if (live.size) handle = requestAnimationFrame(frame);
    };
    return {
      now: () => time,
      add(engine) {
        live.add(engine);
        if (!handle) { last = performance.now(); handle = requestAnimationFrame(frame); }
      },
      remove(engine) { live.delete(engine); },
    };
  })();

  const always = () => true;
  const same = (a, b) => a[0] === b[0] && a[1] === b[1] && a[2] === b[2];
  const BANDS = 5;

  class Engine {
    constructor(view) {
      this.view = view;
      this.cur = clone(rest());
      this.cols = {...CAT};
      this.fx = {punch: 1, dsx: 1, dsy: 1, ringR: 0, ringW: 0, ringOp: 0};
      this.load = null;
      this.token = 0;
      this.colourTok = 0;
      this.moving = null;
      this.tasks = [];
      this.dirty = true;
      this.lastFit = -1;
      this.fresh = true;
      this.state = null;
      this.settled = false;
      this.destroyed = false;
      this.wake();
    }

    // ---------- the clock ----------
    wake() { if (!this.destroyed) clock.add(this); }
    touch() { this.dirty = true; this.wake(); }
    place(pose) { this.cur = pose; this.touch(); }
    tick(time) {
      for (const task of [...this.tasks]) {
        if (!task.alive()) { this.finish(task, false); continue; }
        const p = task.ms > 0 ? Math.min(1, (time - task.t0) / task.ms) : 1;
        if (task.fn) { task.fn(task.ease(p), p); this.dirty = true; }
        if (p >= 1) this.finish(task, true);
      }
      if (this.dirty) { this.dirty = false; this.view.render(this); }
      if (!this.tasks.length) clock.remove(this);
    }
    finish(task, result) {
      this.tasks.splice(this.tasks.indexOf(task), 1);
      task.resolve(result);
    }
    animate(ms, ease, fn, alive = always) {
      return new Promise(resolve => {
        this.tasks.push({t0: clock.now(), ms, ease, fn, alive, resolve});
        this.wake();
      });
    }
    // A wait ends early once its state has been replaced, so nothing idles on a dead script.
    sleep(ms, tk) { return this.animate(ms, E.linear, null, () => tk === this.token).then(() => tk === this.token); }
    pause(ms) { return this.animate(ms, E.linear, null); }
    destroy() {
      this.destroyed = true;
      this.token++;
      clock.remove(this);
      this.tasks.length = 0;
    }

    // ---------- moves ----------
    // Every move runs to the end once started; a new state waits for it.
    tweenTo(to, ms, ease, tk) {
      const from = clone(this.cur);
      this.moving = this.animate(ms, ease, e => { this.cur = lerpPose(from, to, e); }).then(() => { this.place(clone(to)); this.moving = null; });
      return this.moving.then(() => tk === this.token);
    }
    moveTo(to, ms, ease) {
      const from = clone(this.cur);
      return this.animate(ms, ease, e => { this.cur = lerpPose(from, to, e); }).then(() => this.place(clone(to)));
    }
    // One piece at a time, along planned curves.
    async travelTo(to, tk, prefer) {
      const steps = planSequence(this.cur, to, prefer);
      for (const st of steps) {
        const ms = Math.max(300, Math.min(640, 220 + pathLen(st.path) * .95));
        this.moving = this.animate(ms, E.move, e => { this.cur = {...this.cur, [st.id]: pieceAt(st.path, e)}; })
          .then(() => { this.place({...this.cur, [st.id]: {...st.path.b}}); this.moving = null; });
        await this.moving;
        if (tk !== this.token) return false; // stop between pieces, never mid-flight
        await this.pause(40);
      }
      this.place(clone(to));
      return tk === this.token;
    }
    // The first move out of an outcome: all three at once. The mesh hops over the tile if they swap sides.
    openTo(target, tk) {
      const from = clone(this.cur), swap = (from.teal.x > from.blue.x) !== (target.teal.x > target.blue.x);
      this.moving = this.animate(420, E.move, e => {
        const q = lerpPose(from, target, e), s = Math.sin(Math.PI * e);
        if (swap) { q.teal.y -= 70 * s; q.blue.y += 30 * s; }
        this.cur = q;
      }).then(() => { this.place(clone(target)); this.moving = null; });
      return this.moving.then(() => tk === this.token);
    }
    // Only the newest colour change runs, so two fades never fight over a frame.
    colourTo(target, ms, delays = {blue: 0, teal: 0, disc: 0}) {
      const ct = ++this.colourTok, from = {...this.cols}, longest = ms + Math.max(...Object.values(delays));
      return this.animate(longest, E.linear, (e, p) => {
        const now = p * longest, next = {};
        for (const k of IDS) next[k] = mixC(from[k], target[k], E.colour(Math.max(0, Math.min(1, (now - delays[k]) / ms))));
        this.cols = next;
      }, () => ct === this.colourTok);
    }
    isCat() { return IDS.every(id => same(this.cols[id], CAT[id])); }
    async assemble(a, target, tk) {
      const open = seated(this.cur);
      if (open && !await this.travelTo(standOff(this.cur), tk, ['teal'])) return false; // out of the A: the mesh opens first
      const sp = spreadFor(a, this.cur, open); // everyone apart at once
      if (simulClear(this.cur, sp)) { if (!await this.tweenTo(sp, 380, E.move, tk)) return false; }
      else if (!await this.travelTo(sp, tk, IDS)) return false;
      const sl = slotsFor(a, this.cur); // dockers round to their sides
      if (!await this.travelTo(sl, tk, a.order.slice(1))) return false;
      return this.travelTo(target, tk, a.order); // anchor to the middle, others in
    }

    // ---------- states ----------
    async run(state, asset = null) {
      const tk = ++this.token;
      this.state = state;
      this.asset = asset;
      this.settled = false;
      if (this.moving) await this.moving; // let the piece in flight land first
      if (tk !== this.token) return;
      const fresh = this.fresh;
      this.fresh = false;
      if (state === 'busy') await (asset ? this.runLoader(asset, tk, fresh) : this.runWorking(tk, fresh));
      else if (state === 'success') await this.runSuccess(tk);
      else if (state === 'warning') await this.runWarning(tk);
      else if (state === 'error') await this.runError(tk);
      else if (state === 'brand') await this.runBrand(tk);
      else await this.runInfo(tk);
      if (tk === this.token) this.settled = true;
    }
    async runInfo(tk) {
      if (!this.isCat()) this.colourTo(CAT, 240);
      if (!atRest(this.cur)) await this.openTo(rest(), tk);
    }
    async runWorking(tk, fresh) {
      if (!this.isCat()) this.colourTo(CAT, 240);
      const ATT = fits();
      for (let first = true; tk === this.token; first = false) {
        let i;
        do { i = Math.floor(Math.random() * ATT.length); } while (i === this.lastFit);
        const prev = ATT[this.lastFit], a = ATT[i];
        this.lastFit = i;
        if (first && fresh) this.place(clone(a.approach)); // a glyph that has just appeared starts in a fit, never an A
        else if (first) { if (!await this.openTo(a.approach, tk)) return; }
        else if (!STRAIGHT.has(a.name) || !STRAIGHT.has(prev.name)) { if (!await this.assemble(a, a.approach, tk)) return; }
        else if (!await this.travelTo(a.approach, tk, a.order)) return;
        if (!await this.tweenTo(a.contact, 200, E.out, tk)) return; // dock
        if (!await this.tweenTo(a.tap, 120, E.windup, tk)) return; // test the fit
        if (!await this.tweenTo(a.contact, 110, E.snap, tk)) return; // tap
        if (!await this.sleep(180, tk)) return; // not it
      }
    }
    async runLoader(asset, tk, fresh) {
      if (!this.isCat()) this.colourTo(CAT, 240);
      if (fresh) this.place(clone(rest()));
      else if (!atRest(this.cur) && !await this.openTo(rest(), tk)) return;
      const loaders = {mesh: this.loadMesh, texture: this.loadTexture, material: this.loadMaterial};
      this.moving = loaders[asset].call(this, tk).then(() => { this.moving = null; });
      await this.moving;
    }
    async runSuccess(tk) {
      const M = POSES.master;
      if (!this.isCat()) this.colourTo(CAT, 200);
      if (this.cur.teal.x < this.cur.blue.x) { // from the row: the mesh hops over the tile
        const from = clone(this.cur), to = standOff(nudge(M, 16));
        this.moving = this.animate(380, E.move, e => {
          const q = lerpPose(from, to, e), s = Math.sin(Math.PI * e);
          q.teal.y -= 70 * s; q.blue.y += 30 * s;
          this.cur = q;
        }).then(() => { this.place(clone(to)); this.moving = null; });
        await this.moving;
        if (tk !== this.token) return;
      } else if (!await this.tweenTo(standOff(nudge(M, 16)), 340, E.move, tk)) return; // tile and disc to their seats, mesh stands off
      if (!await this.tweenTo(nudge(M, 16), 110, E.out, tk)) return; // the mesh comes in, already wound up
      if (!await this.tweenTo(nudge(M, -3), 80, E.snap, tk)) return; // snap: the mesh presses 3u past its seat
      const effects = this.impact();
      if (!await this.tweenTo(nudge(M, 1), 110, E.recoil, tk)) return; // recoil
      if (!await this.tweenTo(M, 130, E.rest, tk)) return; // rest
      await effects;
      if (!await this.sleep(160, tk)) return;
      await this.colourTo(CAT, 380);
    }
    // The click: hard contact, squash and punch and ripple, colour spreading from the disc.
    // Impact effects always finish: cutting them off would pop.
    impact() {
      const {fx} = this, green = this.view.status().complete;
      fx.dsx = .88; fx.dsy = 1.12; fx.punch = 1; fx.ringC = green;
      const ripple = this.animate(620, E.out, (e, p) => { fx.ringR = 60 + e * 140; fx.ringW = 12 * Math.pow(1 - p, .6); fx.ringOp = Math.pow(1 - p, 1.4); });
      const squash = this.animate(300, E.punchBack, e => { fx.dsx = .88 + (1 - .88) * e; fx.dsy = 1.12 + (1 - 1.12) * e; });
      const colour = this.colourTo(all(green), 220, {disc: 0, blue: 60, teal: 120});
      const punch = this.animate(70, E.punchOut, e => { fx.punch = 1 + .045 * e; })
        .then(() => this.animate(260, E.punchBack, e => { fx.punch = 1.045 - .045 * e; }));
      return Promise.all([ripple, squash, colour, punch]);
    }
    async runWarning(tk) {
      const W = POSES.warning, alive = () => tk === this.token;
      if (!this.isCat()) this.colourTo(CAT, 200); // back to their own colours first
      if (!await this.assemble({...OUT.warning, contact: W}, W, tk)) return; // dot down, stem on the dot, tile on top
      this.colourTo(all(this.view.status().warning), 200);
      // Catch the balance: a few decaying sways, the tile lagging the stem.
      const sway = t => 5 * Math.exp(-2.4 * t) * Math.sin(2 * Math.PI * 1.3 * t);
      if (!await this.animate(1600, E.linear, (e, p) => {
        const t = p * 1.6, w = (1 - p) * (1 - p);
        this.cur = warningPose(WREST.th + sway(t) * w, WREST.ph - .6 * sway(Math.max(0, t - .1)) * w);
      }, alive)) return;
      // Then keep wobbling gently for as long as the warning stands.
      for (let n = 0; tk === this.token; n++) {
        if (!await this.animate(2600, E.linear, (e, p) => {
          const a = 2 * Math.PI * p, amp = n ? 1 : p;
          this.cur = warningPose(WREST.th + 1.2 * amp * Math.sin(a), WREST.ph - .7 * amp * Math.sin(a - .5) * Math.min(1, (n + p) * 2));
        }, alive)) return;
      }
    }
    async runError(tk) {
      const X = POSES.error, open = clone(X);
      open.blue.rot -= 6; open.teal.rot += 6;
      if (!this.isCat()) this.colourTo(CAT, 200);
      if (!await this.assemble({...OUT.error, contact: open}, open, tk)) return; // bar down, bar across, disc pins them
      if (!await this.tweenTo(X, 150, E.out, tk)) return; // clamp shut
      await this.colourTo(all(this.view.status().error), 200);
    }

    // The brand mark's route (the logo's entrance): the tile settles, the mesh waits, the disc comes in, the mesh closes.
    async runBrand(tk) {
      const M = POSES.master, wait = standOff(M);
      this.colourTo(CAT, 240);
      if (!await this.assemble({...OUT.master, contact: wait, fixed: ['teal']}, wait, tk)) return;
      await this.travelTo(M, tk, ['teal']);
    }

    // ---------- loaders (SPEC section 4.7): flat and opaque, a pop and never a blend ----------
    async loadMesh(tk) {
      await this.moveTo(raised('teal'), 120, E.out);
      let last = -1, flip = 1;
      while (tk === this.token) {
        let i;
        do { i = Math.floor(Math.random() * CONFIGS.length); } while (i === last);
        last = i;
        flip = -flip;
        const to = raised('teal');
        to.teal.rot = flip * 3.5;
        to.teal.x += flip * 6;
        const load = this.load = {kind: 'mesh', lines: CONFIGS[i], w: 0};
        await Promise.all([this.moveTo(to, 110, E.snap), this.animate(110, E.out, e => { load.w = G * e; })]);
        await this.sleep(250, tk);
        await this.animate(70, E.windup, e => { load.w = G * (1 - e); });
      }
      this.load = null;
      await this.moveTo(rest(), 100, E.rest);
    }
    async loadTexture(tk) {
      await this.moveTo(raised('blue'), 120, E.out);
      let n = 0;
      while (tk === this.token) {
        const load = this.load = {kind: 'texture', gap: 0, off: [0, 0, 0, 0, 0], tone: Array(BANDS).fill(CAT.blue)};
        await this.animate(60, E.out, e => { load.gap = 9 * e; });
        for (let r = 0; r < 2 && tk === this.token; r++) {
          const from = [...load.off], to = PATTERNS[n++ % PATTERNS.length];
          load.tone = load.tone.map((_, i) => PLATES[(i + n + r * 2) % PLATES.length]); // a pop, never a blend
          await this.animate(90, E.snap, e => { load.off = from.map((f, i) => f + (to[i] - f) * e); });
          if (!await this.sleep(170, tk)) break;
        }
        // Fall into register, top to bottom, each band landing on the tile's own blue.
        const from = [...load.off];
        await Promise.all(from.map((f, i) => this.pause(i * 45)
          .then(() => this.animate(90, E.snap, e => { load.off[i] = f * (1 - e); }))
          .then(() => { load.tone[i] = CAT.blue; })));
        await this.animate(60, E.windup, e => { load.gap = 9 * (1 - e); });
        this.load = null;
        this.touch();
        if (tk !== this.token || !await this.sleep(220, tk)) break;
      }
      this.load = null;
      await this.moveTo(rest(), 100, E.rest);
    }
    async loadMaterial(tk) {
      const R = rest(), r = R.disc.r, D = 38, x0 = R.disc.x, base = 25;
      let right = false;
      while (tk === this.token) {
        const a = right ? x0 + D : x0, b = right ? x0 : x0 + D, load = this.load = {kind: 'material', at: -1.5, ang: base};
        await this.animate(520, E.move, e => {
          const x = a + (b - a) * e;
          this.cur = {...this.cur, disc: {...this.cur.disc, x}};
          load.ang = base + (x - x0) / r * 180 / Math.PI;
          load.at = -1.5 + 2.9 * e;
        });
        right = !right;
        this.load = null;
        this.touch();
        if (!await this.sleep(right ? 110 : 240, tk)) break;
      }
    }
  }

  assembly.Engine = Engine;
  assembly.clock = clock;
})();
