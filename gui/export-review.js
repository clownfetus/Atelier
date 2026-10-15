/* Export review and latest session result. No build logic or credentials live here. */
(function () {
  'use strict';
  let overlay, panel, body, title, actions, lastButton, opener;
  let current = null, busy = false, lastResult = null;

  function el(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  }
  function button(label, action, primary = false) {
    const node = el('button', label, 'btn' + (primary ? ' primary' : ''));
    node.type = 'button'; node.addEventListener('click', action);
    actions.append(node); return node;
  }
  function ensure() {
    if (overlay) return;
    overlay = el('div', undefined, 'overlay export-review-overlay');
    overlay.id = 'export-review-overlay';
    panel = el('section', undefined, 'modal export-review-modal');
    panel.setAttribute('role', 'dialog'); panel.setAttribute('aria-modal', 'true');
    panel.setAttribute('aria-labelledby', 'export-review-title'); panel.tabIndex = -1;
    title = el('h2'); title.id = 'export-review-title';
    body = el('div', undefined, 'export-review-body');
    actions = el('div', undefined, 'modal-row export-review-actions');
    panel.append(title, body, actions); overlay.append(panel); document.body.append(overlay);
    lastButton = el('button', 'Last export', 'btn export-last-result');
    lastButton.id = 'export-last-result'; lastButton.type = 'button'; lastButton.hidden = true;
    lastButton.addEventListener('click', () => {
      if (busy) { show(); return; }
      if (lastResult) { current = lastResult; renderResult(); show(); }
    });
    document.getElementById('install-btn').insertAdjacentElement('afterend', lastButton);
    overlay.addEventListener('keydown', event => {
      if (event.key === 'Escape') {
        event.preventDefault(); event.stopPropagation(); hide(); return;
      }
      if (event.key !== 'Tab') return;
      const focusable = [...panel.querySelectorAll('button:not(:disabled), summary, a[href]')]
        .filter(node => node.getClientRects().length);
      const first = focusable[0], last = focusable[focusable.length - 1];
      if (!first) { event.preventDefault(); panel.focus(); }
      else if (event.shiftKey && (document.activeElement === first || document.activeElement === panel)) {
        event.preventDefault(); last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault(); first.focus();
      }
    });
  }
  function show() {
    if (!overlay.classList.contains('active')) opener = document.activeElement;
    overlay.classList.add('active'); panel.focus();
  }
  function hide() {
    overlay.classList.remove('active');
    if (opener?.isConnected && !opener.disabled) opener.focus();
    else if (!lastButton.hidden && !lastButton.disabled) lastButton.focus();
    else document.getElementById('install-btn').focus();
  }
  function reset(heading, state) {
    title.textContent = heading; body.replaceChildren(); actions.replaceChildren();
    panel.dataset.state = state; panel.setAttribute('aria-busy', String(state === 'busy'));
  }
  function metadata(snapshot) {
    const dl = el('dl', undefined, 'export-review-meta');
    for (const [label, value] of [
      ['Project', snapshot.project || 'Default project'], ['Mod filename', snapshot.modName],
      ['Destination', snapshot.copyToMods ? 'Export folder + ' + snapshot.modsPath : 'Export folder'],
      ['Password protection', snapshot.protected ? 'Enabled' : 'Off'],
    ]) dl.append(el('dt', label), el('dd', value));
    body.append(dl);
  }
  function list(heading, items, getText, open = false) {
    if (!items.length) return;
    const details = el('details', undefined, 'export-review-list'); details.open = open;
    details.append(el('summary', heading + ' · ' + items.length));
    const ul = el('ul');
    for (const item of items) ul.append(el('li', getText(item)));
    details.append(ul); body.append(details);
  }
  function excludedText(item) {
    return (item.name || 'Unnamed asset') + ' · ' + (item.file_type || 'unknown') +
      ' · ' + item.reason + (item.game_rel ? '\n' + item.game_rel : '');
  }
  function renderReview(note) {
    const { snapshot, callbacks } = current; busy = false;
    reset('Review export', 'review'); metadata(snapshot);
    const countLabel = snapshot.included.length + (snapshot.included.length === 1 ? ' asset' : ' assets');
    const summary = el('p', countLabel + ' will be submitted. Only saved project edits are exported.', 'export-review-summary');
    body.append(summary);
    list('Included changes', snapshot.included, item =>
      (item.name || item.game_rel.split('/').pop()) + ' · ' + item.file_type + '\n' + item.game_rel, true);
    list('Excluded changes', snapshot.excluded, excludedText, snapshot.excluded.length > 0);
    if (note) {
      const alert = el('p', note, 'export-review-notice'); alert.setAttribute('role', 'alert'); body.append(alert);
    }
    button('Cancel', hide);
    button('Refresh review', callbacks.refresh).id = 'export-review-refresh';
    button('Export ' + countLabel, () => callbacks.confirm(), true).id = 'export-review-confirm';
  }
  function renderResult() {
    const { snapshot, result, callbacks } = current;
    const built = result.ok || result.built;
    const warning = built && (!result.ok || snapshot.skipped || (result.skipped || []).length);
    reset(built ? (result.installed_dir ? 'Mod installed' : result.ok ? 'Mod exported' : 'Export built; copy failed') : result.cancelled ? 'Export cancelled' : 'Export failed',
      built ? warning ? 'warning' : 'success' : 'error');
    metadata(snapshot);
    const status = el('p', result.error || (warning ? 'Review the skipped items below before testing this mod.' : 'The build has finished.'), 'export-review-summary');
    status.setAttribute('role', 'status'); body.append(status);
    if (result.pak_path) body.append(el('p', 'Export: ' + result.pak_path, 'export-review-path'));
    if (result.installed_dir) body.append(el('p', 'Installed to: ' + result.installed_dir, 'export-review-path'));
    list('Build report · applied operations', result.applied || [], String, true);
    list('Build report · skipped or warnings', result.skipped || [], String, true);
    list('Excluded before export', snapshot.excluded, excludedText, true);
    if (!built) body.append(el('p', 'Your project edits are preserved. Resolve the error, then retry. A connection failure can occur after a build completes; retry checks for existing output first.'));
    if (result.built && !result.ok) body.append(el('p', 'The exported files are available. Check the mods folder in Settings before retrying the build and copy.'));
    button('Close', hide);
    if (built) button('Show exported files', callbacks.reveal).id = 'export-review-reveal';
    if (!result.ok || result.need_mods_folder) button('Settings', () => { hide(); callbacks.settings(); });
    button('Review current selection', callbacks.refresh).id = 'export-review-refresh';
    if (!result.ok) button('Retry export', callbacks.confirm, true).id = 'export-review-retry';
  }
  window.AtelierExportReview = {
    open(snapshot, callbacks, note) {
      ensure(); if (busy) return;
      current = { snapshot, callbacks }; renderReview(note); show();
    },
    checking(snapshot) {
      if (current?.snapshot !== snapshot) return;
      busy = true; reset('Checking export destinations…', 'busy'); metadata(snapshot);
      lastButton.hidden = false; lastButton.textContent = 'View export progress';
      body.append(el('p', 'Checking whether this mod would replace existing output.'));
      button('Hide', hide); show();
    },
    suspend(snapshot) { if (current?.snapshot === snapshot) hide(); },
    cancelCheck(snapshot) {
      if (current?.snapshot !== snapshot) return;
      busy = false;
      lastButton.hidden = !lastResult; lastButton.textContent = 'View export result';
      renderReview(); show();
    },
    start(snapshot) {
      if (current?.snapshot !== snapshot) return;
      busy = true; reset('Building mod…', 'busy'); metadata(snapshot);
      const progress = el('progress'); progress.setAttribute('aria-label', 'Export in progress'); body.append(progress);
      body.append(el('p', snapshot.copyToMods ? 'Building the selected saved edits, then copying the output to your mods folder.' : 'Building the selected saved edits in the export folder.'));
      body.append(el('p', 'This operation has no percentage estimate. You can hide this window; the build will continue.'));
      const stage = el('p', 'Starting…'); stage.id = 'export-job-stage'; stage.setAttribute('role','status'); body.append(stage);
      const cancel = button('Cancel export', async () => {
        try {
          const result = await window.AtelierJobs?.cancelCurrent('export', snapshot.project);
          if (!result?.ok) window.AtelierExportReview.notice(result?.error || 'Job controls are unavailable.');
        } catch (error) { window.AtelierExportReview.notice(error.message); }
      });
      cancel.id = 'export-job-cancel'; cancel.disabled = true;
      button('Hide', hide); show();
      lastButton.hidden = false; lastButton.textContent = 'View export progress';
    },
    jobProgress(job) {
      if (!busy || current?.snapshot?.project !== job.project) return;
      const stage = document.getElementById('export-job-stage');
      if (stage) stage.textContent = job.stage;
      const cancel = document.getElementById('export-job-cancel');
      if (cancel) cancel.disabled = !job.can_cancel || job.state === 'cancelling';
    },
    finish(snapshot, result) {
      if (current?.snapshot !== snapshot) return;
      busy = false; current.result = result; lastResult = current;
      lastButton.hidden = false; lastButton.disabled = false;
      lastButton.textContent = result.ok ? 'View export result' : 'Review export issue';
      renderResult(); show();
    },
    notice(message) {
      if (!current) return;
      const note = el('p', message, 'export-review-notice'); note.setAttribute('role', 'alert'); body.append(note);
    },
  };
})();
