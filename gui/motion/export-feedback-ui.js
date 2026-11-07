// DOM integration only. Export requests, button availability and result messages stay in app.js.
(() => {
  const runs = new WeakMap();
  // How long the Build button shows a result before its icon comes back. It's longer than any result takes to form.
  const RESULT_HOLD = 1800;
  // Glyphs whose caller passed a quiet(state) predicate: while it holds (the export review's stage is
  // drawing this job) they show still poses, and they follow the dialog as it is hidden or shown.
  const quietGlyphs = new Set();
  document.addEventListener('atelier:export-review', () => {
    for (const entry of quietGlyphs) {
      try { entry.follow(); } catch (_) { /* Optional presentation. */ }
    }
  });

  function mountSlot(slot, state, quiet) {
    if (!slot || !window.AtelierMotion?.glyph) return null;
    const host = slot.lastElementChild;
    let glyph = null, still = false;
    const place = () => {
      still = !!quiet?.(state);
      glyph = window.AtelierMotion.glyph.mount(host, {state, ...(still ? {still, reducedMotion: 'reduce'} : {})});
    };
    const entry = {
      set(next) {
        state = next;
        if (still || quiet?.(state)) place();
        else glyph.set(state);
      },
      // A result the stage has already shown stays still; only work picks up again.
      follow() {
        const now = !!quiet(state);
        if (now !== still && (now || state === 'busy')) place();
      },
      destroy() {
        quietGlyphs.delete(entry);
        glyph.destroy();
        delete slot.dataset.glyphMounted;
      },
    };
    try {
      place();
      if (quiet) quietGlyphs.add(entry);
      slot.dataset.glyphMounted = 'true';
      return entry;
    } catch (_) {
      // Keep the original icon if the glyph is unavailable. Only this empty host is owned here.
      host.replaceChildren();
      return null;
    }
  }

  function begin(button, project = window.atelierProject?.(), {quiet} = {}) {
    runs.get(button)?.dispose();
    const slot = button.querySelector('.export-feedback-slot');
    const run = {glyph: mountSlot(slot, 'busy', quiet), timer: null, disposed: false};
    run.dispose = () => {
      if (run.disposed) return;
      run.disposed = true;
      clearTimeout(run.timer);
      run.glyph?.destroy();
      if (runs.get(button) === run) runs.delete(button);
    };
    runs.set(button, run);
    return state => {
      if (runs.get(button) !== run) return;
      // An old project's result belongs to its toast, not the newly selected project's button.
      if (project !== window.atelierProject?.()) { run.dispose(); return; }
      run.glyph?.set(state);
      clearTimeout(run.timer);
      run.timer = setTimeout(() => {
        if (runs.get(button) !== run) return;
        // The glyph doesn't fade: it goes, and the plain icon comes back with a short fade of its own.
        run.dispose();
        if (document.hidden || window.AtelierMotionPolicy?.allows(1) === false) return;
        try { slot?.firstElementChild?.animate([{opacity: 0}, {opacity: 1}], {duration: 120, easing: 'ease-out'}); }
        catch (_) { /* The icon is already showing. */ }
      }, RESULT_HOLD);
    };
  }

  function toast(msg, type, duration, state, {quiet} = {}) {
    const el = document.createElement('div');
    el.className = `toast export-feedback-toast ${type}`;
    el.setAttribute('role', 'status'); el.setAttribute('aria-atomic', 'true');
    el.dataset.operationState = state;
    const slot = document.createElement('span');
    slot.className = 'export-feedback-slot';
    slot.setAttribute('aria-hidden', 'true');
    // All markup here is bundled artwork; filenames and backend errors remain text.
    const icon = state === 'success' ? 'check-circle' : state === 'warning' || state === 'error' ? 'alert-triangle' : 'info';
    slot.innerHTML = state === 'busy'
      ? '<span class="spinner export-feedback-fallback"></span><span></span>'
      : `<i data-lucide="${icon}" size="24" class="export-feedback-fallback"></i><span></span>`;
    const label = document.createElement('span');
    label.className = 'export-feedback-message';
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
      el.className = `toast export-feedback-toast ${outcome === 'error' ? 'warning' : outcome}`;
      el.dataset.operationState = outcome;
      try { motion?.set(outcome); }
      catch (_) { try { motion?.destroy(); } catch (_) {} motion=null; delete slot.dataset.glyphMounted; }
      const fallback = slot.firstElementChild;
      fallback?.remove();
      const icon = document.createElement('i'); icon.dataset.lucide = outcome === 'success' ? 'check-circle' : 'alert-triangle';
      icon.className = 'export-feedback-fallback'; slot.prepend(icon);
      window.AtelierIcons?.createIcons({nodes:[slot]});
      schedule(ms);
    };
    schedule(duration);
    return el;
  }

  window.AtelierExportFeedback = Object.freeze({begin, toast});
})();
