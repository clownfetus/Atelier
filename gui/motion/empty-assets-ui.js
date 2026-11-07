// The Mod tray's empty state. Application responses, never search results,
// establish that a project is genuinely empty.
(() => {
  'use strict';
  const empty = new Map();
  let readyProject = null;
  let active = null;

  function dispose() {
    const previous = active;
    active = null;
    previous?.destroy();
  }

  function begin() {
    // Keep per-project history while hiding the glyph until the next response
    // has passed the application's project/request-generation guards.
    readyProject = null;
    dispose();
  }

  function confirmed(project, count) {
    empty.set(project, count === 0);
    readyProject = project;
  }

  function mount(project, wrapper) {
    dispose();
    if (!wrapper || readyProject !== project || !empty.get(project)) return;
    active = window.AtelierEmptyGlyph?.mount(wrapper) || null;
  }

  window.AtelierEmptyAssetsUI = Object.freeze({begin, confirmed, mount, dispose});
})();
