// Bundled release notes: once after an upgrade, with no dependency on the release check.
(() => {
  'use strict';
  const overlay = document.getElementById('changelog-overlay');
  const panel = overlay.querySelector('.changelog-modal');
  const body = document.getElementById('changelog-body');
  const done = document.getElementById('changelog-done');
  let request, info, ready = false, pending = false, opened = false, opener, closed, resolveClosed;

  function inline(parent, value) {
    // Keep the small subset used by CHANGELOG.md. Markdown links become their labels;
    // all source text is inserted as text nodes, never as HTML.
    const text = String(value || '').replace(/\[([^\]]+)\]\([^)]+\)/g, '$1');
    for (const part of text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g)) {
      if (part.startsWith('**') || part.startsWith('`')) {
        const strong = part.startsWith('**');
        const node = document.createElement(strong ? 'strong' : 'code');
        node.textContent = part.slice(strong ? 2 : 1, strong ? -2 : -1);
        parent.append(node);
      } else parent.append(document.createTextNode(part));
    }
  }

  function render(data) {
    document.getElementById('changelog-version').textContent = 'Atelier ' + data.version;
    document.getElementById('changelog-intro').textContent = data.available
      ? 'Atelier has been updated. Here’s what’s new.' : 'What’s new in this version of Atelier.';
    body.replaceChildren();
    for (const release of data.releases) {
      const section = document.createElement('section');
      section.className = 'changelog-release';
      const heading = document.createElement('h3');
      heading.textContent = release.version;
      section.append(heading);
      if (release.date) {
        const date = document.createElement('p');
        date.className = 'changelog-date'; date.textContent = release.date; section.append(date);
      }
      for (const block of release.blocks || []) {
        const node = document.createElement(block.type === 'heading' ? 'h4' : block.type === 'list' ? 'ul' : 'p');
        if (block.type === 'list') {
          for (const item of block.items) {
            const li = document.createElement('li'); inline(li, item); node.append(li);
          }
        } else inline(node, block.text);
        section.append(node);
      }
      body.append(section);
    }
    body.scrollTop = 0;
  }

  function show(data) {
    if (opened || !data?.releases?.length) return;
    pending = false; opened = true; info = data;
    opener = document.activeElement;
    render(data);
    closed = new Promise(resolve => { resolveClosed = resolve; });
    overlay.classList.add('active');
    body.scrollTop = 0;
    document.addEventListener('keydown', keys, true);
    document.addEventListener('focusin', focus, true);
    done.focus();
  }

  function dismiss() {
    if (!opened) return;
    opened = false;
    overlay.classList.remove('active');
    document.removeEventListener('keydown', keys, true);
    document.removeEventListener('focusin', focus, true);
    (opener?.isConnected ? opener : document.getElementById('menu-btn'))?.focus();
    resolveClosed?.();
    info.available = false;
    fetch('/api/changelog/acknowledge', {method: 'POST', keepalive: true,
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify({version: info.version})})
      .catch(() => {});
  }

  function focus(event) {
    if (opened && !panel.contains(event.target)) done.focus();
  }

  function keys(event) {
    event.stopImmediatePropagation();
    if (event.key === 'Escape') { event.preventDefault(); dismiss(); }
    else if (event.key === 'Tab') {
      const targets = [...panel.querySelectorAll('button, a[href], [tabindex="0"]')];
      const index = targets.indexOf(document.activeElement);
      event.preventDefault();
      targets[(index + (event.shiftKey ? -1 : 1) + targets.length) % targets.length].focus();
    }
  }

  function offer() {
    if (ready && pending && !document.hidden && !document.querySelector('.overlay.active, dialog[open], #ctx-menu.active')) show(info);
  }

  function start() {
    if (!request) request = fetch('/api/changelog').then(response => response.ok ? response.json() : null)
      .then(data => { info = data; pending = !!data?.available; offer(); return data; })
      .catch(() => null);
    return request;
  }

  const observer = new MutationObserver(offer);
  observer.observe(document.body, {subtree: true, attributes: true, attributeFilter: ['class', 'open']});
  document.addEventListener('visibilitychange', offer);
  done.addEventListener('click', dismiss);
  document.getElementById('changelog-close').addEventListener('click', dismiss);
  overlay.addEventListener('click', event => { if (event.target === overlay) dismiss(); });
  window.addEventListener('pagehide', () => observer.disconnect());
  window.AtelierChangelog = Object.freeze({
    start,
    ready() { ready = true; offer(); },
    async show() { const data = await start(); show(data); },
    whenClosed() { return opened ? closed : undefined; },
  });
})();
