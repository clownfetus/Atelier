// One-click D/S processing; shared S targets ask for a D map instead of guessing.
(() => {
  'use strict';
  const button = document.getElementById('process-s-maps'), wrap = document.getElementById('process-s-maps-wrap');
  const hint = document.getElementById('process-s-maps-hint');
  const PAIRING = 'Recolours each S map from the D map in its folder (bicubic resize, Color blend at 100%; S size and alpha are kept). Keep both the D and S maps ticked in your Mod tray so the mod ships them together.';
  let busy = false, hasDiffuse = false, plan = null, project = '', overlay, panel, rows, status, applyButton;
  const el = (tag, text, cls) => window.AtelierJobDialogs.el(tag, text, cls);
  function setBusy(value) {
    busy = value; button.disabled = busy || !hasDiffuse;
    wrap.title = hint.textContent = hasDiffuse ? PAIRING : 'Needs a D map (a texture ending in _D) in your Mod tray first. ' + PAIRING;
    button.textContent = busy ? 'Processing S maps…' : 'Process S maps';
    if (applyButton) applyButton.disabled = busy || !plan ||
      [...rows.querySelectorAll('select')].some(select => !select.value);
  }
  function close() { overlay?.classList.remove('active'); button.focus(); }
  function init() {
    overlay = el('div', undefined, 'overlay'); overlay.id = 's-maps-overlay';
    panel = el('section', undefined, 'modal s-maps-modal'); panel.tabIndex = -1;
    panel.setAttribute('role', 'dialog'); panel.setAttribute('aria-modal', 'true');
    panel.setAttribute('aria-labelledby', 's-maps-title');
    const heading = el('h2', 'Choose shared S-map pairings'); heading.id = 's-maps-title';
    panel.append(heading, el('p', 'Several edited D maps share an S map. Choose which D supplies its color, or skip that S map.'));
    rows = el('div', undefined, 's-maps-pairings');
    status = el('p', '', 's-maps-status'); status.setAttribute('role', 'status');
    const actions = el('div', undefined, 'bulk-actions');
    const cancel = el('button', 'Close', 'btn'); cancel.type = 'button'; cancel.addEventListener('click', close);
    applyButton = el('button', 'Process S maps', 'btn primary'); applyButton.type = 'button';
    applyButton.addEventListener('click', () => apply(Object.fromEntries(
      [...rows.querySelectorAll('select')].map(select => [select.dataset.surface, select.value]))));
    actions.append(cancel, applyButton); panel.append(rows, status, actions);
    overlay.append(panel); document.body.append(overlay);
    window.AtelierJobDialogs.trap(overlay, panel, close);
  }
  function showPairing(result) {
    if (!overlay) init();
    rows.replaceChildren();
    for (const row of result.pairs.filter(row => row.candidates.length > 1)) {
      const label = el('label', row.s, 's-maps-pairing');
      const select = el('select'); select.dataset.surface = row.s;
      const prompt = el('option', 'Choose D map…'); prompt.value = ''; prompt.disabled = true; prompt.selected = true;
      select.append(prompt);
      for (const path of row.candidates) {
        const option = el('option', path); option.value = path; select.append(option);
      }
      const skip = el('option', 'Skip this S map'); skip.value = 'skip'; select.append(skip);
      select.addEventListener('change', () => setBusy(false)); label.append(select); rows.append(label);
    }
    status.textContent = `${result.pairs.length} S maps found; ${result.skipped.length} D maps have no usable match. ` +
      'D files stay unchanged. S dimensions and alpha are preserved.';
    overlay.classList.add('active'); panel.focus(); setBusy(false);
  }
  async function run(path, body = {}) {
    const result = await (window.AtelierJobs?.run || window.api)(path, {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body), project});
    if (!result.ok) throw Error(result.error || 'S-map processing failed');
    return result;
  }
  function failure(error) {
    if (overlay?.classList.contains('active')) status.textContent = error.message;
    window.dispatchEvent(new CustomEvent('atelier-s-maps-error', {detail:{project, error:error.message}}));
    plan = null; setBusy(false);
  }
  async function apply(choices = {}) {
    if (busy || !plan) return;
    if (project !== window.atelierProject()) { failure(Error('Project changed. Click Process S maps again.')); return; }
    setBusy(true);
    try {
      const result = await run('/api/s_maps/process', {plan_id:plan.plan_id, choices});
      plan = null;
      overlay?.classList.remove('active');
      window.dispatchEvent(new CustomEvent('atelier-s-maps-processed', {detail:{...result, project}}));
    } catch (error) { failure(error); }
    finally { setBusy(false); }
  }
  window.AtelierSMapsUI = {
    update(items) {
      hasDiffuse = items.some(item => item.file_type === 'texture' && /_d$/i.test(item.game_rel));
      setBusy(busy);
    },
    async process() {
      if (busy || !hasDiffuse) return;
      project = window.atelierProject(); plan = null; setBusy(true);
      try {
        const result = await run('/api/s_maps/plan');
        if (project !== window.atelierProject()) throw Error('Project changed. Click Process S maps again.');
        plan = result; setBusy(false);
        if (result.pairs.some(row => row.candidates.length > 1)) showPairing(result);
        else await apply();
      } catch (error) { failure(error); }
    },
  };
  setBusy(false);
})();
