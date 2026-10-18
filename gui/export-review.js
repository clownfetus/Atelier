/* Export review and latest session result. No build logic or credentials live here. */
(function () {
  'use strict';
  let overlay, panel, body, title, actions, lastButton, opener, stageHost, stage = null;
  let current = null, busy = false, lastResult = null, preferredFormat = 'standard';

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
    stageHost = el('div', undefined, 'export-review-stage');
    panel.append(title, stageHost, body, actions); overlay.append(panel); document.body.append(overlay);
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
      const focusable = [...panel.querySelectorAll('button:not(:disabled), summary, a[href], input:not(:disabled), select:not(:disabled)')]
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
  // Export feedback elsewhere (toast, button) holds still while this dialog's stage carries the job.
  const announce = () => document.dispatchEvent(new Event('atelier:export-review'));
  function show() {
    const opening = !overlay.classList.contains('active');
    if (opening) opener = document.activeElement;
    overlay.classList.add('active'); panel.focus();
    if (opening) announce();
  }
  function hide() {
    const closing = overlay.classList.contains('active');
    overlay.classList.remove('active');
    if (closing) announce();
    if (opener?.isConnected && !opener.disabled) opener.focus();
    else if (!lastButton.hidden && !lastButton.disabled) lastButton.focus();
    else document.getElementById('install-btn').focus();
  }
  function reset(heading, state) {
    title.textContent = heading; body.replaceChildren(); actions.replaceChildren();
    panel.dataset.state = state; panel.setAttribute('aria-busy', String(state === 'busy'));
    showStage(state === 'review' ? 'idle' : state);
  }
  // Krackle stage: the build charges as a ring, then pops, cracks or splats. Decorative
  // only; the progress bar and status text stay the accessible record of the build.
  function showStage(state) {
    try {
      if (!stage && state !== 'idle' && window.AtelierMotion?.krackleStage) {
        stage = window.AtelierMotion.krackleStage.mount(stageHost, {state: 'idle', size: 156, kind:'export-review'});
      }
      stage?.setState(state);
    } catch (_) {
      stage = null; stageHost.replaceChildren();
    }
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
  // Project Galacta Skin Swapper: app.js passes `skinSwapper` only when the included edits hold a
  // character mesh. Hero and skin are read-only (they come from the mesh); the server checks every
  // rule again before and after building, so the checks here only explain and gate the button.
  function formatChoice(offer) {
    const field = el('fieldset', undefined, 'export-format');
    field.append(el('legend', 'Mod format'));
    const option = (value, label, hint, disabled) => {
      const row = el('label', undefined, 'export-format-option');
      const input = document.createElement('input');
      input.type = 'radio'; input.name = 'export-format'; input.value = value; input.disabled = !!disabled;
      input.checked = current.format === value;
      input.addEventListener('change', () => {
        current.retry = null;
        current.format = preferredFormat = value; renderReview();
        body.querySelector('input[name="export-format"]:checked')?.focus();
      });
      const text = el('span'); text.append(el('b', label), el('small', hint));
      row.append(input, text); field.append(row);
    };
    option('standard', 'Standard mod', 'Replaces the edited game assets.');
    option('skin-swapper', 'Skin Swapper mod (Project Galacta)', offer.status.available
      ? 'Your edited mesh in its own Galacta folder, loaded by the Skin Swapper Companion App.'
      : 'Unavailable: ' + offer.status.reasons.join(' '), !offer.status.available);
    body.append(field);
  }
  function renderSkinSwapper(offer, note) {
    const { snapshot, callbacks } = current;
    const state = current.swapper || (current.swapper = {
      skinName: offer.defaults.skinName || '', author: offer.defaults.author || '',
      sculpts: Object.fromEntries(offer.meshes.map(mesh => [mesh.game_rel, 0])),
    });
    const options = () => ({ skin_name: state.skinName, author: state.author,
      meshes: offer.meshes.map(mesh => ({ game_rel: mesh.game_rel, sculpt: state.sculpts[mesh.game_rel] || 0 })) });
    const target = el('dl', undefined, 'export-review-meta');
    for (const [label, value] of [
      ['Hero', (offer.heroLabel ? offer.heroLabel + ' · ' : '') + offer.hero],
      ['Skin', (offer.skinLabel ? offer.skinLabel + ' · ' : '') + offer.skin],
      ['Galacta folder', `/Game/Marvel/ProjectGalacta/Meshes/${offer.hero}/${offer.skin}/${snapshot.modName}/`],
    ]) target.append(el('dt', label), el('dd', value));
    body.append(target, el('p', 'Hero and skin come from the edited mesh and cannot be changed. The mod filename is the folder name.', 'export-review-summary'));
    const field = (id, label, key) => {
      const wrap = el('label', undefined, 'skin-swapper-field'); wrap.htmlFor = id;
      const input = document.createElement('input');
      input.type = 'text'; input.id = id; input.className = 'setup-input'; input.maxLength = 64; input.value = state[key];
      input.addEventListener('input', () => { state[key] = input.value; schedule(); });
      wrap.append(el('span', label), input); body.append(wrap);
    };
    field('skin-swapper-name', 'Skin name', 'skinName');
    field('skin-swapper-author', 'Author', 'author');
    const meshes = el('div', undefined, 'skin-swapper-meshes');
    for (const mesh of offer.meshes) {
      const name = mesh.name || mesh.game_rel.split('/').pop();
      const row = el('label', undefined, 'skin-swapper-mesh');
      const select = document.createElement('select');
      select.className = 'setup-input'; select.setAttribute('aria-label', 'Hero form for ' + name);
      for (let n = 0; n <= 9; n++) {
        const choice = el('option', n === 0 ? 'Form 0 (default)' : 'Form ' + n); choice.value = String(n); select.append(choice);
      }
      select.value = String(state.sculpts[mesh.game_rel] || 0);
      select.addEventListener('change', () => { state.sculpts[mesh.game_rel] = Number(select.value); schedule(); });
      row.append(el('span', name), select); meshes.append(row);
    }
    body.append(meshes);
    const others = snapshot.included.filter(item => !offer.meshes.includes(item));
    list('Left out of this Skin Swapper mod', others, item =>
      (item.name || item.game_rel.split('/').pop()) + ' · ' + item.file_type + '\nOnly meshes and their configs go into a Skin Swapper mod.');
    const checks = el('ul', undefined, 'skin-swapper-problems'); checks.setAttribute('role', 'status'); checks.hidden = true;
    body.append(checks);
    if (note) {
      const alert = el('p', note, 'export-review-notice'); alert.setAttribute('role', 'alert'); body.append(alert);
    }
    button('Cancel', hide);
    button('Refresh review', callbacks.refresh).id = 'export-review-refresh';
    const build = button('Build Skin Swapper mod', () => {
      const chosen = options(); current.retry = () => offer.build(chosen); offer.build(chosen);
    }, true);
    build.id = 'export-review-confirm'; build.disabled = true;
    let timer = 0, request = 0;
    function schedule() { clearTimeout(timer); build.disabled = true; timer = setTimeout(check, 250); }
    async function check() {
      const id = ++request; let result;
      try { result = await offer.plan(options()); } catch (error) { result = { problems: [error.message] }; }
      if (id !== request || !checks.isConnected) return;
      const problems = [...(result?.problems || ['The Skin Swapper checks could not run.']),
        ...(result?.status && !result.status.available ? result.status.reasons : [])];
      checks.replaceChildren(...problems.map(problem => el('li', problem)));
      checks.hidden = !problems.length;
      build.disabled = problems.length > 0;
    }
    check();
  }
  function renderReview(note) {
    const { snapshot, callbacks } = current; busy = false;
    const offer = callbacks.skinSwapper, swapper = !!offer && current.format === 'skin-swapper';
    reset(swapper ? 'Review Skin Swapper mod' : 'Review export', 'review'); metadata(snapshot);
    if (offer) formatChoice(offer);
    if (swapper) { renderSkinSwapper(offer, note); return; }
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
    button('Export ' + countLabel, () => {
      current.retry = callbacks.confirm;
      callbacks.confirm();
    }, true).id = 'export-review-confirm';
  }
  function renderResult() {
    const { snapshot, result, callbacks } = current;
    const built = result.ok || result.built;
    const warning = built && (!result.ok || snapshot.skipped || (result.skipped || []).length);
    // The heading carries the outcome; the stage only gives it a physical character.
    const suffix = warning && result.ok ? ' with warnings' : '';
    reset(built ? (result.installed_dir ? 'Mod installed' + suffix : result.ok ? 'Mod exported' + suffix : 'Export built; copy failed') : result.cancelled ? 'Export cancelled' : 'Export failed',
      built ? warning ? 'warning' : 'success' : 'error');
    if (result.cancelled && !built) showStage('idle');
    metadata(snapshot);
    const status = el('p', result.error || (warning ? 'Review the skipped items below before testing this mod.' : 'The build has finished.'), 'export-review-summary');
    status.setAttribute('role', 'status'); body.append(status);
    if (result.pak_path) body.append(el('p', 'Export: ' + result.pak_path, 'export-review-path'));
    if (result.installed_dir) body.append(el('p', 'Installed to: ' + result.installed_dir, 'export-review-path'));
    if (result.galacta_folder) {
      body.append(el('p', 'Galacta folder: ' + result.galacta_folder, 'export-review-path'),
        el('p', 'Load it with the Project Galacta Companion App. Atelier never edits skins.txt; the Companion App manages it.'));
    }
    list('Skin Swapper checks that failed', result.problems || [], String, true);
    list('Build report · applied operations', result.applied || [], String, true);
    list('Build report · skipped or warnings', result.skipped || [], String, true);
    list('Excluded before export', snapshot.excluded, excludedText, true);
    if (!built) body.append(el('p', 'Your project edits are preserved. Resolve the error, then retry. A connection failure can occur after a build completes; retry checks for existing output first.'));
    if (result.built && !result.ok) body.append(el('p', 'The exported files are available. Check the mods folder in Settings before retrying the build and copy.'));
    button('Close', hide);
    if (built) button('Show exported files', callbacks.reveal).id = 'export-review-reveal';
    if (!result.ok || result.need_mods_folder) button('Settings', () => { hide(); callbacks.settings(); });
    button('Review current selection', callbacks.refresh).id = 'export-review-refresh';
    if (!result.ok) button('Retry export', current.retry || callbacks.confirm, true).id = 'export-review-retry';
  }
  window.AtelierExportReview = {
    open(snapshot, callbacks, note) {
      ensure(); if (busy) return;
      const swapper = callbacks.skinSwapper?.status?.available && preferredFormat === 'skin-swapper';
      current = { snapshot, callbacks, format: swapper ? 'skin-swapper' : 'standard' }; renderReview(note); show();
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
    // True when the large stage will draw `state` for the current job: busy only while the dialog
    // is open (it can be hidden mid-build), results always (finish() reopens the dialog).
    staging(state) {
      if (!stage || !stageHost?.isConnected || stageHost.dataset.amMicro === 'true') return false;
      if (!window.AtelierMotionPolicy?.allows(2)) return false;
      return state !== 'busy' || overlay.classList.contains('active');
    },
    notice(message) {
      if (!current) return;
      const note = el('p', message, 'export-review-notice'); note.setAttribute('role', 'alert'); body.append(note);
    },
  };
})();
