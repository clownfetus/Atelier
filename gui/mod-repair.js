(() => {
  const byId = id => document.getElementById(id);
  const question = byId('repatch-check');
  const output = byId('repatch-repair-results');
  const labels = {
    repairable: 'Repair available',
    clean: 'No supported fault found',
    review: 'Needs review',
    unreadable: 'Couldn’t read this mod',
  };
  let selected = '', view = 0, startup = false;

  const make = (tag, text, className) => {
    const element = document.createElement(tag);
    element.textContent = text;
    if (className) element.className = className;
    return element;
  };

  function post(path, body, options = {}) {
    const run = window.AtelierJobs?.run || window.api;
    return run('/api/mod_repair/' + path, {
      ...options, method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
  }

  function select(path = '') {
    selected = path;
    view += 1;
    question.disabled = !selected;
    output.replaceChildren();
  }

  async function save(row, button, status) {
    button.disabled = true;
    let progress;
    try {
      const result = await post('save', {token: row.token, suggested_name: row.suggested_name}, {
        onUpdate(job) {
          if (job.state === 'running' && !progress) progress = window.toastSpinner?.('Saving repaired copy…');
        },
      });
      if (result.cancelled) {
        progress?.remove();
        return;
      }
      if (!result.ok || result.status !== 'repaired') {
        status.textContent = result.error || 'Couldn’t save the repaired copy.';
        progress?.resolve(status.textContent, 'error');
        return;
      }
      status.textContent = 'Saved ' + result.name;
      progress?.resolve('Repaired copy saved.', 'success');
      button.remove();
    } catch (_) {
      status.textContent = 'Couldn’t save the repaired copy.';
      progress?.resolve(status.textContent, 'error');
    } finally {
      button.disabled = false;
    }
  }

  function show(row, named = false) {
    const item = make('div', '', 'repatch-repair-item');
    const status = make('strong', labels[row.status] || labels.unreadable);
    if (named) item.append(make('span', row.name, 'muted'));
    item.append(status);
    if (row.reason) item.append(make('span', row.reason, 'muted'));
    if (row.status === 'repairable' && row.token) {
      const button = make('button', 'Save repaired copy', 'btn');
      button.type = 'button';
      button.addEventListener('click', () => save(row, button, status));
      item.append(button);
    }
    output.append(item);
  }

  question.addEventListener('click', async () => {
    const current = ++view;
    question.disabled = true;
    output.replaceChildren(make('span', 'Checking for material issues…', 'muted'));
    try {
      const row = await post('scan', {path: selected});
      if (current !== view) return;
      output.replaceChildren();
      if (row.ok) show(row);
      else if (!row.cancelled) show({status: 'unreadable', reason: row.error});
    } catch (_) {
      if (current !== view) return;
      output.replaceChildren();
      show({status: 'unreadable'});
    } finally {
      if (current === view) question.disabled = !selected;
    }
  });

  async function checkInstalled() {
    if (startup) return;
    startup = true;
    try {
      const run = window.AtelierJobs?.run || window.api;
      const result = await run('/api/mod_repair/installed', {method: 'GET', project: ''});
      if (!result.ok) return;
      const mods = (result.repairs || []).filter(row => row.status === 'repairable' && row.token);
      if (!mods.length) return;
      const notice = make('div', '', 'toast warning');
      notice.id = 'mod-repair-notice';
      notice.append(make('strong', mods.length === 1 ? '1 mod needs repair' : mods.length + ' mods need repair'));
      const review = make('button', 'Review mods', 'btn toast-undo');
      const dismiss = make('button', 'Dismiss', 'btn toast-undo');
      review.type = dismiss.type = 'button';
      review.addEventListener('click', () => {
        notice.remove();
        window.openRepatcher();
        for (const row of mods) show(row, true);
        output.querySelector('button')?.focus();
      });
      dismiss.addEventListener('click', () => notice.remove());
      notice.append(review, dismiss);
      byId('toast-area').append(notice);
    } catch (_) {
      // The manual check remains available if the startup job cannot answer.
    }
  }

  window.AtelierModRepair = Object.freeze({select, checkInstalled});
})();
