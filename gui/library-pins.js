// UI-profile shortcuts only. These never alter projects, game paths or export selection.
(() => {
  'use strict';
  const KEY = 'atelier.homePins.v1';
  const iconNames = AtelierFolderIcons.symbols;
  const folderClasses = new Set(Object.keys(iconNames));
  const views = new Map();
  const pathLabels = new Map();

  function normalizePath(value) {
    if (typeof value !== 'string') return null;
    const path = value.trim().replace(/\\/g, '/');
    if (!path || path.startsWith('/') || /[:\u0000-\u001f\u007f?#]/.test(path)) return null;
    const parts = path.split('/').filter(Boolean);
    for (const part of parts) {
      let decoded = part;
      try { decoded = decodeURIComponent(part); } catch (_) {}
      if (part === '.' || part === '..' || decoded === '.' || decoded === '..' || /[\\/:\u0000-\u001f\u007f]/.test(decoded)) return null;
    }
    return parts.length ? parts.join('/') : null;
  }

  function readableLabel(label) {
    // Browse labels carry IDs for disambiguation in the grid. Shortcuts retain the
    // actual path in their tooltip/accessibility name and lead with the known name.
    return label.trim().replace(/^\d{3,}\s+[—–-]\s+/, '');
  }

  function labelParts(path, labels = pathLabels, previous = []) {
    let prefix = '';
    return path.split('/').map((part, index) => {
      prefix = prefix ? `${prefix}/${part}` : part;
      const known = labels instanceof Map ? labels.get(prefix) :
        (labels && Object.hasOwn(labels, prefix) ? labels[prefix] : undefined);
      if (typeof known === 'string' && known.trim()) return readableLabel(known);
      return typeof previous[index] === 'string' && previous[index].trim() ? previous[index].trim() : part;
    });
  }

  function joinLabel(path, parts) {
    // "Characters" adds no useful context ahead of a hero's name; other roots
    // (Maps, UI, Plugins, etc.) remain useful when identifying nested shortcuts.
    const start = path.startsWith('Characters/') ? 1 : 0;
    return parts.slice(start).join(' · ');
  }

  function makePinLabel(value, labels = pathLabels) {
    const path = normalizePath(value);
    return path ? joinLabel(path, labelParts(path, labels)) : '';
  }

  function normalizePin(value) {
    if (!value || typeof value !== 'object' || (value.type && value.type !== 'folder')) return null;
    const path = normalizePath(value.rel_path ?? value.path);
    if (!path) return null;
    const suppliedLabel = value.pinLabel ?? value.label ?? value.name;
    const label = typeof suppliedLabel === 'string' && suppliedLabel.trim() ? suppliedLabel.trim() : '';
    const autoLabel = value.labelSource === 'path' || typeof value.pinLabel === 'string' ||
      !label || label === path.split('/').at(-1) || label === path || /^\d{3,}\s+[—–-]\s+/.test(label);
    // Refresh old generic shortcut artwork without changing the v1 storage format.
    const category = AtelierFolderIcons.classFor(path.split('/').at(-1));
    const iconCls = category !== 'folder-icon' ? category :
      (folderClasses.has(value.iconCls) ? value.iconCls : 'folder-icon');
    if (!autoLabel) return {path, label, iconCls};
    // Persist the names already learned for this pin, so a reload or a browse of
    // another branch cannot turn a useful hero/skin label back into numeric IDs.
    const context = labelParts(path, pathLabels, Array.isArray(value.context) ? value.context : []);
    return {path, label: joinLabel(path, context), iconCls, labelSource: 'path', context};
  }

  function decode(raw) {
    if (raw === null) return [];
    try {
      const data = JSON.parse(raw);
      if (data?.version !== 1 || !Array.isArray(data.pins)) return null;
      const found = new Set();
      return data.pins.map(normalizePin).filter(pin => pin && !found.has(pin.path) && found.add(pin.path));
    } catch (_) { return null; }
  }

  let pins = [];
  try { pins = decode(localStorage.getItem(KEY)) || []; } catch (_) {}
  const list = () => pins.map(pin => ({...pin, ...(pin.context ? {context: [...pin.context]} : {})}));
  const isPinned = path => pins.some(pin => pin.path === normalizePath(path));

  function updateLabels(labels) {
    const entries = labels instanceof Map ? labels.entries() : Object.entries(labels || {});
    for (const [value, label] of entries) {
      const path = normalizePath(value);
      if (path && typeof label === 'string' && label.trim()) pathLabels.set(path, label.trim());
    }
    const next = pins.map(normalizePin);
    if (JSON.stringify(next) !== JSON.stringify(pins)) {
      pins = next;
      publish();
    }
  }

  function glyph(name, className = '') {
    const icon = document.createElement('i');
    icon.dataset.lucide = name;
    icon.className = className;
    icon.setAttribute('size', '18');
    return icon;
  }

  function updateButton(button) {
    const active = isPinned(button.dataset.libraryPinPath);
    button.setAttribute('aria-pressed', String(active));
    const action = `${active ? 'Unpin' : 'Pin'} ${button.dataset.libraryPinLabel} ${active ? 'from' : 'to'} home`;
    button.setAttribute('aria-label', action);
    button.title = action;
  }

  function publish(persist = true) {
    if (persist) {
      try { localStorage.setItem(KEY, JSON.stringify({version: 1, pins})); } catch (_) { /* Session state still works. */ }
    }
    // Query only live controls. Removed grids retain no references, observers or timers here.
    document.querySelectorAll('.library-pin-toggle[data-library-pin-path]').forEach(updateButton);
    for (const [container, options] of views) {
      if (!container.isConnected) views.delete(container);
      else render(container, options);
    }
    window.dispatchEvent(new CustomEvent('atelier:home-pins-changed', {detail: list()}));
  }

  function toggle(value) {
    const pin = normalizePin(value);
    if (!pin) return false;
    if (isPinned(pin.path)) pins = pins.filter(item => item.path !== pin.path);
    else pins.push(pin);
    publish();
    return isPinned(pin.path);
  }

  function remove(path) {
    const normalized = normalizePath(path);
    if (!normalized || !isPinned(normalized)) return false;
    pins = pins.filter(pin => pin.path !== normalized);
    publish();
    return true;
  }

  function decorate(card, button) {
    if (card?.type !== 'folder' || !button) return button;
    const pin = normalizePin(card);
    if (!pin) return button;
    const wrapper = document.createElement('div');
    wrapper.className = 'folder-card-wrap';
    const control = document.createElement('button');
    control.type = 'button';
    control.className = 'library-pin-toggle';
    control.dataset.libraryPinPath = pin.path;
    control.dataset.libraryPinLabel = pin.label;
    control.append(glyph('pin'));
    updateButton(control);
    control.addEventListener('click', () => toggle(pin));
    wrapper.append(button, control);
    window.AtelierIcons?.createIcons({nodes: [control]});
    return wrapper;
  }

  function render(container, options = {}) {
    if (!container) return;
    for (const host of views.keys()) if (host !== container && !host.isConnected) views.delete(host);
    views.set(container, options);
    const query = String(options.filter || '').trim().toLowerCase();
    const shown = options.isHome ? pins.filter(pin => !query || `${pin.label} ${pin.path}`.toLowerCase().includes(query)) : [];
    container.replaceChildren();
    container.classList.add('library-pins');
    container.hidden = !shown.length;
    container.setAttribute('role', 'navigation');
    container.setAttribute('aria-label', 'Pinned folders');
    if (!shown.length) return;
    const heading = document.createElement('span');
    heading.className = 'library-pins-label';
    heading.textContent = 'Pinned';
    container.append(heading);
    const items = document.createElement('div');
    items.className = 'library-pins-items';
    shown.forEach((pin, index) => {
      const chip = document.createElement('div');
      chip.className = 'library-pin-chip';
      const open = document.createElement('button');
      open.type = 'button';
      open.className = 'library-pin-open';
      open.title = pin.path;
      open.setAttribute('aria-label', `Open ${pin.label} (${pin.path})`);
      open.append(glyph(iconNames[pin.iconCls] || 'folder', `card-icon ${pin.iconCls}`));
      const text = document.createElement('span');
      text.textContent = pin.label;
      open.append(text);
      open.addEventListener('click', () => options.onNavigate?.(pin.path));
      const unpin = document.createElement('button');
      unpin.type = 'button';
      unpin.className = 'library-pin-remove';
      unpin.title = `Unpin ${pin.label} from home`;
      unpin.setAttribute('aria-label', `Unpin ${pin.label} (${pin.path}) from home`);
      unpin.append(glyph('x'));
      unpin.addEventListener('click', () => {
        remove(pin.path);
        const remaining = container.querySelectorAll('.library-pin-open');
        const next = remaining[Math.min(index, remaining.length - 1)] || document.querySelector('#grid-area button.card') || document.getElementById('search-input');
        next?.focus();
      });
      chip.append(open, unpin);
      items.append(chip);
    });
    container.append(items);
    window.AtelierIcons?.createIcons({nodes: [container]});
  }

  window.addEventListener('storage', event => {
    if (event.key !== KEY && event.key !== null) return;
    const next = decode(event.key === null ? null : event.newValue);
    if (!next) return;
    pins = next;
    publish(false);
  });
  window.AtelierLibraryPins = Object.freeze({decorate, render, list, isPinned, toggle, remove, makePinLabel, updateLabels});
})();
