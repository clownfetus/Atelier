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
  let type = 'all', status = 'all', callbacks = {}, previewDialog, previewOpener, previewReveal;
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
  const previewElement = id => document.getElementById('library-preview-' + id);

  function previewLayers(state) {
    if (state.compare === 'original') return [state.original];
    return state.compare === 'wipe' ? [state.edited, state.original] : [state.edited];
  }

  function resizePreviewFrame() {
    const frame = previewElement('frame');
    if (!previewState || frame.hidden) return;
    const { naturalWidth: width, naturalHeight: height } = previewLayers(previewState)[0].image;
    const stage = previewElement('stage'), style = getComputedStyle(stage);
    const scale = previewState.zoom === '200' ? 2 : previewState.zoom === '100' ? 1 : Math.min(1,
      (stage.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight)) / width,
      (stage.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom)) / height);
    frame.style.width = `${width * scale}px`;
    frame.style.height = `${height * scale}px`;
  }

  function previewUrl(src, query) { return src + (src.includes('?') ? '&' : '?') + query; }

  function requestPreviewPixels(state, layer) {
    if (layer.pixels || layer.reading || layer.pixelError) return;
    layer.reading = true;
    const signal = AbortSignal.any([state.abort.signal, AbortSignal.timeout(20000)]);
    fetch(previewUrl(layer.src, 'rgba=1'), { signal }).then(response => {
      if (!response.ok || response.headers.get('Content-Type')?.split(';')[0] !== 'application/octet-stream') throw Error();
      return response.arrayBuffer();
    }).then(buffer => {
      if (buffer.byteLength !== layer.image.naturalWidth * layer.image.naturalHeight * 4) throw Error();
      layer.pixels = new Uint8Array(buffer);
    }).catch(() => { layer.pixelError = true; }).finally(() => {
      layer.reading = false;
      if (state === previewState) renderPreview();
    });
  }

  function drawPreviewLayer(layer, channel) {
    if (layer.channel === channel) return;
    const { naturalWidth: width, naturalHeight: height } = layer.image;
    const canvas = layer.canvas;
    canvas.width = width; canvas.height = height;
    const ctx = canvas.getContext('2d');
    if (channel === 'rgb') ctx.drawImage(layer.image, 0, 0);
    else {
      const frame = ctx.createImageData(width, height), pixels = frame.data;
      const offset = 'rgba'.indexOf(channel);
      for (let i = 0; i < pixels.length; i += 4) {
        pixels[i] = pixels[i + 1] = pixels[i + 2] = layer.pixels[i + offset];
        pixels[i + 3] = 255;
      }
      ctx.putImageData(frame, 0, 0);
    }
    layer.channel = channel;
  }

  function updatePixelReadout() {
    const state = previewState, frame = previewElement('frame'), readout = previewElement('pixel');
    if (!state?.isTexture || frame.hidden) { readout.textContent = ''; return; }
    const rect = frame.getBoundingClientRect();
    const x = (state.pointer?.clientX - rect.left) / rect.width;
    const y = (state.pointer?.clientY - rect.top) / rect.height;
    const inside = x >= 0 && x < 1 && y >= 0 && y < 1;
    const layer = state.compare === 'wipe' && inside && x < state.wipe / 100 ? state.original : previewLayers(state)[0];
    const { naturalWidth: w, naturalHeight: h } = layer.image;
    const size = `${w} × ${h} px`;
    if (!inside || !layer.pixels) {
      readout.textContent = size;
      if (inside) requestPreviewPixels(state, layer);
      return;
    }
    const px = Math.floor(x * w), py = Math.floor(y * h), i = (py * w + px) * 4;
    const [r, g, b, a] = layer.pixels.subarray(i, i + 4);
    const hex = '#' + [r, g, b].map(value => value.toString(16).padStart(2, '0')).join('').toUpperCase();
    readout.textContent = `${size} · (${px}, ${py}) ${hex} · A ${a}`;
  }

  function renderPreview() {
    const state = previewState;
    if (!state) return;
    const frame = previewElement('frame'), message = previewElement('message'), retry = previewElement('retry');
    const layers = previewLayers(state);
    const imageMissing = layers.find(layer => layer.status !== 'loaded');
    if (!imageMissing && state.channel !== 'rgb') layers.forEach(layer => requestPreviewPixels(state, layer));
    const pixelsMissing = !imageMissing && state.channel !== 'rgb' && layers.find(layer => !layer.pixels);
    const blocked = imageMissing || pixelsMissing;
    frame.hidden = !!blocked;
    retry.hidden = !(imageMissing?.status === 'error' || imageMissing?.status === 'timeout' || pixelsMissing?.pixelError);
    if (imageMissing) {
      const name = imageMissing === state.original ? 'Original preview' : 'Preview';
      message.textContent = imageMissing.status === 'error' ? `${name} unavailable.`
        : imageMissing.status === 'timeout' ? `${name} is taking too long. You can retry or close it.`
        : `Loading ${name.toLowerCase()}…`;
    } else if (pixelsMissing) message.textContent = pixelsMissing.pixelError ? 'Texture channels unavailable.' : 'Loading texture channels…';
    else {
      message.textContent = '';
      const showEditedImage = layers.includes(state.edited) && state.channel === 'rgb';
      state.edited.image.hidden = !showEditedImage;
      for (const layer of [state.edited, state.original].filter(Boolean)) {
        layer.root.hidden = !layers.includes(layer);
        layer.canvas.hidden = layer === state.edited && showEditedImage;
        if (!layer.root.hidden && !layer.canvas.hidden) drawPreviewLayer(layer, state.channel);
      }
      previewElement('wipe-wrap').hidden = state.compare !== 'wipe';
      frame.classList.toggle('is-wipe', state.compare === 'wipe');
      resizePreviewFrame();
    }
    updatePixelReadout();
  }

  function loadPreviewLayer(state, layer, bust = false) {
    const image = layer.image;
    clearTimeout(layer.timer);
    layer.status = 'loading';
    image.onload = () => {
      if (state !== previewState) return;
      clearTimeout(layer.timer);
      layer.status = 'loaded';
      renderPreview();
      if (layer === state.edited && !image.hidden) {
        previewReveal?.destroy();
        previewReveal = window.AtelierPolish?.play(image, [{clipPath: 'inset(0 0 100% 0)'}, {clipPath: 'inset(0)'}],
          window.AtelierMotion.unfoldMs, window.AtelierMotion.ease.unfold);
      }
    };
    image.onerror = () => {
      if (state !== previewState) return;
      clearTimeout(layer.timer);
      layer.status = 'error';
      renderPreview();
    };
    layer.timer = setTimeout(() => { layer.status = 'timeout'; renderPreview(); }, 20000);
    image.src = bust ? previewUrl(layer.src, `_t=${Date.now()}`) : layer.src;
    renderPreview();
  }

  function clearPreview() {
    previewState?.abort.abort();
    for (const layer of [previewState?.edited, previewState?.original].filter(Boolean)) {
      clearTimeout(layer.timer);
      layer.image.onload = layer.image.onerror = null;
      layer.image.removeAttribute('src');
      layer.image.hidden = true;
      layer.root.hidden = true;
      layer.canvas.width = layer.canvas.height = 0;
    }
    previewState = null;
    previewReveal?.destroy(); previewReveal = null;
  }

  function syncPreviewToolbar() {
    if (!previewDialog || !previewState) return;
    const toolbar = previewElement('toolbar');
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
    const compareGroup = previewElement('compare-group');
    if (compareGroup) compareGroup.hidden = !previewState.original;
    const checkerBtn = previewElement('checker');
    if (checkerBtn) checkerBtn.setAttribute('aria-pressed', String(!!previewState.checker));
    previewElement('stage').classList.toggle('is-checker', previewState.checker);
    renderPreview();
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
        '<div class="library-preview-stage" id="library-preview-stage">' +
          '<div class="lp-frame" id="library-preview-frame" hidden>' +
            '<div class="lp-layer" id="library-preview-edited"><img alt="" hidden><canvas id="library-preview-canvas" hidden></canvas></div>' +
            '<div class="lp-layer" id="library-preview-original" hidden><canvas id="library-preview-original-canvas"></canvas></div>' +
            '<div class="lp-wipe-wrap" id="library-preview-wipe-wrap" hidden>' +
              '<span class="lp-wipe-label lp-wipe-left">Original</span>' +
              '<span class="lp-wipe-label lp-wipe-right">Edited</span>' +
              '<div class="lp-wipe-line"></div>' +
              '<input type="range" id="library-preview-wipe" min="0" max="100" value="50" aria-label="Original and edited split">' +
            '</div>' +
          '</div>' +
          '<p class="library-preview-message" id="library-preview-message" role="status"></p>' +
        '</div>' +
        '<div class="library-preview-footer"><span></span><div class="lp-footer-actions"><div id="library-preview-actions"></div><button type="button" class="btn" id="library-preview-retry">Retry preview</button></div></div>';
      document.body.append(previewDialog);
      previewElement('close').addEventListener('click', closePreview);
      previewDialog.addEventListener('click', e => { if (e.target === previewDialog) closePreview(); });
      previewElement('toolbar').addEventListener('click', event => {
        const btn = event.target.closest('button');
        const state = previewState;
        if (!btn || !state) return;
        if (btn.dataset.channel) state.channel = btn.dataset.channel;
        else if (btn.dataset.zoom) state.zoom = btn.dataset.zoom;
        else if (btn.dataset.compare) {
          if (!state.original) return;
          state.compare = btn.dataset.compare;
          if (state.compare !== 'edited' && !state.original.status) loadPreviewLayer(state, state.original);
        } else if (btn.id === 'library-preview-checker') state.checker = !state.checker;
        syncPreviewToolbar();
      });
      previewElement('wipe').addEventListener('input', event => {
        if (!previewState) return;
        previewState.wipe = Number(event.target.value);
        previewElement('frame').style.setProperty('--preview-split', `${previewState.wipe}%`);
        updatePixelReadout();
      });
      const stage = previewElement('stage');
      stage.addEventListener('pointermove', event => {
        if (!previewState) return;
        previewState.pointer = { clientX: event.clientX, clientY: event.clientY };
        updatePixelReadout();
      });
      stage.addEventListener('pointerleave', () => {
        if (previewState) previewState.pointer = null;
        updatePixelReadout();
      });
      stage.addEventListener('scroll', updatePixelReadout, { passive: true });
      new ResizeObserver(resizePreviewFrame).observe(stage);
      previewElement('retry').addEventListener('click', () => {
        const state = previewState;
        if (!state) return;
        const layers = previewLayers(state);
        const imageMissing = layers.find(layer => layer.status !== 'loaded');
        if (imageMissing) loadPreviewLayer(state, imageMissing, true);
        else {
          for (const layer of layers) layer.pixelError = false;
          renderPreview();
        }
      });
      previewDialog.addEventListener('close', () => {
        if (previewDialog.open) return; // A previous close can arrive after a new preview opens.
        clearPreview();
        if (previewOpener?.isConnected) previewOpener.focus();
      });
      previewDialog.addEventListener('keydown', e => { if (e.key === 'Escape') e.stopPropagation(); });
    }
    clearPreview();
    previewOpener = opener;
    const img = previewElement('edited').querySelector('img');
    img.alt = label;
    previewState = {
      isTexture,
      edited: { src, image: img, root: previewElement('edited'), canvas: previewElement('canvas') },
      original: originalSrc ? { src: originalSrc, image: new Image(), root: previewElement('original'),
        canvas: previewElement('original-canvas') } : null,
      channel: 'rgb',
      compare: 'edited',
      zoom: 'fit',
      wipe: 50,
      checker: false,
      abort: new AbortController(),
    };
    previewElement('wipe').value = '50';
    previewElement('frame').style.setProperty('--preview-split', '50%');
    const actionHost = previewElement('actions');
    actionHost.replaceChildren();
    for (const act of actions) {
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
    previewElement('title').textContent = label;
    previewElement('path').textContent = path;
    previewDialog.querySelector('.library-preview-footer span').textContent = caption;
    syncPreviewToolbar();
    if (!previewDialog.open) previewDialog.showModal();
    previewElement('stage').scrollTo(0, 0);
    loadPreviewLayer(previewState, previewState.edited);
    previewElement('close').focus();
  }
  window.AtelierLibraryTools = Object.freeze({init, matches, filter, sort, resetFilters, hasFilters,
    decorate, ready, supportsPreview, previewImage, closePreview});
})();
