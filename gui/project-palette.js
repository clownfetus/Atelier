// Colours saved to the active project for reuse across materials.
(() => {
  'use strict';

  const projects = new Map();
  const mounts = new Set();
  const activeProject = () => window.atelierProject?.() || '';
  let visibleProject = '';

  function normalizeHex(value) {
    const clean = String(value || '').trim().toLowerCase();
    return /^#[0-9a-f]{6}$/.test(clean) ? clean : '';
  }

  async function readPalette(response) {
    const data = await response.json();
    if (!response.ok || !data.ok || !Array.isArray(data.palette)) throw Error(data.error || 'Project palette unavailable.');
    return data.palette.map(normalizeHex).filter(Boolean);
  }

  async function load(project = activeProject()) {
    if (!project) return [];
    if (!projects.has(project)) projects.set(project, { colours: null, reading: null, error: false, saving: false });
    const state = projects.get(project);
    if (state.colours) return state.colours;
    if (!state.reading) {
      state.error = false;
      state.reading = window.atelierFetch('/api/project/palette', {}, project).then(readPalette)
        .then(result => { state.colours = result; return result; })
        .catch(() => { state.error = true; return []; })
        .finally(() => { state.reading = null; if (project === activeProject()) renderAll(); });
      if (project === activeProject()) renderAll();
    }
    return state.reading;
  }

  async function save(next, project, state) {
    state.saving = true;
    renderAll();
    try {
      const response = await window.atelierFetch('/api/project/palette', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ palette: next }),
      }, project);
      state.colours = await readPalette(response);
    } catch (_) {
      if (project === activeProject()) window.toast?.('Could not save the project palette.', 'error');
    } finally {
      state.saving = false;
      if (project === activeProject()) renderAll();
    }
  }

  function add(hex) {
    const clean = normalizeHex(hex);
    const project = activeProject(), state = projects.get(project);
    if (!clean || !state?.colours || state.saving) return;
    const { colours } = state;
    if (colours.includes(clean)) {
      if (typeof window.toast === 'function') window.toast(`${clean.toUpperCase()} is already in the project palette`, 'info', 2500);
      return;
    }
    if (colours.length >= 16) {
      if (typeof window.toast === 'function') window.toast('Project palette holds up to 16 colours', 'warning', 3500);
      return;
    }
    save([...colours, clean], project, state);
  }

  function remove(hex) {
    const project = activeProject(), state = projects.get(project);
    if (!state?.colours || state.saving) return;
    save(state.colours.filter(c => c !== hex), project, state);
  }

  function renderMount(entry) {
    if (!entry.host.isConnected) {
      mounts.delete(entry);
      return;
    }
    const { host, onPick, getCurrentHex } = entry;
    const project = activeProject(), state = projects.get(project);
    const colours = state?.colours || [];
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
      empty.textContent = state?.error ? 'Project palette unavailable.' : state?.reading ? 'Loading project palette…'
        : 'Save colours here to reuse them across materials.';
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
        del.disabled = state.saving;
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
    addBtn.textContent = state?.error ? 'Retry palette' : state?.saving ? 'Saving palette…' : '+ Save colour';
    addBtn.title = 'Save the active colour into this project’s palette';
    addBtn.disabled = !state?.error && (!state?.colours || state.saving);
    addBtn.addEventListener('click', () => {
      if (state?.error) { load(project); return; }
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
      if (existing.host === host || !existing.host.isConnected) mounts.delete(existing);
    }
    const entry = { host, onPick, getCurrentHex };
    mounts.add(entry);
    const project = activeProject();
    renderMount(entry);
    load(project);
  }

  window.addEventListener('atelier:project-assets', event => {
    const project = event.detail?.project || '';
    if (project === visibleProject) return;
    if (!projects.get(visibleProject)?.saving) projects.delete(visibleProject);
    visibleProject = project;
    renderAll();
    if (mounts.size) load(project);
  });

  window.AtelierProjectPalette = Object.freeze({ load, add, remove, mount, colours: () => [...(projects.get(activeProject())?.colours || [])] });
})();
