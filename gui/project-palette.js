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

  function addMany(hexList) {
    const project = activeProject(), state = projects.get(project);
    if (!state?.colours || state.saving) return 0;
    const existing = new Set(state.colours);
    const fresh = [];
    for (const raw of hexList || []) {
      const clean = normalizeHex(raw);
      if (clean && !existing.has(clean) && state.colours.length + fresh.length < 16) {
        existing.add(clean);
        fresh.push(clean);
      }
    }
    if (!fresh.length) {
      window.toast?.(state.colours.length >= 16 ? 'Project palette holds up to 16 colours' : 'Those costume colours are already in the project palette', 'info', 2600);
      return 0;
    }
    save([...state.colours, ...fresh], project, state);
    window.toast?.(`Added ${fresh.length} costume colour${fresh.length === 1 ? '' : 's'} to project palette`, 'success', 2600);
    return fresh.length;
  }

  function artworkSourcesFor(path) {
    if (!path) return [];
    const desc = window.AtelierCatalogueArt?.describe(path);
    const hero = desc?.char_id || window.AtelierCatalogueArt?.heroId(path) || '';
    const skin = desc?.skin_id || '';
    if (!hero && !skin) return [];
    const enc = encodeURIComponent;
    return [
      skin && '/api/catalogue/icon/' + enc(skin),
      skin && '/api/catalogue/thumbnail/' + enc(skin),
      hero && '/api/catalogue/hero/' + enc(hero) + '/avatar',
      hero && '/api/catalogue/hero/' + enc(hero) + '/story',
    ].filter(Boolean);
  }

  function sampleFromArtwork(sources) {
    return new Promise(resolve => {
      const urls = [...new Set(sources.filter(Boolean))];
      const img = new Image();
      img.decoding = 'async';
      const next = () => {
        if (!urls.length) { resolve([]); return; }
        img.src = urls.shift();
      };
      img.onload = () => {
        let colours = [];
        try {
          const sampled = window.AtelierPolish?.samplePalette?.(img) || [];
          colours = sampled.map(normalizeHex).filter(Boolean).slice(0, 5);
          if (!colours.length) {
            const single = normalizeHex(window.AtelierPolish?.accent?.(img));
            if (single) colours = [single];
          }
        } catch (_) {}
        if (colours.length) resolve(colours);
        else next();
      };
      img.onerror = next;
      next();
    });
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
    const { host, onPick, getCurrentHex, getArtworkPath } = entry;
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

    const actions = document.createElement('div');
    actions.className = 'project-palette-actions';
    const sources = artworkSourcesFor(getArtworkPath?.());
    if (sources.length) {
      const sampleBtn = document.createElement('button');
      sampleBtn.type = 'button';
      sampleBtn.className = 'btn project-palette-sample';
      sampleBtn.textContent = 'Sample costume art';
      sampleBtn.title = 'Extract colours from this costume’s artwork into the project palette';
      sampleBtn.disabled = !!state?.error || !state?.colours || state.saving;
      sampleBtn.addEventListener('click', async () => {
        if (sampleBtn.disabled) return;
        sampleBtn.disabled = true;
        const sampled = await sampleFromArtwork(sources);
        if (sampled.length) addMany(sampled);
        else {
          window.toast?.('No costume artwork available to sample right now', 'info', 2500);
          renderAll();
        }
      });
      actions.append(sampleBtn);
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
    actions.append(addBtn);

    host.append(label, list, actions);
  }

  function renderAll() {
    for (const entry of [...mounts]) renderMount(entry);
  }

  function mount(host, { onPick, getCurrentHex, getArtworkPath } = {}) {
    if (!host) return;
    for (const existing of [...mounts]) {
      if (existing.host === host || !existing.host.isConnected) mounts.delete(existing);
    }
    const entry = { host, onPick, getCurrentHex, getArtworkPath };
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
