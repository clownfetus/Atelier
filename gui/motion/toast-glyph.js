// A plain toast's icon becomes the small glyph. The icon stays as the fallback until the glyph mounts,
// and every way the toast can leave (timeout, click) destroys the glyph with it.
(() => {
  function icon(toast, type) {
    const original = toast?.querySelector(':scope > i[data-lucide], :scope > svg');
    if (!original || !window.AtelierMotion?.glyph) return null;
    const slot = document.createElement('span');
    slot.className = 'toast-glyph-slot';
    slot.setAttribute('aria-hidden', 'true');
    const host = document.createElement('span');
    toast.insertBefore(slot, original);
    slot.append(original, host);
    original.classList.add('toast-glyph-fallback');
    try {
      const glyph = window.AtelierMotion.glyph.mount(host, {state: ['success', 'warning', 'error'].includes(type) ? type : 'info'});
      slot.dataset.glyphMounted = 'true';
      const remove = toast.remove.bind(toast);
      toast.remove = () => {
        try { glyph.destroy(); } catch (_) { /* The toast still goes. */ }
        remove();
      };
      return glyph;
    } catch (_) {
      host.remove();
      return null;
    }
  }

  window.AtelierToastGlyph = Object.freeze({icon});
})();
