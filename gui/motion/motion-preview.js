/*
 * Settings: Preview motion. Real glyphs at three sizes, on the production engine. Nothing runs until
 * the panel is first on screen, and glyphs stop by themselves while Settings is closed.
 */
(() => {
  'use strict';
  const SIZES = [16, 48, 128];
  const LOGO_SIZE = 32;
  const BUTTONS = {
    states: [['busy', 'Working'], ['info', 'At rest'], ['success', 'Complete'], ['warning', 'Warning'], ['error', 'Error']],
    loaders: [['mesh', 'Mesh'], ['texture', 'Texture'], ['material', 'Material']],
  };
  function build(root) {
    const stage = root.querySelector('.motion-preview-stage'), glyphs = [];
    for (const size of SIZES) {
      const figure = document.createElement('figure'), host = document.createElement('span'), caption = document.createElement('figcaption');
      caption.textContent = `${size} px`;
      figure.append(host, caption);
      stage.append(figure);
      glyphs.push(window.AtelierMotion.glyph.mount(host, {state: 'info', size}));
    }
    root.dataset.ready = 'true';
    return glyphs;
  }
  // The logo's entrance on its own small stage, because it isn't one of the glyph's states.
  function playLogo(root) {
    const stage = root.querySelector('.motion-preview-logo');
    stage.replaceChildren();
    const host = document.createElement('span');
    stage.append(host);
    if (!window.AtelierMotion.glyph.entrance(host, {size: LOGO_SIZE, preview: true})) {
      host.style.cssText = '';
      window.AtelierMotion.glyph.mount(host, {state: 'info', size: LOGO_SIZE});
    }
  }
  function start(root) {
    let glyphs = null;
    const buttons = [];
    let showing = null;
    const show = (button, state, asset) => {
      glyphs ||= build(root);
      for (const other of buttons) other.setAttribute('aria-pressed', String(other === button));
      for (const glyph of glyphs) {
        if (showing === button) glyph.replay();
        else glyph.set(state, {asset});
      }
      showing = button;
    };
    for (const [group, list] of Object.entries(BUTTONS)) {
      const holder = root.querySelector(`[data-preview-group="${group}"]`);
      for (const [value, label] of list) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'btn';
        button.textContent = label;
        button.setAttribute('aria-pressed', 'false');
        button.dataset.preview = value;
        button.addEventListener('click', () => (group === 'loaders' ? show(button, 'busy', value) : show(button, value, undefined)));
        holder.append(button);
        buttons.push(button);
      }
    }
    root.querySelector('[data-preview-logo]').addEventListener('click', () => playLogo(root));
    const firstSeen = new IntersectionObserver(entries => {
      if (!entries.some(entry => entry.isIntersecting)) return;
      firstSeen.disconnect();
      glyphs ||= build(root);
    });
    firstSeen.observe(root);
  }
  const root = document.getElementById('motion-preview');
  if (root) start(root);
})();
