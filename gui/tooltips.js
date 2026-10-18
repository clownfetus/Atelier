// Delegate to dynamic editors too. Keep title as the no-script fallback and
// preserve accessible names while a themed tooltip replaces the native bubble.
(() => {
  'use strict';
  let owner, title, timer, tooltip, addedLabel = false;
  let input = 'pointer';
  const id = 'atelier-tooltip';
  function hide() {
    clearTimeout(timer);
    if (owner) {
      if (!owner.hasAttribute('title')) owner.setAttribute('title', title);
      const description = (owner.getAttribute('aria-describedby') || '').split(/\s+/).filter(value => value && value !== id).join(' ');
      if (description) owner.setAttribute('aria-describedby', description);
      else owner.removeAttribute('aria-describedby');
      if (addedLabel && owner.getAttribute('aria-label') === title) owner.removeAttribute('aria-label');
    }
    if (tooltip) {
      if (typeof tooltip.hidePopover === 'function' && tooltip.matches(':popover-open')) tooltip.hidePopover();
      tooltip.hidden = true;
    }
    owner = null; addedLabel = false;
  }
  function show() {
    if (!owner?.isConnected) { hide(); return; }
    tooltip ||= Object.assign(document.createElement('div'), {id, className: 'studio-tooltip'});
    tooltip.setAttribute('role', 'tooltip');
    tooltip.textContent = title;
    // A dialog's top layer makes unrelated body children inert.
    (owner.closest('dialog[open]') || document.body).append(tooltip);
    tooltip.hidden = false;
    if (typeof tooltip.showPopover === 'function') {
      tooltip.setAttribute('popover', 'manual'); tooltip.showPopover();
    }
    const bounds = owner.getBoundingClientRect(), rect = tooltip.getBoundingClientRect();
    tooltip.style.left = Math.max(8, Math.min(bounds.left, innerWidth - rect.width - 8)) + 'px';
    tooltip.style.top = (bounds.bottom + rect.height + 12 < innerHeight
      ? bounds.bottom + 6 : Math.max(8, bounds.top - rect.height - 6)) + 'px';
    owner.setAttribute('aria-describedby', ((owner.getAttribute('aria-describedby') || '') + ' ' + id).trim());
  }
  function begin(target) {
    if (owner?.contains(target) || tooltip?.contains(target)) return;
    const candidate = target.closest?.('[title]');
    if (candidate === owner) return;
    hide();
    if (!candidate?.getAttribute('title')?.trim()) return;
    owner = candidate; title = owner.getAttribute('title');
    if (!owner.hasAttribute('aria-label') && !owner.hasAttribute('aria-labelledby') && !owner.labels?.length
        && (owner.matches('input,select,textarea') || owner.matches('button,a') && !owner.textContent.trim())) {
      owner.setAttribute('aria-label', title); addedLabel = true;
    }
    owner.removeAttribute('title');
    timer = setTimeout(show, 400);
  }
  document.addEventListener('pointerover', event => {
    // A view transition can retarget the stationary pointer after keyboard focus
    // moved. Preserve the focused control's description until focus/click leaves it.
    if (input === 'keyboard' && owner?.contains(document.activeElement) && !owner.contains(event.target)) return;
    begin(event.target);
  });
  let pointerX, pointerY;
  document.addEventListener('pointermove', event => {
    if (event.clientX === pointerX && event.clientY === pointerY) return;
    pointerX = event.clientX; pointerY = event.clientY;
    input = 'pointer';
    // A real pointer move takes over from keyboard focus, including a focused first card.
    begin(event.target);
  });
  document.addEventListener('focusin', event => { if (input === 'keyboard') begin(event.target); });
  for (const type of ['pointerout', 'focusout']) document.addEventListener(type, event => {
    if ((owner?.contains(event.target) || tooltip?.contains(event.target))
        && !owner?.contains(event.relatedTarget) && !tooltip?.contains(event.relatedTarget)) hide();
  });
  document.addEventListener('keydown', event => { input = 'keyboard'; if (event.key === 'Escape') hide(); }, true);
  document.addEventListener('pointerdown', () => { input = 'pointer'; hide(); }, true);
  document.addEventListener('scroll', hide, true);
  window.addEventListener('blur', hide);
})();
