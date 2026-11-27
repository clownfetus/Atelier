// Mod tray local filtering (search, type pills, hero chips) and saved export selection profiles.
(() => {
  'use strict';

  const TYPE_LABELS = {
    all: 'All',
    texture: 'Textures',
    material: 'Materials',
    mesh: 'Meshes',
    vfx: 'VFX',
    curve: 'Curves',
    text: 'Text',
    world: 'Worlds',
    other: 'Other',
  };

  let query = '';
  let type = 'all';
  let hero = '';
  let activeProject = '';
  let profilesOverlay = null;
  let profilesOpener = null;

  function itemType(item) {
    const ft = item?.file_type || 'other';
    return TYPE_LABELS[ft] ? ft : 'other';
  }

  function hasActiveFilter() {
    return !!(query.trim() || type !== 'all' || hero);
  }

  function clear() {
    query = '';
    type = 'all';
    hero = '';
    const input = document.getElementById('tray-search');
    if (input) input.value = '';
    syncHeroChips();
    window.renderSidebar?.();
  }

  function toggleHero(heroId) {
    hero = hero === heroId ? '' : (heroId || '');
    syncHeroChips();
    window.renderSidebar?.();
  }

  function syncHeroChips() {
    document.querySelectorAll('#mod-tray-heroes .tray-hero-chip').forEach(btn => {
      btn.setAttribute('aria-pressed', String(!!hero && btn.dataset.heroId === hero));
    });
  }

  function filter(allItems, libraryQuery = '') {
    let result = allItems;
    if (libraryQuery) {
      result = result.filter(i => window.AtelierLibraryTools?.matches(i, libraryQuery));
    }
    const q = query.trim().toLowerCase();
    if (q) {
      result = result.filter(i => window.AtelierLibraryTools?.matches(i, q));
    }
    if (type !== 'all') {
      result = result.filter(i => itemType(i) === type);
    }
    if (hero) {
      result = result.filter(i => window.AtelierCatalogueArt?.heroId(i) === hero);
    }
    return result;
  }

  function updateControls(allItems, visibleItems) {
    const bar = document.getElementById('tray-filter-bar');
    if (!bar) return;
    if (allItems.length < 2 && !hasActiveFilter()) {
      bar.hidden = true;
      return;
    }
    bar.hidden = false;
    const pills = bar.querySelector('.tray-type-pills');
    const types = new Set(allItems.map(itemType));
    if (type !== 'all' && !types.has(type)) type = 'all';
    if (pills) {
      if (types.size <= 1) {
        pills.hidden = true;
        pills.replaceChildren();
      } else {
        pills.hidden = false;
        const keys = ['all', ...Object.keys(TYPE_LABELS).filter(k => k !== 'all' && types.has(k))];
        const sig = keys.join(',') + ':' + type;
        if (pills.dataset.sig !== sig) {
          pills.dataset.sig = sig;
          pills.replaceChildren();
          for (const key of keys) {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'tray-type-pill';
            btn.dataset.type = key;
            btn.setAttribute('aria-pressed', String(type === key));
            btn.textContent = TYPE_LABELS[key];
            btn.addEventListener('click', () => {
              type = key;
              window.renderSidebar?.();
            });
            pills.append(btn);
          }
        }
      }
    }
    const summary = bar.querySelector('.tray-filter-summary');
    if (summary) {
      const filtered = hasActiveFilter();
      summary.hidden = !filtered;
      if (filtered) {
        summary.replaceChildren();
        const span = document.createElement('span');
        span.textContent = `Showing ${visibleItems.length} of ${allItems.length}`;
        const inc = document.createElement('button');
        inc.type = 'button'; inc.className = 'tray-filter-link'; inc.textContent = 'Include shown';
        inc.addEventListener('click', () => setShownSelection(visibleItems, true));
        const exc = document.createElement('button');
        exc.type = 'button'; exc.className = 'tray-filter-link'; exc.textContent = 'Exclude shown';
        exc.addEventListener('click', () => setShownSelection(visibleItems, false));
        const clr = document.createElement('button');
        clr.type = 'button'; clr.className = 'tray-filter-link'; clr.textContent = 'Clear';
        clr.addEventListener('click', clear);
        summary.append(span, inc, exc, clr);
      }
    }
    syncHeroChips();
  }

  function setShownSelection(items, selected) {
    for (const item of items) item.selected = selected;
    window.renderSidebar?.();
    window.saveSelection?.();
  }

  // ── Selection Profiles modal ────────────────────────────────────────────────
  function ensureProfilesOverlay() {
    if (profilesOverlay) return profilesOverlay;
    profilesOverlay = document.createElement('div');
    profilesOverlay.id = 'profiles-overlay';
    profilesOverlay.className = 'overlay';
    profilesOverlay.innerHTML = `
      <section class="modal profiles-modal" role="dialog" aria-modal="true" aria-labelledby="profiles-title" tabindex="-1">
        <div class="trash-head">
          <h2 id="profiles-title"><i data-lucide="layers" size="18" aria-hidden="true"></i> Selection profiles</h2>
          <button type="button" class="sb-clear" id="profiles-close" aria-label="Close selection profiles" title="Close"><i data-lucide="x" size="16" aria-hidden="true"></i></button>
        </div>
        <p class="trash-note">Save the current Mod tray checkboxes and mod filename as a reusable preset for this project.</p>
        <form class="profiles-create" id="profiles-form">
          <input id="profiles-name-input" type="text" maxlength="48" placeholder="Profile name (e.g. Body only, No VFX)" aria-label="New profile name" autocomplete="off">
          <button type="submit" class="btn primary">Save current</button>
        </form>
        <div class="profiles-list" id="profiles-list" aria-live="polite"></div>
        <div class="trash-foot">
          <span class="trash-status" id="profiles-status" role="status"></span>
          <div class="trash-foot-actions">
            <button type="button" class="btn" id="profiles-done">Close</button>
          </div>
        </div>
      </section>
    `;
    document.body.append(profilesOverlay);
    profilesOverlay.querySelector('#profiles-close').addEventListener('click', closeProfiles);
    profilesOverlay.querySelector('#profiles-done').addEventListener('click', closeProfiles);
    profilesOverlay.addEventListener('click', event => {
      if (event.target === profilesOverlay) closeProfiles();
    });
    profilesOverlay.addEventListener('keydown', event => {
      if (event.key === 'Escape') {
        event.preventDefault();
        event.stopPropagation();
        closeProfiles();
      }
    });
    profilesOverlay.querySelector('#profiles-form').addEventListener('submit', async event => {
      event.preventDefault();
      const input = profilesOverlay.querySelector('#profiles-name-input');
      const name = (input.value || '').trim();
      if (!name) { input.focus(); return; }
      const project = window.atelierProject?.() || '';
      if (!project) return;
      const items = Object.values(window.AtelierAssetEditors?.projectAssets?.() || []);
      const deselected = items.filter(i => !i.selected && i.game_rel).map(i => i.game_rel);
      const modName = document.getElementById('mod-name-input')?.value?.trim() || '';
      try {
        const res = await window.atelierFetch('/api/project/profiles', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name, deselected, mod_name: modName }),
        }, project);
        const data = await res.json();
        if (!data.ok) throw new Error(data.error || 'Could not save profile.');
        input.value = '';
        renderProfiles(data.profiles || {}, project);
        window.toast?.(`Saved profile “${name}”`, 'success');
      } catch (error) {
        window.toast?.(error.message, 'warning');
      }
    });
    if (window.lucide) window.lucide.createIcons({ nodes: [profilesOverlay] });
    return profilesOverlay;
  }

  function renderProfiles(profiles, project) {
    const list = profilesOverlay.querySelector('#profiles-list');
    const status = profilesOverlay.querySelector('#profiles-status');
    const entries = Object.entries(profiles || {});
    list.replaceChildren();
    status.textContent = entries.length ? `${entries.length} saved profile${entries.length === 1 ? '' : 's'}` : '';
    if (!entries.length) {
      const empty = document.createElement('div');
      empty.className = 'trash-empty';
      empty.innerHTML = '<strong>No selection profiles yet</strong><span>Save your current Mod tray checkboxes above to switch between mod variants quickly.</span>';
      list.append(empty);
      return;
    }
    const allAssets = window.AtelierAssetEditors?.projectAssets?.() || [];
    for (const [name, entry] of entries) {
      const card = document.createElement('div');
      card.className = 'profile-card';
      const desel = new Set(entry.deselected || []);
      const includedCount = allAssets.filter(a => !desel.has(a.game_rel)).length;
      const meta = document.createElement('div');
      meta.className = 'profile-meta';
      const title = document.createElement('div');
      title.className = 'profile-name';
      title.textContent = name;
      const sub = document.createElement('div');
      sub.className = 'profile-sub';
      sub.textContent = `${includedCount} of ${allAssets.length} included` + (entry.mod_name ? ` · ${entry.mod_name}` : '');
      meta.append(title, sub);

      const actions = document.createElement('div');
      actions.className = 'profile-actions';
      const applyBtn = document.createElement('button');
      applyBtn.type = 'button';
      applyBtn.className = 'btn primary';
      applyBtn.textContent = 'Apply';
      applyBtn.addEventListener('click', () => {
        if (typeof window.applySelectionProfile === 'function') {
          window.applySelectionProfile(name, entry);
        }
        closeProfiles();
      });
      const delBtn = document.createElement('button');
      delBtn.type = 'button';
      delBtn.className = 'btn danger';
      delBtn.textContent = 'Delete';
      delBtn.addEventListener('click', async () => {
        try {
          const res = await window.atelierFetch('/api/project/profiles/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name }),
          }, project);
          const data = await res.json();
          if (data.ok) renderProfiles(data.profiles || {}, project);
        } catch (error) {
          window.toast?.(error.message, 'warning');
        }
      });
      actions.append(applyBtn, delBtn);
      card.append(meta, actions);
      list.append(card);
    }
  }

  async function openProfiles() {
    profilesOpener = document.activeElement;
    const root = ensureProfilesOverlay();
    root.classList.add('active');
    root.querySelector('#profiles-name-input')?.focus();
    const project = window.atelierProject?.() || '';
    if (!project) return;
    try {
      const res = await window.atelierFetch('/api/project/profiles', {}, project);
      const data = await res.json();
      if (data.ok) renderProfiles(data.profiles || {}, project);
    } catch (_) {}
  }

  function closeProfiles() {
    if (!profilesOverlay) return;
    profilesOverlay.classList.remove('active');
    if (profilesOpener?.isConnected) profilesOpener.focus();
    profilesOpener = null;
  }

  function init() {
    const input = document.getElementById('tray-search');
    if (input) {
      input.addEventListener('input', () => {
        query = input.value;
        window.renderSidebar?.();
      });
    }
    window.addEventListener('atelier:project-assets', event => {
      const next = event.detail?.project || '';
      if (next !== activeProject) {
        activeProject = next;
        query = '';
        type = 'all';
        hero = '';
        if (input) input.value = '';
      }
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
  else init();

  window.AtelierTrayFilters = Object.freeze({
    filter,
    updateControls,
    toggleHero,
    clear,
    hasActiveFilter,
    selectedHero: () => hero,
    openProfiles,
    closeProfiles,
  });
})();
