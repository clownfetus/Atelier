// Command Palette (Ctrl+K) and Keyboard Shortcuts reference sheet (?).
(() => {
  'use strict';

  let cmdOverlay = null;
  let shortcutsOverlay = null;
  let cmdOpener = null;
  let shortcutsOpener = null;
  let filtered = [];
  let activeIndex = 0;

  const SHORTCUT_GROUPS = [
    {
      title: 'Library & navigation',
      items: [
        ['Command palette', 'Ctrl+K'],
        ['Search heroes, skins and assets', 'Ctrl+F'],
        ['Quick preview selected card', 'Space / P'],
        ['Open context menu on focused card', 'Shift+F10'],
        ['Go to parent folder', 'Backspace / Alt+↑'],
        ['History back / forward', 'Alt+← / Alt+→'],
        ['Keyboard shortcuts', '?'],
      ],
    },
    {
      title: 'Editors',
      items: [
        ['Save material, VFX or bulk edits', 'Ctrl+S'],
        ['Undo parameter edit', 'Ctrl+Z'],
        ['Redo parameter edit', 'Ctrl+Shift+Z'],
        ['Dismiss supported dialogs and previews', 'Escape'],
      ],
    },
    {
      title: 'Mod tray',
      items: [
        ['Mark multiple edits for delete', 'Ctrl+Click'],
        ['Mark range of edits', 'Shift+Click'],
        ['Delete edit without confirmation', 'Shift+Click ×'],
      ],
    },
    {
      title: 'Model Studio & Assembly',
      items: [
        ['Fit model to view', 'F'],
        ['Toggle wireframe', 'W'],
        ['Toggle floor grid', 'G'],
        ['Front / Right / Top camera', '1 / 3 / 7'],
        ['Frame clicked part', 'Double-click'],
      ],
    },
  ];

  function staticCommands() {
    const project = window.atelierProject?.() || '';
    const search = document.querySelector(
      'body:not([data-page="workspace"]) #search-input, #workspace-choice:not([hidden]) #workspace-search, #viewport-overlay.mounted.active #viewport-material-search',
    );
    const cmds = [
      { group: 'Navigation', icon: 'grid-2x2', label: 'Open Library', keywords: 'assets home browse', action: () => document.getElementById('page-library')?.click() },
      { group: 'Navigation', icon: 'palette', label: 'Open Recolour costume workspace', keywords: 'workspace skin studio', action: () => document.getElementById('page-workspace')?.click() },
      { group: 'Navigation', icon: 'folder-kanban', label: 'Switch project…', keywords: 'projects open create', action: () => window.openProjectPicker?.() },
      { group: 'Navigation', icon: 'search', label: 'Focus search', shortcut: document.body.dataset.page === 'workspace' ? '' : 'Ctrl+F', keywords: 'find filter', disabled: () => !search?.getClientRects().length, action: () => { search.focus(); search.select(); } },
      { group: 'Navigation', icon: 'refresh-cw', label: 'Refresh library view', keywords: 'reload grid', action: () => window.renderGrid?.() },
      { group: 'Mod tray', icon: 'download', label: 'Review & build mod…', keywords: 'export install pak', disabled: () => document.getElementById('install-btn')?.disabled, action: () => document.getElementById('install-btn')?.click() },
      { group: 'Mod tray', icon: 'plus', label: 'Add custom asset…', keywords: 'new texture mesh material', action: () => document.getElementById('add-asset-open')?.click() },
      { group: 'Mod tray', icon: 'layers', label: 'Selection profiles…', keywords: 'presets variants checkboxes', disabled: () => !project, action: () => window.AtelierTrayFilters?.openProfiles() },
      { group: 'Mod tray', icon: 'trash-2', label: 'Recently deleted (Project trash)…', keywords: 'trash undo restore recover', disabled: () => !project, action: () => window.AtelierTrash?.open() },
      { group: 'Mod tray', icon: 'sparkles', label: 'Process S maps', keywords: 'specular diffuse blend', disabled: () => document.getElementById('process-s-maps')?.disabled || document.getElementById('process-s-maps-wrap')?.hidden, action: () => document.getElementById('process-s-maps')?.click() },
      { group: 'Tools', icon: 'folder-open', label: 'Open a mod…', keywords: 'inspect pak utoc zip', action: () => window.AtelierModOpen?.open() },
      { group: 'Tools', icon: 'wrench', label: 'Repatch a mod…', keywords: 'fix repair broken patch', action: () => window.openRepatcher?.() },
      { group: 'Tools', icon: 'code-2', label: 'Shader Studio…', keywords: 'dxil disassemble hlsl', action: () => window.openShaderStudio?.() },
      { group: 'Tools', icon: 'sliders-horizontal', label: 'Settings…', keywords: 'appearance theme palette paths blender motion', action: () => window.openPaths?.() },
      { group: 'Tools', icon: 'folder', label: 'Show project folder in Explorer', keywords: 'files folder open', action: () => window.atelierFetch?.('/api/open_projects_folder') },
      { group: 'Tools', icon: 'external-link', label: 'Open export folder', keywords: 'exported mods paks', action: () => window.atelierFetch?.('/api/open_export_folder') },
      { group: 'Tools', icon: 'book-open', label: 'What’s new…', keywords: 'changelog release notes', action: () => window.AtelierChangelog?.show() },
      { group: 'Tools', icon: 'keyboard', label: 'Keyboard shortcuts…', shortcut: '?', keywords: 'keys hotkeys help', action: () => openShortcuts() },
    ];
    const assets = window.AtelierAssetEditors?.projectAssets?.() || [];
    for (const item of assets) {
      cmds.push({
        group: 'Mod tray assets',
        asset: item,
        label: item.name || item.game_rel,
        sub: item.game_rel || '',
        keywords: `${item.file_type || ''} ${item.char_name || ''} ${item.skin_name || ''} ${item.game_rel || ''}`,
        action: () => window.handleImportedFileAction?.(item),
      });
    }
    return cmds.filter(c => !c.disabled?.());
  }

  function ensureCmdOverlay() {
    if (cmdOverlay) return cmdOverlay;
    cmdOverlay = document.createElement('div');
    cmdOverlay.id = 'command-overlay';
    cmdOverlay.className = 'overlay';
    cmdOverlay.innerHTML = `
      <section class="modal cmd-modal" role="dialog" aria-modal="true" aria-label="Command palette" tabindex="-1">
        <div class="cmd-search-bar">
          <i data-lucide="search" size="16" aria-hidden="true"></i>
          <input id="cmd-input" type="search" role="combobox" aria-expanded="true" aria-controls="cmd-list" aria-autocomplete="list" placeholder="Type a command or edited asset…" aria-label="Search commands" autocomplete="off" spellcheck="false">
          <span class="cmd-kbd">Esc</span>
        </div>
        <div class="cmd-list" id="cmd-list" role="listbox" aria-label="Commands"></div>
        <div class="cmd-footer" aria-hidden="true">
          <span><kbd class="cmd-kbd">↑↓</kbd> Navigate</span>
          <span><kbd class="cmd-kbd">↵</kbd> Run</span>
          <span><kbd class="cmd-kbd">Esc</kbd> Close</span>
        </div>
      </section>
    `;
    document.body.append(cmdOverlay);
    const input = cmdOverlay.querySelector('#cmd-input');
    input.addEventListener('input', () => renderCommands(input.value));
    cmdOverlay.addEventListener('click', event => {
      if (event.target === cmdOverlay) closePalette();
    });
    cmdOverlay.addEventListener('keydown', event => {
      if (event.defaultPrevented || event.isComposing) return;
      if (event.key === 'Escape') {
        event.preventDefault();
        event.stopPropagation();
        closePalette();
      } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        if (!filtered.length) return;
        const step = event.key === 'ArrowDown' ? 1 : -1;
        activeIndex = (activeIndex + step + filtered.length) % filtered.length;
        syncActive();
        if (event.target !== input) document.getElementById(`cmd-option-${activeIndex}`)?.focus();
      } else if (event.key === 'Enter' && event.target === input) {
        event.preventDefault();
        const chosen = filtered[activeIndex];
        if (chosen) { closePalette(); chosen.action?.(); }
      }
    });
    if (window.lucide) window.lucide.createIcons({ nodes: [cmdOverlay] });
    return cmdOverlay;
  }

  function syncActive() {
    const buttons = [...cmdOverlay.querySelectorAll('.cmd-item')];
    buttons.forEach((btn, idx) => {
      const on = idx === activeIndex;
      btn.classList.toggle('is-active', on);
      btn.setAttribute('aria-selected', String(on));
    });
    const selected = buttons[activeIndex];
    const input = cmdOverlay.querySelector('#cmd-input');
    if (selected) {
      input.setAttribute('aria-activedescendant', selected.id);
      selected.scrollIntoView({ block: 'nearest' });
    } else input.removeAttribute('aria-activedescendant');
  }

  function renderCommands(rawQuery = '') {
    const list = cmdOverlay.querySelector('#cmd-list');
    const q = rawQuery.trim().toLowerCase();
    const terms = q ? q.split(/\s+/).filter(Boolean) : [];
    const all = staticCommands();
    filtered = terms.length
      ? all.filter(cmd => {
          const hay = `${cmd.group} ${cmd.label} ${cmd.sub || ''} ${cmd.keywords || ''}`.toLowerCase();
          return terms.every(t => hay.includes(t));
        })
      : all.filter(cmd => cmd.group !== 'Mod tray assets').concat(all.filter(cmd => cmd.group === 'Mod tray assets').slice(0, 8));
    activeIndex = 0;
    list.replaceChildren();
    if (!filtered.length) {
      const empty = document.createElement('div');
      empty.className = 'cmd-empty';
      empty.textContent = 'No matching commands or assets.';
      list.append(empty);
      syncActive();
      return;
    }
    let lastGroup = '';
    filtered.forEach((cmd, index) => {
      if (cmd.group !== lastGroup) {
        lastGroup = cmd.group;
        const heading = document.createElement('div');
        heading.className = 'cmd-group-label';
        heading.textContent = cmd.group;
        list.append(heading);
      }
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'cmd-item';
      btn.id = `cmd-option-${index}`;
      btn.setAttribute('role', 'option');
      const main = document.createElement('span');
      main.className = 'cmd-item-main';
      const lead = document.createElement('span');
      lead.className = 'cmd-item-icon';
      lead.setAttribute('aria-hidden', 'true');
      if (cmd.asset) {
        const chip = window.AtelierCatalogueArt?.identityChip(cmd.asset);
        if (chip) {
          chip.classList.add('cmd-item-art');
          lead.append(chip);
        } else {
          const dot = document.createElement('span');
          dot.className = 'cmd-item-dot';
          dot.dataset.fileType = cmd.asset.file_type || '';
          lead.append(dot);
        }
      } else if (cmd.icon) {
        const icon = document.createElement('i');
        icon.setAttribute('data-lucide', cmd.icon);
        icon.setAttribute('size', '14');
        lead.append(icon);
      }
      const copy = document.createElement('span');
      copy.className = 'cmd-item-copy';
      const label = document.createElement('span');
      label.className = 'cmd-item-label';
      label.textContent = cmd.label;
      copy.append(label);
      if (cmd.sub) {
        const sub = document.createElement('span');
        sub.className = 'cmd-item-sub';
        sub.textContent = cmd.sub;
        copy.append(sub);
      }
      main.append(lead, copy);
      btn.append(main);
      if (cmd.shortcut) {
        const kbd = document.createElement('span');
        kbd.className = 'cmd-kbd';
        kbd.textContent = cmd.shortcut;
        btn.append(kbd);
      }
      function selectOption() {
        if (activeIndex === index) return;
        activeIndex = index;
        syncActive();
      }
      btn.addEventListener('focus', selectOption);
      btn.addEventListener('mouseenter', () => {
        if (!list.contains(document.activeElement)) selectOption();
      });
      btn.addEventListener('click', () => { closePalette(); cmd.action?.(); });
      list.append(btn);
    });
    if (window.lucide) window.lucide.createIcons({ nodes: [list] });
    syncActive();
  }

  function openPalette() {
    cmdOpener = document.activeElement;
    const root = ensureCmdOverlay();
    root.classList.add('active');
    const input = root.querySelector('#cmd-input');
    input.value = '';
    renderCommands('');
    input.focus();
  }

  function closePalette() {
    if (!cmdOverlay) return;
    cmdOverlay.classList.remove('active');
    if (cmdOpener?.isConnected) cmdOpener.focus();
    cmdOpener = null;
  }

  function ensureShortcutsOverlay() {
    if (shortcutsOverlay) return shortcutsOverlay;
    shortcutsOverlay = document.createElement('div');
    shortcutsOverlay.id = 'shortcuts-overlay';
    shortcutsOverlay.className = 'overlay';
    const sections = SHORTCUT_GROUPS.map(group => `
      <div class="shortcuts-section">
        <h3>${group.title}</h3>
        <ul class="shortcuts-list">
          ${group.items.map(([label, key]) => `<li><span>${label}</span><span class="cmd-kbd">${key}</span></li>`).join('')}
        </ul>
      </div>
    `).join('');
    shortcutsOverlay.innerHTML = `
      <section class="modal shortcuts-modal" role="dialog" aria-modal="true" aria-labelledby="shortcuts-title" tabindex="-1">
        <div class="trash-head">
          <h2 id="shortcuts-title">Keyboard shortcuts</h2>
          <button type="button" class="sb-clear" id="shortcuts-close" aria-label="Close keyboard shortcuts" title="Close"><i data-lucide="x" size="16" aria-hidden="true"></i></button>
        </div>
        <div class="shortcuts-grid">${sections}</div>
        <div class="trash-foot">
          <span class="trash-status">Press Ctrl+K to search commands.</span>
          <div class="trash-foot-actions">
            <button type="button" class="btn" id="shortcuts-done">Close</button>
          </div>
        </div>
      </section>
    `;
    document.body.append(shortcutsOverlay);
    shortcutsOverlay.querySelector('#shortcuts-close').addEventListener('click', closeShortcuts);
    shortcutsOverlay.querySelector('#shortcuts-done').addEventListener('click', closeShortcuts);
    shortcutsOverlay.addEventListener('click', event => {
      if (event.target === shortcutsOverlay) closeShortcuts();
    });
    shortcutsOverlay.addEventListener('keydown', event => {
      if (event.key === 'Escape' && !event.defaultPrevented) {
        event.preventDefault();
        event.stopPropagation();
        closeShortcuts();
      }
    });
    if (window.lucide) window.lucide.createIcons({ nodes: [shortcutsOverlay] });
    return shortcutsOverlay;
  }

  function openShortcuts() {
    shortcutsOpener = document.activeElement;
    const root = ensureShortcutsOverlay();
    root.classList.add('active');
    root.querySelector('.shortcuts-modal')?.focus();
  }

  function closeShortcuts() {
    if (!shortcutsOverlay) return;
    shortcutsOverlay.classList.remove('active');
    if (shortcutsOpener?.isConnected) shortcutsOpener.focus();
    shortcutsOpener = null;
  }

  document.addEventListener('keydown', event => {
    if (event.defaultPrevented || event.isComposing) return;
    const otherSurface = '.overlay.active:not(.mounted), dialog[open], #ctx-menu.active';
    if ((event.ctrlKey || event.metaKey) && !event.altKey && !event.shiftKey && event.key.toLowerCase() === 'k') {
      if (cmdOverlay?.classList.contains('active')) {
        event.preventDefault();
        closePalette();
        return;
      }
      if (document.querySelector(otherSurface)) return;
      event.preventDefault();
      openPalette();
      return;
    }
    if (event.key === '?' && !event.ctrlKey && !event.metaKey && !event.altKey) {
      const target = event.target;
      if (target instanceof HTMLElement && target.closest('input, textarea, select, [contenteditable="true"]')) return;
      if (document.querySelector(otherSurface)) return;
      event.preventDefault();
      openShortcuts();
    }
  });

  window.AtelierCommands = Object.freeze({ openPalette, closePalette, openShortcuts, closeShortcuts });
})();
