// Category tab navigation for the Settings dialog.
(() => {
  'use strict';

  const TABS = [
    { id: 'all', label: 'All' },
    { id: 'appearance', label: 'Appearance' },
    { id: 'paths', label: 'Paths & keys' },
    { id: 'export', label: 'Export & tools' },
    { id: 'behaviour', label: 'Behaviour & motion' },
  ];

  let active = 'all';

  function dialog() {
    return document.getElementById('setup-dialog');
  }

  function bar() {
    return document.getElementById('settings-tabs');
  }

  function select(tabId, { scrollTop = true } = {}) {
    if (!TABS.some(t => t.id === tabId)) tabId = 'all';
    active = tabId;
    const dlg = dialog();
    if (dlg) dlg.dataset.settingsTab = tabId;
    const body = dlg?.querySelector('.setup-body');
    if (body) {
      body.setAttribute('aria-labelledby', `settings-tab-${tabId}`);
      if (scrollTop) body.scrollTop = 0;
    }
    const nav = bar();
    if (nav) {
      nav.querySelectorAll('.settings-tab').forEach(btn => {
        const selected = btn.dataset.tab === tabId;
        btn.setAttribute('aria-selected', String(selected));
        btn.tabIndex = selected ? 0 : -1;
      });
    }
  }

  function revealField(fieldId) {
    if (!fieldId) {
      select('all', { scrollTop: true });
      return;
    }
    const el = document.getElementById(fieldId);
    const group = el?.closest('[data-settings-group]')?.dataset.settingsGroup;
    if (group && active !== 'all' && active !== group) {
      select(group, { scrollTop: false });
    }
    el?.scrollIntoView({ block: 'nearest' });
  }

  function init() {
    const nav = bar();
    if (!nav) return;
    const body = dialog()?.querySelector('.setup-body');
    if (!body) return;
    body.id = 'settings-panel';
    body.setAttribute('role', 'tabpanel');
    nav.replaceChildren();
    for (const tab of TABS) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'settings-tab';
      btn.id = `settings-tab-${tab.id}`;
      btn.setAttribute('role', 'tab');
      btn.setAttribute('aria-controls', body.id);
      btn.dataset.tab = tab.id;
      btn.textContent = tab.label;
      btn.addEventListener('click', () => select(tab.id));
      nav.append(btn);
    }
    nav.addEventListener('keydown', event => {
      const buttons = [...nav.querySelectorAll('.settings-tab')];
      const idx = buttons.indexOf(document.activeElement);
      if (idx < 0) return;
      let next = -1;
      if (event.key === 'ArrowRight') next = (idx + 1) % buttons.length;
      else if (event.key === 'ArrowLeft') next = (idx - 1 + buttons.length) % buttons.length;
      else if (event.key === 'Home') next = 0;
      else if (event.key === 'End') next = buttons.length - 1;
      if (next >= 0) {
        event.preventDefault();
        buttons[next].focus();
        select(buttons[next].dataset.tab);
      }
    });
    select('all', { scrollTop: false });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
  else init();

  window.AtelierSettingsTabs = Object.freeze({ select, revealField, current: () => active });
})();
