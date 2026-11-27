// Shared per-project colour palette for Material Editor and Model Studio.
(() => {
  'use strict';

  let cachedProject = '';
  let colours = [];
  let loaded = false;
  const mounts = new Set();

  function normalizeHex(value) {
    const clean = String(value || '').trim().toLowerCase();
    return /^#[0-9a-f]{6}$/.test(clean) ? clean : '';
  }

  async function load(project = window.atelierProject?.() || '') {
    if (!project) {
      cachedProject = '';
      colours = [];
      loaded = true;
      renderAll();
      return colours;
    }
    if (project === cachedProject && loaded) return colours;
    cachedProject = project;
    try {
      const response = await window.atelierFetch('/api/project/palette', {}, project);
      const data = await response.json();
      if (project !== cachedProject) return colours;
      colours = Array.isArray(data.palette) ? data.palette.map(normalizeHex).filter(Boolean) : [];
      loaded = true;
    } catch (_) {
      colours = [];
      loaded = true;
    }
    renderAll();
    return colours;
  }

  async function save(next, project = window.atelierProject?.() || '') {
    if (!project) return;
    const dedup = [];
    for (const item of next) {
      const hex = normalizeHex(item);
      if (hex && !dedup.includes(hex) && dedup.length < 16) dedup.push(hex);
    }
    colours = dedup;
    cachedProject = project;
    loaded = true;
    renderAll();
    try {
      const response = await window.atelierFetch('/api/project/palette', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ palette: dedup }),
      }, project);
      const data = await response.json();
      if (data.ok && Array.isArray(data.palette) && project === cachedProject) {
        colours = data.palette;
        renderAll();
      }
    } catch (_) {}
  }

  function add(hex) {
    const clean = normalizeHex(hex);
    if (!clean) return;
    if (colours.includes(clean)) {
      if (typeof window.toast === 'function') window.toast(`${clean.toUpperCase()} is already in the project palette`, 'info', 2500);
      return;
    }
    if (colours.length >= 16) {
      if (typeof window.toast === 'function') window.toast('Project palette holds up to 16 colours', 'warning', 3500);
      return;
    }
    save([...colours, clean]);
  }

  function remove(hex) {
    save(colours.filter(c => c !== hex));
  }

  function renderMount(entry) {
    if (!entry.host.isConnected) {
      mounts.delete(entry);
      return;
    }
    const { host, onPick, getCurrentHex } = entry;
    host.className = 'project-palette-bar';
    host.replaceChildren();

    const label = document.createElement('span');
    label.className = 'project-palette-label';
    label.textContent = 'Project palette';

    const list = document.createElement('div');
    list.className = 'project-palette-swatches';
    if (!colours.length) {
      const empty = document.createElement('span');
      empty.className = 'project-palette-empty';
      empty.textContent = 'Save colours here to reuse them across materials.';
      list.append(empty);
    } else {
      for (const hex of colours) {
        const wrap = document.createElement('span');
        wrap.className = 'project-palette-chip-wrap';
        const chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'project-palette-chip';
        chip.style.setProperty('--swatch-hex', hex);
        chip.title = `Apply ${hex.toUpperCase()}`;
        chip.setAttribute('aria-label', `Apply colour ${hex.toUpperCase()}`);
        chip.addEventListener('click', () => {
          if (typeof onPick === 'function') onPick(hex);
          else if (navigator.clipboard?.writeText) {
            navigator.clipboard.writeText(hex.toUpperCase()).catch(() => {});
            window.toast?.(`Copied ${hex.toUpperCase()}`, 'info', 2000);
          }
        });
        const del = document.createElement('button');
        del.type = 'button';
        del.className = 'project-palette-del';
        del.textContent = '×';
        del.title = `Remove ${hex.toUpperCase()}`;
        del.setAttribute('aria-label', `Remove colour ${hex.toUpperCase()}`);
        del.addEventListener('click', event => {
          event.stopPropagation();
          remove(hex);
        });
        wrap.append(chip, del);
        list.append(wrap);
      }
    }

    const addBtn = document.createElement('button');
    addBtn.type = 'button';
    addBtn.className = 'btn project-palette-add';
    addBtn.textContent = '+ Save colour';
    addBtn.title = 'Save the active colour into this project’s palette';
    addBtn.addEventListener('click', () => {
      const hex = normalizeHex(getCurrentHex?.());
      if (hex) add(hex);
      else window.toast?.('Select or edit a colour parameter first', 'info', 2500);
    });

    host.append(label, list, addBtn);
  }

  function renderAll() {
    for (const entry of [...mounts]) renderMount(entry);
  }

  function mount(host, { onPick, getCurrentHex } = {}) {
    if (!host) return;
    for (const existing of [...mounts]) {
      if (existing.host === host) mounts.delete(existing);
    }
    const entry = { host, onPick, getCurrentHex };
    mounts.add(entry);
    const project = window.atelierProject?.() || '';
    if (project !== cachedProject || !loaded) load(project);
    else renderMount(entry);
  }

  window.addEventListener('atelier:project-assets', event => {
    const project = event.detail?.project || '';
    if (project !== cachedProject) {
      loaded = false;
      load(project);
    }
  });

  window.AtelierProjectPalette = Object.freeze({ load, add, remove, mount, colours: () => [...colours] });
})();
