/* Review each affected file before committing a recoverable batch save. */
(function () {
  'use strict';
  let overlay, panel, body, controls, choices, status, applyButton, previewButton, title, intro, hint;
  let source, operation, scope, factor, color, value, parameter, materialSource, sourceResults;
  let selectAll, selectNone, selectionCount, sourceTimer, searchRevision = 0;
  let project, sources, items = [], previewId, busy = false, opener, projectLine, materials = false;
  const el = (...args) => window.AtelierJobDialogs.el(...args);
  function select(id, label, values) {
    const wrapper = el('label', label), input = el('select'); input.id = id;
    values.forEach(([value, text]) => { const option = el('option', text); option.value = value; input.append(option); });
    wrapper.append(input); controls.append(wrapper); input.addEventListener('change', invalidate); return input;
  }
  function invalidate() {
    previewId = null; applyButton.disabled = true;
    factor.parentElement.hidden = operation.value !== 'multiply';
    scope.parentElement.hidden = operation.value !== 'multiply';
    color.parentElement.hidden = operation.value !== 'recolor';
    value.parentElement.hidden = !['set_opacity', 'set_scalar'].includes(operation.value);
    parameter.parentElement.hidden = operation.value !== 'set_scalar';
    materialSource.parentElement.hidden = !['reparent', 'replace_material'].includes(operation.value);
    value.min = operation.value === 'set_opacity' ? '0' : '';
    value.max = operation.value === 'set_opacity' ? '1' : '';
    hint.textContent = ({
      set_opacity: 'Updates existing Opacity and OpacityMultiplier scalar overrides. Materials without either stay unchanged. Choose Set scalar for another parameter name.',
      set_scalar: 'Matches an existing scalar override by its full name, ignoring letter case. Missing parameters are listed as unchanged.',
      reparent: 'Changes the parent while keeping this material’s parameters and textures. Choose a parent whose shader supports those overrides.',
      replace_material: 'Copies the source’s full game material, including its parent, textures, parameters and shader settings. Clears each changed target’s custom texture, dye and intensity options.',
    })[operation.value] || 'RGB edits preserve alpha. Multiply all channels also changes scalar values.';
    body.replaceChildren();
    const count = choices.querySelectorAll('input:checked').length;
    selectionCount.textContent = count + ' of ' + items.length + ' selected';
    selectAll.disabled = busy || count === items.length;
    selectNone.disabled = busy || count === 0;
    status.textContent = count > 1000 ? 'Choose up to 1,000 assets per batch.' : 'Review the batch before saving.';
    previewButton.disabled = busy || count === 0 || count > 1000;
  }
  function selectItems(checked) {
    choices.querySelectorAll('input').forEach(input => { input.checked = checked; }); invalidate();
  }
  function listItems() {
    items = sources[source.value] || [];
    choices.replaceChildren();
    for (const item of items) {
      const label = el('label', undefined, 'bulk-choice'), input = el('input'); input.type = 'checkbox'; input.checked = true; input.value = item.game_rel;
      input.addEventListener('change', invalidate);
      const text = el('span', item.name || item.game_rel.split('/').pop()); text.append(el('div', item.game_rel, 'bulk-path'));
      label.append(input, text); choices.append(label);
    }
    if (!items.length) choices.append(el('p', materials ? 'No materials in this selection. Choose another asset source or browse a material folder.' : 'No VFX or curve assets in this selection. Browse a VFX/curve folder or edit assets first.'));
    invalidate();
  }
  function hide() {
    clearTimeout(sourceTimer); ++searchRevision;
    overlay.classList.remove('active'); if (opener?.isConnected) opener.focus();
  }
  function searchSource() {
    invalidate(); clearTimeout(sourceTimer); const revision = ++searchRevision;
    sourceResults.hidden = true;
    const query = materialSource.value.trim(), owner = project, op = operation.value;
    if (query.length < 2) return;
    sourceTimer = setTimeout(async () => {
      try {
        const response = await window.atelierFetch('/api/material_sources?q=' + encodeURIComponent(query) + (op === 'reparent' ? '&parents=true' : ''), {}, owner);
        const result = await response.json();
        if (revision !== searchRevision || owner !== project || !overlay.classList.contains('active')) return;
        if (!result.ok) throw new Error(result.error || 'Could not search materials');
        sourceResults.replaceChildren(...(result.materials || []).map(path => {
          const option = el('option', path); option.value = path; option.title = path; return option;
        }));
        sourceResults.selectedIndex = -1; sourceResults.hidden = !sourceResults.options.length;
      } catch (error) { if (revision === searchRevision) status.textContent = error.message + '. You can paste a full material path.'; }
    }, 250);
  }
  function init() {
    overlay = el('div', undefined, 'overlay bulk-overlay'); overlay.id = 'bulk-overlay';
    panel = el('section', undefined, 'modal bulk-modal'); panel.tabIndex = -1;
    panel.setAttribute('role', 'dialog'); panel.setAttribute('aria-modal', 'true'); panel.setAttribute('aria-labelledby', 'bulk-title');
    title = el('h2'); title.id = 'bulk-title';
    projectLine = el('p', undefined, 'muted');
    intro = el('p');
    controls = el('div', undefined, 'bulk-controls');
    source = select('bulk-source', 'Assets', [['edited', 'Selected edited assets'], ['folder', 'Current folder']]);
    operation = select('bulk-operation', 'Operation', [['multiply', 'Multiply values'], ['recolor', 'Replace RGB']]);
    scope = select('bulk-scope', 'Channels', [['rgb', 'Color RGB only'], ['alpha', 'Alpha only'], ['all', 'All channels and scalars']]);
    const factorLabel = el('label', 'Multiplier'); factor = el('input'); factor.id = 'bulk-factor'; factor.type = 'number'; factor.step = 'any'; factor.value = '1.2'; factorLabel.append(factor); controls.append(factorLabel);
    const colorLabel = el('label', 'New RGB'); color = el('input'); color.id = 'bulk-color'; color.type = 'color'; color.value = '#66bbee'; colorLabel.append(color); controls.append(colorLabel);
    const valueLabel = el('label', 'New value'); value = el('input'); value.id = 'bulk-value'; value.type = 'number'; value.step = 'any'; value.value = '0'; valueLabel.append(value); controls.append(valueLabel);
    const parameterLabel = el('label', 'Scalar name'); parameter = el('input'); parameter.id = 'bulk-parameter'; parameter.placeholder = 'e.g. OpacityMultiplier'; parameterLabel.append(parameter); controls.append(parameterLabel);
    const sourceLabel = el('label', 'Find or paste a material path', 'bulk-material-source'); materialSource = el('input'); materialSource.id = 'bulk-material-source'; materialSource.type = 'search'; materialSource.placeholder = 'Character, material name or /Game/Marvel/…'; sourceLabel.append(materialSource);
    sourceResults = el('select'); sourceResults.id = 'bulk-source-results'; sourceResults.size = 4; sourceResults.hidden = true; sourceResults.setAttribute('aria-label', 'Matching material sources'); sourceLabel.append(sourceResults); controls.append(sourceLabel);
    materialSource.addEventListener('input', searchSource);
    sourceResults.addEventListener('change', () => { materialSource.value = sourceResults.value; ++searchRevision; clearTimeout(sourceTimer); sourceResults.hidden = true; invalidate(); });
    operation.addEventListener('change', () => { ++searchRevision; clearTimeout(sourceTimer); sourceResults.hidden = true; });
    value.addEventListener('input', invalidate); parameter.addEventListener('input', invalidate);
    factor.addEventListener('input', invalidate); color.addEventListener('input', invalidate);
    source.addEventListener('change', listItems);
    hint = el('p', undefined, 'bulk-hint');
    const selectionTools = el('div', undefined, 'bulk-selection-tools');
    selectionCount = el('span'); selectionCount.id = 'bulk-selection-count'; selectionCount.setAttribute('aria-live', 'polite');
    selectAll = el('button', 'Select all', 'btn'); selectAll.id = 'bulk-select-all'; selectAll.type = 'button'; selectAll.addEventListener('click', () => selectItems(true));
    selectNone = el('button', 'Clear selection', 'btn'); selectNone.id = 'bulk-select-none'; selectNone.type = 'button'; selectNone.addEventListener('click', () => selectItems(false));
    selectionTools.append(selectionCount, selectAll, selectNone);
    choices = el('div', undefined, 'bulk-list'); choices.id = 'bulk-list';
    choices.setAttribute('role', 'group'); choices.setAttribute('aria-label', 'Assets to edit');
    body = el('div', undefined, 'bulk-body'); body.id = 'bulk-results';
    status = el('p'); status.id = 'bulk-status'; status.setAttribute('role', 'status');
    const actions = el('div', undefined, 'bulk-actions'), close = el('button', 'Close', 'btn'); close.id = 'bulk-close'; close.addEventListener('click', hide);
    const activity = el('button', 'Activity', 'btn'); activity.addEventListener('click', () => { hide(); document.getElementById('job-activity').click(); });
    previewButton = el('button', 'Review batch', 'btn'); previewButton.id = 'bulk-preview'; previewButton.addEventListener('click', preview);
    applyButton = el('button', 'Save reviewed edits', 'btn primary'); applyButton.id = 'bulk-apply'; applyButton.disabled = true; applyButton.addEventListener('click', apply);
    actions.append(activity, close, previewButton, applyButton); panel.append(title, projectLine, intro, controls, hint, selectionTools, choices, body, status, actions); overlay.append(panel); document.body.append(overlay);
    panel.addEventListener('keydown', event => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
        event.preventDefault(); event.stopPropagation();
        if (!applyButton.disabled) apply();
      }
      if (!busy && (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'a' &&
          !event.target.closest('input:not([type="checkbox"]), textarea, select, [contenteditable="true"]')) {
        event.preventDefault(); selectItems(true);
      }
    });
    window.AtelierJobDialogs.trap(overlay, panel, hide);
  }
  function inputSpec() {
    if (['reparent', 'replace_material'].includes(operation.value)) {
      const source = materialSource.value.trim();
      if (!source) throw new Error('Choose or paste a material path.');
      return {operation: operation.value, source};
    }
    if (['set_opacity', 'set_scalar'].includes(operation.value)) {
      if (!value.value.trim() || !Number.isFinite(Number(value.value))) throw new Error('Enter a finite value.');
      if (operation.value === 'set_opacity' && (Number(value.value) < 0 || Number(value.value) > 1)) throw new Error('Opacity must be between 0 and 1.');
      if (operation.value === 'set_scalar' && !parameter.value.trim()) throw new Error('Enter the full scalar name.');
      return {operation: operation.value, value: Number(value.value), parameter: parameter.value.trim()};
    }
    if (operation.value === 'recolor') return {operation: 'recolor', color: [1,3,5].map(i => parseInt(color.value.slice(i,i+2),16)/255)};
    const multiplier = factor.value.trim();
    if (!multiplier || !Number.isFinite(Number(multiplier))) throw new Error('Enter a finite multiplier.');
    return {operation: 'multiply', scope: scope.value, factor: Number(multiplier)};
  }
  function setBusy(value) {
    const focusedInside = panel.contains(document.activeElement);
    busy = value; panel.setAttribute('aria-busy', String(value));
    controls.querySelectorAll('input,select').forEach(node => { node.disabled = value; });
    choices.querySelectorAll('input').forEach(node => { node.disabled = value; });
    const count = choices.querySelectorAll('input:checked').length;
    selectAll.disabled = value || count === items.length; selectNone.disabled = value || count === 0;
    previewButton.disabled = value || count === 0 || count > 1000; applyButton.disabled = value || !previewId;
    if (focusedInside && overlay.classList.contains('active') &&
        (!panel.contains(document.activeElement) || document.activeElement.disabled)) panel.focus();
  }
  async function run(path, payload) {
    return window.AtelierJobs.run(path, {project, method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload)});
  }
  async function preview() {
    if (busy) return;
    previewId = null;
    try {
      if (project !== window.atelierProject()) throw new Error('Project changed. Close and reopen the batch editor.');
      const selected = [...choices.querySelectorAll('input:checked')].map(input => input.value);
      if (!selected.length) throw new Error('Select at least one asset.');
      const edit = inputSpec(); previewId = null; setBusy(true); status.textContent = 'Reading selected assets…'; body.replaceChildren();
      const result = await run('/api/bulk/preview', {items:selected, edit});
      if (!result.ok) throw new Error(result.error || 'Review failed');
      const table = el('table', undefined, 'bulk-results'), head = el('tr');
      ['Asset', 'Values changed', 'Example'].forEach(text => head.append(el('th', text))); table.append(head);
      for (const row of result.assets) {
        const tr = el('tr'), cell = el('td', row.game_rel.split('/').pop());
        cell.append(el('div', row.game_rel, 'bulk-path'));
        if (row.global) cell.append(el('p', 'Global collection: affects every referencing material.', 'warning'));
        tr.append(cell, el('td', String(row.changes)), el('td', row.note || (row.sample ? row.sample.before + ' → ' + row.sample.after : 'Already at the requested value')));
        table.append(tr);
      }
      body.append(table); previewId = result.changed_assets ? result.preview_id : null;
      status.textContent = result.changed_assets + ' assets · ' + result.changed_values + ' values will change. ' + (result.assets.length - result.changed_assets) + ' unchanged. Review expires in 15 minutes.';
    } catch (error) { previewId = null; status.textContent = error.message; }
    finally { setBusy(false); }
  }
  async function apply() {
    if (!previewId || busy) return;
    try {
      if (project !== window.atelierProject()) throw new Error('Project changed. Close and reopen the batch editor.');
      setBusy(true); status.textContent = 'Saving reviewed project edits…';
      const result = await run('/api/bulk/apply', {preview_id:previewId});
      previewId = null;
      if (!result.ok) throw new Error(result.error || 'Save failed');
      status.textContent = 'Saved ' + result.changed_assets + ' assets. Export the project to build a mod.';
      window.dispatchEvent(new CustomEvent('atelier-bulk-saved', {detail:{project, assets: result.assets}}));
    } catch (error) { previewId = null; status.textContent = error.message; }
    finally { setBusy(false); }
  }
  window.AtelierBulkEdit = {
    open(selection, projectName, options = {}) {
      if (!overlay) init();
      if (busy) { overlay.classList.add('active'); panel.focus(); return; }
      opener = document.activeElement; sources = selection; project = projectName;
      ++searchRevision; clearTimeout(sourceTimer); sourceResults.hidden = true;
      materials = options.kind === 'material';
      title.textContent = materials ? 'Bulk edit materials' : 'Bulk VFX / curve editing';
      intro.textContent = 'Select assets, choose a change and review every affected file before saving. Export the project separately to build a mod.';
      const operations = materials ? [['set_opacity', 'Set opacity'], ['set_scalar', 'Set scalar'], ['reparent', 'Change parent'], ['replace_material', 'Replace material'], ['multiply', 'Multiply values'], ['recolor', 'Replace RGB']] : [['multiply', 'Multiply values'], ['recolor', 'Replace RGB']];
      operation.replaceChildren(...operations.map(([value, text]) => { const option = el('option', text); option.value = value; return option; }));
      projectLine.textContent = 'Project: ' + (projectName || 'Default project');
      source.value = options.source || (selection.edited.length ? 'edited' : 'folder');
      body.replaceChildren(); listItems(); overlay.classList.add('active'); panel.focus();
    },
  };
})();
