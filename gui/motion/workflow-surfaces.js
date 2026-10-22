// Opening an ordinary tool surface draws one finite border seam after a gesture.
// Job/import/export stages and editor headers retain their existing owners.
(() => {
  'use strict';
  const eligible = new Set(['setup-overlay', 'project-overlay', 'job-overlay',
    'add-asset-overlay', 'bulk-overlay', 'proj-name-overlay', 'proj-delete-overlay',
    'repatch-overlay', 'shader-overlay', 'texopt-overlay', 'mesh-edit-overlay']);
  const opened = new Set(), pending = new Map();
  let armed = false, interaction = 0;
  const arm = () => { armed = true; interaction++; };
  document.addEventListener('pointerdown', arm, {capture: true, passive: true});
  document.addEventListener('keydown', arm, true);
  function cancel(overlay) {
    const plan = pending.get(overlay);
    if (plan) cancelAnimationFrame(plan.frame);
    pending.delete(overlay);
  }
  function sync() {
    for (const overlay of opened) if (!overlay.isConnected || !overlay.classList.contains('active')) {
      opened.delete(overlay); cancel(overlay);
    }
    for (const overlay of document.querySelectorAll('.overlay.active')) {
      if (!eligible.has(overlay.id) || opened.has(overlay)) continue;
      opened.add(overlay);
      if (!armed || document.hidden || !window.AtelierMotionPolicy?.allows(2)) continue;
      const plan = {frame: 0, interaction}; pending.set(overlay, plan);
      plan.frame = requestAnimationFrame(() => {
        plan.frame = requestAnimationFrame(() => {
          if (pending.get(overlay) !== plan) return;
          pending.delete(overlay);
          // A subsequent action owns attention; a late panel entrance must not
          // claim the shared moment ahead of that action's incoming ink.
          if (interaction === plan.interaction && overlay.isConnected && overlay.classList.contains('active'))
            window.AtelierMotion?.workflow?.panel?.(overlay.firstElementChild);
        });
      });
    }
  }
  const observer = new MutationObserver(sync);
  observer.observe(document.documentElement, {subtree: true, childList: true, attributes: true, attributeFilter: ['class']});
  sync();
  const stop = () => { for (const overlay of pending.keys()) cancel(overlay); };
  window.AtelierMotionPolicy?.query().addEventListener('change', stop);
  document.addEventListener('visibilitychange', () => { if (document.hidden) stop(); });
  window.addEventListener('pagehide', () => {
    stop(); observer.disconnect(); opened.clear();
    document.removeEventListener('pointerdown', arm, true); document.removeEventListener('keydown', arm, true);
    window.AtelierMotionPolicy?.query().removeEventListener('change', stop);
  }, {once: true});
})();
