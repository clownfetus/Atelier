// Apply appearance before CSS to avoid a flash. UI colors never enter projects.
(() => {
  'use strict';
  const themeKey = 'atelier.theme', paletteKey = 'atelier.appearance';
  const modes = ['light', 'dark'], colors = ['background', 'surface', 'foreground', 'accent'];
  const validTheme = value => ['system', ...modes].includes(value);
  const system = window.matchMedia('(prefers-color-scheme: dark)');
  const palettes = {
    studio: {
      light: ['#f5f6f8', '#e4e7eb', '#23272e', '#37639d'],
      dark: ['#17191d', '#2b2f35', '#e4e6e9', '#98b7e2'],
    },
    darcula: {
      light: ['#faf8f4', '#ebe6de', '#323232', '#875327'],
      dark: ['#2b2b2b', '#3c3f41', '#a9b7c6', '#e7b176'],
    },
    repak: {
      light: ['#faf7f7', '#ece5e5', '#272326', '#aa2436'],
      dark: ['#101012', '#252527', '#f2eeee', '#ff5c68'],
    },
    contrast: {light:['#ffffff','#ededed','#000000','#003c99'], dark:['#080808','#181818','#ffffff','#afd2ff']},
    blueprint: {light:['#edf4fa','#dce8f2','#152e48','#215f9b'], dark:['#102235','#1b344c','#e4eff9','#88c5ff']},
    comic: {light:['#faf5e8','#e9e0ca','#201d17','#a12b24'], dark:['#201e19','#343028','#fff3d7','#ff9a80']},
  };
  const defaults = () => ({preset: 'studio', custom: {}, saved: []});
  const validColors = p => p && colors.every(key => typeof p[key] === 'string' && /^#[0-9a-f]{6}$/i.test(p[key]));
  const copyColors = p => Object.fromEntries(colors.map(key => [key, p[key].toLowerCase()]));
  function read(key) {
    try { return localStorage.getItem(key); } catch { return null; }
  }
  function write(key, value) {
    try { localStorage.setItem(key, value); } catch { /* In-session fallback. */ }
  }
  function parseAppearance(value) {
    const clean = defaults();
    try {
      const saved = JSON.parse(value);
      if (!saved || ![1, 2].includes(saved.version)) return clean;
      if (Array.isArray(saved.saved)) {
        for (const entry of saved.saved.slice(0, 24)) {
          if (!entry || !/^palette-[a-z0-9-]{1,80}$/.test(entry.id) || typeof entry.name !== 'string'
              || !entry.name.trim() || !modes.every(mode => validColors(entry.colors?.[mode]))
              || clean.saved.some(p => p.id === entry.id)) continue;
          clean.saved.push({id: entry.id, name: entry.name.trim().slice(0, 40),
            colors: Object.fromEntries(modes.map(mode => [mode, copyColors(entry.colors[mode])]))});
        }
      }
      if ([...Object.keys(palettes), 'custom', ...clean.saved.map(p => p.id)].includes(saved.preset)) clean.preset = saved.preset;
      if (saved.preset === 'dracula') clean.preset = 'darcula';
      for (const mode of modes) {
        const candidate = saved.custom?.[mode];
        if (validColors(candidate)) clean.custom[mode] = copyColors(candidate);
      }
    } catch { /* Invalid or old storage falls back to Studio. */ }
    return clean;
  }
  const savedTheme = read(themeKey);
  let preference = validTheme(savedTheme) ? savedTheme : 'system';
  let appearance = parseAppearance(read(paletteKey));
  const applied = new Set();
  const resolvedMode = () => preference === 'system' ? (system.matches ? 'dark' : 'light') : preference;
  let nativeScheduled = false, lastNative = '';
  function syncNative() {
    if (!window.pywebview?.api?.set_window_theme) return;
    if (nativeScheduled) return;
    nativeScheduled = true;
    queueMicrotask(() => {
      nativeScheduled = false;
      const mode = resolvedMode(), payload = [mode, palette(appearance.preset, mode).background, preference,
        palette(appearance.preset, 'light').background, palette(appearance.preset, 'dark').background];
      const signature = JSON.stringify(payload); if (signature === lastNative) return; lastNative = signature;
      window.pywebview.api.set_window_theme(...payload).catch(() => {lastNative = '';});
    });
  }
  window.addEventListener('pywebviewready', syncNative);
  function palette(preset, mode) {
    const saved = appearance.saved.find(p => p.id === preset);
    if (saved) return {...saved.colors[mode]};
    if (preset === 'custom' && appearance.custom[mode]) return {...appearance.custom[mode]};
    return Object.fromEntries(colors.map((key, index) => [key, (palettes[preset] || palettes.studio)[mode][index]]));
  }
  const rgb = hex => hex.slice(1).match(/../g).map(value => parseInt(value, 16));
  const mix = (a, b, weight) => '#' + rgb(a).map((value, index) =>
    Math.round(value * (1 - weight) + rgb(b)[index] * weight).toString(16).padStart(2, '0')).join('');
  const luminance = hex => rgb(hex).map(v => v / 255).map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4)
    .reduce((total, value, index) => total + value * [.2126, .7152, .0722][index], 0);
  const contrast = (a, b) => (Math.max(luminance(a), luminance(b)) + .05) / (Math.min(luminance(a), luminance(b)) + .05);
  function readable(color, backgrounds, target = 4.5) {
    const score = candidate => Math.min(...backgrounds.map(bg => contrast(candidate, bg)));
    const end = score('#ffffff') > score('#000000') ? '#ffffff' : '#000000';
    for (let step = 0; step <= 100; step++) {
      const candidate = mix(color, end, step / 100);
      if (score(candidate) >= target) return candidate;
    }
    return end;
  }
  function roles(p, mode) {
    const bg = p.background, fg = readable(p.foreground, [bg]);
    let surface = p.surface;
    // A black background with a white surface cannot share one text color.
    // Bring the surface toward the chosen background until both remain readable.
    for (let step = 0; contrast(fg, surface) < 4.5 && step <= 100; step++) surface = mix(p.surface, bg, step / 100);
    const low = mix(bg, surface, .35), backgrounds = [bg, low, surface];
    const primary = readable(p.accent, backgrounds);
    const primaryContainer = mix(surface, primary, .18);
    const secondaryContainer = mix(surface, primary, .08);
    const error = readable(mode === 'dark' ? '#df9d99' : '#ad3032', backgrounds);
    const errorContainer = mix(surface, error, .16);
    return {
      'surface': bg,
      'surface-container-lowest': bg,
      'surface-container-low': low,
      'surface-container': mix(bg, surface, .65),
      'surface-container-high': surface,
      'surface-container-highest': surface,
      'on-surface': fg,
      'on-surface-variant': readable(mix(fg, bg, .22), backgrounds),
      'primary': primary, 'on-primary': readable(fg, [primary]),
      'primary-container': primaryContainer, 'on-primary-container': readable(fg, [primaryContainer]),
      'secondary-container': secondaryContainer, 'on-secondary-container': readable(fg, [secondaryContainer]),
      'outline': readable(mix(fg, bg, .45), backgrounds, 3),
      'outline-variant': mix(surface, fg, .2),
      'error': error, 'error-container': errorContainer, 'on-error-container': readable(fg, [errorContainer]),
    };
  }
  let artworkAccent = null;
  window.addEventListener('atelier:artwork', event => { artworkAccent = event.detail?.accent || null; applyNow(); });
  window.addEventListener('atelier:preferences', () => applyNow());
  function apply() { if (!window.AtelierPreferences?.revealTheme(applyNow)) applyNow(); }
  function applyNow() {
    const mode = resolvedMode(), p = palette(appearance.preset, mode), root = document.documentElement;
    root.dataset.theme = mode;
    root.dataset.palette = appearance.preset;
    applied.forEach(key => root.style.removeProperty(key));
    applied.clear();
    const set = (key, value) => { root.style.setProperty(key, value); applied.add(key); };
    if (window.AtelierPreferences?.adaptive() && artworkAccent) p.accent = artworkAccent;
    if (appearance.preset !== 'studio' || window.AtelierPreferences?.adaptive() && artworkAccent) {
      const derived = roles(p, mode);
      for (const [key, value] of Object.entries(derived)) set('--md-sys-color-' + key, value);
      const backgrounds = [derived.surface, derived['surface-container-low'], derived['surface-container-high']];
      for (const [key, value] of Object.entries({success: '#3e6d4a', warning: '#786020', info: p.accent})) {
        set('--studio-' + key, readable(value, backgrounds));
      }
      const blackMark = contrast('#000000', derived['surface-container-low']) >= contrast('#ffffff', derived['surface-container-low']);
      set('--studio-brand-color', blackMark ? '#000000' : '#ffffff');
      set('--studio-brand-filter', blackMark ? 'brightness(0)' : 'brightness(0) invert(1)');
    }
    document.querySelectorAll('[data-theme-picker]').forEach(picker => { picker.value = preference; });
    renderSaved();
    document.querySelectorAll('[data-theme-preset]').forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.themePreset === appearance.preset));
      const swatches = button.querySelector('.theme-swatches');
      if (!swatches) return;
      const preview = palette(button.dataset.themePreset, mode);
      swatches.replaceChildren(...colors.map(key => {
        const dot = document.createElement('i'); dot.style.backgroundColor = preview[key]; return dot;
      }));
    });
    document.querySelectorAll('[data-theme-color]').forEach(input => {
      input.value = p[input.dataset.themeColor];
      input.nextElementSibling.value = input.value;
    });
    const warning = document.getElementById('theme-contrast');
    if (warning) {
      warning.hidden = Math.min(contrast(p.foreground, p.background), contrast(p.foreground, p.surface)) >= 4.5;
      warning.textContent = warning.hidden ? '' : 'Text and surface shades have been adjusted for readable contrast. Your chosen colors are kept in the palette.';
    }
    const remove = document.getElementById('theme-palette-delete');
    if (remove) remove.hidden = !appearance.saved.some(p => p.id === appearance.preset);
    syncNative();
  }
  function save() {
    write(paletteKey, JSON.stringify({version: 2, ...appearance}));
    apply();
  }
  function customize() {
    if (appearance.preset === 'custom') return;
    for (const mode of modes) {
      if (mode === resolvedMode() || !appearance.custom[mode]) appearance.custom[mode] = palette(appearance.preset, mode);
    }
    appearance.preset = 'custom';
  }
  function choosePreset(button) {
    if (button.dataset.themePreset === 'custom') {
      if (modes.some(mode => appearance.custom[mode])) appearance.preset = 'custom';
      else customize();
    } else appearance.preset = button.dataset.themePreset;
    save();
    if (appearance.preset === 'custom') document.querySelector('[data-theme-color="background"]').focus();
  }
  function renderSaved() {
    const group = document.querySelector('.theme-palettes');
    if (!group) return;
    const existing = [...group.querySelectorAll('[data-saved-palette]')];
    for (const button of existing) {
      if (!appearance.saved.some(p => p.id === button.dataset.themePreset)) button.remove();
    }
    for (const saved of appearance.saved) {
      if ([...group.children].some(button => button.dataset.themePreset === saved.id)) continue;
      const button = document.createElement('button'); button.type = 'button'; button.className = 'theme-preset';
      button.dataset.themePreset = saved.id; button.dataset.savedPalette = 'true';
      const swatches = document.createElement('span'); swatches.className = 'theme-swatches'; swatches.setAttribute('aria-hidden', 'true');
      const label = document.createElement('span'); label.textContent = saved.name;
      button.append(swatches, label); button.addEventListener('click', () => choosePreset(button));
      group.insertBefore(button, group.querySelector('[data-theme-preset="custom"]'));
    }
  }
  apply();
  system.addEventListener('change', () => { if (preference === 'system') apply(); });
  window.addEventListener('storage', event => {
    if (event.key === themeKey) preference = validTheme(event.newValue) ? event.newValue : 'system';
    else if (event.key === paletteKey) appearance = parseAppearance(event.newValue);
    else if (event.key === null) { preference = 'system'; appearance = defaults(); }
    else return;
    apply();
  });
  document.addEventListener('DOMContentLoaded', () => {
    apply();
    document.querySelectorAll('[data-theme-picker]').forEach(picker => {
      picker.addEventListener('change', () => {
        if (!validTheme(picker.value)) return;
        preference = picker.value; write(themeKey, preference); apply();
      });
    });
    document.querySelectorAll('[data-theme-preset]:not([data-saved-palette])').forEach(button => {
      button.addEventListener('click', () => {
        choosePreset(button);
      });
    });
    const name = document.getElementById('theme-palette-name'), store = document.getElementById('theme-palette-save');
    name.addEventListener('input', () => { store.disabled = !name.value.trim() || appearance.saved.length >= 24; });
    store.addEventListener('click', () => {
      if (!name.value.trim() || appearance.saved.length >= 24) return;
      const id = 'palette-' + crypto.randomUUID();
      appearance.saved.push({id, name: name.value.trim().slice(0, 40),
        colors: Object.fromEntries(modes.map(mode => [mode, palette(appearance.preset, mode)]))});
      appearance.preset = id; name.value = ''; store.disabled = true; save();
      document.querySelector('[data-theme-preset="' + id + '"]').focus();
    });
    document.getElementById('theme-palette-delete').addEventListener('click', () => {
      appearance.saved = appearance.saved.filter(p => p.id !== appearance.preset);
      appearance.preset = 'studio'; save();
      document.querySelector('[data-theme-preset="studio"]').focus();
    });
    document.querySelectorAll('[data-theme-color]').forEach(input => {
      const update = () => {
        if (!/^#[0-9a-f]{6}$/i.test(input.value)) return;
        const value = input.value;
        customize();
        appearance.custom[resolvedMode()] ||= palette('studio', resolvedMode());
        appearance.custom[resolvedMode()][input.dataset.themeColor] = value;
        save();
      };
      input.addEventListener('input', update);
      input.addEventListener('change', update);
    });
  });
})();
