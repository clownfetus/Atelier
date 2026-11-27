/* Export review and latest session result. No build logic or credentials live here. */
(function () {
  'use strict';
  let overlay, panel, banner, koStamp, body, title, count, report, actions, lastButton, opener, stageHost, glyph = null;
  let current = null, busy = false, lastResult = null, preferredFormat = 'standard', bannerToken = 0;

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
    banner = el('div', undefined, 'export-review-banner');
    banner.setAttribute('aria-hidden', 'true'); banner.hidden = true;
    koStamp = el('span', undefined, 'export-review-ko');
    koStamp.setAttribute('aria-hidden', 'true'); koStamp.hidden = true;
    banner.append(koStamp);
    const header = el('div', undefined, 'export-review-header');
    title = el('h2'); title.id = 'export-review-title';
    count = el('span', undefined, 'export-review-count'); count.hidden = true;
    header.append(title, count);
    const content = el('div', undefined, 'export-review-content');
    body = el('div', undefined, 'export-review-body');
    report = el('div', undefined, 'export-review-report'); report.hidden = true;
    actions = el('div', undefined, 'modal-row export-review-actions');
    stageHost = el('div', undefined, 'export-review-stage');
    content.append(stageHost, body, report);
    panel.append(banner, header, content, actions); overlay.append(panel); document.body.append(overlay);
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
  function updateBanner(snapshot, state) {
    const token = ++bannerToken;
    banner.hidden = true; banner.style.removeProperty('--export-banner');
    koStamp.hidden = true; koStamp.style.removeProperty('--export-ko');
    const items = snapshot?.included || [];
    const heroes = new Set(), skins = new Set();
    for (const item of items) {
      const desc = window.AtelierCatalogueArt?.describe(item.game_rel || '');
      const sid = /^\d{7}$/.test(item.skin_id || '') ? item.skin_id : (desc?.skin_id || '');
      const cid = sid ? sid.slice(0, 4) : (/^\d{4}$/.test(item.char_id || '') ? item.char_id : (window.AtelierCatalogueArt?.heroId(item) || ''));
      if (/^\d{4}$/.test(cid)) heroes.add(cid);
      if (/^\d{7}$/.test(sid)) skins.add(sid);
    }
    if (!heroes.size) return;
    const hero = [...heroes][0];
    const singleHero = heroes.size === 1;
    const singleSkin = singleHero && skins.size === 1 ? [...skins][0] : '';
    const bannerUrl = window.AtelierCatalogueArt?.bannerUrl || (u => u);
    const sources = [
      singleSkin && bannerUrl('/api/catalogue/banner/' + singleSkin),
      bannerUrl('/api/catalogue/banner/' + hero),
      '/api/catalogue/hero/' + hero + '/story',
    ].filter(Boolean);
    const probe = new Image(); probe.decoding = 'async';
    const next = () => {
      if (token !== bannerToken) return;
      if (!sources.length) return;
      probe.src = sources.shift();
    };
    probe.onload = () => {
      if (token !== bannerToken) return;
      const loaded = probe.getAttribute('src');
      if (loaded) {
        banner.style.setProperty('--export-banner', `url("${loaded}")`);
        banner.hidden = false;
      }
    };
    probe.onerror = next;
    next();
    if (singleHero && (state === 'success' || state === 'warning')) {
      const koUrl = '/api/catalogue/hero/' + hero + '/kill';
      const koProbe = new Image(); koProbe.decoding = 'async';
      koProbe.onload = () => {
        if (token !== bannerToken) return;
        koStamp.style.setProperty('--export-ko', `url("${koUrl}")`);
        koStamp.hidden = false;
        banner.hidden = false;
      };
      koProbe.src = koUrl;
    }
  }
  function reset(heading, state, {stageState = state, result = false} = {}) {
    title.textContent = heading; body.replaceChildren(); actions.replaceChildren();
    count.hidden = true; report.hidden = true; report.replaceChildren();
    panel.classList.toggle('export-review-result', result);
    panel.querySelector('.export-review-content').scrollTop = 0;
    panel.dataset.state = state; panel.setAttribute('aria-busy', String(state === 'busy'));
    updateBanner(current?.snapshot, state);
    showStage(stageState);
  }
  // The build runs in the glyph, which then forms its result. Decorative only; the progress bar and
  // status text stay the accessible record of the build.
  function showStage(state) {
    if (!/^(busy|success|warning|error|info)$/.test(state) || !window.AtelierMotion?.glyph) {
      glyph?.destroy(); glyph = null;
      return;
    }
    // Busy after busy (checking straight into the build) carries on, and a result takes over from
    // wherever the pieces are. Only a just-finished build performs its result; a reopened one is still.
    const still = state !== 'busy' && !current?.fresh;
    try {
      if (glyph && (!still || glyph.state === state)) { if (!still) glyph.set(state); return; }
      glyph?.destroy();
      glyph = window.AtelierMotion.glyph.mount(stageHost, {state, size: state === 'busy' ? 216 : 156, still});
    } catch (_) {
      glyph = null; stageHost.replaceChildren();
    }
  }
  const exportLabel = copyToMods => copyToMods ? 'Export and install' : 'Export mod';

  function destinationChoice(snapshot) {
    const field = el('div', undefined, 'export-review-destination');
    const select = el('select', undefined, 'setup-input');
    select.setAttribute('aria-label', 'Destination');
    const exportOnly = el('option', 'Export only'); exportOnly.value = 'export';
    const install = el('option', 'Export and install'); install.value = 'install';
    install.disabled = !snapshot.modsPath;
    select.append(exportOnly, install); select.value = snapshot.copyToMods ? 'install' : 'export';
    const path = el('small', snapshot.modsPath, 'export-review-path');
    path.hidden = !snapshot.copyToMods;
    select.addEventListener('change', () => {
      const copyToMods = select.value === 'install';
      current.snapshot = Object.freeze({...current.snapshot, copyToMods});
      current.callbacks.rememberDestination?.(copyToMods);
      path.hidden = !copyToMods;
      actions.querySelector('#export-review-confirm').textContent = exportLabel(copyToMods);
    });
    field.append(select, path);
    if (!snapshot.modsPath) {
      const settings = el('button', 'Set mods folder…', 'btn'); settings.type = 'button';
      settings.addEventListener('click', () => {
        const {snapshot, callbacks} = current;
        hide();
        callbacks.settings({
          field: 'setup-mods',
          onSave: () => {
            if (window.atelierProject() === snapshot.project) return callbacks.refresh();
          },
        });
      });
      field.append(settings);
    }
    return field;
  }

  function reviewFields(snapshot, destination = snapshot.copyToMods ? 'Export folder + ' + snapshot.modsPath : 'Export folder') {
    return [
      ['Project', snapshot.project || 'Default project'], ['Mod filename', snapshot.modName],
      ['Destination', destination],
    ];
  }
  function metadata(snapshot, editable = false, parent = body) {
    const dl = el('dl', undefined, 'export-review-meta');
    for (const [label, value] of reviewFields(snapshot, editable ? destinationChoice(snapshot) : undefined)) {
      const detail = el('dd'); detail.append(value);
      dl.append(el('dt', label), detail);
    }
    parent.append(dl);
  }
  function list(heading, items, getContent, open = false, parent = body) {
    if (!items.length) return;
    const details = el('details', undefined, 'export-review-list'); details.open = open;
    details.append(el('summary', heading + ' · ' + items.length));
    const ul = el('ul');
    for (const item of items) {
      const row = el('li'); row.append(getContent(item)); ul.append(row);
    }
    details.append(ul); parent.append(details);
  }
  const fileName = (path = '') => path.split(/[\\/]/).pop();
  function assetName(item) {
    if (item.display_name) return item.display_name;
    const name = item.name || fileName(item.game_rel) || 'Unnamed asset';
    if (item.file_type === 'material' && /^(?:MI|M|Mat)[_-]/i.test(name)) {
      const part = window.AtelierViewport?.label?.(name);
      if (part && part !== 'Material') return /\bmaterial$/i.test(part) ? part : part + ' material';
    }
    if (item.file_type === 'texture') {
      const part = /^T_(?:\d{4}_)?\d{7}_([a-z][a-z0-9_]+)$/i.exec(name)?.[1];
      if (part) return part.replace(/_D$/i, '').replace(/([a-z])([A-Z])/g, '$1 $2').replace(/_/g, ' ') + ' texture';
    }
    return name;
  }
  function assetRow(item) {
    const row = document.createDocumentFragment();
    const heading = el('div', undefined, 'export-review-asset');
    heading.append(el('strong', assetName(item)));
    if (item.reason) heading.append(el('span', item.reason));
    row.append(heading);
    if (item.game_rel) row.append(el('span', item.game_rel, 'export-review-asset-path'));
    return row;
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
    });
    const options = () => ({ skin_name: state.skinName, author: state.author,
      meshes: offer.meshes.map(mesh => ({ game_rel: mesh.game_rel })) });
    const target = el('dl', undefined, 'export-review-meta');
    for (const [label, value] of [
      ['Hero', (offer.heroLabel ? offer.heroLabel + ' · ' : '') + offer.hero],
      ['Skin', (offer.skinLabel ? offer.skinLabel + ' · ' : '') + offer.skin],
      ['Galacta folder', `/Game/Marvel/ProjectGalacta/Meshes/${offer.hero}/${offer.skin}/${snapshot.modName}/`],
    ]) target.append(el('dt', label), el('dd', value));
    body.append(target, el('p', 'Hero, skin and form come from the edited mesh and cannot be changed. The mod filename is the folder name.', 'export-review-summary'));
    const field = (id, label, key) => {
      const wrap = el('label', undefined, 'skin-swapper-field'); wrap.htmlFor = id;
      const input = document.createElement('input');
      input.type = 'text'; input.id = id; input.className = 'setup-input'; input.maxLength = 64; input.value = state[key];
      input.addEventListener('input', () => { state[key] = input.value; schedule(); });
      wrap.append(el('span', label), input); body.append(wrap);
    };
    field('skin-swapper-name', 'Skin name', 'skinName');
    field('skin-swapper-author', 'Author', 'author');
    const meshes = el('div', undefined, 'skin-swapper-meshes'), forms = new Map();
    for (const mesh of offer.meshes) {
      const name = mesh.name || mesh.game_rel.split('/').pop();
      const row = el('div', undefined, 'skin-swapper-mesh');
      const form = el('span', 'Reading form…', 'skin-swapper-form');
      form.setAttribute('aria-label', 'Hero form for ' + name);
      forms.set(mesh.game_rel, form);
      row.append(el('span', name), form); meshes.append(row);
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
    const build = button(exportLabel(snapshot.copyToMods), () => {
      const chosen = options(), reviewed = current.snapshot;
      current.retry = () => offer.build(chosen, reviewed); current.retry();
    }, true);
    build.id = 'export-review-confirm'; build.disabled = true;
    let timer = 0, request = 0;
    function schedule() { clearTimeout(timer); build.disabled = true; timer = setTimeout(check, 250); }
    async function check() {
      const id = ++request; let result;
      try { result = await offer.plan(options()); } catch (error) { result = { problems: [error.message] }; }
      if (id !== request || !checks.isConnected) return;
      for (const [gameRel, form] of forms) {
        const entry = result?.entries?.find(entry => entry.game_rel === gameRel);
        form.textContent = Number.isInteger(entry?.sculpt)
          ? entry.sculpt === 0 ? 'Form 0 (default)' : 'Form ' + entry.sculpt
          : 'Form unavailable';
      }
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
    reset(swapper ? 'Review Skin Swapper mod' : 'Review mod', 'review'); metadata(snapshot, true);
    if (offer) formatChoice(offer);
    if (swapper) { renderSkinSwapper(offer, note); return; }
    count.textContent = snapshot.included.length + ' of ' + (snapshot.included.length + snapshot.excluded.length) + ' included';
    count.hidden = false;
    body.append(el('p', 'Only saved project edits are included.', 'export-review-summary'));
    list('Included changes', snapshot.included, assetRow, true);
    list('Excluded changes', snapshot.excluded, assetRow, true);
    if (note) {
      const alert = el('p', note, 'export-review-notice'); alert.setAttribute('role', 'alert'); body.append(alert);
    }
    button('Cancel', hide);
    button('Refresh review', callbacks.refresh).id = 'export-review-refresh';
    button(exportLabel(snapshot.copyToMods), () => {
      const reviewed = current.snapshot;
      current.retry = () => callbacks.confirm(reviewed); current.retry();
    }, true).id = 'export-review-confirm';
  }

  function resultMessage(text) {
    const message = el('p', text, 'export-review-summary');
    message.setAttribute('role', 'status');
    return message;
  }
  function warningMessage(snapshot, skipped, copyError) {
    const note = el('div', undefined, 'export-review-warning');
    let heading, message, nextStep;
    if (copyError) {
      heading = 'Installation failed';
      message = copyError;
      nextStep = 'Check the mods folder in Settings, then retry the export and install.';
    } else if (skipped.length) {
      const first = String(skipped[0]);
      const unreadable = /^(.+?): (could not read (?:the )?replacement texture|PNG missing and decode failed)\b/i.exec(first);
      const matching = unreadable && snapshot.included.filter(item =>
        fileName(item.game_rel) === unreadable[1] && item.file_type === 'texture');
      if (skipped.length === 1 && !snapshot.skipped && matching?.length === 1) {
        heading = '1 texture skipped';
        message = assetName(matching[0]) + ' could not be read.';
        nextStep = /^PNG missing/i.test(unreadable[2]) ? 'Re-import this texture and export again.' :
          'Check the replacement image and export again.';
      } else {
        heading = skipped.length === 1 ? '1 build warning' : skipped.length + ' build warnings';
        message = first;
        nextStep = 'Review the build report before testing this mod.';
      }
    } else {
      const selected = snapshot.excluded.find(item => item.selected);
      heading = snapshot.skipped === 1 ? '1 selected edit excluded' : snapshot.skipped + ' selected edits excluded';
      message = selected ? assetName(selected) + ' · ' + selected.reason : '';
      nextStep = 'Review the build report before testing this mod.';
    }
    note.append(el('strong', heading), resultMessage(message), el('p', nextStep));
    return note;
  }
  function copyWithSelection(text) {
    const field = el('textarea', undefined, 'export-review-copy-field');
    const previous = document.activeElement;
    field.value = text; field.readOnly = true; field.tabIndex = -1;
    panel.append(field); field.select();
    try { return document.execCommand('copy'); }
    catch (_) { return false; }
    finally { field.remove(); previous?.focus({preventScroll: true}); }
  }
  function buildReport(snapshot, result, paths, installSections) {
    const applied = result.applied || [], skipped = result.skipped || [];
    const sections = [
      ['Skin Swapper checks that failed', result.problems || []],
      ['Applied operations', applied],
      ['Skipped or warnings', skipped],
      ['Excluded before export', snapshot.excluded.map(excludedText)],
      ...installSections,
    ];
    const totals = [applied.length && applied.length + ' applied', skipped.length && skipped.length + ' skipped',
      snapshot.excluded.length && snapshot.excluded.length + ' excluded'].filter(Boolean);
    const build = el('details', undefined, 'export-review-list');
    const summary = el('summary', 'Build report');
    if (totals.length) summary.append(el('span', ' · ' + totals.join(', '), 'export-review-report-count'));
    const details = el('div', undefined, 'export-review-report-details');
    metadata(snapshot, false, details);
    for (const [heading, items] of sections) list(heading, items, String, true, details);
    build.append(summary, details);

    const receipt = ['Atelier export diagnostics', title.textContent,
      ...[...reviewFields(snapshot), ...paths].map(([label, value]) => label + ': ' + value)];
    if (result.error) receipt.push('', String(result.error));
    for (const [heading, items] of sections) {
      if (items.length) receipt.push('', heading, ...items.map(item => '• ' + item));
    }
    const text = receipt.join('\n');
    const copied = el('p', '', 'export-review-copy-status'); copied.setAttribute('role', 'status');
    const copy = el('button', 'Copy diagnostics', 'btn export-review-copy');
    copy.type = 'button';
    copy.addEventListener('click', async () => {
      let ok = true;
      try { await navigator.clipboard.writeText(text); }
      catch (_) {
        if (!copy.isConnected || !overlay.classList.contains('active')) return;
        ok = copyWithSelection(text);
      }
      if (!copy.isConnected) return;
      copied.textContent = ok ? 'Diagnostics copied.' : 'Could not copy diagnostics. Select the text in the build report to copy it.';
      if (!ok) build.open = true;
    });
    report.append(build, copy, copied);
    report.hidden = false;
  }
  function renderResult() {
    const { snapshot, result, callbacks } = current;
    const built = result.ok || result.built;
    const pending = !!result.install_token;
    const installWarning = result.install_warning;
    const skipped = result.skipped || [];
    const buildWarnings = snapshot.skipped || skipped.length;
    const warning = built && (!result.ok || buildWarnings || pending ||
      Object.values(installWarning || {}).some(items => items.length));
    const suffix = warning && result.ok ? ' with warnings' : '';
    reset(pending ? 'Review install warnings' : built ? (result.installed_dir ? 'Mod installed' + suffix : result.ok ? 'Mod exported' + suffix : 'Export built; copy failed') : result.cancelled ? 'Export cancelled' : 'Export failed',
      built ? warning ? 'warning' : 'success' : 'error', {result: true, stageState: result.cancelled && !built ? 'info' : undefined});
    if (pending) {
      body.append(resultMessage(result.error || 'The built files are in the export folder. Choose whether to copy them to your mods folder.'));
    } else if (built && (!result.ok || buildWarnings)) {
      const copyError = !result.ok ? result.error || 'The mod could not be copied to your mods folder.' : '';
      body.append(warningMessage(snapshot, skipped, copyError));
    } else if (!built) {
      body.append(resultMessage(result.error || (result.cancelled ? 'Export cancelled.' : 'The build could not finish.')));
      body.append(el('p', result.cancelled ? 'Your project edits are preserved.' :
        'Your project edits are preserved. Resolve the error, then retry. Retry checks for existing output first.'));
    } else if (result.kept_export) {
      body.append(resultMessage('The files are saved in the export folder.'));
    }
    const paths = [['Exported file', result.pak_path], ['Installed to', result.installed_dir]].filter(([, path]) => path);
    for (const [label, path] of paths) {
      const output = el('div', undefined, 'export-review-output');
      output.append(el('p', label), el('code', path, 'export-review-path'));
      body.append(output);
    }
    if (result.galacta_folder) {
      paths.push(['Galacta folder', result.galacta_folder]);
      body.append(el('p', 'Galacta folder: ' + result.galacta_folder, 'export-review-path'),
        el('p', 'Load it with the Project Galacta Companion App. Atelier never edits skins.txt; the Companion App manages it.'));
    }
    if (installWarning?.conflicts?.length) {
      body.append(el('p', 'Other enabled mods contain the same packages. The game may load a different version of these packages.'));
    }
    if (installWarning?.unreadable?.length) {
      body.append(el('p', 'The conflict scan is incomplete.', 'export-review-notice'));
    }
    const installSections = [
      ...(installWarning?.conflicts || []).map(conflict => [conflict.mod, conflict.paths]),
      ['Unreadable containers', (installWarning?.unreadable || []).map(item =>
        (item.source === 'export' ? 'Built export · ' : '') + item.file + '\n' + item.reason)],
      ['Matching filenames in your mods folder', installWarning?.replacements || []],
    ];
    for (const [heading, items] of installSections) list(heading, items, String, true);
    list('Skin Swapper checks that failed', result.problems || [], String, true);
    const reportSnapshot = result.kept_export ? {...snapshot, copyToMods: false} : snapshot;
    buildReport(reportSnapshot, result, paths, installSections);
    current.fresh = false;
    if (pending) {
      button('Show exported files', callbacks.reveal).id = 'export-review-reveal';
      button('Keep export only', () => decideInstall(false));
      button('Install anyway', () => decideInstall(true), true);
      return;
    }
    button('Close', hide);
    if (built) button('Show exported files', callbacks.reveal).id = 'export-review-reveal';
    if (!result.ok || result.need_mods_folder) button('Settings', () => { hide(); callbacks.settings(); });
    button('Review current selection', callbacks.refresh).id = 'export-review-refresh';
    if (!result.ok) button('Retry export', current.retry || (() => callbacks.confirm(snapshot)), true).id = 'export-review-retry';
  }
  async function decideInstall(install) {
    if (busy || !current.result?.install_token) return;
    const {snapshot, result, callbacks} = current;
    busy = true;
    reset(install ? 'Checking install warnings…' : 'Keeping export…', 'busy');
    lastButton.textContent = 'View install progress';
    metadata(snapshot);
    button('Hide', hide); panel.focus();
    let next;
    try {
      const response = await callbacks.decideInstall(result.install_token, install);
      next = {...result, install_token: null, ...response, built: true};
    } catch (error) {
      next = {...result, ok: false, built: true, error: error.message};
    }
    window.AtelierExportReview.finish(snapshot, next);
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
      body.append(el('p', snapshot.copyToMods ? 'Building the selected saved edits, then checking for conflicts in your mods folder.' : 'Building the selected saved edits in the export folder.'));
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
      busy = false; current.result = result; current.fresh = true; lastResult = current;
      lastButton.hidden = false; lastButton.disabled = false;
      lastButton.textContent = result.install_token ? 'Review install warnings' : result.ok ? 'View export result' : 'Review export issue';
      renderResult(); show();
    },
    // True when the large stage will draw `state` for the current job: busy only while the dialog
    // is open (it can be hidden mid-build), results always (finish() reopens the dialog).
    staging(state) {
      if (!glyph || !stageHost?.isConnected) return false;
      return state !== 'busy' || overlay.classList.contains('active');
    },
    notice(message) {
      if (!current) return;
      const note = el('p', message, 'export-review-notice'); note.setAttribute('role', 'alert'); body.append(note);
    },
  };
})();
