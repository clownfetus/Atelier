// Shared-asset warning banner (Material Editor) and Where-is-this-used / Safe Fork dialog.
(() => {
  'use strict';

  let dialog = null;
  let opener = null;
  let activeCheckId = 0;

  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  function ensureDialog() {
    if (dialog) return dialog;
    dialog = document.createElement('dialog');
    dialog.id = 'asset-refs-dialog';
    dialog.setAttribute('aria-labelledby', 'ar-title');
    dialog.innerHTML =
      '<div class="ar-head">' +
        '<div><h2 id="ar-title">Where is this asset used?</h2><p class="ar-path" id="ar-path"></p></div>' +
        '<button type="button" class="sb-clear" id="ar-close" title="Close"><i data-lucide="x" size="16"></i></button>' +
      '</div>' +
      '<div class="ar-body" id="ar-body"></div>' +
      '<div class="ar-foot"><button type="button" class="btn" id="ar-done">Close</button></div>';
    document.body.append(dialog);
    window.lucide?.createIcons({ nodes: [dialog] });

    const close = () => { if (dialog.open) dialog.close(); };
    dialog.querySelector('#ar-close').addEventListener('click', close);
    dialog.querySelector('#ar-done').addEventListener('click', close);
    dialog.addEventListener('click', e => { if (e.target === dialog) close(); });
    dialog.addEventListener('close', () => { if (opener?.isConnected) opener.focus(); });
    return dialog;
  }

  async function runSafeFork(gameRel, fileType, customName, triggerBtn) {
    if (triggerBtn) { triggerBtn.disabled = true; triggerBtn.textContent = 'Creating private copy…'; }
    try {
      const fetchFn = window.atelierFetch || fetch;
      const res = await fetchFn('/api/asset_refs/fork', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          game_rel: gameRel,
          file_type: fileType || undefined,
          name: (customName || '').trim() || undefined,
        }),
      }).then(r => r.json());
      if (!res.ok) throw new Error(res.error || 'Could not create a private copy.');
      window.toast?.(res.hint || 'Private copy added to your project.', 'success', 6000);
      window.dispatchEvent(new CustomEvent('atelier-asset-added', { detail: res.asset }));
      window.loadSidebar?.();
      if (dialog?.open) dialog.close();
      return res;
    } catch (err) {
      window.toast?.(err.message || 'Safe Fork failed.', 'error', 6000);
      return null;
    } finally {
      if (triggerBtn && triggerBtn.isConnected) {
        triggerBtn.disabled = false;
        triggerBtn.textContent = 'Make private copy';
      }
    }
  }

  async function openUsage(gameRel, triggerEl) {
    if (!gameRel) return;
    ensureDialog();
    opener = triggerEl || document.activeElement;
    dialog.querySelector('#ar-title').textContent = `Where is ${gameRel.split('/').pop()} used?`;
    dialog.querySelector('#ar-path').textContent = gameRel;
    const body = dialog.querySelector('#ar-body');
    body.innerHTML = '<div class="ar-summary">Checking costume buckets and cached references…</div>';
    if (!dialog.open) dialog.showModal();

    try {
      const fetchFn = window.atelierFetch || fetch;
      const data = await fetchFn(`/api/asset_refs?game_rel=${encodeURIComponent(gameRel)}&deep=1`).then(r => r.json());
      if (!data.ok) throw new Error(data.error || 'Could not inspect references.');
      renderUsageBody(body, data);
    } catch (err) {
      body.innerHTML = `<div class="ar-summary">${esc(err.message)}</div>`;
    }
  }

  function renderUsageBody(body, data) {
    body.replaceChildren();

    const summary = document.createElement('div');
    summary.className = 'ar-summary' + (data.is_shared ? ' is-shared' : '');
    summary.textContent = data.summary;
    body.append(summary);

    const skins = data.affected_skins || [];
    if (skins.length) {
      const sec = document.createElement('section');
      sec.className = 'ar-section';
      const h3 = document.createElement('h3');
      h3.textContent = skins.length === 1 ? 'Costume scope' : `Potentially affected costumes (${skins.length})`;
      const chips = document.createElement('div');
      chips.className = 'ar-chips';
      for (const skin of skins) {
        const chip = document.createElement('span');
        chip.className = 'ar-chip';
        chip.textContent = skin.label || skin.skin_id;
        chips.append(chip);
      }
      sec.append(h3, chips);
      body.append(sec);
    }

    const refs = data.verified_referrers || [];
    const details = document.createElement('details');
    details.className = 'ar-refs-details';
    details.open = refs.length > 0 && refs.length <= 8;
    const sum = document.createElement('summary');
    sum.textContent = refs.length
      ? `Verified references in inspected assets (${refs.length})`
      : 'No cached materials or meshes reference this path yet';
    details.append(sum);
    if (refs.length) {
      const ul = document.createElement('ul');
      ul.className = 'ar-ref-list';
      for (const ref of refs) {
        const li = document.createElement('li');
        const strong = document.createElement('strong');
        strong.textContent = `${ref.name}${ref.skin_label ? ` · ${ref.skin_label}` : ''}`;
        const code = document.createElement('code');
        code.textContent = ref.game_rel;
        li.append(strong, code);
        ul.append(li);
      }
      details.append(ul);
    }
    body.append(details);

    if (data.fork?.forkable) {
      const forkBox = document.createElement('div');
      forkBox.className = 'ar-fork-box';
      const title = document.createElement('strong');
      title.textContent = 'Want to edit this safely for one costume?';
      const desc = document.createElement('p');
      desc.textContent = `Creates an independent copy under /Game/Marvel/${data.fork.folder}/ so other costumes keep their original look.`;
      const fields = document.createElement('div');
      fields.className = 'ar-fork-fields';
      const input = document.createElement('input');
      input.type = 'text';
      input.className = 'ar-fork-input';
      input.value = data.fork.name;
      input.setAttribute('aria-label', 'Private copy asset name');
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'btn primary';
      btn.textContent = 'Make private copy';
      btn.addEventListener('click', () => runSafeFork(data.game_rel, data.file_type, input.value, btn));
      fields.append(input, btn);
      forkBox.append(title, desc, fields);
      body.append(forkBox);
    }
  }

  function clearMaterialBanner() {
    activeCheckId++;
    const banner = document.getElementById('mat-shared-banner');
    if (banner) { banner.hidden = true; banner.replaceChildren(); }
  }

  async function checkMaterial(gameRel) {
    clearMaterialBanner();
    const banner = document.getElementById('mat-shared-banner');
    if (!banner || !gameRel) return;
    const token = ++activeCheckId;
    try {
      const fetchFn = window.atelierFetch || fetch;
      const data = await fetchFn(`/api/asset_refs?game_rel=${encodeURIComponent(gameRel)}&deep=0`).then(r => r.json());
      if (token !== activeCheckId || !data?.ok || !data.is_shared) return;
      banner.replaceChildren();
      const copy = document.createElement('div');
      copy.className = 'shared-banner-copy';
      copy.innerHTML = '<i data-lucide="alert-triangle" size="15"></i>';
      const span = document.createElement('span');
      span.textContent = data.summary;
      copy.append(span);

      const actions = document.createElement('div');
      actions.className = 'shared-banner-actions';
      const seeBtn = document.createElement('button');
      seeBtn.type = 'button';
      seeBtn.className = 'btn';
      seeBtn.textContent = 'See where';
      seeBtn.addEventListener('click', () => openUsage(gameRel, seeBtn));
      actions.append(seeBtn);

      if (data.fork?.forkable) {
        const forkBtn = document.createElement('button');
        forkBtn.type = 'button';
        forkBtn.className = 'btn';
        forkBtn.textContent = 'Make private copy';
        forkBtn.addEventListener('click', () => runSafeFork(gameRel, data.file_type, data.fork.name, forkBtn));
        actions.append(forkBtn);
      }

      banner.append(copy, actions);
      window.lucide?.createIcons({ nodes: [banner] });
      banner.hidden = false;
    } catch (_) { /* Non-blocking advisory check. */ }
  }

  window.AtelierAssetRefs = Object.freeze({ openUsage, checkMaterial, clearMaterialBanner });
})();
