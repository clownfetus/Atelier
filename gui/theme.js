// Runs in <head> before styles: a saved theme never flashes the opposite scheme.
// Appearance is local UI state; it never enters Python config or project metadata.
(() => {
  const key = 'atelier.theme';
  const valid = value => ['system', 'light', 'dark'].includes(value);
  const system = window.matchMedia('(prefers-color-scheme: dark)');
  let preference = 'system';
  try {
    const saved = localStorage.getItem(key);
    if (valid(saved)) preference = saved;
  } catch { /* WebView storage can be unavailable; keep an in-memory preference. */ }

  function apply() {
    const theme = preference === 'system' ? (system.matches ? 'dark' : 'light') : preference;
    document.documentElement.dataset.theme = theme;
    document.querySelectorAll('[data-theme-picker]').forEach(picker => {
      picker.value = preference;
    });
  }

  apply();
  system.addEventListener('change', () => { if (preference === 'system') apply(); });
  window.addEventListener('storage', event => {
    if (event.key === key || event.key === null) {
      preference = valid(event.newValue) ? event.newValue : 'system';
      apply();
    }
  });
  document.addEventListener('DOMContentLoaded', () => {
    apply();
    document.querySelectorAll('[data-theme-picker]').forEach(picker => {
      picker.addEventListener('change', () => {
        if (!valid(picker.value)) return;
        preference = picker.value;
        try { localStorage.setItem(key, preference); } catch { /* Session-only fallback. */ }
        apply();
      });
    });
  });
})();
