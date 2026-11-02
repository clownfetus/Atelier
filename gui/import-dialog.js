// Edit All import dialog, in the identity v1.0 design language.
// app.js owns the request, SSE progress and the library refresh; AtelierPolish owns the
// result dots. This file writes the dialog's status text and, once the job ends, holds
// its result until the user dismisses it. Text renders first: the Krackle import ink only
// shows where the work went (asset cards → stage → Mod tray) and may be missing entirely.
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const overlay = $('prog-overlay'), box = $('prog-box');
  if (!overlay || !box) return;
  const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;
  const tray = () => $('sidebar-header');
  let total = 0, imported = 0, held = false, ink = null;

  function inkStage() {
    if (ink) return ink;
    try { ink = window.AtelierMotion?.importInk?.mount($('import-stage'), {shield: box, window: $('import-stage')}) || null; }
    catch (_) { ink = null; $('import-stage').replaceChildren(); }
    return ink;
  }
  const play = (method, ...args) => { try { inkStage()?.[method](...args); } catch (_) { /* presentation is optional */ } };

  function status(title, detail = null, current = '') {
    $('import-status-title').textContent = title;
    if (detail !== null) $('prog-counter').textContent = detail;
    $('import-current').textContent = current;
  }
  const NOTES = {
    busy: 'Completed assets are kept if you cancel. Hide this view to keep working; Activity shows the result.',
    success: 'Open any texture in the Mod tray to start editing.',
    warning: 'Textures that did not import stay in the library. Edit All again to retry just those.',
    error: 'Nothing was added to the Mod tray.',
    cancelled: '',
  };
  function actions(kind) {
    const result = kind !== 'busy';
    $('import-hide').hidden = result;
    $('import-cancel').hidden = result;
    $('import-done').hidden = !result;
    // The note keeps its space, so the dialog never jumps when the result arrives.
    const note = $('import-note');
    note.textContent = NOTES[kind] || '';
    note.style.visibility = note.textContent ? '' : 'hidden';
  }
  // The ink leaves from the actual cards being imported; the Edit All button stands in for them.
  function sources(items) {
    // Library cards are keyed by rel_path, falling back to game_rel (library-tools.js).
    const wanted = new Set(items.flatMap(item => [item.rel_path, item.game_rel]).filter(Boolean));
    const cards = [...document.querySelectorAll('#grid-area .card')].filter(card => wanted.has(card.dataset.libraryPath));
    return cards.length ? cards : [$('import-all-btn')].filter(Boolean);
  }

  function begin(items) {
    total = items.length; imported = 0; held = false;
    box.dataset.importState = 'busy';
    box.setAttribute('aria-busy', 'true');
    $('import-kicker').textContent = `Import · ${plural(total, 'texture')}`;
    status('Extracting from game');
    actions('busy');
    play('begin', sources(items));
  }
  function progress(data) {
    if (held || data.done) return;
    if (data.game_rel) {
      if (data.ok !== false) imported++;
      status('Importing', null, data.name || '');
      play('item', data.ok !== false, tray());
    } else if (data.name) {
      status(String(data.name).replace(/…$/, '').replace(/^Decoding$/, 'Decoding textures'));
    }
  }
  // Returns true when the dialog stays open to show the result; false when it was hidden.
  function finish(data) {
    const count = Array.isArray(data.results) ? data.results.length : imported;
    const all = data.total || total;
    const cancelled = /cancel/i.test(data.error || '');
    const kind = !data.error && count >= all ? 'success' : count > 0 ? 'warning' : cancelled ? 'cancelled' : 'error';
    if (kind === 'success') status(`Imported ${plural(count, 'texture')}`, 'Added to the Mod tray, ready to edit.');
    else if (kind === 'warning') status(cancelled ? 'Import cancelled' : 'Imported with warnings',
      `${count} of ${all} added to the Mod tray · ${all - count} ${cancelled ? 'not imported' : 'failed'}`);
    else if (kind === 'cancelled') status('Import cancelled', 'Nothing was added to the Mod tray.');
    else status('Import failed', data.error || 'No textures could be imported.');
    box.dataset.importState = kind;
    box.removeAttribute('aria-busy');
    play('finish', kind, tray());
    if (!overlay.classList.contains('active')) return false;
    held = true;
    actions(kind);
    $('import-done').focus();
    return true;
  }
  // The request itself failed before the job started; app.js closes the dialog.
  function abandon() {
    held = false;
    box.removeAttribute('aria-busy');
    box.dataset.importState = 'idle';
    play('setState', 'idle');
  }
  function dismiss() {
    if (!held) return;
    held = false;
    overlay.classList.remove('active');
  }
  $('import-done').addEventListener('click', dismiss);
  overlay.addEventListener('keydown', event => { if (held && event.key === 'Escape') { event.preventDefault(); dismiss(); } });

  window.AtelierImportDialog = Object.freeze({begin, progress, finish, abandon});
})();
