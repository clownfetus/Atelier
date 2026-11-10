// Your mod: the workspace's view of the Mod tray. Every slot is a saved edit in the active project;
// the tray in app.js stays the one source of edits, selection, Restore and the export review.
(() => {
  const $ = id => document.getElementById(id);
  const changes = new Map();          // project|game_rel|mtime -> Promise of colour changes
  const restored = new Set();         // edits Restore removed, so their Undo can refresh the stage
  let queue = Promise.resolve(), project = '', rendered = false;
  let departures = [];

  const tray = () => window.AtelierModTray;
  const costume = item => [item.char_name, item.skin_name].filter(Boolean).join(' / ');
  const label = item => item.file_type === 'material' ? window.AtelierViewport?.label?.(item.name) || item.name : item.name;
  const kind = {texture:'Texture', material:'Colours', mesh:'Model', vfx:'Effect', curve:'Curve'};
  const version = item => JSON.stringify([item.mtime, item.selected, item.file_type, item.name, item.char_name, item.skin_name]);

  // Original reads go through the game reader one at a time, and each saved version is read once.
  function colourChanges(item) {
    const origin = project;
    const key = [origin, item.game_rel, item.mtime].join('|');
    if (!changes.has(key)) {
      const url = '/api/material_changes?game_rel=' + encodeURIComponent(item.game_rel);
      const request = queue.then(() => window.atelierFetch(url, {}, origin).then(r => r.json()))
        .then(data => data.ok ? data.changes : null, () => null);
      queue = request.then(() => {});
      changes.set(key, request);
    }
    return changes.get(key);
  }

  function swatch(colour, title) {
    const chip = document.createElement('span');
    chip.className = 'workspace-swatch' + (colour ? '' : ' workspace-swatch--none');
    if (colour) chip.style.background = colour;
    chip.title = title;
    return chip;
  }

  function visual(item) {
    const frame = document.createElement('span'), host = document.createElement('span');
    frame.className = 'workspace-slot-visual'; frame.setAttribute('aria-hidden', 'true');
    host.className = 'workspace-slot-art'; frame.append(host);
    if (item.file_type === 'material') {
      colourChanges(item).then(list => {
        if (!list?.length) { host.textContent = list ? 'Settings' : ''; return; }
        const [first] = list;
        const arrow = document.createElement('span'); arrow.className = 'workspace-swatch-arrow'; arrow.textContent = '→';
        host.replaceChildren(swatch(first.before, `${first.name}: ${first.before || 'not in the original'}`), arrow,
          swatch(first.after, `${first.name}: ${first.after}`));
        if (list.length > 1) {
          const more = document.createElement('span'); more.className = 'workspace-swatch-more'; more.textContent = '+' + (list.length - 1);
          host.append(more);
        }
        host.closest('li')?.setAttribute('data-changes', String(list.length));
      });
      return frame;
    }
    const url = tray()?.preview(item);
    if (url) {
      const image = document.createElement('img'); image.alt = ''; image.loading = 'lazy'; image.src = url;
      image.onerror = () => image.remove();
      host.append(image);
    }
    return frame;
  }

  function slot(item) {
    const li = document.createElement('li');
    li.className = 'workspace-slot' + (item.selected ? '' : ' workspace-slot--left-out');
    li.dataset.token = item.token; li.dataset.gameRel = item.game_rel;
    li.dataset.savedVersion = String(item.mtime || '');
    li.dataset.slotVersion = version(item);
    const text = document.createElement('span'); text.className = 'workspace-slot-text';
    const name = document.createElement('strong'); name.textContent = label(item);
    const sub = document.createElement('span');
    sub.textContent = [kind[item.file_type] || 'Edit', costume(item), item.selected ? '' : 'Not in the mod'].filter(Boolean).join(' · ');
    text.append(name, sub);
    const restore = document.createElement('button');
    restore.className = 'at-btn at-btn--quiet workspace-restore'; restore.type = 'button'; restore.textContent = 'Restore';
    restore.setAttribute('aria-label', `Restore ${label(item)} to the original`);
    restore.onclick = () => restoreSlot(item);
    li.append(visual(item), text, restore);
    return li;
  }

  async function restoreSlot(item) {
    const origin = window.atelierProject?.();
    const viewport = window.AtelierViewport;
    if (viewport?.hasPendingEdits?.()) {
      $('workspace-dock-status').textContent = 'Save or revert your colour changes before restoring.';
      viewport.focusPendingEdits(); return;
    }
    if (!(await tray()?.restore(item.token))) return;
    if (origin!==window.atelierProject?.()) return;
    restored.add(item.game_rel);
    viewport?.reloadMaterials?.();
  }

  function render() {
    const active = window.atelierProject?.() || '';
    const animate = rendered && active === project;
    rendered = true;
    departures.forEach(dispose => dispose()); departures = [];
    if (active !== project) { project = active; restored.clear(); }
    const items = (tray()?.items() || []).sort((a, b) =>
      costume(a).localeCompare(costume(b)) || label(a).localeCompare(label(b)));
    const back = [...restored].filter(rel => items.some(item => item.game_rel === rel));
    if (back.length) { back.forEach(rel => restored.delete(rel)); window.AtelierViewport?.reloadMaterials?.(); }

    const list = $('workspace-dock-list'), focused = document.activeElement?.closest?.('.workspace-slot')?.dataset.token;
    const previous = new Map([...list.children].map(row => [row.dataset.token, {row, rect: row.getBoundingClientRect()}]));
    const added = [];
    list.replaceChildren(...items.map(item => {
      const before = animate ? previous.get(item.token) : undefined;
      if (before?.row.dataset.slotVersion === version(item)) return before.row;
      const next = slot(item);
      if (animate && (!before || before.row.dataset.savedVersion !== next.dataset.savedVersion)) added.push({row: next, fresh: !before});
      return next;
    }));
    if (focused) list.querySelector(`[data-token="${CSS.escape(focused)}"] .workspace-restore`)?.focus({preventScroll: true});

    const included = items.filter(item => item.selected).length, count = $('workspace-dock-count');
    if (window.AtelierPolish) window.AtelierPolish.count(count, items.length); else count.textContent = String(items.length);
    count.setAttribute('aria-label', `${items.length} edit${items.length === 1 ? '' : 's'}`);
    $('workspace-dock').classList.toggle('empty', !items.length);
    $('workspace-dock-status').textContent = !items.length ? 'Save a colour change and it collects here.'
      : included === items.length ? 'Everything here goes into your mod.'
      : `${included} of ${items.length} go into your mod. Choose which in Library’s Mod tray.`;
    $('workspace-review').disabled = !included;
    if (animate) {
      for (const [token, entry] of previous) if (!items.some(item => item.token === token))
        departures.push(window.AtelierPolish?.foldAway(entry.row, entry.rect, $('workspace')) || (() => {}));
      for (const {row, fresh} of added) window.AtelierPolish?.seat(row, fresh, {
        thumb: row.querySelector('.workspace-slot-visual'), parts: row.querySelectorAll('.workspace-slot-text, .workspace-restore'), horizontal: true,
      });
    }
  }

  $('workspace-review').onclick = () => tray()?.review();
  window.addEventListener('atelier:project-assets', render);
  render();
})();
