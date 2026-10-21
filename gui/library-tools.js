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
  let type = 'all', status = 'all', callbacks = {}, previewDialog, previewOpener, previewTimer;
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
  function sort(cards) {
    if (prefs.sort === 'recommended') return cards;
    const name = (a, b) => collator.compare(a.label, b.label);
    const folders = (a, b) => Number(b.type === 'folder') - Number(a.type === 'folder');
    return [...cards].sort((a, b) => folders(a, b) ||
      (prefs.sort === 'type' ? collator.compare(a.file_type || '', b.file_type || '') :
        prefs.sort === 'edited' ? Number(!!b.imported) - Number(!!a.imported) : 0) ||
      (prefs.sort === 'name-desc' ? -name(a, b) : name(a, b)));
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
  function previewImage({label, path, src, caption}, opener) {
    if (!previewDialog) {
      previewDialog = document.createElement('dialog'); previewDialog.id = 'library-preview';
      previewDialog.setAttribute('aria-labelledby', 'library-preview-title');
      previewDialog.innerHTML = '<div class="library-preview-heading"><div><h2 id="library-preview-title"></h2><p id="library-preview-path"></p></div><button type="button" class="btn" id="library-preview-close">Close</button></div><div class="library-preview-stage"><img alt=""><p class="library-preview-message" role="status"></p></div><div class="library-preview-footer"><span></span><button type="button" class="btn" id="library-preview-retry">Retry preview</button></div>';
      document.body.append(previewDialog);
      document.getElementById('library-preview-close').addEventListener('click', closePreview);
      previewDialog.addEventListener('click', e => { if (e.target === previewDialog) closePreview(); });
      previewDialog.addEventListener('close', () => {
        clearTimeout(previewTimer);
        const img = previewDialog.querySelector('img'); img.onload = img.onerror = null; img.removeAttribute('src');
        if (previewOpener?.isConnected) previewOpener.focus();
      });
      previewDialog.addEventListener('keydown', e => { if (e.key === 'Escape') e.stopPropagation(); });
    }
    previewOpener = opener;
    const img = previewDialog.querySelector('img'), message = previewDialog.querySelector('.library-preview-message');
    const retry = document.getElementById('library-preview-retry');
    document.getElementById('library-preview-title').textContent = label;
    document.getElementById('library-preview-path').textContent = path;
    previewDialog.querySelector('.library-preview-footer span').textContent = caption;
    const load = bust => {
      clearTimeout(previewTimer);
      message.textContent = 'Loading preview…'; img.hidden = true; retry.hidden = true;
      img.onload = () => { clearTimeout(previewTimer); img.hidden = false; message.textContent = ''; retry.hidden = true; };
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
    decorate, ready, supportsPreview, previewImage, closePreview, preferredSort: () => prefs.sort});
})();
