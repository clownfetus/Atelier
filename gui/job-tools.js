/* Durable job status and cancellation. Native operations remain on the server. */
(function () {
  'use strict';
  const active = new Set(['queued', 'running', 'cancelling']);
  const live = new Map();
  let timer, hidden = false, overlay, body, activityButton, rendered = '';
  const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
  function el(tag, text, cls) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (cls) node.className = cls;
    return node;
  }
  async function request(path, options = {}, project = window.atelierProject()) {
    const response = await window.atelierFetch(path, options, project);
    let result;
    try { result = await response.json(); }
    catch (_) { throw new Error('The server returned an unreadable job response.'); }
    if (!response.ok) throw new Error(result.error || 'Job request failed');
    return result;
  }
  function notify(job) {
    live.set(job.id, job);
    window.dispatchEvent(new CustomEvent('atelier-job', {detail: job}));
    if (job.kind === 'export') window.AtelierExportReview?.jobProgress?.(job);
  }
  async function cancel(job, project = job.project) {
    const response = await request('/api/jobs/' + encodeURIComponent(job.id) + '/cancel', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}',
    }, project);
    if (response.job) notify(response.job);
    return response;
  }
  function render(rows) {
    const signature = JSON.stringify([window.atelierProject(), rows]);
    if (signature === rendered) return;
    rendered = signature;
    const focusedRow = document.activeElement.closest?.('.job-row');
    const focusJob = focusedRow?.dataset.jobId;
    const focusLabel = focusedRow ? document.activeElement.textContent : null;
    body.replaceChildren();
    body.append(el('p', 'Project: ' + (window.atelierProject() || 'Default project')));
    body.append(el('p', 'Jobs belong to this project. Completed results remain available after reopening Atelier.'));
    if (!rows.length) body.append(el('p', 'No jobs yet.', 'muted'));
    for (const job of rows) {
      const row = el('article', undefined, 'job-row'); row.dataset.jobId = job.id;
      row.append(el('strong', job.label), el('span', job.state, 'job-state'));
      const stage = el('p', job.stage); stage.setAttribute('role', 'status'); row.append(stage);
      if (job.total) row.append(el('p', job.current + ' / ' + job.total));
      if (job.error) row.append(el('p', job.error, 'warning'));
      const result = job.result || {};
      if (result.pak_path || result.pak) row.append(el('p', result.pak_path || result.pak, 'job-path'));
      if (active.has(job.state)) {
        const button = el('button', job.can_cancel ? 'Cancel' : 'Finishing file publication…', 'btn');
        button.disabled = !job.can_cancel || job.state === 'cancelling';
        button.addEventListener('click', async () => {
          button.disabled = true;
          try { await cancel(job); await refresh(); }
          catch (error) { toast(error.message, 'warning'); button.disabled = false; }
        });
        row.append(button);
      } else if (job.kind === 'export' && (job.state === 'interrupted' || job.state === 'cancelled' || job.state === 'failed')) {
        const review = el('button', 'Review current export', 'btn');
        review.addEventListener('click', () => { overlay.classList.remove('active'); document.getElementById('install-btn').click(); });
        row.append(review);
      }
      if (result.ok || result.built) {
        if (job.kind === 'export' || job.kind === 'repatch') {
          const reveal = el('button', 'Show exported files', 'btn');
          reveal.addEventListener('click', () => window.atelierFetch('/api/open_export_folder'));
          row.append(reveal);
        }
      }
      body.append(row);
    }
    const count = rows.filter(job => active.has(job.state)).length;
    activityButton.textContent = count ? 'Activity · ' + count : 'Activity';
    if (focusJob) {
      const row = [...body.querySelectorAll('.job-row')].find(node => node.dataset.jobId === focusJob);
      const buttons = [...(row?.querySelectorAll('button:not(:disabled)') || [])];
      (buttons.find(node => node.textContent === focusLabel) || buttons[0] || body.parentElement).focus();
    }
  }
  async function refresh() {
    if (!window.atelierFetch) return;
    const project = window.atelierProject();
    const result = await request('/api/jobs', {}, project);
    if (project !== window.atelierProject()) return;
    for (const job of result.jobs || []) notify(job);
    render(result.jobs || []);
  }
  async function tick() {
    if (hidden) return;
    try { await refresh(); }
    catch (_) { if (overlay?.classList.contains('active')) { rendered = ''; body.replaceChildren(el('p', 'Connection unavailable. Activity will reconnect automatically.', 'warning')); } }
    timer = setTimeout(tick, 2200);
  }
  function init() {
    activityButton = el('button', 'Activity', 'btn job-activity-button'); activityButton.id = 'job-activity';
    document.getElementById('topbar').append(activityButton);
    overlay = el('div', undefined, 'overlay job-overlay'); overlay.id = 'job-overlay';
    const panel = el('section', undefined, 'modal job-modal'); panel.tabIndex = -1;
    panel.setAttribute('role', 'dialog'); panel.setAttribute('aria-modal', 'true'); panel.setAttribute('aria-labelledby', 'job-title');
    const title = el('h2', 'Activity'); title.id = 'job-title';
    body = el('div', undefined, 'job-body');
    const close = el('button', 'Close', 'btn');
    const hide = () => { overlay.classList.remove('active'); activityButton.focus(); };
    close.addEventListener('click', hide);
    panel.append(title, body, close); overlay.append(panel); document.body.append(overlay);
    activityButton.addEventListener('click', async () => {
      overlay.classList.add('active'); panel.focus();
      try { await refresh(); } catch (error) { body.replaceChildren(el('p', error.message, 'warning')); }
    });
    window.AtelierJobDialogs.trap(overlay, panel, hide);
    timer = setTimeout(tick, 400);
  }
  window.AtelierJobDialogs = {
    el,
    trap(overlay, panel, hide) {
      overlay.addEventListener('keydown', event => {
        if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); hide(); }
        if (event.key !== 'Tab') return;
        const nodes = [...panel.querySelectorAll('button:not(:disabled),input:not(:disabled),select:not(:disabled),summary,a[href]')].filter(n => n.getClientRects().length);
        const first = nodes[0], last = nodes[nodes.length-1];
        if (!first) { event.preventDefault(); panel.focus(); }
        else if (event.shiftKey && (document.activeElement === first || document.activeElement === panel)) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      });
    },
  };
  window.AtelierJobs = {
    async run(path, options = {}) {
      const {project = window.atelierProject(), ...opts} = options;
      const input = JSON.parse(opts.body || '{}');
      const result = await request(path, {...opts, body: JSON.stringify({...input, background: true})}, project);
      // Keep old callers and fixture responses compatible.
      if (!result.job_id) return result;
      if (result.job) notify(result.job);
      let failures = 0;
      while (!hidden) {
        await delay(350);
        try {
          const payload = await request('/api/jobs/' + encodeURIComponent(result.job_id), {}, project);
          const job = payload.job;
          if (!job) throw new Error('Job status is unavailable');
          notify(job); failures = 0;
          if (!active.has(job.state)) return job.result || {ok: false, interrupted: job.state === 'interrupted', error: job.error || job.stage};
        } catch (error) {
          // Reconnect to the same job; never resubmit a build after a dropped response.
          if (++failures >= 30) return {ok: false, error: 'Connection lost. Check Activity before retrying; the job may still be running.'};
          await delay(1000);
        }
      }
      return {ok: false, error: 'This view was closed. Reopen Activity to check the job.'};
    },
    async cancelCurrent(kind, project = window.atelierProject()) {
      const job = [...live.values()].find(j => j.project === project && j.kind === kind && active.has(j.state));
      if (!job) return {ok: false, error: 'Waiting for the job to start. Check Activity.'};
      return cancel(job, project);
    },
    refresh,
  };
  window.addEventListener('pagehide', () => { hidden = true; clearTimeout(timer); });
  document.addEventListener('DOMContentLoaded', init);
})();
