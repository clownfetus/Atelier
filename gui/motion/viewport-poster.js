// Presentation only: the costume artwork the user opened lands on the Model Studio stage as a poster
// while the model decodes, stays dimmed behind the arriving geometry, and leaves with the reveal sweep.
// Model loading never waits for it. Missing artwork, a refused moment, Calm and Off skip parts of it.
(() => {
  'use strict';
  const motion = window.AtelierMotion ||= {};
  const allows = tier => window.AtelierMotionPolicy ? AtelierMotionPolicy.allows(tier) : !matchMedia('(prefers-reduced-motion: reduce)').matches;
  const visible = el => el?.isConnected && el.getClientRects().length;
  // Room below the poster for the loader formation and its message while the model decodes.
  const LOADER_RESERVE = 250;
  let pointer = null, current = null;
  document.addEventListener('pointerdown', event => { pointer = {target: event.target, at: performance.now()}; }, true);

  // Read before the studio opens: the pressed artwork first, then keyboard focus.
  function source() {
    const entering = !document.getElementById('viewport-overlay')?.classList.contains('active');
    if (!entering) return {entering};
    const recent = pointer && performance.now() - pointer.at < 4000 ? pointer.target : null;
    for (const origin of [recent, document.activeElement]) {
      if (!origin?.closest || origin.closest('#viewport-overlay')) continue;
      const host = origin.closest('.card, .roster-skin, .roster-portrait, .search-result, button');
      const image = host?.querySelector('img.hero-portrait, img.roster-skin-icon, img');
      if (visible(image) && image.complete && image.naturalWidth)
        return {entering, image, rect: image.getBoundingClientRect(), radius: parseFloat(getComputedStyle(image).borderTopLeftRadius) || 0};
    }
    return {entering};
  }

  function begin({skinId, origin, stage, canvas}) {
    end();
    if (!stage || !canvas || !origin?.entering) return;
    const sharp = /^\d{7}$/.test(skinId || '') ? new URL('/api/catalogue/thumbnail/' + skinId, location.href).href : null;
    const first = origin.image?.currentSrc || origin.image?.src || sharp;
    if (!first) return;
    const aspect = origin.image ? origin.image.naturalWidth / origin.image.naturalHeight : 1;
    const poster = document.createElement('figure'); poster.className = 'vp-poster'; poster.dataset.phase = 'loading';
    poster.setAttribute('aria-hidden', 'true');
    const image = new Image(); image.alt = ''; image.decoding = 'async'; image.draggable = false; image.src = first;
    image.onerror = () => { if (current?.image === image) end(); };
    poster.append(image); canvas.before(poster); stage.classList.add('vp-has-poster');
    const state = current = {poster, image, stage, canvas, aspect, phase: 'loading', flight: null};
    const target = place(state);
    if (sharp && sharp !== first) {
      const better = new Image(); better.decoding = 'async'; better.src = sharp;
      better.decode().then(() => { if (current === state) image.src = sharp; }).catch(() => {});
    }
    // The flight belongs to the studio's own 'viewport-load' moment, so it never claims one of its own.
    if (origin.image && allows(2) && !document.hidden) { fly(state, origin, target); return; }
    if (allows(1) && !document.hidden) {
      try { poster.animate([{opacity: 0, transform: 'scale(.97)'}, {opacity: 1, transform: 'none'}],
        {duration: 200, easing: motion.ease?.standard || 'cubic-bezier(.2,0,0,1)'}); } catch (_) {}
    }
  }

  // Centred over the canvas, above the loader's reserved space; fixed for the poster's lifetime.
  function place(state) {
    const {poster, stage, canvas, aspect} = state;
    const area = canvas.getBoundingClientRect(), box = stage.getBoundingClientRect();
    const room = area.height - LOADER_RESERVE - 24;
    const height = Math.max(96, Math.min(room, area.width * .46 / aspect, 520)), width = height * aspect;
    const left = area.x - box.x + (area.width - width) / 2, top = area.y - box.y + 24 + Math.max(0, (room - height) / 2);
    Object.assign(poster.style, {left: left + 'px', top: top + 'px', width: width + 'px', height: height + 'px'});
    return new DOMRect(box.x + left, box.y + top, width, height);
  }

  // A disposable copy above the fading overlay carries the artwork from its card to the stage.
  function fly(state, origin, target) {
    const {poster} = state, from = origin.rect;
    poster.style.visibility = 'hidden';
    const ghost = new Image(); ghost.className = 'vp-poster-flight'; ghost.alt = ''; ghost.setAttribute('aria-hidden', 'true');
    ghost.src = origin.image.currentSrc || origin.image.src;
    Object.assign(ghost.style, {left: target.x + 'px', top: target.y + 'px', width: target.width + 'px', height: target.height + 'px'});
    document.body.append(ghost);
    // Start as the card's own crop (cover), then open out to the whole poster.
    const scale = Math.max(from.width / target.width, from.height / target.height);
    const dx = from.x + from.width / 2 - (target.x + target.width / 2), dy = from.y + from.height / 2 - (target.y + target.height / 2);
    const ix = Math.max(0, (target.width - from.width / scale) / 2), iy = Math.max(0, (target.height - from.height / scale) / 2);
    let animation;
    const land = () => {
      if (state.flight !== land) return;
      state.flight = null; animation?.cancel(); ghost.remove();
      if (poster.isConnected) poster.style.visibility = '';
    };
    state.flight = land;
    try {
      animation = ghost.animate([
        {transform: `translate(${dx}px,${dy}px) scale(${scale})`, clipPath: `inset(${iy}px ${ix}px round ${origin.radius / scale}px)`},
        {transform: 'none', clipPath: 'inset(0px 0px round 6px)'}],
        {duration: 460, easing: motion.ease?.emphasized || motion.ease?.standard || 'cubic-bezier(.2,0,0,1)'});
      animation.finished.then(land, land);
    } catch (_) { land(); }
    setTimeout(land, 540);
  }

  // Called by the inspection renderer for each live frame, after it has advanced the reveal sweep.
  function frame(assetsLoading, reveal, sweeping) {
    const state = current;
    if (!state || state.phase === 'settled') return;
    if (document.getElementById('viewport-loading')?.style.display !== 'none') {
      // A loader that stays up with nothing loading is an error or empty result: its text must read clearly.
      if (!assetsLoading) end();
      return;
    }
    if (sweeping) {
      state.phase = 'reveal'; state.poster.dataset.phase = 'reveal';
      state.poster.style.setProperty('--vp-poster-wipe', reveal.toFixed(3));
      return;
    }
    if (assetsLoading) { if (state.phase === 'loading') { state.phase = 'geometry'; state.poster.dataset.phase = 'geometry'; } return; }
    settle(state);
  }

  function settle(state) {
    state.phase = 'settled'; state.flight?.();
    if (!allows(1) || document.hidden || state.poster.dataset.phase === 'reveal') { end(); return; }
    state.poster.dataset.phase = 'settled';
    setTimeout(() => { if (current === state) end(); }, 240);
  }

  function end() {
    const state = current; current = null;
    if (!state) return;
    state.flight?.(); state.poster.remove(); state.stage.classList.remove('vp-has-poster');
  }

  window.addEventListener('resize', () => { if (current?.phase === 'loading' && !current.flight) place(current); });
  document.addEventListener('visibilitychange', () => { if (document.hidden) current?.flight?.(); });
  window.AtelierMotionPolicy?.query().addEventListener('change', () => { if (!allows(2)) current?.flight?.(); });
  window.addEventListener('pagehide', end);
  motion.viewportPoster = Object.freeze({source, begin, frame, end});
})();
