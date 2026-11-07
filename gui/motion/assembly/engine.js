/*
 * Atelier motion system: the state machine (SPEC section 4).
 * One engine per glyph, all on one shared animation-frame clock. An engine only asks for frames
 * while it has something to animate, so a settled glyph costs nothing. Moves land: once a piece
 * has started travelling it finishes, and a new state waits for it. Load after planner.js.
 */
(() => {
  'use strict';
  const assembly = window.AtelierMotion.assembly;
  const {CAT, PLATES, G, IDS, E, POSES, OUT, WREST, STRAIGHT, CONFIGS, PATTERNS, FRAME, clone, mixC, all, warningPose, standOff, nudge, fits, rest, atRest, raised, micro, logoStart, frameOf} = assembly.pieces;
  const {lerpPose, pieceAt, pathLen, known, planLive, simulClear, spreadFor, slotsFor, seated} = assembly.planner;

  // One clock for every glyph: 30 glyphs share one frame callback. Time stops when no glyph needs it,
  // and a long gap (a hidden window) moves it on by at most a quarter of a second.
  const clock = (() => {
    const live = new Set();
    let handle = 0, last = 0;
    const frame = stamp => {
      handle = 0;
      const dt = Math.max(0, Math.min(250, stamp - last));
      last = stamp;
      for (const engine of [...live]) engine.tick(dt);
      if (live.size) handle = requestAnimationFrame(frame);
    };
    return {
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
  const JOSTLE_PX = 1.5;
  const JOSTLE_MS = 900;

  class Engine {
    constructor(view, tier = 'inline', height = 48, reduced = false, width = height * 1.5) {
      this.view = view;
      this.width = width;
      this.reduced = reduced;
      this.visible = !document.hidden;
      this.modeNow = this.mode();
      this.formed = false;
      this.tier = tier;
      this.height = height;
      this.time = 0;
      this.pace = 1;
      this.cur = clone(tier === 'micro' ? micro().info : rest());
      this.box = this.frameFor('info');
      this.cols = {...CAT};
      this.fx = {punch: 1, dsx: 1, dsy: 1, ringR: 0, ringW: 0, ringOp: 0};
      this.load = null;
      this.token = 0;
      this.colourTok = 0;
      this.frameTok = 0;
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
    // Time stops for a glyph nobody can see, so a state set meanwhile plays when it comes back into view.
    wake() { if (!this.destroyed && this.visible && (this.dirty || this.tasks.length)) clock.add(this); }
    setVisible(visible) {
      if (visible === this.visible) return;
      this.visible = visible;
      if (visible) this.wake();
      else clock.remove(this);
    }
    // Paint now, not on the next frame, so a new glyph is never blank.
    flush() { this.dirty = false; this.view.render(this); if (!this.tasks.length) clock.remove(this); }
    mode() {
      if (this.reduced) return 'off';
      const policy = window.AtelierMotionPolicy;
      if (policy) return policy.mode();
      return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'off' : 'full';
    }
    // A change to the Motion setting or to system reduced motion: the piece in flight lands, then the
    // glyph follows the new setting. A shape that has already formed just holds, in the new setting's way.
    policyChanged() {
      const next = this.mode();
      if (next === this.modeNow || !this.state) return;
      this.modeNow = next;
      if (this.state === 'busy' || !this.formed) this.run(this.state, this.asset);
      else if (!this.settled || this.state === 'warning') this.run(this.state, this.asset, 'hold');
    }
    themeChanged() {
      if (!this.settled && this.state !== 'warning') return;
      if (this.state !== 'busy') { this.cols = this.heldColours(this.state); this.touch(); }
    }
    touch() { this.dirty = true; this.wake(); }
    place(pose) { this.cur = pose; this.touch(); }
    tick(dt) {
      this.time += dt;
      for (const task of [...this.tasks]) {
        if (!task.alive()) { this.finish(task, false); continue; }
        const p = task.ms > 0 ? Math.min(1, (this.time - task.t0) / task.ms) : 1;
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
        this.tasks.push({t0: this.time, ms, ease, fn, alive, resolve});
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

    // ---------- size ----------
    // The tier comes from the host's rendered height. Between Stage and Inline the running animation just
    // carries on in its new frame. Micro has its own poses, so crossing into or out of it starts the state again.
    setSize(tier, height, width) {
      const before = this.tier;
      this.tier = tier;
      this.height = height;
      this.width = width;
      if ((before === 'micro') !== (tier === 'micro')) this.run(this.state, this.asset, 'place');
      else if (before !== tier || tier === 'micro') { this.box = this.frameFor(this.frameName || this.state); this.touch(); }
    }
    scaleOf(box) { return Math.min(this.height / box[3], this.width / box[2]); }
    // Which part of the canvas the host shows for a shape.
    frameFor(name) {
      if (name === 'entrance') return frameOf(POSES.master);
      if (this.tier === 'stage') return FRAME.canvas;
      if (this.tier === 'micro') {
        const pose = micro()[name] || micro().info;
        if (name !== 'busy') return frameOf(pose);
        // Room for the pieces to jostle, in units at the size they'll be drawn.
        return frameOf(pose, JOSTLE_PX / this.scaleOf(frameOf(pose)));
      }
      if (name === 'row' || name === 'info') return FRAME.row;
      if (name === 'success' || name === 'brand') return FRAME.a;
      if (name === 'warning-formed') return frameOf(POSES.warning, 8);
      if (name === 'error-formed') return frameOf(POSES.error, 8);
      return FRAME.canvas;
    }
    frameTo(name, fresh) {
      this.frameName = name;
      const to = this.frameFor(name), ft = ++this.frameTok;
      if (fresh || this.tier === 'stage') { this.box = to; this.touch(); return Promise.resolve(true); }
      const from = [...this.box];
      return this.animate(280, E.move, e => { this.box = from.map((v, i) => v + (to[i] - v) * e); }, () => ft === this.frameTok);
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
      const steps = known(this.cur, to, prefer) || await planLive(this.cur, to, prefer);
      if (tk !== this.token) return false; // replaced while planning: nothing has moved
      for (const st of steps) {
        const ms = Math.max(300, Math.min(640, 220 + pathLen(st.path) * .95)) * this.pace;
        this.moving = this.animate(ms, E.move, e => { this.cur = {...this.cur, [st.id]: pieceAt(st.path, e)}; })
          .then(() => { this.place({...this.cur, [st.id]: {...st.path.b}}); this.moving = null; });
        await this.moving;
        if (tk !== this.token) return false; // stop between pieces, never mid-flight
        await this.pause(40 * this.pace);
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
      if (simulClear(this.cur, sp)) { if (!await this.tweenTo(sp, 380 * this.pace, E.move, tk)) return false; }
      else if (!await this.travelTo(sp, tk, IDS)) return false;
      const sl = slotsFor(a, this.cur); // dockers round to their sides
      if (!await this.travelTo(sl, tk, a.order.slice(1))) return false;
      return this.travelTo(target, tk, a.order); // anchor to the middle, others in
    }

    // ---------- states ----------
    // How a shape looks once it has finished, in this glyph's geometry.
    heldPose(state) {
      if (state === 'entrance') return POSES.master;
      if (this.tier === 'micro') return micro()[state] || micro().info;
      return {success: POSES.master, warning: POSES.warning, error: POSES.error}[state] || rest();
    }
    heldColours(state) {
      const status = this.view.status();
      if (state === 'warning') return all(status.warning);
      if (state === 'error') return all(status.error);
      return state === 'success' && this.tier === 'micro' ? all(status.complete) : {...CAT};
    }
    placeHeld(state) {
      this.load = null;
      this.cols = this.heldColours(state);
      this.frameName = state === 'warning' || state === 'error' ? `${state}-formed` : state;
      this.box = this.frameFor(this.frameName);
      this.place(clone(this.heldPose(state)));
    }
    async run(state, asset = null, how = null) {
      const tk = ++this.token;
      this.state = state;
      this.asset = asset;
      this.settled = false;
      this.formed = false;
      if (this.moving) await this.moving; // let the piece in flight land first
      if (tk !== this.token) return;
      this.pace = 1;
      this.modeNow = this.mode();
      if (how === 'place') {
        if (state !== 'busy') { this.placeHeld(state); this.formed = this.settled = true; return; }
        this.fresh = true;
      }
      const fresh = this.fresh;
      this.fresh = false;
      if (how === 'hold') await this.runHold(tk);
      else if (state === 'entrance' && this.modeNow !== 'full') { this.placeHeld(state); this.onEntrance?.(); }
      else if (state === 'entrance') await this.runEntrance(tk, fresh);
      else if (this.modeNow === 'off') await this.runStill(tk, fresh);
      else if (this.tier === 'micro') await this.runMicro(tk, fresh);
      else if (state === 'busy') await (asset ? this.runLoader(asset, tk, fresh) : this.runWorking(tk, fresh));
      else if (state === 'success') await this.runSuccess(tk);
      else if (state === 'warning') await this.runWarning(tk);
      else if (state === 'error') await this.runError(tk);
      else if (state === 'brand') await this.runBrand(tk);
      else await this.runInfo(tk, fresh);
      if (tk === this.token) { this.formed = state !== 'busy'; this.settled = true; }
    }
    // Off, or system reduced motion: no travel. Each state is a still pose, and the whole glyph
    // cross-fades between them. This is the only fade allowed, and only for accessibility.
    async crossFade(tk, change) {
      const from = this.opacity ?? 1;
      this.moving = this.animate(150 * from, E.linear, e => { this.opacity = from * (1 - e); }).then(() => { this.moving = null; });
      await this.moving;
      if (tk !== this.token) return false;
      change();
      this.moving = this.animate(150, E.linear, e => { this.opacity = e; }).then(() => { this.opacity = 1; this.touch(); this.moving = null; });
      await this.moving;
      return tk === this.token;
    }
    stillPose() {
      if (this.state !== 'busy') return this.heldPose(this.state);
      if (this.tier === 'micro') return micro().busy;
      return this.asset ? rest() : fits()[0].contact;
    }
    async runStill(tk, fresh) {
      const state = this.state, pose = this.stillPose();
      const change = () => {
        this.load = null;
        this.fx = {punch: 1, dsx: 1, dsy: 1, ringR: 0, ringW: 0, ringOp: 0};
        this.cols = this.heldColours(state);
        this.frameName = state === 'busy' ? (this.asset ? 'row' : 'busy') : state === 'warning' || state === 'error' ? `${state}-formed` : state;
        this.box = this.frameFor(this.frameName);
        this.place(clone(pose));
      };
      if (fresh) change();
      else if (!await this.crossFade(tk, change)) return;
      if (state !== 'success' || this.tier === 'micro') return;
      // Complete still changes colour: green after a beat, then home.
      if (!await this.sleep(120, tk)) return;
      await this.colourTo(all(this.view.status().complete), 240);
      if (!await this.sleep(160, tk)) return;
      await this.colourTo(CAT, 380);
    }
    // The shape is already formed and the setting changed: stay on it, in the new setting's way.
    async runHold(tk) {
      const state = this.state, pose = this.heldPose(state), cols = this.heldColours(state);
      if (this.modeNow === 'off') {
        await this.crossFade(tk, () => { this.cols = cols; this.place(clone(pose)); });
        return;
      }
      this.colourTo(cols, 200);
      if (!await this.tweenTo(pose, 240, E.rest, tk)) return;
      if (state === 'warning' && this.wobbles()) await this.wobble(tk);
    }
    wobbles() { return this.tier === 'stage' && this.modeNow === 'full'; }
    // Micro: a static shape with one short settle, and a small jostle while busy (SPEC section 5).
    async runMicro(tk, fresh) {
      const name = this.state === 'brand' ? 'success' : this.state, base = micro()[name], status = this.view.status();
      const target = {success: all(status.complete), warning: all(status.warning), error: all(status.error)}[name] || CAT;
      this.load = null;
      this.frameTo(name, true);
      const cx = (base.blue.x + base.teal.x + base.disc.x) / 3, cy = (base.blue.y + base.teal.y + base.disc.y) / 3;
      const u = JOSTLE_PX / this.scaleOf(this.box), out = {};
      for (const id of IDS) {
        // In the row the ends move outwards and the tile lifts. Elsewhere each piece moves away from the middle.
        const row = name === 'busy' || name === 'info', v = row ? {blue: [0, -1], teal: [-1, 0], disc: [1, 0]}[id] : [base[id].x - cx, base[id].y - cy], l = Math.hypot(...v) || 1;
        out[id] = [v[0] / l * u, v[1] / l * u];
      }
      const cur = this.cur = clone(base);
      const offset = (id, by) => { cur[id].x = base[id].x + out[id][0] * by; cur[id].y = base[id].y + out[id][1] * by; };
      if (name !== 'busy') {
        // Shape first, then colour: the status colour only arrives once the shape has come together.
        if (!fresh && !this.isCat()) this.cols = {...CAT};
        const colour = this.pause(100).then(() => this.colourTo(target, 100));
        await this.animate(200, E.out, e => { for (const id of IDS) offset(id, 1 - e); });
        await colour;
        return;
      }
      this.cols = {...CAT};
      this.touch();
      // Each piece moves out and back in turn, so they never line up into a shape.
      const windows = {blue: 0, teal: .16, disc: .32}, width = .5;
      while (tk === this.token) {
        if (!await this.animate(JOSTLE_MS, E.linear, (e, p) => {
          for (const id of IDS) {
            const u = (p - windows[id]) / width, s = u > 0 && u < 1 ? Math.sin(Math.PI * u) : 0;
            offset(id, s * s);
          }
        }, () => tk === this.token)) return;
      }
    }
    async runInfo(tk, fresh) {
      const framed = this.frameTo('info', fresh);
      if (!this.isCat()) this.colourTo(CAT, 240);
      if (!atRest(this.cur)) await this.openTo(rest(), tk);
      await framed;
    }
    async runWorking(tk, fresh) {
      this.frameTo('busy', fresh);
      if (this.tier === 'inline') this.pace = .8;
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
        if (!await this.tweenTo(a.contact, 200 * this.pace, E.out, tk)) return; // dock
        if (!await this.tweenTo(a.tap, 120 * this.pace, E.windup, tk)) return; // test the fit
        if (!await this.tweenTo(a.contact, 110 * this.pace, E.snap, tk)) return; // tap
        if (!await this.sleep(180 * this.pace, tk)) return; // not it
      }
    }
    async runLoader(asset, tk, fresh) {
      this.frameTo('row', fresh);
      if (!this.isCat()) this.colourTo(CAT, 240);
      if (fresh) this.place(clone(rest()));
      else if (!atRest(this.cur) && !await this.openTo(rest(), tk)) return;
      const loaders = this.modeNow === 'calm'
        ? {mesh: this.calmMesh, texture: this.calmTexture, material: this.calmMaterial}
        : {mesh: this.loadMesh, texture: this.loadTexture, material: this.loadMaterial};
      this.moving = loaders[asset].call(this, tk).then(() => { this.moving = null; });
      await this.moving;
    }
    async runSuccess(tk) {
      const M = POSES.master;
      const framed = this.frameTo('success');
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
      this.formed = true;
      const effects = this.impact();
      if (!await this.tweenTo(nudge(M, 1), 110, E.recoil, tk)) return; // recoil
      if (!await this.tweenTo(M, 130, E.rest, tk)) return; // rest
      await Promise.all([effects, framed]);
      if (!await this.sleep(160, tk)) return;
      await this.colourTo(CAT, 380);
    }
    // The click: hard contact, squash and punch and ripple, colour spreading from the disc.
    // Impact effects always finish: cutting them off would pop.
    impact() {
      const {fx} = this, green = this.view.status().complete, colour = this.colourTo(all(green), 220, {disc: 0, blue: 60, teal: 120});
      if (this.modeNow !== 'full') return colour; // Calm: the shape and the colour, without the flourish
      window.AtelierFoley?.click();
      fx.dsx = .88; fx.dsy = 1.12; fx.punch = 1; fx.ringC = green;
      const ripple = this.tier !== 'stage' ? null : this.animate(620, E.out, (e, p) => { fx.ringR = 60 + e * 140; fx.ringW = 12 * Math.pow(1 - p, .6); fx.ringOp = Math.pow(1 - p, 1.4); });
      const squash = this.animate(300, E.punchBack, e => { fx.dsx = .88 + (1 - .88) * e; fx.dsy = 1.12 + (1 - 1.12) * e; });
      const punch = this.animate(70, E.punchOut, e => { fx.punch = 1 + .045 * e; })
        .then(() => this.animate(260, E.punchBack, e => { fx.punch = 1.045 - .045 * e; }));
      return Promise.all([ripple, squash, colour, punch]);
    }
    async runWarning(tk) {
      const W = POSES.warning, alive = () => tk === this.token;
      this.frameTo('warning');
      if (!this.isCat()) this.colourTo(CAT, 200); // back to their own colours first
      if (!await this.assemble({...OUT.warning, contact: W}, W, tk)) return; // dot down, stem on the dot, tile on top
      this.formed = true;
      this.colourTo(all(this.view.status().warning), 200);
      // Catch the balance: a few decaying sways, the tile lagging the stem.
      const sway = t => 5 * Math.exp(-2.4 * t) * Math.sin(2 * Math.PI * 1.3 * t);
      if (!this.wobbles()) {
        // One sway and then still.
        const swayMs = 1000 / 1.3 * .8;
        if (!await this.animate(swayMs, E.linear, (e, p) => {
          const t = p / 1.3, w = (1 - p) * (1 - p);
          this.cur = warningPose(WREST.th + sway(t) * w, WREST.ph - .6 * sway(Math.max(0, t - .1)) * w);
        }, alive)) return;
        this.place(clone(W));
        await this.frameTo('warning-formed');
        return;
      }
      if (!await this.animate(1600, E.linear, (e, p) => {
        const t = p * 1.6, w = (1 - p) * (1 - p);
        this.cur = warningPose(WREST.th + sway(t) * w, WREST.ph - .6 * sway(Math.max(0, t - .1)) * w);
      }, alive)) return;
      await this.wobble(tk);
    }
    // Keep wobbling gently for as long as the warning stands.
    async wobble(tk) {
      const alive = () => tk === this.token;
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
      this.frameTo('error');
      if (!this.isCat()) this.colourTo(CAT, 200);
      if (!await this.assemble({...OUT.error, contact: open}, open, tk)) return; // bar down, bar across, disc pins them
      if (!await this.tweenTo(X, 150, E.out, tk)) return; // clamp shut
      this.formed = true;
      await Promise.all([this.frameTo('error-formed'), this.colourTo(all(this.view.status().error), 200)]);
    }

    // The brand mark's route (the logo's entrance): the tile settles, the mesh waits, the disc comes in, the mesh closes.
    async runBrand(tk) {
      const M = POSES.master, wait = standOff(M);
      this.frameTo('brand');
      this.colourTo(CAT, 240);
      if (!await this.assemble({...OUT.master, contact: wait, fixed: ['teal']}, wait, tk)) return;
      await this.travelTo(M, tk, ['teal']);
    }

    // The header logo's entrance at small sizes. A brand moment and not a status: category colours only,
    // with no green, click, punch or ripple. It ends exactly on the master mark, so the still logo can take over.
    async runEntrance(tk, fresh) {
      const M = POSES.master, start = logoStart();
      this.frameTo('entrance', true);
      if (fresh) this.place(start);
      this.pace = .8;
      // The tile settles and the mesh goes to its stand-off, then the disc comes in and the mesh closes.
      if (!await this.travelTo({blue: M.blue, teal: standOff(M).teal, disc: start.disc}, tk, ['blue', 'teal'])) return;
      if (!await this.travelTo(M, tk, ['disc', 'teal'])) return;
      this.place(clone(M));
      this.onEntrance?.();
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
    // Calm's loaders: nothing lifts, leans, slides or changes colour, and the rhythm is slow. One piece
    // shows it's working with its own quietest gesture, and a new state lands within a step.
    async calmMesh(tk) {
      let last = -1;
      while (tk === this.token) {
        let i;
        do { i = Math.floor(Math.random() * CONFIGS.length); } while (i === last);
        last = i;
        const load = this.load = {kind: 'mesh', lines: CONFIGS[i], w: 0};
        await this.animate(240, E.windup, e => { load.w = G * e; });
        await this.sleep(700, tk);
        await this.animate(240, E.windup, e => { load.w = G * (1 - e); });
        this.load = null;
        this.touch();
        if (!await this.sleep(420, tk)) break;
      }
      this.load = null;
      this.touch();
    }
    async calmTexture(tk) {
      while (tk === this.token) {
        const load = this.load = {kind: 'texture', gap: 0, off: [0, 0, 0, 0, 0], tone: Array(BANDS).fill(CAT.blue)};
        await this.animate(240, E.windup, e => { load.gap = 9 * e; });
        await this.sleep(700, tk);
        await this.animate(240, E.windup, e => { load.gap = 9 * (1 - e); });
        this.load = null;
        this.touch();
        if (!await this.sleep(420, tk)) break;
      }
      this.load = null;
      this.touch();
    }
    async calmMaterial(tk) {
      while (tk === this.token) {
        const load = this.load = {kind: 'material', at: -1.5, ang: 25};
        await this.animate(620, E.move, e => { load.at = -1.5 + 2.9 * e; });
        this.load = null;
        this.touch();
        if (!await this.sleep(980, tk)) break;
      }
      this.load = null;
      this.touch();
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
