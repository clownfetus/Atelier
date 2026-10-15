// Folder identities shared by the asset grid and persisted home shortcuts.
// Match complete category names, never arbitrary substrings of hero/skin names.
(() => {
  'use strict';
  const rules = [
    [/^(characters?|npcs?)$/i, 'char-icon', 'square-user-round'],
    [/^(ui|icons?)$/i, 'ui-folder-icon', 'swatch-book'],
    [/^(textures?|placeholdertextures)$/i, 'texture-folder-icon', 'image'],
    [/^((engine|editor|enginedebug)?materials?|materialfunctions|materialtemplates)$/i, 'material-folder-icon', 'circle-star'],
    [/^(vfx|effects?|vectorfields|enginevolumetrics)$/i, 'vfx-folder-icon', 'sparkles'],
    [/^(mesh|meshes|enginemeshes|editormeshes|gltf)$/i, 'mesh-folder-icon', 'scan-box'],
    [/^(text|stringtables?)$/i, 'text-folder-icon', 'type-outline'],
    [/^nameplates?$/i, 'nameplate-folder-icon', 'id-card'],
    [/^plugins?$/i, 'plugin-folder-icon', 'puzzle'],
    [/^weapons?$/i, 'weapon-folder-icon', 'swords'],
    [/^(animations?|animsequences?|animmontages?|blendspaces?)$/i, 'animation-folder-icon', 'folder-animation'],
    [/^(audio|audiobanks?|sounds?|soundcues?|cues?|enginesounds|wwise)$/i, 'audio-folder-icon', 'folder-audio'],
    [/^(maps?|levels?|worlds?|maptemplates|openworldtemplate)$/i, 'map-folder-icon', 'folder-map'],
    [/^(lights?|lighting|lightprofiles?|enginelightprofiles)$/i, 'light-folder-icon', 'folder-light'],
    [/^(blueprints?|editorblueprintresources)$/i, 'blueprint-folder-icon', 'folder-blueprint'],
    [/^(ai|behaviou?rtrees?|blackboards?)$/i, 'ai-folder-icon', 'folder-ai'],
    [/^(abilities|ability|abilitysystem|enginedamagetypes)$/i, 'ability-folder-icon', 'folder-ability'],
    [/^(physics|physicsassets?|chaos)$/i, 'physics-folder-icon', 'folder-physics'],
    [/^(controls?|input|inputactions?)$/i, 'controls-folder-icon', 'folder-controls'],
    [/^(data|datatables?|enums?)$/i, 'data-folder-icon', 'folder-data'],
    [/^(arttools|tools|utilities)$/i, 'tools-folder-icon', 'folder-tools'],
    [/^(environment|environmenthydrac|landscapes?|editorlandscaperesources|foliage|speedtree\d*)$/i, 'environment-folder-icon', 'folder-environment'],
    [/^(fonts?|enginefonts)$/i, 'font-folder-icon', 'folder-font'],
    [/^(movies?(?:_activity|_level|bink)?|cinematics?|sequences?)$/i, 'movie-folder-icon', 'folder-movie'],
    [/^(l10n|locali[sz]ation)$/i, 'language-folder-icon', 'folder-language'],
    [/^functions?$/i, 'code-folder-icon', 'folder-code'],
    [/^(statistics|analytics)$/i, 'statistics-folder-icon', 'folder-statistics'],
    [/^pipelines?$/i, 'pipeline-folder-icon', 'folder-pipeline'],
    [/^((engine|editor)?resources|defaultassets|marvel_lq)$/i, 'resources-folder-icon', 'folder-resources'],
    [/^marvel_encrypt$/i, 'security-folder-icon', 'folder-security'],
    [/^mobileresources$/i, 'mobile-folder-icon', 'folder-mobile'],
    [/^vreditor$/i, 'vr-folder-icon', 'folder-vr'],
    [/^(basicshapes|shapes)$/i, 'shapes-folder-icon', 'folder-shapes'],
    [/^(enginesky|sky|skies)$/i, 'sky-folder-icon', 'folder-sky'],
    [/^deformers?$/i, 'deformer-folder-icon', 'folder-deformer'],
    [/^prototypes?$/i, 'prototype-folder-icon', 'folder-prototype'],
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
