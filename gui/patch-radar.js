// Game Patch Radar — quiet post-update detection banner & review dialog.
(() => {
  'use strict';

  let dialog = null;
  let opener = null;
  let dismissedProject = '';
  let lastScan = null;

  function formatStamp(iso) {
    if (!iso) return '';
    try {
      const d = new Date(iso);
      return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
    } catch (_) { return iso; }
  }

  function hideBanner() {
    const banner = document.getElementById('patch-radar-banner');
    if (banner) banner.hidden = true;
  }

  function showBanner(data) {
    const banner = document.getElementById('patch-radar-banner');
    if (!banner) return;
    const count = (data.changed?.length || 0) + (data.removed?.length || 0);
    if (!data.needs_attention || !count) {
      banner.hidden = true;
      return;
    }
    const project = window.atelierProject?.() || '';
    if (project && project === dismissedProject) return;
    const summaryEl = document.getElementById('patch-radar-banner-summary');
    if (summaryEl) {
      summaryEl.textContent = `${count} edited asset${count === 1 ? '' : 's'} changed in the latest game files.`;
    }
    banner.hidden = false;
    window.lucide?.createIcons({ nodes: [banner] });
  }

  async function checkQuiet() {
    try {
      const fetchFn = window.atelierFetch || fetch;
      const data = await fetchFn('/api/patch_radar').then(r => r.json());
      if (data?.ok) {
        lastScan = data;
        showBanner(data);
      }
    } catch (_) { /* Advisory check; never interrupt startup or project switches. */ }
  }

  function ensureDialog() {
    if (dialog) return dialog;
    dialog = document.createElement('dialog');
    dialog.id = 'patch-radar-dialog';
    dialog.setAttribute('aria-labelledby', 'pr-title');
    dialog.innerHTML =
      '<div class="pr-head">' +
        '<div><h2 id="pr-title">Game patch radar</h2><p class="pr-sub" id="pr-sub">Checks whether Marvel Rivals updated any vanilla assets your project edits.</p></div>' +
        '<button type="button" class="sb-clear" id="pr-close" title="Close"><i data-lucide="x" size="16"></i></button>' +
      '</div>' +
      '<div class="pr-body" id="pr-body"></div>' +
      '<div class="pr-foot">' +
        '<button type="button" class="btn" id="pr-repatch">Open Repatcher…</button>' +
        '<div class="pr-foot-right">' +
          '<button type="button" class="btn" id="pr-baseline">Mark current patch as baseline</button>' +
          '<button type="button" class="btn primary" id="pr-done">Close</button>' +
        '</div>' +
      '</div>';
    document.body.append(dialog);
    window.lucide?.createIcons({ nodes: [dialog] });

    const close = () => { if (dialog.open) dialog.close(); };
    dialog.querySelector('#pr-close').addEventListener('click', close);
    dialog.querySelector('#pr-done').addEventListener('click', close);
    dialog.addEventListener('click', e => { if (e.target === dialog) close(); });
    dialog.addEventListener('close', () => { if (opener?.isConnected) opener.focus(); });

    dialog.querySelector('#pr-repatch').addEventListener('click', () => {
      close();
      window.openRepatcher?.();
    });
    dialog.querySelector('#pr-baseline').addEventListener('click', async event => {
      const btn = event.currentTarget;
      btn.disabled = true;
      btn.textContent = 'Recording…';
      try {
        const fetchFn = window.atelierFetch || fetch;
        const res = await fetchFn('/api/patch_radar/baseline', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({}),
        }).then(r => r.json());
        if (!res.ok) throw new Error(res.error || 'Could not record baseline.');
        window.toast?.(`Baseline recorded for ${res.tracked_count} asset${res.tracked_count === 1 ? '' : 's'}`, 'success', 4000);
        hideBanner();
        await refreshDialog();
      } catch (err) {
        window.toast?.(err.message, 'error', 5000);
      } finally {
        btn.disabled = false;
        btn.textContent = 'Mark current patch as baseline';
      }
    });
    return dialog;
  }

  function openAssetFromRadar(item) {
    if (dialog?.open) dialog.close();
    const assets = window.AtelierAssetEditors?.projectAssets?.() || [];
    const match = assets.find(a => (a.game_rel || '').toLowerCase() === (item.game_rel || '').toLowerCase());
    if (match && window.handleImportedFileAction) {
      window.handleImportedFileAction(match);
      return;
    }
    if (item.file_type === 'mesh') {
      window.AtelierViewport?.openMesh?.(item.game_rel, item.name);
      return;
    }
    window.toast?.(`Look for ${item.name} in the Mod tray.`, 'info');
  }

  function renderDialog(data) {
    const body = dialog.querySelector('#pr-body');
    const sub = dialog.querySelector('#pr-sub');
    const baselineBtn = dialog.querySelector('#pr-baseline');
    body.replaceChildren();

    const affected = (data.changed?.length || 0) + (data.removed?.length || 0);
    sub.textContent = data.has_baseline
      ? `Baseline recorded ${formatStamp(data.recorded_at)} · ${data.summary}`
      : data.summary;
    baselineBtn.textContent = data.has_baseline ? 'Mark current patch reviewed' : 'Record baseline now';

    const stats = document.createElement('div');
    stats.className = 'pr-stats';
    const addStat = (label, cls = '') => {
      const el = document.createElement('span');
      el.className = 'pr-stat' + (cls ? ' ' + cls : '');
      el.textContent = label;
      stats.append(el);
    };
    if (data.has_baseline) {
      addStat(`${data.changed?.length || 0} changed`, (data.changed?.length || 0) ? 'is-warn' : 'is-ok');
      if (data.removed?.length) addStat(`${data.removed.length} missing`, 'is-warn');
      addStat(`${data.unchanged_count || 0} unchanged`, 'is-ok');
    } else {
      addStat(`${data.unchanged_count || 0} project edits ready to track`);
    }
    body.append(stats);

    const allFlagged = [...(data.removed || []), ...(data.changed || [])];
    if (!allFlagged.length) {
      const ok = document.createElement('div');
      ok.className = 'pr-card';
      ok.textContent = data.has_baseline
        ? 'No vanilla targets for this project changed since your last baseline. Your edits are up to date with the current game patch.'
        : 'Once you export a mod (or click Record baseline now), Atelier tracks lightweight pak fingerprints for your edited targets so future game updates flag only what actually changed.';
      body.append(ok);
      return;
    }

    const list = document.createElement('div');
    list.className = 'pr-list';
    for (const item of allFlagged) {
      const card = document.createElement('div');
      card.className = 'pr-card';

      const top = document.createElement('div');
      top.className = 'pr-card-top';
      const title = document.createElement('span');
      title.className = 'pr-card-title';
      title.textContent = item.name;
      const risk = document.createElement('span');
      risk.className = 'pr-risk';
      risk.dataset.risk = item.risk || 'medium';
      risk.textContent = `${item.risk || 'medium'} impact`;
      top.append(title, risk);

      const reason = document.createElement('div');
      reason.className = 'pr-card-reason';
      reason.textContent = item.reason;

      const advice = document.createElement('div');
      advice.className = 'pr-card-advice';
      advice.textContent = item.advice;

      const path = document.createElement('div');
      path.className = 'pr-card-path';
      path.textContent = item.game_rel;

      const actions = document.createElement('div');
      actions.className = 'pr-card-actions';
      const openBtn = document.createElement('button');
      openBtn.type = 'button';
      openBtn.className = 'btn';
      openBtn.textContent = 'Inspect asset';
      openBtn.addEventListener('click', () => openAssetFromRadar(item));
      actions.append(openBtn);

      card.append(top, reason, advice, path, actions);
      list.append(card);
    }
    body.append(list);
  }

  async function refreshDialog() {
    ensureDialog();
    const body = dialog.querySelector('#pr-body');
    body.innerHTML = '<div class="pr-card">Scanning edited targets against current game files…</div>';
    try {
      const fetchFn = window.atelierFetch || fetch;
      const data = await fetchFn('/api/patch_radar').then(r => r.json());
      if (!data.ok) throw new Error(data.error || 'Scan failed.');
      lastScan = data;
      showBanner(data);
      renderDialog(data);
    } catch (err) {
      body.innerHTML = `<div class="pr-card">${err.message}</div>`;
    }
  }

  async function open(triggerEl) {
    ensureDialog();
    opener = triggerEl || document.activeElement;
    if (!dialog.open) dialog.showModal();
    await refreshDialog();
  }

  document.getElementById('patch-radar-inspect')?.addEventListener('click', event => open(event.currentTarget));
  document.getElementById('patch-radar-dismiss')?.addEventListener('click', () => {
    dismissedProject = window.atelierProject?.() || '';
    hideBanner();
  });

  window.AtelierPatchRadar = Object.freeze({ open, checkQuiet, hideBanner, lastScan: () => lastScan });
})();
