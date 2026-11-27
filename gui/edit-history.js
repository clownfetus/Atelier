// Step-by-step Undo / Redo snapshot history for Atelier editors (Ctrl+Z / Ctrl+Shift+Z).
(() => {
  'use strict';

  const registry = new Map();

  function clone(value) {
    if (typeof structuredClone === 'function') return structuredClone(value);
    return JSON.parse(JSON.stringify(value));
  }

  function create({ limit = 50, coalesceMs = 350 } = {}) {
    let entries = [];
    let cursor = -1;
    let lastKey = '';
    let lastAt = 0;

    function reset(snapshot) {
      entries = snapshot == null ? [] : [clone(snapshot)];
      cursor = entries.length - 1;
      lastKey = '';
      lastAt = 0;
    }

    function record(snapshot, key = '') {
      if (snapshot == null) return;
      const now = Date.now();
      const copy = clone(snapshot);
      if (cursor >= 0 && key && key === lastKey && now - lastAt <= coalesceMs && cursor === entries.length - 1) {
        entries[cursor] = copy;
        lastAt = now;
        return;
      }
      if (cursor < entries.length - 1) entries = entries.slice(0, cursor + 1);
      entries.push(copy);
      if (entries.length > limit) {
        entries.shift();
      }
      cursor = entries.length - 1;
      lastKey = key || '';
      lastAt = now;
    }

    function undo() {
      if (cursor <= 0) return null;
      cursor--;
      lastKey = '';
      lastAt = 0;
      return clone(entries[cursor]);
    }

    function redo() {
      if (cursor < 0 || cursor >= entries.length - 1) return null;
      cursor++;
      lastKey = '';
      lastAt = 0;
      return clone(entries[cursor]);
    }

    return {
      reset,
      record,
      undo,
      redo,
      canUndo: () => cursor > 0,
      canRedo: () => cursor >= 0 && cursor < entries.length - 1,
      size: () => entries.length,
    };
  }

  function register(overlayId, handlers) {
    registry.set(overlayId, handlers);
  }

  function topOverlayId() {
    const active = [...document.querySelectorAll('.overlay.active:not(.mounted)')];
    return active.at(-1)?.id || '';
  }

  document.addEventListener('keydown', event => {
    if (!(event.ctrlKey || event.metaKey) || event.altKey) return;
    const key = event.key.toLowerCase();
    const isUndo = key === 'z' && !event.shiftKey;
    const isRedo = (key === 'z' && event.shiftKey) || (key === 'y' && !event.shiftKey);
    if (!isUndo && !isRedo) return;
    const target = event.target;
    if (target instanceof HTMLElement && target.matches('input[type="text"], input[type="search"], textarea, [contenteditable="true"]')) {
      return;
    }
    const id = topOverlayId();
    const handler = registry.get(id);
    if (!handler) return;
    const handled = isUndo ? handler.undo?.() : handler.redo?.();
    if (handled) {
      event.preventDefault();
      event.stopPropagation();
    }
  });

  window.AtelierHistory = Object.freeze({ create, register });
})();
