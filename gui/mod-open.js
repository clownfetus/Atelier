// Open a mod: read a cooked mod and keep what you can edit. One page in the setup page's model: it
// says what the mod holds, asks only for what is missing (a locked mod's password), and has one
// primary action. The server owns every read and write; this file presents them.
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const KINDS = [
    ['texture', 'Textures', "Each one goes into your Mod tray as an edit of the game texture it replaces, ready to open in the texture editor."],
    ['material', 'Materials', "Each one goes into your Mod tray with the mod's colours and numbers on the game's material."],
    ['mesh', 'Meshes', 'Read only for now. Save the JSON to see what the mod changes.'],
    ['animation', 'Animations', 'Read only for now. Save the JSON to see what the mod changes.'],
    ['sound', 'Sounds', "Read only for now. Atelier can't play or add sounds yet."],
    ['effect', 'Effects', 'Read only for now. Save the JSON to see what the mod changes.'],
    ['data', 'Data', 'Read only.'],
    ['config', 'Config files', 'Read only. Config files change game settings rather than assets.'],
    ['other', 'Other files', 'Read only.'],
  ];
  const WHERE = {mod: 'in this mod', game: 'in the game', missing: 'not in the game'};
  const NOUN = {texture: 'texture', material: 'material'};
  let overlay, opener = null, project = '', path = '', locked = false, phase = 'empty';
  let mod = null, selected = new Set(), outcomes = {}, busy = false, changed = false, glyphs = {};

  const plural = (n, word) => n + ' ' + word + (n === 1 ? '' : 's');
  const full = () => window.AtelierMotionPolicy ? window.AtelierMotionPolicy.allows(3) : true;
  const el = (tag, cls, text) => { const node = document.createElement(tag); if (cls) node.className = cls; if (text != null) node.textContent = text; return node; };
  const post = (url, body) => window.atelierFetch(url, {method: 'POST', body: JSON.stringify(body || {})}, project)
    .then(r => r.json()).catch(() => ({ok: false, error: 'Atelier did not answer. Try again.'}));
  const job = (url, body, onUpdate) => window.AtelierJobs
    ? window.AtelierJobs.run(url, {method: 'POST', body: JSON.stringify(body), project, onUpdate})
    : post(url, body);

  function glyph(host, name, state) {
    if (!state) { glyphs[name]?.destroy(); glyphs[name] = null; host.replaceChildren(); return; }
    if (glyphs[name]) { glyphs[name].setState(state); return; }
    try { glyphs[name] = window.AtelierMotion.krackleGlyph.mount(host, {state, reducedMotion: full() ? 'system' : 'reduce'}); }
    catch (_) { glyphs[name] = null; host.replaceChildren(); }
  }
  function lede(text) { if ($('mod-open-lede').textContent !== text) $('mod-open-lede').textContent = text; }

  function init() {
    overlay = $('mod-open-overlay');
    $('mod-open-close').addEventListener('click', close);
    $('mod-open-pick').addEventListener('click', pick);
    $('mod-open-unlock').addEventListener('click', () => read());
    $('mod-open-password').addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); read(); } });
    $('mod-open-add').addEventListener('click', add);
    $('mod-open-save-all').addEventListener('click', () => saveJson(null));
    overlay.addEventListener('keydown', event => { if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(); } });
    window.addEventListener('atelier:preferences', () => { for (const g of Object.values(glyphs)) g?.setReducedMotion?.(full() ? 'system' : 'reduce'); });
  }

  function open() {
    if (!overlay) init();
    const current = window.atelierProject?.() || '';
    if (current !== project && !busy) { project = current; reset(); }
    opener = document.activeElement;
    overlay.classList.add('active');
    render();
    $('mod-open-title').focus();
  }
  function reset() {
    path = ''; locked = false; phase = 'empty'; mod = null; selected = new Set(); outcomes = {};
    $('mod-open-password').value = '';
  }
  function close() {
    overlay.classList.remove('active');
    if (changed) { changed = false; window.loadSidebar?.(); }
    if (opener?.isConnected) opener.focus();
  }

  async function pick() {
    if (busy) return;
    const result = await post('/api/mod_open/pick');
    if (!result.ok) { phase = 'failed'; render(result.error || 'The file picker did not open.'); return; }
    if (!result.path) return;
    path = result.path; locked = !!result.locked; mod = null; outcomes = {}; selected = new Set();
    $('mod-open-password').value = '';
    if (locked) { phase = 'locked'; render(); $('mod-open-password').focus(); return; }
    read();
  }

  async function read() {
    if (busy || !path) return;
    busy = true; phase = 'reading'; render();
    const name = path.split(/[\\/]/).pop();
    lede('Reading ' + name + '…');
    const result = await job('/api/mod_open/read', {path, unlock: $('mod-open-password').value}, update => {
      if (phase === 'reading' && update.stage) lede(update.total ? `${update.stage} (${update.current} of ${update.total})` : update.stage);
    });
    busy = false;
    if (result.locked) { phase = 'locked'; render(); $('mod-open-password-what').textContent = $('mod-open-password').value ? "That password didn't open it. Try again." : 'Its author locked this mod. Enter the password they gave you.'; $('mod-open-password').focus(); return; }
    if (!result.ok) { phase = 'failed'; render(result.error || 'Atelier could not read this mod.'); return; }
    mod = result.mod; locked = false; phase = 'read';
    selected = new Set(mod.assets.filter(a => a.editable && !a.in_tray).map(a => a.id));
    render();
  }

  async function add() {
    if (busy || !mod || !selected.size) return;
    busy = true; phase = 'adding';
    const ids = [...selected];
    render();
    glyph($('mod-open-outcome'), 'outcome', 'busy');
    const result = await job('/api/mod_open/add', {key: mod.key, ids}, update => {
      if (phase === 'adding' && update.stage) $('mod-open-note').textContent = update.total ? `${update.stage} (${update.current + 1} of ${update.total})` : update.stage;
    });
    busy = false; phase = 'read';
    if (result.mod_state) mod = result.mod_state;
    for (const row of result.added || []) outcomes[row.id] = {added: true, note: row.note || ''};
    for (const row of result.skipped || []) outcomes[row.id] = {added: false, note: row.reason || ''};
    if ((result.added || []).length) changed = true;
    for (const row of result.added || []) selected.delete(row.id);
    const added = (result.added || []).length, skipped = (result.skipped || []).length;
    let message, state;
    if (added && !skipped) { message = `Added ${plural(added, 'asset')} to your Mod tray.`; state = 'success'; }
    else if (added) { message = `Added ${added} of ${added + skipped} to your Mod tray. ${skipped} could not be added; each says why.`; state = 'warning'; }
    else if (result.cancelled) { message = 'Cancelled. Nothing was added.'; state = 'info'; }
    else { message = result.error && !skipped ? result.error : 'Nothing was added to the Mod tray. Each asset says why.'; state = 'error'; }
    render();
    $('mod-open-note').textContent = message;
    glyph($('mod-open-outcome'), 'outcome', state);
  }

  async function saveJson(ids) {
    if (!mod) return;
    const result = await post('/api/mod_open/save_json', ids ? {key: mod.key, ids} : {key: mod.key});
    if (result.cancelled) return;
    $('mod-open-note').textContent = result.ok
      ? (result.saved === 1 ? 'Saved ' + result.path.split(/[\\/]/).pop() + ' and showed it in its folder.' : `Saved ${plural(result.saved, 'file')} with a README and showed the folder.`)
      : (result.error || 'Atelier could not save the JSON.');
  }

  function status(asset) {
    const outcome = outcomes[asset.id];
    if (outcome?.added) return ['yours', 'Added to your Mod tray.' + (outcome.note ? ' ' + outcome.note : '')];
    if (outcome) return ['problem', outcome.note || 'Atelier could not add this asset.'];
    if (asset.editable && asset.in_tray) return ['replace', `Already in your Mod tray. Tick it to replace your edit with the mod's version.`];
    if (asset.in_tray) return ['yours', 'In your Mod tray.'];
    if (asset.editable && asset.how === 'add') return ['ready', 'New in this mod. It is added as your own asset at the same path.'];
    if (asset.editable) return ['ready', `Replaces the game's ${NOUN[asset.kind]}.`];
    if (asset.reason) return [asset.json ? 'readonly' : 'problem', asset.reason];
    return ['readonly', asset.in_game ? "Replaces the game's file." : 'New in this mod.'];
  }

  function assetRow(asset) {
    const [state, text] = status(asset);
    const row = el('li', 'at-modopen-asset'); row.dataset.state = state; row.dataset.id = asset.id;
    const check = el('span', 'at-modopen-check');
    if (asset.editable) {
      const box = el('input'); box.type = 'checkbox'; box.checked = selected.has(asset.id); box.disabled = busy;
      box.setAttribute('aria-label', 'Add ' + asset.name + ' to your Mod tray');
      box.addEventListener('change', () => { box.checked ? selected.add(asset.id) : selected.delete(asset.id); renderFoot(); });
      check.append(box);
    }
    const detail = el('div', 'at-modopen-detail');
    detail.append(el('span', 'at-modopen-name', asset.name),
      el('span', 'at-modopen-path', (asset.class ? asset.class + ' · ' : '') + asset.path),
      el('span', 'at-modopen-status', text));
    const refs = asset.references || [];
    if (asset.parent && !refs.some(ref => ref.path === asset.parent)) refs.unshift({path: asset.parent, where: null});
    if (refs.length) {
      const box = el('details', 'at-modopen-refs');
      const others = refs.length - (asset.parent ? 1 : 0);
      box.append(el('summary', null, asset.parent ? 'Parent material' + (others ? ` and ${plural(others, 'other package')}` : '') : 'Uses ' + plural(refs.length, 'package')));
      const list = el('ul');
      for (const ref of refs) {
        const item = el('li', null, ref.path);
        const where = ref.path === asset.parent ? 'parent material, ' + (WHERE[ref.where] || '') : WHERE[ref.where];
        if (where) item.append(el('span', null, where.replace(/, $/, '')));
        list.append(item);
      }
      box.append(list); detail.append(box);
    }
    row.append(check, detail);
    if (asset.json || asset.text) {
      const save = el('button', 'at-btn at-btn--quiet', asset.json ? 'JSON' : 'Save');
      save.type = 'button'; save.disabled = busy;
      save.setAttribute('aria-label', (asset.json ? 'Save the JSON of ' : 'Save ') + asset.name);
      save.addEventListener('click', () => saveJson([asset.id]));
      row.append(save);
    }
    return row;
  }

  function renderGroups() {
    const host = $('mod-open-groups');
    host.replaceChildren();
    if (!mod) return;
    for (const [kind, title, note] of KINDS) {
      const assets = mod.assets.filter(a => a.kind === kind);
      if (!assets.length) continue;
      const group = el('section', 'at-modopen-group'); group.dataset.kind = kind;
      const head = el('header', 'at-modopen-group-head');
      const h2 = el('h2', null, title + ' '); h2.append(el('span', 'at-modopen-n', String(assets.length)));
      head.append(h2, el('p', 'at-modopen-group-note', note));
      const editable = assets.filter(a => a.editable);
      if (editable.length > 1) {
        const all = editable.every(a => selected.has(a.id));
        const toggle = el('button', 'at-btn at-btn--quiet', all ? 'Select none' : 'Select all');
        toggle.type = 'button'; toggle.disabled = busy;
        toggle.addEventListener('click', () => { for (const a of editable) all ? selected.delete(a.id) : selected.add(a.id); renderGroups(); renderFoot(); });
        head.append(toggle);
      }
      const list = el('ul', 'at-modopen-assets');
      for (const asset of assets) list.append(assetRow(asset));
      group.append(head, list); host.append(group);
    }
  }

  function renderFoot() {
    const foot = $('mod-open-foot');
    foot.hidden = !mod;
    if (!mod) return;
    const count = [...selected].filter(id => mod.assets.some(a => a.id === id && a.editable)).length;
    const button = $('mod-open-add');
    button.textContent = phase === 'adding' ? 'Adding…' : count ? `Add ${count} to Mod tray` : 'Add to Mod tray';
    button.disabled = busy || !count;
    $('mod-open-save-all').disabled = busy || !mod.assets.some(a => a.json || a.text);
  }

  function render(error = '') {
    if (!overlay) return;
    const row = $('mod-open-file-row'), name = path.split(/[\\/]/).pop();
    const problems = (mod?.containers || []).filter(c => c.problem);
    const state = {empty: 'waiting', locked: 'done', reading: 'pending', read: problems.length ? 'missing' : 'done', adding: 'done', failed: 'missing'}[phase];
    row.dataset.state = state;
    glyph(row.querySelector('.at-setup-glyph'), 'file', {pending: 'busy', done: 'success', missing: phase === 'failed' ? 'error' : 'warning'}[state] || null);
    const what = $('mod-open-what'), where = $('mod-open-where');
    where.textContent = path || '';
    const total = mod ? mod.assets.length : 0, editable = mod ? mod.assets.filter(a => a.editable).length : 0;
    what.textContent = {
      empty: 'A .pak, .utoc, .ucas or .zip.',
      locked: name,
      reading: 'Reading…',
      read: total ? `${plural(total, 'asset')}, ${editable} you can add to your Mod tray` + (problems.length ? `, ${plural(problems.length, 'problem')}` : '') : 'Nothing Atelier could read',
      adding: total ? `${plural(total, 'asset')}, ${editable} you can add to your Mod tray` : '',
      failed: error || 'Atelier could not read this mod.',
    }[phase];
    const list = $('mod-open-problems'); list.replaceChildren();
    for (const c of problems) { const item = el('li'); item.append(el('code', null, c.name), document.createTextNode(': ' + c.problem)); list.append(item); }
    const pickButton = $('mod-open-pick');
    pickButton.textContent = path ? 'Change' : 'Choose mod…';
    pickButton.className = 'at-btn ' + (path ? 'at-btn--quiet' : 'at-btn--primary');
    pickButton.disabled = busy;
    $('mod-open-password-row').hidden = phase !== 'locked';
    $('mod-open-unlock').disabled = busy;
    if (phase === 'empty') lede('Choose a cooked mod. Atelier shows what each asset is, where it lives in the game and what it uses, and adds what you can edit to your Mod tray.');
    else if (phase === 'locked') lede('This mod is locked. Enter its password to open it.');
    else if (phase === 'failed') lede('Atelier could not read ' + (name || 'this mod') + '.');
    else if (phase === 'read') lede(total ? `${name} holds ${plural(total, 'asset')}. Tick what you want in your Mod tray, or save any asset's JSON to study it.` : `Atelier found nothing it could read in ${name}.`);
    if (phase === 'read' && !Object.keys(outcomes).length) $('mod-open-note').textContent = editable || !total ? '' : 'Nothing in this mod can go in the Mod tray yet. You can still save its JSON.';
    renderGroups();
    renderFoot();
    if (phase !== 'adding' && !Object.keys(outcomes).length) glyph($('mod-open-outcome'), 'outcome', null);
  }

  window.AtelierModOpen = Object.freeze({open});
  document.addEventListener('DOMContentLoaded', () => { if (!overlay) init(); });
})();
