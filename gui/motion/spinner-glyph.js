// Every .spinner on the page is the Micro glyph, working, however it was added. Its plain ring in style.css
// only shows if the glyph can't mount. A thumbnail's spinner is never seen, and the export fallback has
// a glyph of its own beside it, so those two stay as they are.
(() => {
  'use strict';
  const SKIP = '.export-feedback-fallback';
  const live = new Map();

  function upgrade(spinner) {
    const motion = window.AtelierMotion?.glyph;
    if (!motion || live.has(spinner) || spinner.matches(SKIP)) return;
    // A copy of a spinner carries the original's drawing, with nothing behind it.
    if (spinner.hasAttribute('data-atelier-motion')) spinner.replaceChildren();
    try { live.set(spinner, motion.mount(spinner, {state: 'busy'})); }
    catch (error) { console.warn('Spinner glyph unavailable', error); }
  }

  function scan(node) {
    if (node.nodeType !== 1) return;
    if (node.classList?.contains('spinner')) upgrade(node);
    for (const spinner of [...node.getElementsByClassName('spinner')]) upgrade(spinner);
  }

  new MutationObserver(records => {
    for (const record of records) for (const node of record.addedNodes) scan(node);
    for (const [spinner, glyph] of live) {
      if (!spinner.isConnected) { live.delete(spinner); glyph.destroy(); }
    }
  }).observe(document.documentElement, {childList: true, subtree: true});
  scan(document.documentElement);
})();
