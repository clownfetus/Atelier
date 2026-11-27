// Uniform keyboard focus containment and focus return for .overlay modals.
(() => {
  'use strict';

  const SELF_MANAGED = new Set([
    'atelier-confirm',
    'setup-overlay',
    'changelog-overlay',
    'export-review-overlay',
  ]);
  const FOCUSABLE = [
    'a[href]',
    'area[href]',
    'button:not([disabled])',
    'input:not([disabled]):not([type="hidden"])',
    'select:not([disabled])',
    'textarea:not([disabled])',
    'summary',
    '[tabindex]:not([tabindex="-1"])',
  ].join(',');

  const openers = new WeakMap();
  const stack = [];

  function isVisible(el) {
    if (!el || !el.isConnected) return false;
    if (el.hidden || el.closest('[hidden],[inert]')) return false;
    const style = getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden') return false;
    return el.getClientRects().length > 0;
  }

  function focusables(root) {
    return [...root.querySelectorAll(FOCUSABLE)].filter(el =>
      el.tabIndex >= 0 && !el.matches(':disabled') && isVisible(el));
  }

  function isActiveModal(node) {
    return node instanceof HTMLElement &&
      node.classList.contains('overlay') &&
      node.classList.contains('active') &&
      !node.classList.contains('mounted');
  }

  function topOverlay() {
    for (let i = stack.length - 1; i >= 0; i--) {
      if (isActiveModal(stack[i])) return stack[i];
      stack.splice(i, 1);
    }
    return null;
  }

  function modalPanel(overlay) {
    return overlay.querySelector('[role="dialog"],[role="alertdialog"],.modal') || overlay;
  }

  function onOpened(overlay) {
    if (!stack.includes(overlay)) stack.push(overlay);
    if (SELF_MANAGED.has(overlay.id)) return;
    const current = document.activeElement;
    if (current instanceof HTMLElement && !overlay.contains(current)) {
      openers.set(overlay, current);
    }
    const panel = modalPanel(overlay);
    if (!panel.hasAttribute('tabindex')) panel.tabIndex = -1;
    // Let the caller focus a specific field first; only fall back if focus remained outside.
    queueMicrotask(() => {
      if (!isActiveModal(overlay) || topOverlay() !== overlay) return;
      if (overlay.contains(document.activeElement)) return;
      const targets = focusables(panel);
      (targets[0] || panel).focus({ preventScroll: true });
    });
  }

  function onClosed(overlay) {
    const idx = stack.indexOf(overlay);
    if (idx >= 0) stack.splice(idx, 1);
    if (SELF_MANAGED.has(overlay.id)) return;
    const opener = openers.get(overlay);
    openers.delete(overlay);
    if (opener?.isConnected && (!document.activeElement || document.activeElement === document.body || overlay.contains(document.activeElement))) {
      opener.focus({ preventScroll: true });
    }
  }

  function syncOverlay(overlay) {
    if (isActiveModal(overlay)) {
      if (!stack.includes(overlay)) onOpened(overlay);
    } else if (stack.includes(overlay)) {
      onClosed(overlay);
    }
  }

  document.addEventListener('keydown', event => {
    if (event.key !== 'Tab' || event.defaultPrevented) return;
    if (document.querySelector('dialog[open]') || event.target.closest?.('#ctx-menu.active')) return;
    const overlay = topOverlay();
    if (!overlay || SELF_MANAGED.has(overlay.id)) return;
    const panel = modalPanel(overlay);
    const items = focusables(panel);
    if (!items.length) {
      event.preventDefault();
      panel.focus({ preventScroll: true });
      return;
    }
    const first = items[0];
    const last = items[items.length - 1];
    const active = document.activeElement;
    if (!panel.contains(active)) {
      event.preventDefault();
      (event.shiftKey ? last : first).focus({ preventScroll: true });
    } else if (event.shiftKey && (active === first || active === panel)) {
      event.preventDefault();
      last.focus({ preventScroll: true });
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus({ preventScroll: true });
    }
  }, true);

  function init() {
    document.querySelectorAll('.overlay').forEach(syncOverlay);
    const observer = new MutationObserver(records => {
      for (const record of records) {
        if (record.type === 'attributes' && record.target instanceof HTMLElement && record.target.classList.contains('overlay')) {
          syncOverlay(record.target);
        } else if (record.type === 'childList') {
          for (const node of record.addedNodes) {
            if (node instanceof HTMLElement && node.classList.contains('overlay')) syncOverlay(node);
          }
          for (const node of record.removedNodes) {
            if (node instanceof HTMLElement && stack.includes(node)) onClosed(node);
          }
        }
      }
    });
    observer.observe(document.body, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ['class'],
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
  else init();

  window.AtelierModal = Object.freeze({ topOverlay, focusables });
})();
