// Colourblind & Readability Lens — preview-only SVG colour-matrix filters for Model Studio & VFX.
(() => {
  'use strict';

  // Scientifically standard CVD simulation matrices (Machado et al., 2009, severity 1.0) + Rec.709 luminance.
  const MATRICES = Object.freeze({
    protanopia:   '0.152286 1.052583 -0.204868 0 0  0.114503 0.786281 0.099216 0 0  -0.003882 -0.048116 1.051998 0 0  0 0 0 1 0',
    deuteranopia: '0.367322 0.860646 -0.227968 0 0  0.280085 0.672501 0.047413 0 0  -0.011820 0.042940 0.968881 0 0  0 0 0 1 0',
    tritanopia:   '1.255528 -0.076749 -0.178779 0 0  -0.078411 0.930809 0.147602 0 0  0.004733 0.691367 0.303900 0 0  0 0 0 1 0',
    grayscale:    '0.2126 0.7152 0.0722 0 0  0.2126 0.7152 0.0722 0 0  0.2126 0.7152 0.0722 0 0  0 0 0 1 0',
  });

  const MODES = Object.freeze([
    { id: 'normal', label: 'Normal vision' },
    { id: 'protanopia', label: 'Protanopia (red-weak)' },
    { id: 'deuteranopia', label: 'Deuteranopia (green-weak)' },
    { id: 'tritanopia', label: 'Tritanopia (blue-weak)' },
    { id: 'grayscale', label: 'Luminance contrast' },
  ]);

  let svgInjected = false;

  function ensureSvgFilters() {
    if (svgInjected || typeof document === 'undefined') return;
    svgInjected = true;
    const ns = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(ns, 'svg');
    svg.id = 'atelier-vision-filters';
    svg.setAttribute('aria-hidden', 'true');
    svg.style.cssText = 'position:absolute;width:0;height:0;overflow:hidden;pointer-events:none';
    const defs = document.createElementNS(ns, 'defs');
    for (const [id, values] of Object.entries(MATRICES)) {
      const filter = document.createElementNS(ns, 'filter');
      filter.id = `atelier-lens-${id}`;
      filter.setAttribute('color-interpolation-filters', 'sRGB');
      const matrix = document.createElementNS(ns, 'feColorMatrix');
      matrix.setAttribute('type', 'matrix');
      matrix.setAttribute('values', values);
      filter.append(matrix);
      defs.append(filter);
    }
    svg.append(defs);
    document.body.append(svg);
  }

  function filterCss(mode) {
    return MATRICES[mode] ? `url(#atelier-lens-${mode})` : 'none';
  }

  function applyViewport(mode) {
    ensureSvgFilters();
    const canvas = document.getElementById('viewport-canvas');
    if (canvas) canvas.style.filter = filterCss(mode);
    const select = document.getElementById('viewport-vision-lens');
    if (select && select.value !== mode) select.value = MATRICES[mode] ? mode : 'normal';
  }

  function applyVfx(mode) {
    ensureSvgFilters();
    const body = document.getElementById('vfx-body');
    const clean = MATRICES[mode] ? mode : 'normal';
    if (body) {
      if (clean === 'normal') {
        body.removeAttribute('data-vision-lens');
        body.style.removeProperty('--vfx-lens-filter');
      } else {
        body.dataset.visionLens = clean;
        body.style.setProperty('--vfx-lens-filter', filterCss(clean));
      }
    }
    const select = document.getElementById('vfx-vision-lens');
    if (select && select.value !== clean) select.value = clean;
  }

  function populateSelect(select) {
    if (!select || select.options.length) return;
    for (const m of MODES) select.append(new Option(m.label, m.id));
  }

  function init() {
    if (typeof document === 'undefined') return;
    const vpSelect = document.getElementById('viewport-vision-lens');
    if (vpSelect) {
      populateSelect(vpSelect);
      vpSelect.addEventListener('change', e => applyViewport(e.target.value));
    }
    const vfxSelect = document.getElementById('vfx-vision-lens');
    if (vfxSelect) {
      populateSelect(vfxSelect);
      vfxSelect.addEventListener('change', e => applyVfx(e.target.value));
    }
  }

  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
    else init();
  }

  if (typeof window !== 'undefined') {
    window.AtelierVisionLens = Object.freeze({ MODES, MATRICES, filterCss, applyViewport, applyVfx });
  }
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = { MODES, MATRICES, filterCss };
  }
})();
