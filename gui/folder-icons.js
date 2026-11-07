// Folder identities shared by the asset grid and persisted home shortcuts.
// Match complete category names, never arbitrary substrings of hero/skin names.
(() => {
  'use strict';
  // An icon goes only on a folder a modder would open (D9). Anything else gets the plain folder.
  const rules = [
    [/^(characters?|npcs?)$/i, 'char-icon', 'square-user-round'],
    [/^(ui|icons?)$/i, 'ui-folder-icon', 'swatch-book'],
    [/^textures?$/i, 'texture-folder-icon', 'image'],
    [/^materials?$/i, 'material-folder-icon', 'circle-star'],
    [/^(mesh|meshes)$/i, 'mesh-folder-icon', 'scan-box'],
    [/^(vfx|effects?)$/i, 'vfx-folder-icon', 'sparkles'],
    [/^weapons?$/i, 'weapon-folder-icon', 'swords'],
    [/^(abilities|ability|abilitysystem)$/i, 'ability-folder-icon', 'folder-ability'],
    [/^(environment|landscapes?|foliage)$/i, 'environment-folder-icon', 'folder-environment'],
    [/^blueprints?$/i, 'blueprint-folder-icon', 'folder-blueprint'],
    [/^plugins?$/i, 'plugin-folder-icon', 'puzzle'],
    [/^nameplates?$/i, 'nameplate-folder-icon', 'id-card'],
    [/^data$/i, 'data-folder-icon', 'folder-data'],
    [/^(text|stringtables?)$/i, 'text-folder-icon', 'type-outline'],
    [/^(l10n|locali[sz]ation)$/i, 'language-folder-icon', 'folder-language'],
    [/^maps?$/i, 'map-folder-icon', 'folder-map'],
  ];
  const symbols = Object.freeze(Object.fromEntries([
    ['folder-icon', 'folder'], ...rules.map(([, cls, symbol]) => [cls, symbol]),
  ]));
  // Keep the established home ordering independent of added artwork coverage.
  const featured = /^(characters?|ui|textures?|materials?|vfx|effects?|meshes?|text|stringtables?|nameplates?|plugins|weapons?)$/i;
  window.AtelierFolderIcons = Object.freeze({
    symbols,
    classFor: name => rules.find(([pattern]) => pattern.test(String(name ?? '')))?.[1] || 'folder-icon',
    isFeatured: name => featured.test(String(name ?? '')),
  });
})();
