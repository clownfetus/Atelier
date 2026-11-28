// Installed Mods Drawer & Clean-Test Sandbox popover beside Launch game.
(() => {
  'use strict';

  const trigger = document.getElementById('mods-drawer-btn');
  if (!trigger) return;

  let panel = null;
  let open = false;
  let state = null;
  let filterText = '';
  let busy = false;

  const currentModName = () => (document.getElementById('mod-name-input')?.value || '').trim();

  function formatBytes(bytes) {
    if (!bytes || bytes < 1024) return `${bytes || 0} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function updateDot(cleanTest) {
    const dot = trigger.querySelector('.mods-clean-dot');
    if (dot) dot.hidden = !cleanTest?.active;
    trigger.title = cleanTest?.active
      ? `Installed mods (Clean-test active: ${cleanTest.paused_ids?.length || 0} paused)`
      : 'Installed mods & clean-test mode';
  }

  function ensurePanel() {
    if (panel) return panel;
    panel = document.createElement('section');
    panel.id = 'mods-drawer-panel';
    panel.setAttribute('aria-label', 'Installed mods');
    panel.hidden = true;
    panel.innerHTML =
      '<div class="md-header">' +
        '<div class="md-title-wrap"><h2 class="md-title">Installed mods</h2><span class="md-count" id="md-count"></span></div>' +
        '<div class="md-head-actions">' +
          '<button type="button" class="md-icon-btn" id="md-refresh" title="Refresh installed mods" aria-label="Refresh installed mods"><i data-lucide="refresh-cw" size="14"></i></button>' +
          '<button type="button" class="md-icon-btn" id="md-open-folder" title="Open mods folder" aria-label="Open mods folder"><i data-lucide="folder-open" size="14"></i></button>' +
        '</div>' +
      '</div>' +
      '<div class="md-notice" id="md-notice" role="status" hidden></div>' +
      '<div class="md-sandbox" id="md-sandbox" hidden></div>' +
      '<div class="md-search-wrap" id="md-search-wrap" hidden>' +
        '<input type="search" class="md-search" id="md-search" placeholder="Filter installed mods…" aria-label="Filter installed mods">' +
      '</div>' +
      '<div class="md-list" id="md-list"></div>';
    document.body.append(panel);
    window.lucide?.createIcons({ nodes: [panel] });

    panel.querySelector('#md-refresh').addEventListener('click', () => refresh());
    panel.querySelector('#md-open-folder').addEventListener('click', async () => {
      try {
        const res = await fetch('/api/mods/open_folder', { method: 'POST' }).then(r => r.json());
        if (!res.ok) window.toast?.(res.error || 'Could not open the mods folder.', 'warning');
      } catch (err) { window.toast?.(err.message, 'error'); }
    });
    panel.querySelector('#md-search').addEventListener('input', event => {
      filterText = event.target.value.trim().toLowerCase();
      render();
    });
    return panel;
  }

  function positionPanel() {
    if (!panel) return;
    const rect = trigger.getBoundingClientRect();
    const right = Math.max(12, window.innerWidth - rect.right);
    panel.style.top = `${Math.round(rect.bottom + 6)}px`;
    panel.style.right = `${Math.round(right)}px`;
  }

  async function refresh() {
    ensurePanel();
    const list = panel.querySelector('#md-list');
    if (!state) list.innerHTML = '<div class="md-empty">Checking installed mods…</div>';
    try {
      const q = new URLSearchParams({ current_mod: currentModName() });
      const data = await fetch(`/api/mods/installed?${q}`).then(r => r.json());
      state = data;
      updateDot(data.clean_test);
      render();
    } catch (err) {
      list.innerHTML = `<div class="md-empty">Could not read your mods folder: ${err.message}</div>`;
    }
  }

  async function toggleOne(modId, enabled) {
    if (busy) return;
    busy = true;
    try {
      const res = await fetch('/api/mods/toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: modId, enabled }),
      }).then(r => r.json());
      if (!res.ok) {
        window.toast?.(res.error || 'Could not switch that mod.', 'warning', 5000);
      }
    } catch (err) {
      window.toast?.(err.message, 'error', 5000);
    } finally {
      busy = false;
      await refresh();
    }
  }

  async function toggleCleanTest(enable) {
    if (busy) return;
    busy = true;
    try {
      const res = await fetch('/api/mods/clean_test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enable, keep_mod: currentModName() }),
      }).then(r => r.json());
      if (!res.ok) {
        window.toast?.(res.error || 'Could not update clean-test mode.', 'warning', 5000);
      } else if (enable) {
        window.toast?.(`Clean-test active · ${res.paused || 0} other mod${res.paused === 1 ? '' : 's'} paused`, 'success', 4000);
      } else {
        window.toast?.(`Restored ${res.restored || 0} paused mod${res.restored === 1 ? '' : 's'}`, 'success', 4000);
      }
    } catch (err) {
      window.toast?.(err.message, 'error', 5000);
    } finally {
      busy = false;
      await refresh();
    }
  }

  function render() {
    if (!panel || !state) return;
    const countEl = panel.querySelector('#md-count');
    const notice = panel.querySelector('#md-notice');
    const sandbox = panel.querySelector('#md-sandbox');
    const searchWrap = panel.querySelector('#md-search-wrap');
    const list = panel.querySelector('#md-list');

    countEl.textContent = state.configured ? `${state.enabled_count} of ${state.total_count} active` : 'Not set';
    notice.hidden = !state.game_running;
    if (state.game_running) notice.textContent = 'Close Marvel Rivals before switching installed mods.';

    if (!state.configured || !state.exists) {
      sandbox.hidden = true;
      searchWrap.hidden = true;
      list.innerHTML = '';
      const empty = document.createElement('div');
      empty.className = 'md-empty';
      empty.textContent = state.configured
        ? 'Your configured mods folder does not exist yet. Export and install a mod to create it.'
        : 'Set your Marvel Rivals mods folder in Settings to manage installed mods here.';
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'btn';
      btn.textContent = 'Open Settings';
      btn.addEventListener('click', () => { closeDrawer(); window.openPaths?.(); });
      empty.append(btn);
      list.append(empty);
      return;
    }

    const clean = state.clean_test;
    const mods = state.mods || [];
    sandbox.hidden = mods.length < 2 && !clean?.active;
    sandbox.classList.toggle('is-active', !!clean?.active);
    sandbox.replaceChildren();
    if (!sandbox.hidden) {
      const copy = document.createElement('div');
      copy.className = 'md-sandbox-copy';
      const title = document.createElement('strong');
      const sub = document.createElement('small');
      const action = document.createElement('button');
      action.type = 'button';
      action.className = clean?.active ? 'btn primary' : 'btn';
      action.disabled = !!state.game_running || busy;
      if (clean?.active) {
        const pausedCount = (clean.paused_ids || []).length;
        title.textContent = 'Clean-test mode active';
        sub.textContent = `${pausedCount} other mod${pausedCount === 1 ? '' : 's'} paused${clean.keep_mod ? ` · testing ${clean.keep_mod}` : ''}.`;
        action.textContent = 'Restore all';
        action.addEventListener('click', () => toggleCleanTest(false));
      } else {
        const modLabel = currentModName();
        title.textContent = 'Test this mod alone';
        sub.textContent = modLabel
          ? `Pauses other mods so you can test ${modLabel}, then restores them in one click.`
          : 'Temporarily pauses other enabled mods, then restores them in one click.';
        action.textContent = 'Pause others';
        action.addEventListener('click', () => toggleCleanTest(true));
      }
      copy.append(title, sub);
      sandbox.append(copy, action);
    }

    searchWrap.hidden = mods.length < 6;
    const visible = filterText
      ? mods.filter(m => m.name.toLowerCase().includes(filterText) || (m.folder || '').toLowerCase().includes(filterText))
      : mods;

    list.replaceChildren();
    if (!visible.length) {
      const empty = document.createElement('div');
      empty.className = 'md-empty';
      empty.textContent = mods.length ? 'No installed mods match that filter.' : 'No mods found in your ~mods folder yet.';
      list.append(empty);
      return;
    }

    for (const mod of visible) {
      const row = document.createElement('div');
      row.className = 'md-row' + (mod.enabled ? '' : ' is-disabled');

      const meta = document.createElement('div');
      meta.className = 'md-meta';
      const nameLine = document.createElement('div');
      nameLine.className = 'md-name-line';
      const name = document.createElement('span');
      name.className = 'md-name';
      name.textContent = mod.name;
      name.title = mod.id;
      nameLine.append(name);
      if (mod.is_current) {
        const pill = document.createElement('span');
        pill.className = 'md-pill';
        pill.textContent = 'This project';
        nameLine.append(pill);
      }
      const sub = document.createElement('span');
      sub.className = 'md-sub';
      sub.textContent = `${mod.kind} · ${formatBytes(mod.size_bytes)}${mod.folder ? ` · ${mod.folder}` : ''}`;
      meta.append(nameLine, sub);

      const sw = document.createElement('label');
      sw.className = 'switch';
      sw.title = mod.enabled ? `Disable ${mod.name}` : `Enable ${mod.name}`;
      const input = document.createElement('input');
      input.type = 'checkbox';
      input.checked = !!mod.enabled;
      input.disabled = !!state.game_running || busy;
      input.setAttribute('aria-label', `${mod.enabled ? 'Disable' : 'Enable'} ${mod.name}`);
      input.addEventListener('change', () => toggleOne(mod.id, input.checked));
      const track = document.createElement('span');
      track.className = 'switch-track';
      sw.append(input, track);

      row.append(meta, sw);
      list.append(row);
    }
  }

  function openDrawer() {
    ensurePanel();
    if (open) return;
    open = true;
    trigger.setAttribute('aria-expanded', 'true');
    positionPanel();
    panel.hidden = false;
    window.AtelierMotion?.unfold?.(panel, 'top');
    refresh();
  }

  function closeDrawer() {
    if (!open || !panel) return;
    open = false;
    trigger.setAttribute('aria-expanded', 'false');
    if (window.AtelierMotion?.fold) {
      window.AtelierMotion.fold(panel, 'top', () => { if (!open) panel.hidden = true; });
    } else {
      panel.hidden = true;
    }
  }

  trigger.addEventListener('click', event => {
    event.stopPropagation();
    if (open) closeDrawer(); else openDrawer();
  });

  document.addEventListener('click', event => {
    if (!open || !panel) return;
    if (panel.contains(event.target) || trigger.contains(event.target)) return;
    closeDrawer();
  });

  document.addEventListener('keydown', event => {
    if (open && event.key === 'Escape') {
      event.preventDefault();
      closeDrawer();
      trigger.focus();
    }
  });

  window.addEventListener('resize', () => { if (open) positionPanel(); });

  // Quietly check clean-test badge on load so the dot stays visible across restarts.
  fetch('/api/mods/installed').then(r => r.json()).then(d => updateDot(d?.clean_test)).catch(() => {});

  window.AtelierModsDrawer = Object.freeze({ open: openDrawer, close: closeDrawer, refresh });
})();
