// DOM integration only. Export requests, button availability and result messages stay in app.js.
(() => {
  const runs = new WeakMap();

  function mountSlot(slot, state) {
    if (!slot || !window.AtelierMotion?.exportFeedback) return null;
    const host = slot.lastElementChild;
    try {
      const motion = window.AtelierMotion.exportFeedback.mount(host, {state});
      slot.dataset.amMounted = 'true';
      const destroy = motion.destroy;
      motion.destroy = () => {
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

  function begin(button, project = window.atelierProject?.()) {
    const previous = runs.get(button);
    if (previous) {
      clearTimeout(previous.timer);
      previous.motion?.destroy();
    }
    const run = {motion: mountSlot(button.querySelector('.am-export-feedback-slot'), 'busy'), timer: null};
    runs.set(button, run);
    return state => {
      if (runs.get(button) !== run) return;
      const reset = () => {
        if (runs.get(button) !== run) return;
        run.motion?.destroy();
        runs.delete(button);
      };
      // An old project's result belongs to its toast, not the newly selected project's button.
      if (project !== window.atelierProject?.()) { reset(); return; }
      run.motion?.setState(state);
      clearTimeout(run.timer);
      run.timer = setTimeout(reset, 1800);
    };
  }

  function toast(msg, type, duration, state) {
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
    let motion = mountSlot(slot, state);

    let disposed = false, timer = null, remaining = duration, start = Date.now();
    const remove = el.remove.bind(el);
    function dispose() {
      if (disposed) return;
      disposed = true;
      clearTimeout(timer);
      motion?.destroy();
      remove();
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
      try { motion?.setState(outcome); }
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
