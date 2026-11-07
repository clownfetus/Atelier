// Opt-in notification ownership. Application code alone decides whether a save succeeded.
(() => {
  function toast(msg, state = 'success', duration = 4000) {
    const area = document.getElementById('toast-area');
    if (!area) return null;
    const tone = ['success', 'warning', 'error'].includes(state) ? state : 'info';
    const el = document.createElement('div');
    el.className = `toast material-save-toast ${tone}`;
    const slot = document.createElement('span');
    slot.className = 'material-save-slot';
    slot.setAttribute('aria-hidden', 'true');
    const icon = state === 'success' ? 'check-circle'
      : state === 'warning' || state === 'error' ? 'alert-triangle' : 'save';
    // Bundled trusted glyphs; this fallback works even if the animation script is absent.
    const artwork = window.AtelierSymbolPaths?.[icon];
    const fallback = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    fallback.setAttribute('class', 'material-save-fallback studio-icon');
    fallback.setAttribute('viewBox', artwork?.viewBox || '0 0 24 24');
    fallback.setAttribute('width', '24'); fallback.setAttribute('height', '24');
    fallback.setAttribute('fill', 'currentColor');
    fallback.setAttribute('aria-hidden', 'true'); fallback.setAttribute('focusable', 'false');
    fallback.innerHTML = artwork?.body || '<circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2"/><path d="M12 7v6" stroke="currentColor" stroke-width="2"/><circle cx="12" cy="17" r="1"/>';
    const host = document.createElement('span');
    slot.append(fallback, host);
    const label = document.createElement('span');
    label.className = 'material-save-message';
    label.textContent = String(msg ?? '');
    el.append(slot, label);

    let motion = null, disposed = false, timer = null;
    let remaining = duration, started = 0, hovered = false;
    const nativeRemove = el.remove.bind(el);
    function stopMotion() {
      try { motion?.destroy(); }
      catch (error) { console.warn('Material save animation cleanup unavailable', error); }
      finally {
        motion = null;
        host.replaceChildren();
        delete slot.dataset.amMounted;
      }
    }
    function dispose() {
      if (disposed) return;
      disposed = true;
      clearTimeout(timer);
      const finish = () => { stopMotion(); nativeRemove(); };
      try { if (window.AtelierPolish?.leave) { window.AtelierPolish.leave(el, finish); return; } } catch (_) { /* Fall through. */ }
      finish();
    }
    // All application removal paths use this element's remove(), never a last-toast query.
    el.remove = dispose;
    area.appendChild(el);
    if (duration > 0) { el.classList.add('toast-timed'); el.style.setProperty('--toast-duration', duration+'ms'); }
    try {
      if (window.AtelierMotion?.glyph) {
        motion = window.AtelierMotion.glyph.mount(host, {state: state === 'saving' ? 'busy' : tone});
        slot.dataset.amMounted = 'true';
      }
    } catch (error) {
      console.warn('Material save animation unavailable', error);
      stopMotion();
    }
    if (duration > 0) {
      const schedule = () => {
        started = Date.now();
        timer = setTimeout(dispose, remaining);
      };
      schedule();
      el.addEventListener('mouseenter', () => {
        if (disposed || hovered) return;
        hovered = true;
        clearTimeout(timer);
        remaining = Math.max(0, remaining - (Date.now() - started));
      });
      el.addEventListener('mouseleave', () => {
        if (disposed || !hovered) return;
        hovered = false;
        schedule();
      });
    }
    el.addEventListener('click', dispose);
    return el;
  }

  // The glyph beside a Save button for as long as that save runs. It reports the wait and nothing else: the
  // toast carries the result. It goes when the save ends or its editor is no longer the current one.
  // asset is 'material' only where the save really is a material's (D16).
  function saving(anchor, current, asset) {
    if (!anchor?.isConnected || !window.AtelierMotion?.glyph) return () => {};
    const badge = document.createElement('span');
    badge.className = 'material-save-badge';
    badge.setAttribute('aria-hidden', 'true');
    anchor.before(badge);
    let glyph = null, watch = null;
    const stop = () => {
      watch?.disconnect(); watch = null;
      try { glyph?.destroy(); } catch (_) { /* Presentation is optional. */ }
      glyph = null;
      badge.remove();
    };
    try { glyph = window.AtelierMotion.glyph.mount(badge, {state: 'busy', asset}); }
    catch (_) { stop(); return () => {}; }
    const overlay = anchor.closest('.overlay');
    if (overlay && current) {
      watch = new MutationObserver(() => { if (!current()) stop(); });
      watch.observe(overlay, {attributes: true, attributeFilter: ['class']});
    }
    return stop;
  }

  window.AtelierMaterialSaveFeedback = Object.freeze({toast, saving});
})();
