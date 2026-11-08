// Shared motion timing. Load after tokens.css and before the motion controllers.
(() => {
  'use strict';
  const motion = window.AtelierMotion ||= {};
  const tokens = getComputedStyle(document.documentElement);
  function milliseconds(name, fallback) {
    const value = tokens.getPropertyValue(name).trim();
    const amount = parseFloat(value) * (value.endsWith('ms') ? 1 : 1000);
    return Number.isFinite(amount) && amount > 0 ? amount : fallback;
  }
  motion.beatMs = milliseconds('--motion-beat', 1040);
  motion.exitMs = milliseconds('--studio-motion-exit', 120);
  motion.panelMs = milliseconds('--studio-motion-panel', 320);
  motion.travelMs = milliseconds('--studio-motion-travel', 520);
  motion.unfoldMs = milliseconds('--studio-motion-unfold', 280);
  motion.foldMs = milliseconds('--studio-motion-fold', 190);
  motion.unfoldLargeMs = milliseconds('--studio-motion-unfold-large', 400);
  motion.springMs = Object.freeze({
    snappy: milliseconds('--studio-spring-snappy-duration', 340),
    bouncy: milliseconds('--studio-spring-bouncy-duration', 610),
  });
  motion.ease = Object.freeze({
    standard: tokens.getPropertyValue('--studio-easing').trim() || 'cubic-bezier(0.2, 0, 0, 1)',
    exit: tokens.getPropertyValue('--studio-easing-exit').trim() || 'cubic-bezier(0.3, 0, 1, 1)',
    emphasized: tokens.getPropertyValue('--studio-easing-emphasized').trim() || 'cubic-bezier(0.05, 0.7, 0.1, 1)',
    snappy: tokens.getPropertyValue('--studio-spring-snappy').trim() || 'cubic-bezier(0.22, 0.8, 0.32, 1.12)',
    bouncy: tokens.getPropertyValue('--studio-spring-bouncy').trim() || 'cubic-bezier(0.34, 1.56, 0.64, 1)',
    unfold: tokens.getPropertyValue('--studio-easing-unfold').trim() || 'cubic-bezier(0.16, 1, 0.3, 1)',
  });
  // The glyph's curves (move, out, snap, recoil and the rest) live in assembly/pieces.js, as assembly.curves.

  // Pop-ups (P4b.7): a menu, tooltip or caption opens out of the edge it belongs to and folds back into it.
  // `edge` names that edge: 'top' opens downwards (a menu under its button), 'bottom' opens upwards (a toast,
  // a menu flipped above its pointer), 'centre' opens both ways. The clip's spare 40px leaves room for the
  // menu shadow. Nothing fades. Off and reduced motion cut: unfold does nothing and fold calls done at once.
  const CLOSED = {top: 'inset(0 -40px 100% -40px)', bottom: 'inset(100% -40px 0 -40px)', centre: 'inset(50% -40px 50% -40px)'};
  const NUDGE = {top: '0 -6px', bottom: '0 6px', centre: '0 6px'};
  const OPEN = 'inset(-40px)';
  const playing = new WeakMap();
  const still = () => window.AtelierMotionPolicy ? !window.AtelierMotionPolicy.allows(1) : matchMedia('(prefers-reduced-motion: reduce)').matches;
  function run(el, frames, duration, easing) {
    playing.get(el)?.cancel();
    if (!el?.isConnected || typeof el.animate !== 'function' || still() || document.hidden) { playing.delete(el); return null; }
    const animation = el.animate(frames, {duration, easing});
    playing.set(el, animation);
    animation.finished.then(() => { if (playing.get(el) === animation) playing.delete(el); }, () => {});
    return animation;
  }
  motion.unfold = (el, edge = 'top', duration = motion.unfoldMs) => run(el,
    [{clipPath: CLOSED[edge] || CLOSED.top, translate: NUDGE[edge] || NUDGE.top}, {clipPath: OPEN, translate: '0 0'}], duration, motion.ease.unfold);
  // Folds the pop-up away and then calls done, which hides or removes it. A fold already under way is replaced.
  motion.fold = (el, edge = 'top', done = () => {}, duration = motion.foldMs) => {
    let called = false; const finish = () => { if (!called) { called = true; done(); } };
    const animation = run(el, [{clipPath: OPEN, translate: '0 0'}, {clipPath: CLOSED[edge] || CLOSED.top, translate: NUDGE[edge] || NUDGE.top}],
      duration, motion.ease.exit);
    if (!animation) { finish(); return null; }
    animation.effect.updateTiming({fill: 'forwards'});
    animation.finished.then(() => { finish(); animation.cancel(); }, () => {});
    setTimeout(() => { if (playing.get(el) === animation) finish(); }, duration + 80);
    return animation;
  };
  // Stops a fold without finishing it, when the pop-up is asked back before it has gone.
  motion.unfoldStop = el => { playing.get(el)?.cancel(); playing.delete(el); };
})();
