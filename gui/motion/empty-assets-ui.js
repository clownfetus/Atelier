// Sidebar ownership for the supplied Gemini illustration. Application responses,
// never the presentation component or search results, establish genuine emptiness.
(() => {
  'use strict';
  const projects = new Map();
  let readyProject = null;
  let active = null;

  function dispose() {
    const previous = active;
    active = null;
    if (!previous) return;
    try { previous.motion.destroy(); }
    catch (error) { console.warn('Empty assets animation cleanup unavailable', error); }
    finally {
      previous.host.remove();
      previous.fallback?.classList.remove('am-empty-assets-fallback-hidden');
    }
  }

  function begin() {
    // Keep per-project history while hiding presentation until the next response
    // has passed the application's project/request-generation guards.
    readyProject = null;
    dispose();
  }

  function confirmed(project, count) {
    let record = projects.get(project);
    if (!record) {
      record = {wasEmpty: false, seenEmpty: false, pending: false};
      projects.set(project, record);
    }
    const empty = count === 0;
    if (!empty) record.pending = false;
    else if (!record.seenEmpty || !record.wasEmpty) record.pending = true;
    record.wasEmpty = empty;
    readyProject = project;
  }

  function mount(project, wrapper) {
    dispose();
    const record = projects.get(project);
    if (!wrapper || readyProject !== project || !record?.wasEmpty) return;
    const component = window.AtelierMotion?.emptyAssets;
    if (!component) return;
    const fallback = wrapper.querySelector('svg');
    const host = document.createElement('div');
    host.className = 'am-empty-assets-host';
    host.setAttribute('aria-hidden', 'true');
    wrapper.insertBefore(host, wrapper.firstChild);
    try {
      const motion = component.mount(host, {
        state: record.pending ? 'entering' : 'settled', reducedMotion: 'system',
      });
      active = {motion, host, fallback};
      fallback?.classList.add('am-empty-assets-fallback-hidden');
      record.pending = false;
      record.seenEmpty = true;
    } catch (error) {
      host.remove();
      fallback?.classList.remove('am-empty-assets-fallback-hidden');
      console.warn('Empty assets illustration unavailable', error);
    }
  }

  window.AtelierEmptyAssetsUI = Object.freeze({begin, confirmed, mount, dispose});
})();
