// Local presentation preferences, filtering, keyboard movement and read-only previews.
(() => {
  'use strict';
  const KEY = 'atelier.libraryView.v1';
  const sorts = new Set(['recommended', 'name', 'name-desc', 'type', 'edited']);
  const sizes = new Set([128, 156, 196, 236]);
  let prefs = {size: 156, sort: 'recommended'};
  try {
    const saved = JSON.parse(localStorage.getItem(KEY));
    if (sizes.has(saved?.size)) prefs.size = saved.size;
    if (sorts.has(saved?.sort)) prefs.sort = saved.sort;
  } catch (_) {}
  let type = 'all', status = 'all', callbacks = {}, previewDialog, previewOpener, previewTimer, previewReveal;
  const items = new WeakMap();
  const normalize = value => String(value ?? '').normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/\\/g, '/');
  const words = query => normalize(query).trim().split(/\s+/).filter(Boolean);
  function matches(item, query) {
    const haystack = normalize([item.name, item.label, item.game_rel, item.rel_path,
      item.char_name, item.skin_name, item.skin_id, item.searchText].filter(Boolean).join(' '));
    return words(query).every(term => haystack.includes(term));
  }
  function filter(cards, query) {
    syncFilterControls(query);
    return cards.filter(card => matches(card, query) &&
      (type === 'all' || (type === 'folder' ? card.type === 'folder' : card.type === 'asset' && card.file_type === type)) &&
      (status === 'all' || card.type === 'asset' && (status === 'edited' ? !!card.imported : !card.imported)));
  }
  const collator = new Intl.Collator(undefined, {numeric: true, sensitivity: 'base'});
  function sort(cards, {home = false} = {}) {
    const recommended = prefs.sort === 'recommended';
    const roles = window.AtelierFolderEmblems?.roles;
    const coloured = [], featured = [], rest = [];
    for (const card of cards) {
      const isFolder = card.type === 'folder';
      const role = isFolder && roles?.[card.iconCls];
      if (role && role !== 'neutral') coloured.push(card);
      else if (recommended && home && isFolder && AtelierFolderIcons.isFeatured(card.name)) featured.push(card);
      else rest.push(card);
    }
    if (recommended) return coloured.concat(featured, rest);

    const name = (a, b) => collator.compare(a.label, b.label);
    const folders = (a, b) => Number(b.type === 'folder') - Number(a.type === 'folder');
    const compare = (a, b) => folders(a, b) ||
      (prefs.sort === 'type' ? collator.compare(a.file_type || '', b.file_type || '') :
        prefs.sort === 'edited' ? Number(!!b.imported) - Number(!!a.imported) : 0) ||
      (prefs.sort === 'name-desc' ? -name(a, b) : name(a, b));
    return coloured.sort(compare).concat(rest.sort(compare));
  }
  function persist() {
    try { localStorage.setItem(KEY, JSON.stringify(prefs)); } catch (_) {}
  }
  function resetFilters(notify = true) {
    type = status = 'all';
    for (const id of ['library-type', 'library-status']) {
      const control = document.getElementById(id); if (control) control.value = 'all';
    }
    syncFilterControls('');
    if (notify) callbacks.change?.();
  }
  function hasFilters() { return type !== 'all' || status !== 'all'; }
  function syncFilterControls(query) {
    const clear = document.getElementById('library-clear');
    if (clear) clear.hidden = !hasFilters() && !String(query || '').trim();
    for (const id of ['library-type', 'library-status']) {
      const control = document.getElementById(id);
      if (control) control.dataset.active = String(control.value !== 'all');
    }
  }
  function init(options) {
    callbacks = options;
    const explorer = document.getElementById('explorer');
    const size = document.getElementById('library-size'), order = document.getElementById('library-sort');
    size.value = String(prefs.size); order.value = prefs.sort;
    syncFilterControls('');
    explorer.style.setProperty('--card-w', `${prefs.size}px`);
    size.addEventListener('change', () => {
      if (!sizes.has(+size.value)) return;
      prefs.size = +size.value; explorer.style.setProperty('--card-w', `${prefs.size}px`); persist();
    });
    order.addEventListener('change', () => {
      if (!sorts.has(order.value)) return;
      prefs.sort = order.value; persist(); callbacks.change?.();
    });
    document.getElementById('library-type').addEventListener('change', e => { type = e.target.value; callbacks.change?.(); });
    document.getElementById('library-status').addEventListener('change', e => { status = e.target.value; callbacks.change?.(); });
    document.getElementById('library-clear').addEventListener('click', () => {
      const restoreFocus = document.activeElement === document.getElementById('library-clear');
      const destination = type !== 'all' ? 'library-type' : status !== 'all' ? 'library-status' : 'search-input';
      document.getElementById('search-input').value = ''; resetFilters();
      if (restoreFocus) document.getElementById(destination).focus();
    });
    document.getElementById('grid-area').addEventListener('keydown', onKey);
  }
  function supportsPreview(card) {
    return !!(card.thumbnail || card.type === 'asset' && ['texture', 'mesh'].includes(card.file_type) ||
      card.type === 'folder' && /^Characters\/\d{4}\/\d{7}$/i.test(card.rel_path || ''));
  }
  function decorate(card, button, wrapper) {
    items.set(button, card);
    button.dataset.libraryPath = card.rel_path || card.game_rel || card.label;
    button.tabIndex = -1;
    button.addEventListener('focus', () => {
      button.closest('.grid')?.querySelectorAll('button.card').forEach(el => { el.tabIndex = el === button ? 0 : -1; });
    });
    if (!supportsPreview(card)) return wrapper;
    button.setAttribute('aria-keyshortcuts', 'Space P');
    if (wrapper === button) {
      wrapper = document.createElement('div'); wrapper.className = 'asset-card-wrap'; wrapper.append(button);
    }
    const preview = document.createElement('button');
    preview.type = 'button'; preview.className = 'library-preview-button';
    preview.title = `Preview ${card.label} (Space)`;
    preview.setAttribute('aria-label', `Preview ${card.label}`);
    const icon = document.createElement('i'); icon.dataset.lucide = card.file_type === 'mesh' ? 'box' : 'search';
    icon.setAttribute('size', '16'); preview.append(icon);
    preview.addEventListener('click', () => callbacks.preview?.(card, preview));
    wrapper.append(preview);
    return wrapper;
  }
  function ready(grid, focusPath) {
    const buttons = [...grid.querySelectorAll('button.card')];
    const first = buttons.find(el => el.dataset.libraryPath === focusPath) || buttons[0];
    if (first) { first.tabIndex = 0; if (focusPath) first.focus({preventScroll: true}); }
  }
  function onKey(event) {
    const button = event.target.closest('button.card');
    if (!button || document.querySelector('.overlay.active, dialog[open]') || event.ctrlKey || event.metaKey || event.altKey) return;
    const card = items.get(button);
    if (event.key === 'F10' && event.shiftKey) {
      event.preventDefault(); callbacks.context?.(card, button); return;
    }
    if ((event.key === ' ' || event.key.toLowerCase() === 'p') && supportsPreview(card)) {
      event.preventDefault(); callbacks.preview?.(card, button); return;
    }
    if (event.key === 'Backspace') { event.preventDefault(); callbacks.parent?.(); return; }
    const buttons = [...button.closest('.grid').querySelectorAll('button.card')];
    const index = buttons.indexOf(button), rect = button.getBoundingClientRect();
    let target;
    if (event.key === 'Home') target = buttons[0];
    else if (event.key === 'End') target = buttons.at(-1);
    else if (event.key === 'ArrowLeft') target = buttons[Math.max(0, index - 1)];
    else if (event.key === 'ArrowRight') target = buttons[Math.min(buttons.length - 1, index + 1)];
    else if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
      const direction = event.key === 'ArrowDown' ? 1 : -1;
      const candidates = buttons.map(el => ({el, rect: el.getBoundingClientRect()}))
        .filter(p => (p.rect.top - rect.top) * direction > 2);
      candidates.sort((a, b) => Math.abs(a.rect.top - rect.top) - Math.abs(b.rect.top - rect.top) ||
        Math.abs(a.rect.left - rect.left) - Math.abs(b.rect.left - rect.left));
      target = candidates[0]?.el || button;
    } else return;
    event.preventDefault(); target?.focus(); target?.scrollIntoView({block: 'nearest', inline: 'nearest'});
  }
  function closePreview() { if (previewDialog?.open) previewDialog.close(); }
  let previewState = null;

  function renderPreviewCanvas() {
    if (!previewDialog || !previewState) return;
    const img = previewDialog.querySelector('.library-preview-stage img');
    const canvas = previewDialog.querySelector('#library-preview-canvas');
    const stage = previewDialog.querySelector('.library-preview-stage');
    const wipeWrap = previewDialog.querySelector('#library-preview-wipe-wrap');
    const wipeLine = previewDialog.querySelector('#library-preview-wipe-line');
    const { channel, compare, zoom, wipe, origImg, loaded } = previewState;
    const useCanvas = loaded && (channel !== 'rgb' || compare !== 'edited');
    if (stage) {
      stage.dataset.zoom = zoom;
      stage.classList.toggle('is-checker', !!previewState.checker);
    }
    if (wipeWrap) wipeWrap.hidden = !(loaded && compare === 'wipe' && origImg && origImg.complete && origImg.naturalWidth > 0);
    if (wipeLine) wipeLine.style.left = `${wipe}%`;
    if (!loaded) {
      if (canvas) canvas.hidden = true;
      return;
    }
    const w = img.naturalWidth || 0, h = img.naturalHeight || 0;
    if (!useCanvas || !w || !h || !canvas) {
      if (canvas) canvas.hidden = true;
      img.hidden = false;
      img.style.width = zoom === 'fit' ? '' : `${Math.round(w * (zoom === '200' ? 2 : 1))}px`;
      img.style.height = zoom === 'fit' ? '' : `${Math.round(h * (zoom === '200' ? 2 : 1))}px`;
      return;
    }
    img.hidden = true;
    canvas.hidden = false;
    if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
    canvas.style.width = zoom === 'fit' ? '' : `${Math.round(w * (zoom === '200' ? 2 : 1))}px`;
    canvas.style.height = zoom === 'fit' ? '' : `${Math.round(h * (zoom === '200' ? 2 : 1))}px`;
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    if (!ctx) return;
    ctx.clearRect(0, 0, w, h);
    const hasOrig = !!(origImg && origImg.complete && origImg.naturalWidth > 0);
    if (compare === 'original' && hasOrig) {
      ctx.drawImage(origImg, 0, 0, w, h);
    } else if (compare === 'wipe' && hasOrig) {
      const splitX = Math.round(w * (wipe / 100));
      ctx.drawImage(img, 0, 0, w, h);
      if (splitX > 0) {
        ctx.save();
        ctx.beginPath();
        ctx.rect(0, 0, splitX, h);
        ctx.clip();
        ctx.clearRect(0, 0, splitX, h);
        ctx.drawImage(origImg, 0, 0, w, h);
        ctx.restore();
      }
    } else {
      ctx.drawImage(img, 0, 0, w, h);
    }
    if (channel !== 'rgb') {
      try {
        const frame = ctx.getImageData(0, 0, w, h);
        const data = frame.data;
        const offset = channel === 'r' ? 0 : channel === 'g' ? 1 : channel === 'b' ? 2 : 3;
        for (let i = 0; i < data.length; i += 4) {
          const v = data[i + offset];
          data[i] = v; data[i + 1] = v; data[i + 2] = v; data[i + 3] = 255;
        }
        ctx.putImageData(frame, 0, 0);
      } catch (_) {}
    }
  }

  function updatePixelReadout(event) {
    if (!previewDialog || !previewState?.loaded || !previewState.isTexture) return;
    const readout = previewDialog.querySelector('#library-preview-pixel');
    if (!readout) return;
    const img = previewDialog.querySelector('.library-preview-stage img');
    const canvas = previewDialog.querySelector('#library-preview-canvas');
    const target = canvas && !canvas.hidden ? canvas : img;
    if (!target || target.hidden) return;
    const rect = target.getBoundingClientRect();
    const w = img.naturalWidth, h = img.naturalHeight;
    if (!rect.width || !rect.height || !w || !h) return;
    const px = Math.floor(((event.clientX - rect.left) / rect.width) * w);
    const py = Math.floor(((event.clientY - rect.top) / rect.height) * h);
    if (px < 0 || py < 0 || px >= w || py >= h) { readout.textContent = `${w} × ${h} px`; return; }
    try {
      if (!previewState.sampleCanvas) {
        const sc = document.createElement('canvas');
        sc.width = w; sc.height = h;
        const sctx = sc.getContext('2d', { willReadFrequently: true });
        if (sctx) sctx.drawImage(img, 0, 0, w, h);
        previewState.sampleCanvas = sc;
      }
      const p = previewState.sampleCanvas.getContext('2d', { willReadFrequently: true }).getImageData(px, py, 1, 1).data;
      const hex = '#' + [p[0], p[1], p[2]].map(v => v.toString(16).padStart(2, '0')).join('').toUpperCase();
      readout.textContent = `${w} × ${h} px · (${px}, ${py}) ${hex} · A ${p[3]}`;
    } catch (_) {
      readout.textContent = `${w} × ${h} px`;
    }
  }

  function syncPreviewToolbar() {
    if (!previewDialog || !previewState) return;
    const toolbar = previewDialog.querySelector('#library-preview-toolbar');
    if (toolbar) toolbar.hidden = !previewState.isTexture;
    toolbar?.querySelectorAll('[data-channel]').forEach(btn => {
      btn.setAttribute('aria-pressed', String(btn.dataset.channel === previewState.channel));
    });
    toolbar?.querySelectorAll('[data-zoom]').forEach(btn => {
      btn.setAttribute('aria-pressed', String(btn.dataset.zoom === previewState.zoom));
    });
    toolbar?.querySelectorAll('[data-compare]').forEach(btn => {
      btn.setAttribute('aria-pressed', String(btn.dataset.compare === previewState.compare));
    });
    const compareGroup = previewDialog.querySelector('#library-preview-compare-group');
    if (compareGroup) compareGroup.hidden = !previewState.originalSrc;
    const checkerBtn = previewDialog.querySelector('#library-preview-checker');
    if (checkerBtn) checkerBtn.setAttribute('aria-pressed', String(!!previewState.checker));
    renderPreviewCanvas();
  }

  function previewImage({label, path, src, caption, isTexture = false, originalSrc = '', actions = []}, opener) {
    if (!previewDialog) {
      previewDialog = document.createElement('dialog'); previewDialog.id = 'library-preview';
      previewDialog.setAttribute('aria-labelledby', 'library-preview-title');
      previewDialog.innerHTML =
        '<div class="library-preview-heading"><div><h2 id="library-preview-title"></h2><p id="library-preview-path"></p></div><button type="button" class="btn" id="library-preview-close">Close</button></div>' +
        '<div class="library-preview-toolbar" id="library-preview-toolbar" hidden>' +
          '<div class="lp-group" role="group" aria-label="Texture channels">' +
            '<button type="button" class="lp-btn" data-channel="rgb" aria-pressed="true">RGB</button>' +
            '<button type="button" class="lp-btn" data-channel="r" aria-pressed="false">R</button>' +
            '<button type="button" class="lp-btn" data-channel="g" aria-pressed="false">G</button>' +
            '<button type="button" class="lp-btn" data-channel="b" aria-pressed="false">B</button>' +
            '<button type="button" class="lp-btn" data-channel="a" aria-pressed="false">A</button>' +
          '</div>' +
          '<div class="lp-group" id="library-preview-compare-group" role="group" aria-label="Compare original and edited" hidden>' +
            '<button type="button" class="lp-btn" data-compare="edited" aria-pressed="true">Edited</button>' +
            '<button type="button" class="lp-btn" data-compare="original" aria-pressed="false">Original</button>' +
            '<button type="button" class="lp-btn" data-compare="wipe" aria-pressed="false">Wipe</button>' +
          '</div>' +
          '<div class="lp-group" role="group" aria-label="Zoom">' +
            '<button type="button" class="lp-btn" data-zoom="fit" aria-pressed="true">Fit</button>' +
            '<button type="button" class="lp-btn" data-zoom="100" aria-pressed="false">1:1</button>' +
            '<button type="button" class="lp-btn" data-zoom="200" aria-pressed="false">200%</button>' +
          '</div>' +
          '<button type="button" class="lp-btn" id="library-preview-checker" aria-pressed="false" title="Toggle transparency checkerboard">Checker</button>' +
          '<span class="lp-pixel" id="library-preview-pixel"></span>' +
        '</div>' +
        '<div class="library-preview-stage">' +
          '<img alt="">' +
          '<canvas id="library-preview-canvas" hidden></canvas>' +
          '<div class="lp-wipe-wrap" id="library-preview-wipe-wrap" hidden>' +
            '<span class="lp-wipe-label lp-wipe-left">Original</span>' +
            '<span class="lp-wipe-label lp-wipe-right">Edited</span>' +
            '<div class="lp-wipe-line" id="library-preview-wipe-line"></div>' +
            '<input type="range" id="library-preview-wipe" min="0" max="100" value="50" aria-label="Original and edited split">' +
          '</div>' +
          '<p class="library-preview-message" role="status"></p>' +
        '</div>' +
        '<div class="library-preview-footer"><span></span><div class="lp-footer-actions"><div id="library-preview-actions"></div><button type="button" class="btn" id="library-preview-retry">Retry preview</button></div></div>';
      document.body.append(previewDialog);
      document.getElementById('library-preview-close').addEventListener('click', closePreview);
      previewDialog.addEventListener('click', e => { if (e.target === previewDialog) closePreview(); });
      previewDialog.querySelector('#library-preview-toolbar').addEventListener('click', event => {
        const btn = event.target.closest('button');
        if (!btn || !previewState) return;
        if (btn.dataset.channel) { previewState.channel = btn.dataset.channel; syncPreviewToolbar(); }
        else if (btn.dataset.zoom) { previewState.zoom = btn.dataset.zoom; syncPreviewToolbar(); }
        else if (btn.dataset.compare) {
          previewState.compare = btn.dataset.compare;
          if (previewState.compare !== 'edited' && previewState.originalSrc && !previewState.origImg) {
            const orig = new Image();
            orig.onload = () => renderPreviewCanvas();
            orig.src = previewState.originalSrc;
            previewState.origImg = orig;
          }
          syncPreviewToolbar();
        } else if (btn.id === 'library-preview-checker') {
          previewState.checker = !previewState.checker;
          syncPreviewToolbar();
        }
      });
      previewDialog.querySelector('#library-preview-wipe').addEventListener('input', event => {
        if (!previewState) return;
        previewState.wipe = Number(event.target.value) || 0;
        renderPreviewCanvas();
      });
      const stage = previewDialog.querySelector('.library-preview-stage');
      stage.addEventListener('mousemove', updatePixelReadout);
      stage.addEventListener('mouseleave', () => {
        const img = previewDialog.querySelector('.library-preview-stage img');
        const readout = previewDialog.querySelector('#library-preview-pixel');
        if (readout && previewState?.loaded && img?.naturalWidth) readout.textContent = `${img.naturalWidth} × ${img.naturalHeight} px`;
      });
      previewDialog.addEventListener('close', () => {
        if (previewDialog.open) return; // A previous close can arrive after a new preview opens.
        clearTimeout(previewTimer);
        const img = previewDialog.querySelector('.library-preview-stage img');
        img.onload = img.onerror = null; img.removeAttribute('src');
        img.style.width = ''; img.style.height = '';
        const canvas = previewDialog.querySelector('#library-preview-canvas');
        if (canvas) { canvas.hidden = true; canvas.width = 0; canvas.height = 0; }
        previewState = null;
        previewReveal?.destroy(); previewReveal = null;
        if (previewOpener?.isConnected) previewOpener.focus();
      });
      previewDialog.addEventListener('keydown', e => { if (e.key === 'Escape') e.stopPropagation(); });
    }
    previewOpener = opener;
    previewState = {
      isTexture: !!isTexture,
      originalSrc: originalSrc || '',
      origImg: null,
      channel: 'rgb',
      compare: 'edited',
      zoom: 'fit',
      wipe: 50,
      checker: false,
      loaded: false,
      sampleCanvas: null,
    };
    const wipeInput = previewDialog.querySelector('#library-preview-wipe');
    if (wipeInput) wipeInput.value = '50';
    const readout = previewDialog.querySelector('#library-preview-pixel');
    if (readout) readout.textContent = '';
    const actionHost = previewDialog.querySelector('#library-preview-actions');
    if (actionHost) {
      actionHost.replaceChildren();
      for (const act of actions || []) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'btn';
        btn.textContent = act.label;
        btn.addEventListener('click', () => {
          closePreview();
          act.action?.();
        });
        actionHost.append(btn);
      }
    }
    syncPreviewToolbar();
    const img = previewDialog.querySelector('.library-preview-stage img'), message = previewDialog.querySelector('.library-preview-message');
    const retry = document.getElementById('library-preview-retry');
    document.getElementById('library-preview-title').textContent = label;
    document.getElementById('library-preview-path').textContent = path;
    previewDialog.querySelector('.library-preview-footer span').textContent = caption;
    const load = bust => {
      clearTimeout(previewTimer);
      previewReveal?.destroy(); previewReveal = null;
      if (previewState) { previewState.loaded = false; previewState.sampleCanvas = null; }
      message.textContent = 'Loading preview…'; img.hidden = true; retry.hidden = true;
      const canvas = previewDialog.querySelector('#library-preview-canvas');
      if (canvas) canvas.hidden = true;
      img.onload = () => {
        clearTimeout(previewTimer);
        if (previewState) previewState.loaded = true;
        img.hidden = false; message.textContent = ''; retry.hidden = true;
        if (readout && isTexture && img.naturalWidth) readout.textContent = `${img.naturalWidth} × ${img.naturalHeight} px`;
        renderPreviewCanvas();
        previewReveal = window.AtelierPolish?.play(img, [{clipPath: 'inset(0 0 100% 0)'}, {clipPath: 'inset(0)'}],
          window.AtelierMotion.unfoldMs, window.AtelierMotion.ease.unfold);
      };
      img.onerror = () => { clearTimeout(previewTimer); message.textContent = 'Preview unavailable. Try again after the thumbnail has loaded.'; retry.hidden = false; };
      previewTimer = setTimeout(() => { message.textContent = 'Preview is taking too long. You can retry or close it.'; retry.hidden = false; }, 20000);
      img.alt = label; img.src = src + (bust ? `${src.includes('?') ? '&' : '?'}_t=${Date.now()}` : '');
    };
    retry.onclick = () => load(true);
    load(false);
    if (!previewDialog.open) previewDialog.showModal();
    document.getElementById('library-preview-close').focus();
  }
  window.AtelierLibraryTools = Object.freeze({init, matches, filter, sort, resetFilters, hasFilters,
    decorate, ready, supportsPreview, previewImage, closePreview});
})();
