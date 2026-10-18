// DOM integration only. Export requests, button availability and result messages stay in app.js.
(() => {
  const runs = new WeakMap();
  const resetting = new Set();
  const motionQuery = window.AtelierMotionPolicy?.query() || window.matchMedia?.('(prefers-reduced-motion: reduce)');
  function stopResets() {
    if (document.hidden || motionQuery?.matches) for (const dispose of [...resetting]) dispose();
  }
  document.addEventListener('visibilitychange', stopResets);
  motionQuery?.addEventListener('change', stopResets);
  window.addEventListener('pagehide', () => { for (const dispose of [...resetting]) dispose(); });
  // Motions whose caller passed a quiet(state) predicate: while it holds (the export review's stage
  // is drawing this job) they show still poses, and they follow the dialog as it is hidden or shown.
  const quietMotions = new Map();
  const quietMode = (quiet, state) => (quiet?.(state) ? 'reduce' : 'system');
  document.addEventListener('atelier:export-review', () => {
    for (const [motion, entry] of quietMotions) {
      try { motion.setReducedMotion(quietMode(entry.quiet, entry.state)); } catch (_) { /* Optional presentation. */ }
    }
  });

  function mountSlot(slot, state, quiet) {
    if (!slot || !window.AtelierMotion?.exportFeedback) return null;
    const host = slot.lastElementChild;
    try {
      const motion = window.AtelierMotion.exportFeedback.mount(host, {state, reducedMotion: quietMode(quiet, state)});
      if (quiet) quietMotions.set(motion, {quiet, state});
      slot.dataset.amMounted = 'true';
      const destroy = motion.destroy;
      motion.destroy = () => {
        quietMotions.delete(motion);
        destroy();
        delete slot.dataset.amMounted;
      };
      return motion;
    } catch (_) {
      // Keep the original icon if motion is unavailable. Only this empty host is owned here.
      host.replaceChildren();
      host.removeAttribute('data-atelier-motion');
      host.removeAttribute('data-am-state');
      host.removeAttribute('data-am-reduced');
      delete slot.dataset.amMounted;
      return null;
    }
  }

  // Settle a mounted motion into a new state, re-reading its quiet predicate first.
  function settleMotion(motion, state) {
    const entry = quietMotions.get(motion);
    if (entry) { entry.state = state; motion.setReducedMotion(quietMode(entry.quiet, state)); }
    motion.setState(state);
  }

  function begin(button, project = window.atelierProject?.(), {quiet} = {}) {
    const previous = runs.get(button);
    previous?.dispose();
    const slot = button.querySelector('.am-export-feedback-slot');
    const run = {motion: mountSlot(slot, 'busy', quiet), timer: null, animations: [], disposed: false};
    run.dispose = () => {
      if (run.disposed) return;
      run.disposed = true;
      clearTimeout(run.timer);
      resetting.delete(run.dispose);
      for (const animation of run.animations) animation.cancel();
      if (slot) delete slot.dataset.amResetting;
      run.motion?.destroy();
      if (runs.get(button) === run) runs.delete(button);
    };
    runs.set(button, run);
    return state => {
      if (runs.get(button) !== run) return;
      const reset = (animate = true) => {
        if (runs.get(button) !== run) return;
        const fallback = slot?.firstElementChild, host = slot?.lastElementChild;
        if (!animate || !run.motion || !fallback || !host || document.hidden || motionQuery?.matches ||
            window.AtelierMotionPolicy?.allows(1) === false || !button.getClientRects().length) {
          run.dispose(); return;
        }
        const finish = () => { if (runs.get(button) === run) run.dispose(); };
        try {
          // Keep both icons in the same fixed slot until the static download icon has arrived.
          run.motion.setReducedMotion('reduce');
          slot.dataset.amResetting = 'true';
          resetting.add(run.dispose);
          run.animations.push(host.animate([{opacity: 1}, {opacity: 0}],
            {duration: AtelierMotion.exitMs, easing: AtelierMotion.ease.exit, fill: 'both'}));
          run.animations.push(fallback.animate([{opacity: 0}, {opacity: 1}],
            {duration: AtelierMotion.exitMs, easing: AtelierMotion.ease.standard, fill: 'both'}));
          Promise.all(run.animations.map(animation => animation.finished)).then(finish, finish);
          run.timer = setTimeout(finish, AtelierMotion.exitMs + 80);
        } catch (_) { finish(); }
      };
      // An old project's result belongs to its toast, not the newly selected project's button.
      if (project !== window.atelierProject?.()) { reset(false); return; }
      if (run.motion) settleMotion(run.motion, state);
      clearTimeout(run.timer);
      run.timer = setTimeout(() => reset(), 1800);
    };
  }

  function toast(msg, type, duration, state, {quiet} = {}) {
    const el = document.createElement('div');
    el.className = `toast am-export-feedback-toast ${type}`;
    el.setAttribute('role', 'status'); el.setAttribute('aria-atomic', 'true');
    el.dataset.operationState = state;
    const slot = document.createElement('span');
    slot.className = 'am-export-feedback-slot';
    slot.setAttribute('aria-hidden', 'true');
    // All markup here is bundled artwork; filenames and backend errors remain text.
    const icon = state === 'success' ? 'check-circle' : state === 'warning' || state === 'error' ? 'alert-triangle' : 'info';
    slot.innerHTML = state === 'busy'
      ? '<span class="spinner am-export-feedback-fallback"></span><span></span>'
      : `<i data-lucide="${icon}" size="24" class="am-export-feedback-fallback"></i><span></span>`;
    const label = document.createElement('span');
    label.className = 'am-export-feedback-message';
    label.textContent = msg;
    el.append(slot, label);
    document.getElementById('toast-area').appendChild(el);
    window.AtelierIcons?.createIcons({nodes: [slot]});
    let motion = mountSlot(slot, state, quiet);

    let disposed = false, timer = null, remaining = duration, start = Date.now();
    const remove = el.remove.bind(el);
    function dispose() {
      if (disposed) return;
      disposed = true;
      clearTimeout(timer);
      // Effects stop now; the glyph holds its still pose while the toast fades, then goes with it.
      try { motion?.setReducedMotion('reduce'); } catch (_) { /* Destroyed below. */ }
      const finish = () => { motion?.destroy(); remove(); };
      try { if (window.AtelierPolish?.leave) { window.AtelierPolish.leave(el, finish); return; } } catch (_) { /* Fall through. */ }
      finish();
    }
    // Existing _runInstall's t.remove(), click and timeout share one cleanup path.
    el.remove = dispose;
    function schedule(ms) {
      clearTimeout(timer); remaining = ms; start = Date.now();
      el.style.setProperty('--toast-duration', ms + 'ms');
      el.classList.remove('toast-timed'); void el.offsetWidth;
      if (ms > 0) { el.classList.add('toast-timed'); timer = setTimeout(dispose, ms); }
    }
    el.addEventListener('mouseenter', () => {
        if (!duration) return;
        clearTimeout(timer);
        remaining = Math.max(0, remaining - (Date.now() - start));
    });
    el.addEventListener('mouseleave', () => {
        if (disposed || !duration) return;
        start = Date.now();
        timer = setTimeout(dispose, remaining);
    });
    el.addEventListener('click', () => { if (duration) dispose(); });
    el.resolve = (message, outcome = 'success', ms = 4000) => {
      if (disposed) return;
      label.textContent = message; state = outcome; duration = ms;
      el.className = `toast am-export-feedback-toast ${outcome === 'error' ? 'warning' : outcome}`;
      el.dataset.operationState = outcome;
      try { if (motion) settleMotion(motion, outcome); }
      catch (_) { try { motion?.destroy(); } catch (_) {} motion=null; delete slot.dataset.amMounted; }
      const fallback = slot.firstElementChild;
      fallback?.remove();
      const icon = document.createElement('i'); icon.dataset.lucide = outcome === 'success' ? 'check-circle' : 'alert-triangle';
      icon.className = 'am-export-feedback-fallback'; slot.prepend(icon);
      window.AtelierIcons?.createIcons({nodes:[slot]});
      schedule(ms);
    };
    schedule(duration);
    return el;
  }

  window.AtelierExportFeedback = Object.freeze({begin, toast});
})();
