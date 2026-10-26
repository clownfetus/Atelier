// Decorative motion takes its pigment from the current costume, hero or theme.
// These inks never replace control, selection, ownership or outcome colours.
(() => {
  'use strict';
  const motion = window.AtelierMotion ||= {}, root = document.documentElement;
  const K = window.AtelierKrackleInks;
  let artwork = {accent: null, colors: []}, queued = false, destroyed = false;
  const valid = value => /^#[0-9a-f]{6}$/i.test(value || '');
  const localTokens = ['--vp-skin-colour', '--roster-skin-accent', '--roster-accent', '--library-art-colour'];
  const hex = rgb => '#' + rgb.slice(0, 3).map(n => Math.round(Math.max(0, Math.min(255, n))).toString(16).padStart(2, '0')).join('');
  function rgba(value) {
    const text = String(value).trim();
    if (valid(text)) return [...text.slice(1).match(/../g).map(n => parseInt(n, 16)), 1];
    const srgb = /^color\(srgb\s+([^)]+)\)$/.exec(text);
    const rgb = /^rgba?\(([^)]+)\)$/.exec(text);
    if (!srgb && !rgb) return null;
    const parts = (srgb || rgb)[1].split(/[\s,/]+/).filter(Boolean);
    if (parts.length < 3 || parts.some(n => !Number.isFinite(parseFloat(n)))) return null;
    return parts.slice(0, 3).map(n => parseFloat(n) * (n.endsWith('%') ? 2.55 : srgb ? 255 : 1))
      .concat(parts[3] ? parseFloat(parts[3]) / (parts[3].endsWith('%') ? 100 : 1) : 1);
  }
  function surface(host) {
    const composite = [0, 0, 0]; let alpha = 0;
    for (let node = host; node; node = node.parentElement) {
      const colour = rgba(getComputedStyle(node).backgroundColor);
      if (!colour) continue;
      const weight = (1 - alpha) * colour[3];
      for (let i = 0; i < 3; i++) composite[i] += colour[i] * weight;
      alpha += weight;
      if (alpha >= .999) return hex(composite);
    }
    const fallback = rgba(getComputedStyle(root).getPropertyValue('--bg2')) || [32, 35, 41, 1];
    return hex(composite.map((n, i) => n + fallback[i] * (1 - alpha)));
  }
  function context(host) {
    const style = getComputedStyle(host);
    for (const token of localTokens) {
      const colour = style.getPropertyValue(token).trim();
      if (valid(colour)) return {colour, source: 'artwork'};
    }
    // A hero's pigment lives on its art wrapper, inside the clickable card.
    const art = host.matches('.roster-portrait') && host.querySelector('.roster-art');
    const colour = art && getComputedStyle(art).getPropertyValue('--roster-accent').trim();
    if (valid(colour)) return {colour, source: 'artwork'};
    const viewport = document.querySelector('#viewport-overlay.active #viewport-box');
    if (viewport) {
      const colour = getComputedStyle(viewport).getPropertyValue('--vp-skin-colour').trim();
      // While a new costume loads, never borrow the previous library costume.
      return valid(colour) ? {colour, source: 'artwork'} : {colour: null, source: 'theme'};
    }
    return {colour: artwork.accent, source: artwork.accent ? 'artwork' : 'theme'};
  }
  function resolve(host = root) {
    const selected = context(host), css = getComputedStyle(host), ground = surface(host);
    const raw = selected.colour || hex(rgba(css.getPropertyValue('--acc')) || [152, 183, 226]);
    let charge = raw, rift = raw;
    if (K) {
      charge = K.fit(raw, ground);
      // Only use another sampled pigment from this same artwork, never an unrelated purple.
      const sameArt = selected.colour && selected.colour === artwork.accent;
      const second = sameArt && artwork.colors.find(colour => K.deltaE(colour, raw) > 24);
      rift = K.fit(second || raw, ground);
    }
    return {charge, rift, source: selected.source};
  }
  function refresh() {
    if (queued || destroyed) return;
    queued = true;
    queueMicrotask(() => {
      queued = false;
      if (destroyed) return;
      const inks = resolve();
      root.style.setProperty('--krackle-energy', inks.charge);
      root.style.setProperty('--krackle-energy-rift', inks.rift);
      root.dataset.kracklePigment = inks.source;
      // Local surfaces (especially the dark model stage) fit their own contrast.
      const viewport = document.getElementById('viewport-box');
      if (viewport) {
        const local = resolve(viewport);
        viewport.style.setProperty('--krackle-energy', local.charge);
        viewport.style.setProperty('--krackle-energy-rift', local.rift);
      }
      window.dispatchEvent(new Event('atelier:energy'));
    });
  }
  const receive = event => {
    const detail = event.detail || {};
    artwork = {accent: valid(detail.accent) ? detail.accent : null,
      colors: Array.isArray(detail.colors) ? detail.colors.filter(valid).slice(0, 8) : []};
    refresh();
  };
  const fit = (colour, host = root) => K ? K.fit(colour, surface(host)) : colour;
  motion.energy = Object.freeze({resolve, refresh, fit});
  window.addEventListener('atelier:artwork', receive);
  window.addEventListener('atelier:inks', refresh);
  const observer = new MutationObserver(refresh);
  const overlay = document.getElementById('viewport-overlay');
  if (overlay) observer.observe(overlay, {attributes: true, attributeFilter: ['class']});
  window.addEventListener('pagehide', () => {
    destroyed = true; observer.disconnect();
    window.removeEventListener('atelier:artwork', receive);
    window.removeEventListener('atelier:inks', refresh);
  }, {once: true});
  refresh();
})();
