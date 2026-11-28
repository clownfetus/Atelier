// Look Presets & One-Click Hero Colour Theme modal.
(() => {
  'use strict';

  let dialog = null;
  let opener = null;
  let looks = [];
  let targets = [];
  let activeLookId = '24k-gold';
  let swatches = { primary: '#e2b857', secondary: '#1c1d24', accent: '#fff0b3', energy: '#ffbe44' };
  let busy = false;

  const SWATCH_META = [
    ['primary', 'Primary'],
    ['secondary', 'Secondary'],
    ['accent', 'Accent / trim'],
    ['energy', 'Energy / VFX'],
  ];

  function ensureDialog() {
    if (dialog) return dialog;
    dialog = document.createElement('dialog');
    dialog.id = 'hero-theme-dialog';
    dialog.setAttribute('aria-labelledby', 'ht-title');
    dialog.innerHTML =
      '<div class="ht-head">' +
        '<div><h2 id="ht-title">Look presets &amp; Hero theme</h2><p>Pick a curated look or four swatches, review the matching assets, and apply in one step.</p></div>' +
        '<button type="button" class="sb-clear" id="ht-close" title="Close"><i data-lucide="x" size="16"></i></button>' +
      '</div>' +
      '<div class="ht-body">' +
        '<section><h3 class="ht-section-title">1. Choose a look preset</h3><div class="ht-looks-grid" id="ht-looks"></div></section>' +
        '<section>' +
          '<h3 class="ht-section-title">2. Fine-tune palette</h3>' +
          '<div class="ht-swatches" id="ht-swatches"></div>' +
          '<div class="ht-save-row">' +
            '<input type="text" id="ht-custom-name" maxlength="48" placeholder="Name these colours to save as a reusable look…" aria-label="Custom look name">' +
            '<button type="button" class="btn" id="ht-save-look">Save look</button>' +
          '</div>' +
        '</section>' +
        '<section>' +
          '<h3 class="ht-section-title" id="ht-targets-title">3. Review matching assets</h3>' +
          '<div class="ht-targets" id="ht-targets"></div>' +
        '</section>' +
      '</div>' +
      '<div class="ht-foot">' +
        '<span class="ht-status" id="ht-status" role="status"></span>' +
        '<div class="ht-foot-actions">' +
          '<button type="button" class="btn" id="ht-cancel">Cancel</button>' +
          '<button type="button" class="btn primary" id="ht-apply">Apply theme</button>' +
        '</div>' +
      '</div>';
    document.body.append(dialog);
    window.lucide?.createIcons({ nodes: [dialog] });

    const close = () => { if (!busy && dialog.open) dialog.close(); };
    dialog.querySelector('#ht-close').addEventListener('click', close);
    dialog.querySelector('#ht-cancel').addEventListener('click', close);
    dialog.addEventListener('click', e => { if (e.target === dialog) close(); });
    dialog.addEventListener('close', () => { if (opener?.isConnected) opener.focus(); });

    dialog.querySelector('#ht-save-look').addEventListener('click', saveLook);
    dialog.querySelector('#ht-apply').addEventListener('click', applySelected);
    return dialog;
  }

  function renderSwatches() {
    const host = dialog.querySelector('#ht-swatches');
    host.replaceChildren();
    for (const [key, label] of SWATCH_META) {
      const box = document.createElement('label');
      box.className = 'ht-swatch-field';
      const cap = document.createElement('span');
      cap.textContent = label;
      const row = document.createElement('div');
      row.className = 'ht-swatch-row';
      const input = document.createElement('input');
      input.type = 'color';
      input.value = swatches[key];
      input.setAttribute('aria-label', `${label} colour`);
      const hex = document.createElement('span');
      hex.className = 'ht-swatch-hex';
      hex.textContent = swatches[key];
      input.addEventListener('input', () => {
        swatches[key] = input.value.toLowerCase();
        hex.textContent = swatches[key];
        activeLookId = '';
        renderLooks();
      });
      row.append(input, hex);
      box.append(cap, row);
      host.append(box);
    }
  }

  function renderLooks() {
    const grid = dialog.querySelector('#ht-looks');
    grid.replaceChildren();
    for (const look of looks) {
      const card = document.createElement('button');
      card.type = 'button';
      card.className = 'ht-look-card';
      card.setAttribute('aria-pressed', String(look.id === activeLookId));
      const stripes = document.createElement('div');
      stripes.className = 'ht-stripes';
      for (const k of ['primary', 'secondary', 'accent', 'energy']) {
        const s = document.createElement('span');
        s.style.background = look[k];
        stripes.append(s);
      }
      const name = document.createElement('span');
      name.className = 'ht-look-name';
      name.textContent = look.name;
      const desc = document.createElement('span');
      desc.className = 'ht-look-desc';
      desc.textContent = look.description || '';
      card.append(stripes, name, desc);
      card.addEventListener('click', () => {
        activeLookId = look.id;
        swatches = { primary: look.primary, secondary: look.secondary, accent: look.accent, energy: look.energy };
        renderLooks();
        renderSwatches();
      });
      if (!look.builtin) {
        const del = document.createElement('button');
        del.type = 'button';
        del.className = 'ht-look-del';
        del.title = `Remove ${look.name}`;
        del.textContent = '×';
        del.addEventListener('click', async e => {
          e.stopPropagation();
          await deleteLook(look.id);
        });
        card.append(del);
      }
      grid.append(card);
    }
  }

  function syncApplyCount() {
    const checked = targets.filter(t => t.checked).length;
    const applyBtn = dialog.querySelector('#ht-apply');
    const title = dialog.querySelector('#ht-targets-title');
    if (title) title.textContent = `3. Review matching assets (${checked} of ${targets.length} selected)`;
    if (applyBtn) {
      applyBtn.disabled = busy || checked === 0;
      applyBtn.textContent = busy ? 'Applying…' : checked ? `Apply theme (${checked})` : 'Select an asset';
    }
  }

  function renderTargets() {
    const host = dialog.querySelector('#ht-targets');
    host.replaceChildren();
    if (!targets.length) {
      host.textContent = 'Open a costume in Recolour costume or edit at least one material, VFX or curve in this project to apply a theme.';
      syncApplyCount();
      return;
    }
    const groups = new Map();
    for (const item of targets) {
      if (!groups.has(item.group)) groups.set(item.group, []);
      groups.get(item.group).push(item);
    }
    for (const [groupName, items] of groups) {
      const wrap = document.createElement('div');
      const head = document.createElement('div');
      head.className = 'ht-group-head';
      head.textContent = groupName;
      wrap.append(head);
      for (const item of items) {
        const row = document.createElement('label');
        row.className = 'ht-target-row';
        const left = document.createElement('span');
        left.className = 'ht-target-left';
        const cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.checked = !!item.checked;
        cb.addEventListener('change', () => { item.checked = cb.checked; syncApplyCount(); });
        const name = document.createElement('span');
        name.className = 'ht-target-name';
        name.textContent = item.name;
        name.title = item.game_rel;
        left.append(cb, name);
        row.append(left);
        if (item.shared) {
          const tag = document.createElement('span');
          tag.className = 'ht-shared-tag';
          tag.textContent = 'Shared';
          tag.title = 'Shared across multiple costumes — unchecked by default';
          row.append(tag);
        }
        wrap.append(row);
      }
      host.append(wrap);
    }
    syncApplyCount();
  }

  async function saveLook() {
    const input = dialog.querySelector('#ht-custom-name');
    const name = input.value.trim();
    if (!name) { input.focus(); return; }
    try {
      const fetchFn = window.atelierFetch || fetch;
      const res = await fetchFn('/api/themes/looks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, ...swatches }),
      }).then(r => r.json());
      if (!res.ok) throw new Error(res.error || 'Could not save look.');
      looks = res.looks || looks;
      activeLookId = looks.find(l => l.name.toLowerCase() === name.toLowerCase())?.id || '';
      input.value = '';
      renderLooks();
      window.toast?.(`Saved look "${name}"`, 'success', 3000);
    } catch (err) {
      window.toast?.(err.message, 'warning', 4500);
    }
  }

  async function deleteLook(id) {
    try {
      const fetchFn = window.atelierFetch || fetch;
      const res = await fetchFn('/api/themes/looks/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id }),
      }).then(r => r.json());
      if (res.ok) {
        looks = res.looks || [];
        renderLooks();
      }
    } catch (_) {}
  }

  async function applySelected() {
    const chosen = targets.filter(t => t.checked);
    if (!chosen.length || busy) return;
    busy = true;
    const status = dialog.querySelector('#ht-status');
    status.textContent = `Applying theme to ${chosen.length} asset${chosen.length === 1 ? '' : 's'}…`;
    syncApplyCount();
    try {
      const fetchFn = window.atelierFetch || fetch;
      const res = await fetchFn('/api/themes/apply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ targets: chosen, theme: swatches }),
      }).then(r => r.json());
      if (!res.ok) throw new Error(res.error || 'Could not apply theme.');
      window.toast?.(`Applied theme to ${res.applied_count} asset${res.applied_count === 1 ? '' : 's'}`, 'success', 4500);
      window.loadSidebar?.();
      window.AtelierViewport?.reloadMaterials?.();
      dialog.close();
    } catch (err) {
      status.textContent = err.message;
      window.toast?.(err.message, 'warning', 5000);
    } finally {
      busy = false;
      syncApplyCount();
    }
  }

  async function open({ skinId = '', heroId = '' } = {}, triggerEl) {
    ensureDialog();
    opener = triggerEl || document.activeElement;
    const status = dialog.querySelector('#ht-status');
    status.textContent = 'Loading presets and matching assets…';
    dialog.querySelector('#ht-targets').textContent = 'Scanning costume materials and VFX…';
    if (!dialog.open) dialog.showModal();
    try {
      const fetchFn = window.atelierFetch || fetch;
      const [looksRes, propRes] = await Promise.all([
        fetchFn('/api/themes/looks').then(r => r.json()),
        fetchFn('/api/themes/propose', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ skin_id: skinId, hero_id: heroId }),
        }).then(r => r.json()),
      ]);
      looks = looksRes?.looks || [];
      targets = propRes?.targets || [];
      if (looks.length && !looks.some(l => l.id === activeLookId)) {
        activeLookId = looks[0].id;
        swatches = { primary: looks[0].primary, secondary: looks[0].secondary, accent: looks[0].accent, energy: looks[0].energy };
      }
      renderLooks();
      renderSwatches();
      renderTargets();
      status.textContent = 'All theme changes can be reverted individually in the Mod tray.';
    } catch (err) {
      status.textContent = err.message;
    }
  }

  document.getElementById('workspace-themes')?.addEventListener('click', event => open({}, event.currentTarget));

  window.AtelierHeroThemes = Object.freeze({ open });
})();
