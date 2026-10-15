/* Review each affected file before committing a recoverable batch save. */
(function () {
  'use strict';
  let overlay, panel, body, controls, choices, status, applyButton, previewButton;
  let source, operation, scope, factor, color, project, sources, items = [], previewId, busy = false, opener, projectLine;
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
    status.textContent = 'Review the batch before saving.';
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
    if (!items.length) choices.append(el('p', 'No VFX or curve assets in this selection. Browse a VFX/curve folder or edit assets first.'));
    invalidate();
  }
  function hide() {
    overlay.classList.remove('active'); if (opener?.isConnected) opener.focus();
  }
  function init() {
    overlay = el('div', undefined, 'overlay bulk-overlay'); overlay.id = 'bulk-overlay';
    panel = el('section', undefined, 'modal bulk-modal'); panel.tabIndex = -1;
    panel.setAttribute('role', 'dialog'); panel.setAttribute('aria-modal', 'true'); panel.setAttribute('aria-labelledby', 'bulk-title');
    const title = el('h2', 'Bulk VFX / curve editing'); title.id = 'bulk-title';
    projectLine = el('p', undefined, 'muted');
    const intro = el('p', 'Multiply values or replace RGB across selected assets. Review shows affected files and value counts. Saves update project edits; export separately to build a mod.');
    controls = el('div', undefined, 'bulk-controls');
    source = select('bulk-source', 'Assets', [['edited', 'Selected edited assets'], ['folder', 'Current folder']]);
    operation = select('bulk-operation', 'Operation', [['multiply', 'Multiply values'], ['recolor', 'Replace RGB']]);
    scope = select('bulk-scope', 'Channels', [['rgb', 'Color RGB only'], ['alpha', 'Alpha only'], ['all', 'All channels and scalars']]);
    const factorLabel = el('label', 'Multiplier'); factor = el('input'); factor.id = 'bulk-factor'; factor.type = 'number'; factor.step = 'any'; factor.value = '1.2'; factorLabel.append(factor); controls.append(factorLabel);
    const colorLabel = el('label', 'New RGB'); color = el('input'); color.id = 'bulk-color'; color.type = 'color'; color.value = '#66bbee'; colorLabel.append(color); controls.append(colorLabel);
    factor.addEventListener('input', invalidate); color.addEventListener('input', invalidate);
    source.addEventListener('change', listItems);
    choices = el('div', undefined, 'bulk-list'); choices.id = 'bulk-list';
    body = el('div', undefined, 'bulk-body'); body.id = 'bulk-results';
    status = el('p'); status.id = 'bulk-status'; status.setAttribute('role', 'status');
    const actions = el('div', undefined, 'bulk-actions'), close = el('button', 'Close', 'btn'); close.id = 'bulk-close'; close.addEventListener('click', hide);
    const activity = el('button', 'Activity', 'btn'); activity.addEventListener('click', () => { hide(); document.getElementById('job-activity').click(); });
    previewButton = el('button', 'Review batch', 'btn'); previewButton.id = 'bulk-preview'; previewButton.addEventListener('click', preview);
    applyButton = el('button', 'Save reviewed edits', 'btn primary'); applyButton.id = 'bulk-apply'; applyButton.disabled = true; applyButton.addEventListener('click', apply);
    actions.append(activity, close, previewButton, applyButton); panel.append(title, projectLine, intro, controls, choices, body, status, actions); overlay.append(panel); document.body.append(overlay);
    window.AtelierJobDialogs.trap(overlay, panel, hide);
  }
  function inputSpec() {
    if (operation.value === 'recolor') return {operation: 'recolor', color: [1,3,5].map(i => parseInt(color.value.slice(i,i+2),16)/255)};
    const value = factor.value.trim();
    if (!value || !Number.isFinite(Number(value))) throw new Error('Enter a finite multiplier.');
    return {operation: 'multiply', scope: scope.value, factor: Number(value)};
  }
  function setBusy(value) {
    busy = value; panel.setAttribute('aria-busy', String(value));
    controls.querySelectorAll('input,select').forEach(node => { node.disabled = value; });
    choices.querySelectorAll('input').forEach(node => { node.disabled = value; });
    previewButton.disabled = value; applyButton.disabled = value || !previewId;
  }
  async function run(path, payload) {
    return window.AtelierJobs.run(path, {project, method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload)});
  }
  async function preview() {
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
        tr.append(cell, el('td', String(row.changes)), el('td', row.sample ? row.sample.before + ' → ' + row.sample.after : 'Unchanged'));
        table.append(tr);
      }
      body.append(table); previewId = result.changed_assets ? result.preview_id : null;
      status.textContent = result.changed_assets + ' assets · ' + result.changed_values + ' values will change. Alpha stays unchanged for RGB edits. Preview expires in 15 minutes.';
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
      window.dispatchEvent(new CustomEvent('atelier-bulk-saved', {detail:{project}}));
    } catch (error) { previewId = null; status.textContent = error.message; }
    finally { setBusy(false); }
  }
  window.AtelierBulkEdit = {
    open(selection, projectName) {
      if (!overlay) init();
      if (busy) { overlay.classList.add('active'); panel.focus(); return; }
      opener = document.activeElement; sources = selection; project = projectName;
      projectLine.textContent = 'Project: ' + (projectName || 'Default project');
      source.value = selection.edited.length ? 'edited' : 'folder';
      body.replaceChildren(); listItems(); overlay.classList.add('active'); panel.focus();
    },
  };
})();
