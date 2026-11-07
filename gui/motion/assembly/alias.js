/*
 * The old glyph's callers on the assembly glyph, unchanged: Activity rows, toasts, Open a mod and the
 * update button. The setup rows still pass `found` and keep the old glyph until first-run setup
 * changes over. This file goes when Krackle does. Load after glyph.js and krackle-glyph.js.
 */
(() => {
  'use strict';
  const motion = window.AtelierMotion, old = motion.krackleGlyph;

  function mount(host, options) {
    const opts = options || {};
    if (opts.found) return old.mount(host, opts);
    let state = opts.state, reduced = opts.reducedMotion;
    let glyph = motion.glyph.mount(host, {state, reducedMotion: reduced});
    return {
      setState(next) { state = next; glyph.set(next); },
      replay() { glyph.replay(); },
      // A glyph's own reducedMotion is fixed when it's mounted, so a change means mounting it again.
      setReducedMotion(mode) {
        if (mode === reduced) return;
        reduced = mode;
        glyph.destroy();
        glyph = motion.glyph.mount(host, {state, reducedMotion: reduced});
      },
      destroy() { glyph.destroy(); },
    };
  }

  motion.krackleGlyph = {mount};
})();
