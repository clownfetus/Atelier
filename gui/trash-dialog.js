// Recently deleted project edits: browse, restore, or permanently discard trash batches.
(() => {
  'use strict';

  let overlay = null;
  let opener = null;
  let trashSession = null;

  function isCurrent(session) {
    return session && session === trashSession && session.project === (window.atelierProject?.() || '');
  }

  function formatWhen(seconds) {
    if (!Number.isFinite(seconds)) return '';
    const diff = Math.max(0, Date.now() / 1000 - seconds);
    if (diff < 60) return 'Just now';
    if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)} h ago`;
    const days = Math.floor(diff / 86400);
    return `${days} day${days === 1 ? '' : 's'} ago`;
  }

  function formatRemaining(expiresAt) {
    if (expiresAt == null) return 'Kept until removed';
    const rem = expiresAt - Date.now() / 1000;
    if (rem <= 0) return 'Expiring soon';
    const days = Math.ceil(rem / 86400);
    return `${days} day${days === 1 ? '' : 's'} left`;
  }

  function ensureOverlay() {
    if (overlay) return overlay;
    overlay = document.createElement('div');
    overlay.id = 'trash-overlay';
    overlay.className = 'overlay';
    overlay.innerHTML = `
      <section class="modal trash-modal" role="dialog" aria-modal="true" aria-labelledby="trash-title" tabindex="-1">
        <div class="trash-head">
          <h2 id="trash-title"><i data-lucide="trash-2" size="18" aria-hidden="true"></i> Recently deleted</h2>
          <button type="button" class="sb-clear" id="trash-close" aria-label="Close recently deleted" title="Close"><i data-lucide="x" size="16" aria-hidden="true"></i></button>
        </div>
        <p class="trash-note">Deleted edits stay in this project's trash for 7 days (up to 20 batches) and are never included in exported mods.</p>
        <div class="trash-body" id="trash-body" aria-live="polite"></div>
        <div class="trash-foot">
          <span class="trash-status" id="trash-status" role="status"></span>
          <div class="trash-foot-actions">
            <button type="button" class="btn danger" id="trash-empty-btn" hidden>Empty trash</button>
            <button type="button" class="btn" id="trash-done">Close</button>
          </div>
        </div>
      </section>
    `;
    document.body.appendChild(overlay);
    overlay.querySelector('#trash-close').addEventListener('click', close);
    overlay.querySelector('#trash-done').addEventListener('click', close);
    overlay.querySelector('#trash-empty-btn').addEventListener('click', () => discardEntries(trashSession));
    overlay.addEventListener('click', event => {
      if (event.target === overlay && !trashSession?.busy) close();
    });
    overlay.addEventListener('keydown', event => {
      if (event.key === 'Escape' && !trashSession?.busy) {
        event.preventDefault();
        event.stopPropagation();
        close();
      }
    });
    if (window.lucide) window.lucide.createIcons({ nodes: [overlay] });
    return overlay;
  }

  function setStatus(text) {
    const el = overlay?.querySelector('#trash-status');
    if (el) el.textContent = text || '';
  }

  function setBusy(session, busy) {
    session.busy = busy;
    const controls = overlay.querySelectorAll('#trash-empty-btn, .trash-card-actions button');
    for (const button of controls) button.disabled = busy;
  }

  async function refresh(session = trashSession) {
    if (!isCurrent(session)) return;
    const body = overlay.querySelector('#trash-body');
    const emptyBtn = overlay.querySelector('#trash-empty-btn');
    const refreshId = ++session.refreshId;
    const current = () => isCurrent(session) && refreshId === session.refreshId;
    if (!session.project) {
      body.innerHTML = '<div class="trash-empty"><strong>No active project</strong><span>Open a project to inspect its recently deleted edits.</span></div>';
      emptyBtn.hidden = true;
      setStatus('');
      return;
    }
    body.innerHTML = '<div class="trash-empty"><span>Loading recently deleted edits…</span></div>';
    emptyBtn.hidden = true;
    try {
      const response = await window.atelierFetch('/api/trash', {}, session.project);
      const data = await response.json();
      if (!current()) return;
      if (!data.ok) throw new Error(data.error || 'Could not load project trash.');
      renderEntries(data.entries || [], session);
    } catch (error) {
      if (!current()) return;
      body.innerHTML = '';
      const box = document.createElement('div');
      box.className = 'trash-empty';
      const strong = document.createElement('strong');
      strong.textContent = 'Could not load project trash';
      const detail = document.createElement('span');
      detail.textContent = error.message;
      box.append(strong, detail);
      body.append(box);
      setStatus('');
    }
  }

  function renderEntries(entries, session) {
    const body = overlay.querySelector('#trash-body');
    const emptyBtn = overlay.querySelector('#trash-empty-btn');
    body.replaceChildren();
    const readyCount = entries.filter(e => e.state === 'ready').length;
    emptyBtn.hidden = readyCount === 0;
    emptyBtn.disabled = session.busy;
    if (!entries.length) {
      const empty = document.createElement('div');
      empty.className = 'trash-empty';
      const strong = document.createElement('strong');
      strong.textContent = 'Project trash is empty';
      const desc = document.createElement('span');
      desc.textContent = 'Edits you remove from the Mod tray will appear here so you can restore them later.';
      empty.append(strong, desc);
      body.append(empty);
      setStatus('');
      return;
    }
    const totalAssets = entries.reduce((sum, entry) => sum + (entry.count || 0), 0);
    setStatus(`${entries.length} batch${entries.length === 1 ? '' : 'es'} · ${totalAssets} asset${totalAssets === 1 ? '' : 's'}`);
    for (const item of entries) {
      const card = document.createElement('article');
      card.className = 'trash-card';
      card.dataset.entry = item.entry;

      const head = document.createElement('div');
      head.className = 'trash-card-head';
      const meta = document.createElement('div');
      meta.className = 'trash-card-meta';
      const title = document.createElement('div');
      title.className = 'trash-card-title';
      const plural = item.count === 1 ? '' : 's';
      title.textContent = item.state === 'kept'
        ? `Saved files from ${item.count} interrupted edit deletion${plural}`
        : `${item.count} edited asset${plural}`;
      const sub = document.createElement('div');
      sub.className = 'trash-card-sub';
      sub.textContent = `${formatWhen(item.deleted_at)} · ${formatRemaining(item.expires_at)}`;
      meta.append(title, sub);

      const actions = document.createElement('div');
      actions.className = 'trash-card-actions';
      const restoreBtn = document.createElement('button');
      restoreBtn.type = 'button';
      restoreBtn.className = 'btn primary';
      restoreBtn.textContent = 'Restore';
      restoreBtn.disabled = session.busy;
      restoreBtn.addEventListener('click', () => restoreEntry(session, item));

      const discardBtn = document.createElement('button');
      discardBtn.type = 'button';
      discardBtn.className = 'btn danger';
      discardBtn.textContent = 'Remove';
      discardBtn.disabled = session.busy;
      discardBtn.addEventListener('click', () => discardEntries(session, item));

      actions.append(restoreBtn, discardBtn);
      head.append(meta, actions);
      card.append(head);

      const list = document.createElement('ul');
      list.className = 'trash-assets';
      const visible = (item.assets || []).slice(0, 6);
      for (const asset of visible) {
        const li = document.createElement('li');
        const name = document.createElement('span');
        name.className = 'trash-asset-name';
        name.textContent = asset.name;
        name.title = asset.game_rel;
        const path = document.createElement('span');
        path.className = 'trash-asset-path';
        const parts = asset.game_rel.split('/');
        path.textContent = parts.length > 1 ? parts.slice(0, -1).join('/') : '';
        path.title = asset.game_rel;
        li.append(name, path);
        list.append(li);
      }
      if ((item.assets || []).length > visible.length) {
        const more = document.createElement('li');
        more.className = 'trash-more';
        more.textContent = `+ ${item.assets.length - visible.length} more asset${item.assets.length - visible.length === 1 ? '' : 's'}`;
        list.append(more);
      }
      card.append(list);
      body.append(card);
    }
  }

  async function restoreEntry(session, item) {
    if (!isCurrent(session) || session.busy) return;
    const {project} = session;
    setBusy(session, true);
    setStatus('Restoring edits…');
    try {
      const response = await window.atelierFetch('/api/restore_imported', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ entry: item.entry }),
      }, project);
      const data = await response.json();
      if (data.game_rels?.length && project === window.atelierProject?.()) {
        if (typeof window.loadSidebar === 'function') await window.loadSidebar();
        if (project === window.atelierProject?.()) window.renderGrid?.().catch(() => {});
      }
      if (!isCurrent(session)) return;
      if (data.ok) {
        const n = data.game_rels?.length || item.count;
        if (typeof window.toast === 'function') window.toast(`Restored ${n} edited asset${n === 1 ? '' : 's'}`, 'success');
      } else {
        if (typeof window.toast === 'function') window.toast(data.error || 'Some assets could not be restored.', 'warning', 7000);
      }
    } catch (error) {
      if (isCurrent(session)) window.toast?.(error.message || 'Could not restore edits.', 'warning');
    } finally {
      if (isCurrent(session)) {
        setBusy(session, false);
        await refresh(session);
      }
    }
  }

  async function discardEntries(session, item) {
    if (!isCurrent(session) || !session.project || session.busy) return;
    const confirmed = await window.AtelierDialog.confirm(item ? {
      title: 'Permanently delete batch?',
      body: `Remove ${item.count} deleted asset${item.count === 1 ? '' : 's'} from the project trash? This cannot be undone.`,
      confirmLabel: 'Remove permanently',
      tone: 'danger',
    } : {
      title: 'Empty project trash?',
      body: 'All ready batches in this project’s trash will be permanently deleted. This cannot be undone.',
      confirmLabel: 'Empty trash',
      tone: 'danger',
    });
    if (!confirmed || !isCurrent(session) || session.busy) return;
    setBusy(session, true);
    setStatus(item ? 'Removing from trash…' : 'Emptying trash…');
    try {
      const response = await window.atelierFetch('/api/trash/discard', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(item ? { entry: item.entry } : { all: true }),
      }, session.project);
      const data = await response.json();
      if (!isCurrent(session)) return;
      if (!data.ok) throw new Error(data.error || 'Could not remove files from the project trash.');
      window.toast?.(item ? 'Removed from project trash' : 'Project trash emptied', 'info');
    } catch (error) {
      if (isCurrent(session)) window.toast?.(error.message, 'warning');
    } finally {
      if (isCurrent(session)) {
        setBusy(session, false);
        await refresh(session);
      }
    }
  }

  function open() {
    const root = ensureOverlay();
    if (!root.classList.contains('active')) opener = document.activeElement;
    trashSession = {project: window.atelierProject?.() || '', busy: false, refreshId: 0};
    root.classList.add('active');
    root.querySelector('.trash-modal')?.focus();
    refresh();
  }

  function close() {
    if (!overlay) return;
    trashSession = null;
    overlay.classList.remove('active');
    if (opener?.isConnected) opener.focus();
    opener = null;
  }

  window.addEventListener('atelier:project-assets', event => {
    if (trashSession && trashSession.project !== (event.detail?.project || '')) close();
  });

  window.AtelierTrash = Object.freeze({ open, close, refresh });
})();
