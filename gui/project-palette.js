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

  function hexToHsl(hex) {
    const clean = normalizeHex(hex);
    if (!clean) return null;
    const r = parseInt(clean.slice(1, 3), 16) / 255;
    const g = parseInt(clean.slice(3, 5), 16) / 255;
    const b = parseInt(clean.slice(5, 7), 16) / 255;
    const max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min;
    const l = (max + min) / 2;
    let h = 0, s = 0;
    if (d !== 0) {
      s = d / (1 - Math.abs(2 * l - 1));
      if (max === r) h = ((g - b) / d + (g < b ? 6 : 0)) * 60;
      else if (max === g) h = ((b - r) / d + 2) * 60;
      else h = ((r - g) / d + 4) * 60;
    }
    return { h, s: s * 100, l: l * 100 };
  }

  function hslToHex(h, s, l) {
    const hh = ((h % 360) + 360) % 360;
    const ss = Math.max(0, Math.min(100, s)) / 100;
    const ll = Math.max(0, Math.min(100, l)) / 100;
    const c = (1 - Math.abs(2 * ll - 1)) * ss;
    const x = c * (1 - Math.abs(((hh / 60) % 2) - 1));
    const m = ll - c / 2;
    let r = 0, g = 0, b = 0;
    if (hh < 60) [r, g, b] = [c, x, 0];
    else if (hh < 120) [r, g, b] = [x, c, 0];
    else if (hh < 180) [r, g, b] = [0, c, x];
    else if (hh < 240) [r, g, b] = [0, x, c];
    else if (hh < 300) [r, g, b] = [x, 0, c];
    else [r, g, b] = [c, 0, x];
    return '#' + [r, g, b].map(v => Math.round((v + m) * 255).toString(16).padStart(2, '0')).join('');
  }

  function buildHarmonies(hex) {
    const hsl = hexToHsl(hex);
    if (!hsl) return [];
    const { h, s, l } = hsl;
    const tint = hslToHex(h, Math.max(8, s * 0.92), Math.min(92, l + 18));
    const shade = hslToHex(h, Math.min(100, s * 1.05), Math.max(10, l - 18));
    return [
      { name: 'Complement', colours: [hslToHex(h + 180, s, l)] },
      { name: 'Analogous', colours: [hslToHex(h - 30, s, l), hslToHex(h + 30, s, l)] },
      { name: 'Triadic', colours: [hslToHex(h + 120, s, l), hslToHex(h + 240, s, l)] },
      { name: 'Tint & shade', colours: [tint, shade] },
    ];
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

    const harmonyBtn = document.createElement('button');
    harmonyBtn.type = 'button';
    harmonyBtn.className = 'btn project-palette-harmonies';
    harmonyBtn.textContent = 'Harmonies';
    harmonyBtn.title = 'Generate complementary, analogous, triadic and tint/shade colours from the active colour';
    harmonyBtn.setAttribute('aria-expanded', String(!!entry.harmoniesOpen));
    harmonyBtn.addEventListener('click', () => {
      entry.harmoniesOpen = !entry.harmoniesOpen;
      renderMount(entry);
    });
    actions.append(harmonyBtn);

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

    if (entry.harmoniesOpen) {
      const panel = document.createElement('div');
      panel.className = 'project-palette-harmony-panel';
      const baseHex = normalizeHex(getCurrentHex?.()) || colours[0] || '';
      const head = document.createElement('div');
      head.className = 'project-palette-harmony-head';
      if (baseHex) {
        const baseDot = document.createElement('span');
        baseDot.className = 'project-palette-harmony-base';
        baseDot.style.background = baseHex;
        const heading = document.createElement('span');
        heading.textContent = `Harmonies from ${baseHex.toUpperCase()} — click to apply, Shift+click to save`;
        const refresh = document.createElement('button');
        refresh.type = 'button';
        refresh.className = 'btn project-palette-harmony-refresh';
        refresh.textContent = 'Update';
        refresh.title = 'Recalculate harmonies from the active colour';
        refresh.addEventListener('click', () => renderMount(entry));
        head.append(baseDot, heading, refresh);
        panel.append(head);

        const groups = document.createElement('div');
        groups.className = 'project-palette-harmony-groups';
        for (const group of buildHarmonies(baseHex)) {
          const block = document.createElement('div');
          block.className = 'project-palette-harmony-group';
          const groupLabel = document.createElement('span');
          groupLabel.className = 'project-palette-harmony-name';
          groupLabel.textContent = group.name;
          const chips = document.createElement('div');
          chips.className = 'project-palette-harmony-chips';
          for (const hex of group.colours) {
            const chip = document.createElement('button');
            chip.type = 'button';
            chip.className = 'project-palette-chip';
            chip.style.setProperty('--swatch-hex', hex);
            chip.title = `${group.name}: ${hex.toUpperCase()} (click to apply, Shift+click to save)`;
            chip.setAttribute('aria-label', `${group.name} colour ${hex.toUpperCase()}`);
            chip.addEventListener('click', event => {
              if (event.shiftKey) { add(hex); return; }
              if (typeof onPick === 'function') {
                onPick(hex);
                renderMount(entry);
              } else if (navigator.clipboard?.writeText) {
                navigator.clipboard.writeText(hex.toUpperCase()).catch(() => {});
                window.toast?.(`Copied ${hex.toUpperCase()}`, 'info', 2000);
              }
            });
            chips.append(chip);
          }
          block.append(groupLabel, chips);
          groups.append(block);
        }
        panel.append(groups);
      } else {
        const empty = document.createElement('span');
        empty.className = 'project-palette-empty';
        empty.textContent = 'Select or edit a colour parameter first to generate harmonies.';
        head.append(empty);
        panel.append(head);
      }
      host.append(panel);
    }
  }

  function renderAll() {
    for (const entry of [...mounts]) renderMount(entry);
  }

  function mount(host, { onPick, getCurrentHex, getArtworkPath } = {}) {
    if (!host) return;
    for (const existing of [...mounts]) {
      if (existing.host === host || !existing.host.isConnected) mounts.delete(existing);
    }
    const entry = { host, onPick, getCurrentHex, getArtworkPath, harmoniesOpen: false };
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
