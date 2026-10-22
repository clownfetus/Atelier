import * as THREE from 'three';
import {assetKey, verifiedBinding, bindingNotice, boundTextures, relatedMaterials, textureUsers, modelSections, hitSection} from './assembly-data.js';

const $ = id => document.getElementById(id);
const make = (tag, text, cls) => {
  const node = document.createElement(tag);
  if (text != null) node.textContent = text;
  if (cls) node.className = cls;
  return node;
};
const leaf = path => String(path || '').split('/').pop();
const roleLabel = source => ({basecolor:'Diffuse', specular:'Specular', normal:'Normal', orm:'Packed mask',
  dye:'ColorID', emissive:'Emissive', opacity:'Opacity', ao:'Occlusion'}[source.role] || source.slot);

export function createAssemblyView(api) {
  const box = $('viewport-box'), body = $('viewport-body'), stage = $('viewport-stage');
  let active = false, sections = [], surface = null, texture = null, lastMaterial = null;
  let query = '', effectsKey = '', effectsRequest = null, effectResults = new Map(), materialFocus = false;
  let thumbnails = new Map(), thumbPending = new Map(), thumbQueue = [], thumbReaders = 0, thumbGeneration = 0;
  let imageObserver = null, shelfSignature = '', syncFrame = 0, linkTimer = 0;
  let geometryCollapsed = false, texturesCollapsed = false, resizeState = null;
  let lastGeometrySection = null;
  const geometry = make('aside', null, 'assembly-geometry'); geometry.id = 'assembly-geometry';
  geometry.setAttribute('aria-label', 'Assembly geometry');
  geometry.innerHTML = `
    <div class="assembly-panel-head"><span class="assembly-number">01</span><h3>Geometry</h3><button id="assembly-geometry-collapse" class="assembly-icon" aria-label="Collapse geometry" aria-expanded="true"><i data-lucide="chevron-left" size="16"></i></button></div>
    <div class="assembly-geometry-content">
      <div class="assembly-project"><i data-lucide="folder" size="14"></i><span id="assembly-project"></span></div>
      <label class="assembly-search"><i data-lucide="search" size="15"></i><input id="assembly-search" type="search" placeholder="Find a surface" aria-label="Find an assembly surface"></label>
      <div class="assembly-list-heading"><span>Visible surfaces</span><span id="assembly-section-count"></span></div>
      <div id="assembly-sections" role="group" aria-label="Mesh sections"></div>
      <div id="assembly-geometry-selection"></div>
      <details id="assembly-effects"><summary><i data-lucide="sparkles" size="16"></i> Effects <span id="assembly-effect-count"></span></summary><div id="assembly-effect-content"></div></details>
      <p class="assembly-footnote">Select a surface to follow its material and texture bindings.</p>
    </div>`;
  const geometryResize = make('div', null, 'assembly-resize assembly-geometry-resize');
  geometryResize.setAttribute('role', 'separator'); geometryResize.tabIndex = 0;
  geometryResize.setAttribute('aria-label', 'Resize geometry panel'); geometryResize.setAttribute('aria-orientation', 'vertical');
  geometry.append(geometryResize); body.prepend(geometry);

  const shelf = make('section', null, 'assembly-textures'); shelf.id = 'assembly-textures';
  shelf.setAttribute('aria-label', 'Connected textures');
  shelf.innerHTML = `<div class="assembly-panel-head"><span class="assembly-number">03</span><h3>Textures</h3><span id="assembly-texture-count" class="assembly-count"></span><span id="assembly-texture-context"></span><button id="assembly-textures-collapse" class="assembly-icon" aria-label="Collapse textures" aria-expanded="true"><i data-lucide="chevron-down" size="16"></i></button></div>
    <div id="assembly-texture-cards" role="group" aria-label="Material texture bindings"></div>
    <div id="assembly-texture-actions" hidden></div>`;
  body.append(shelf);

  const context = make('div'); context.id = 'assembly-material-context';
  $('viewport-material-editor').before(context);
  const resourceResize = geometryResize.cloneNode(); resourceResize.className = 'assembly-resize assembly-material-resize';
  resourceResize.setAttribute('aria-label', 'Resize material panel'); $('viewport-materials').prepend(resourceResize);

  const selection = make('div', null, 'assembly-stage-selection'); selection.id = 'assembly-stage-selection';
  selection.setAttribute('aria-live', 'polite'); stage.append(selection);
  const links = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  links.id = 'assembly-links'; links.setAttribute('aria-hidden', 'true');
  links.innerHTML = '<path/><path/><circle r="4"/>'; stage.append(links);
  const focusPanel = make('button', 'Geometry', 'assembly-geometry-reopen'); focusPanel.id = 'assembly-geometry-reopen';
  focusPanel.setAttribute('aria-label', 'Expand geometry panel'); stage.append(focusPanel);

  function button(label, action, cls = '') {
    const control = make('button', label, cls); control.type = 'button'; control.addEventListener('click', action); return control;
  }
  function chip(text, changed = false) { return make('span', text, 'assembly-badge' + (changed ? ' is-project' : '')); }
  function projectRecord(path) { return api.projectAssets?.().find(item => assetKey(item.game_rel) === assetKey(path)); }
  function ownership(path, custom = false) { return custom ? 'Project image' : projectRecord(path) ? 'In project' : 'Game original'; }
  function currentSection() { return hitSection(sections, surface) || sections.find(section => section.name === api.state().selected) || null; }
  function selectedInfo() { return api.state().data[api.state().selected]; }
  function choose(section) {
    surface = section; texture = null; materialFocus = false;
    api.choose(section.name, section); pulse();
  }
  function selectTexture(source) {
    texture = source; updateRelationships(); renderTextureActions(); pulse();
  }

  function renderGeometry() {
    const {data, selected, project} = api.state();
    $('assembly-project').textContent = project || 'Current project';
    $('assembly-section-count').textContent = String(sections.length);
    const list = $('assembly-sections'), picked = currentSection(), focused = document.activeElement?.closest('.assembly-section')?.dataset.section;
    const scroll = list.scrollTop;
    list.replaceChildren();
    const groups = new Map();
    for (const section of sections) {
      if (query && !`${api.label(section.name)} ${section.owner.name} ${section.mesh_game_rel}`.toLowerCase().includes(query)) continue;
      if (!groups.has(section.owner)) groups.set(section.owner, []);
      groups.get(section.owner).push(section);
    }
    for (const [owner, entries] of groups) {
      const heading = make('div', null, 'assembly-mesh-heading');
      heading.append(make('span', owner.kind === 'weapon' ? 'Held weapon' : 'Mesh'), make('strong', owner.name));
      heading.title = entries[0].mesh_game_rel; list.append(heading);
      for (const section of entries) {
        const row = button('', () => choose(section), 'assembly-section');
        row.dataset.section = section.id; row.dataset.material = section.name;
        row.setAttribute('aria-pressed', String(picked?.id === section.id && selected === section.name));
        const dot = make('span', null, 'assembly-section-dot');
        const info = data[section.name];
        if (info?.colors?.length) dot.style.background = api.swatch(section.name, info);
        const name = make('span', api.label(section.name));
        row.append(dot, name, make('small', String(sections.indexOf(section)+1).padStart(2,'0')));
        row.title = `${section.owner.name} · Preview section ${section.groupIndex + 1} · ${info?.slot_name || section.name}`;
        row.classList.toggle('is-hidden', !section.material.visible);
        list.append(row);
        if (focused === section.id) row.focus({preventScroll:true});
      }
    }
    if (!list.childElementCount) list.append(make('p', query ? 'No matching surfaces.' : 'Surfaces appear as the model loads.', 'assembly-empty'));
    list.scrollTop = scroll;
    if (picked?.id !== lastGeometrySection) {
      const row = [...list.querySelectorAll('.assembly-section')].find(row=>row.dataset.section === picked?.id);
      if (row) {
        const region = list.getBoundingClientRect(), bounds = row.getBoundingClientRect();
        if (bounds.top < region.top) list.scrollTop -= region.top - bounds.top;
        else if (bounds.bottom > region.bottom) list.scrollTop += bounds.bottom - region.bottom;
      }
      lastGeometrySection = picked?.id;
    }
    const detail = $('assembly-geometry-selection');
    const expanded = detail.dataset.material === selected && detail.querySelector('details')?.open;
    detail.replaceChildren(); detail.dataset.material = selected || '';
    if (!picked || !selected) return;
    const info = data[selected];
    detail.append(make('span', 'Selected surface', 'assembly-eyebrow'), make('strong', api.label(selected)));
    const dl = make('dl', null, 'assembly-properties');
    const values = [['Surface', String(sections.indexOf(picked)+1)], ['Mesh part', picked.object.name || 'Unnamed primitive'],
      ['Geometry group', String(picked.groupIndex+1)], ['Triangles', picked.triangles.toLocaleString()],
      ['Material slot', Number.isInteger(info?.slot_index) ? String(info.slot_index) : info?.shared_slots ? `${info.shared_slots.length} shared slots` : 'Unverified']];
    for (const [label, value] of values) dl.append(make('dt', label), make('dd', value));
    const properties = make('details', null, 'assembly-geometry-properties'); properties.open = !!expanded;
    const slot = Number.isInteger(info?.slot_index) ? `Slot ${info.slot_index}` : info?.shared_slots ? 'Shared slots' : 'Unverified slot';
    properties.append(make('summary', `${slot} · ${picked.triangles.toLocaleString()} triangles`), dl);
    detail.append(properties, chip(ownership(picked.mesh_game_rel), !!projectRecord(picked.mesh_game_rel)));
    if (verifiedBinding(info)) {
      const visibility = make('div', null, 'assembly-visibility');
      const eye = api.sectionControl(selected);
      if (eye) {visibility.append(make('span', 'Export visibility'), eye);detail.append(visibility);}
    }
    const actions = make('div', null, 'assembly-geometry-actions');
    const uv = button('Inspect UVs', () => api.uv(surface || picked));
    uv.disabled = !picked.material.visible;
    const blender = button('Edit in Blender', () => api.blender(picked.mesh_game_rel));
    const replace = button('Replace model', () => api.replaceMesh(picked.mesh_game_rel));
    actions.append(uv, blender, replace); detail.append(actions);
  }

  function renderMaterial() {
    const {data, selected, edited} = api.state(), info = data[selected];
    const section = currentSection(), trusted = verifiedBinding(info);
    context.replaceChildren(); box.classList.toggle('assembly-unverified', !!selected && !trusted);
    if (selected && !info && api.state().loading) {
      context.append(make('span', '02 / MATERIAL', 'assembly-eyebrow'), make('p', 'Reading material references…', 'assembly-empty'));return;
    }
    if (!selected) {
      context.append(make('span', '02 / MATERIAL', 'assembly-eyebrow'), make('h3', 'Follow the surface'),
        make('p', 'Choose a part of the model. Its material, shader and connected textures will appear here.', 'assembly-empty'));
      return;
    }
    context.append(make('span', '02 / MATERIAL', 'assembly-eyebrow'));
    const card = button('', () => { materialFocus = true; texture = null; updateRelationships(); renderTextureActions(); pulse(); }, 'assembly-material-card');
    card.setAttribute('aria-label', 'Highlight sections using this material'); card.disabled = !trusted;
    const swatch = make('span', null, 'assembly-material-swatch');
    if (info) swatch.style.background = api.swatch(selected, info);
    card.append(swatch, make('strong', trusted ? leaf(info.game_rel) : info?.slot_name || api.label(selected))); context.append(card);
    if (!trusted) {
      context.append(chip('Reference unverified'), make('p', bindingNotice(info), 'assembly-reference-warning'));
      if (info?.game_rel) context.append(make('p', `Preview candidate: ${info.game_rel}`, 'assembly-path'));
      context.append(make('p', 'Connected editing is available when the mesh’s material reference is verified. Inspect mode retains the existing preview controls.', 'assembly-empty'));
      return;
    }
    context.append(chip(ownership(info.game_rel), !!projectRecord(info.game_rel)),
      ...(edited[selected] ? [chip('Unsaved colours', true)] : []));
    if (info.material_error) context.append(make('p', `Material properties unavailable: ${info.material_error}`, 'assembly-reference-warning'));
    const path = make('p', info.game_rel, 'assembly-path'); path.title = info.game_rel; context.append(path);
    const materialNames = relatedMaterials(data, info.game_rel), affected = sections.filter(s => materialNames.includes(s.name));
    const used = make('div', null, 'assembly-affected');
    used.append(make('span', `Affects ${affected.length} visible section${affected.length === 1 ? '' : 's'}`));
    for (const other of affected) {
      const control = button(`${api.label(other.name)} · ${sections.indexOf(other)+1}`, () => choose(other));
      control.title = `${other.owner.name} · Section ${other.groupIndex + 1}`;
      control.setAttribute('aria-pressed', String(other.id === section?.id)); used.append(control);
    }
    context.append(used);
    const shader = make('dl', null, 'assembly-properties');
    shader.append(make('dt', 'Shader'), make('dd', info.surface?.parent || 'Not reported'),
      make('dt', 'Texture slots'), make('dd', String(boundTextures(info).length)));
    if (info.surface?.blend) shader.append(make('dt', 'Blend'), make('dd', info.surface.blend.replace('BLEND_', '')));
    context.append(shader, button('Edit material', () => api.editMaterial(selected), 'assembly-primary'));
    if (info.visibility_warning) context.append(make('p', info.visibility_warning, 'assembly-empty'));
    const inferred = (info.texture_sources || []).filter(source => source.inferred);
    if (inferred.length) context.append(make('p', `${inferred.length} preview shader default${inferred.length === 1 ? '' : 's'} omitted from connected slots: ${inferred.map(s=>s.slot).join(', ')}.`, 'assembly-empty'));
  }

  // Small CPU thumbnails are shared by URL and project, capped at 48 images. Two
  // readers and intersection loading prevent extracting off-screen slot images.
  function clearThumbnailWork() {
    thumbGeneration++; thumbQueue = []; imageObserver?.disconnect(); imageObserver = null;
    for (const pending of thumbPending.values()) pending.controller.abort();
    thumbPending.clear();
  }
  function releaseThumbnails() {
    clearThumbnailWork(); for (const url of thumbnails.values()) URL.revokeObjectURL(url); thumbnails.clear();
  }
  function loadThumb(img, url) {
    if (thumbnails.has(url)) { img.src = thumbnails.get(url); return; }
    thumbQueue.push({img, url, generation:thumbGeneration}); pumpThumbs();
  }
  function pumpThumbs() {
    while (thumbReaders < 2 && thumbQueue.length) {
      const item = thumbQueue.shift();
      if (!item.img.isConnected || item.generation !== thumbGeneration || !active || texturesCollapsed) continue;
      thumbReaders++;
      const controller = new AbortController(); thumbPending.set(item.img, {controller});
      api.fetch(item.url, {signal:controller.signal}).then(response => {
        if (!response.ok) throw Error('Thumbnail unavailable'); return response.blob();
      }).then(blob => {
        if (item.generation !== thumbGeneration || !item.img.isConnected) return;
        const url = URL.createObjectURL(blob);
        if (thumbnails.has(item.url)) URL.revokeObjectURL(url);
        else thumbnails.set(item.url, url);
        item.img.src = thumbnails.get(item.url);
        while (thumbnails.size > 48) { const key = thumbnails.keys().next().value; URL.revokeObjectURL(thumbnails.get(key)); thumbnails.delete(key); }
      }).catch(error => {
        if (error.name !== 'AbortError' && item.img.isConnected) {
          item.img.parentElement.dataset.failed = 'true'; item.img.alt = 'Preview unavailable';
        }
      }).finally(() => { thumbReaders--; thumbPending.delete(item.img); pumpThumbs(); });
    }
  }
  function thumbnailURL(source, info) {
    const query = new URLSearchParams({game_rel:source.custom ? info.game_rel : source.game_rel,
      v:source.url, ...(source.custom ? {slot:source.slot} : {})});
    return api.url('/api/assembly_thumbnail?' + query);
  }
  function renderTextures(force = false) {
    const info = selectedInfo(), sources = boundTextures(info);
    if (!info && api.state().selected && api.state().loading) return;
    const signature = JSON.stringify([api.state().project, api.state().selected, sources, texturesCollapsed]);
    $('assembly-texture-count').textContent = sources.length ? String(sources.length) : '';
    $('assembly-texture-context').textContent = verifiedBinding(info) ? leaf(info.game_rel) : 'Select a verified material';
    if (signature === shelfSignature && !force) { renderTextureActions(); return; }
    shelfSignature = signature; clearThumbnailWork();
    const cards = $('assembly-texture-cards'); cards.replaceChildren();
    if (texture && info) texture = sources.find(source => source.slot === texture.slot) || null;
    if (texturesCollapsed || !active) return;
    if (!sources.length) {
      cards.append(make('p', info && verifiedBinding(info) ? 'No explicit texture bindings were reported for this material.' : 'Select a model surface to reveal its connected textures.', 'assembly-empty'));
    } else {
      imageObserver = new IntersectionObserver(entries => {
        for (const entry of entries) if (entry.isIntersecting) {
          imageObserver?.unobserve(entry.target); loadThumb(entry.target, entry.target.dataset.src);
        }
      }, {root:cards, rootMargin:'0px 100px'});
      for (const source of sources) {
        const card = button('', () => selectTexture(source), 'assembly-texture-card');
        card.dataset.asset = source.game_rel; card.dataset.slot = source.slot; card.setAttribute('aria-pressed', 'false');
        card.title = `${source.slot}\n${source.game_rel}\n${ownership(source.game_rel, source.custom)}`;
        const preview = make('span', null, 'assembly-texture-preview');
        const img = make('img'); img.alt = ''; img.width = img.height = 80; img.decoding = 'async';
        img.dataset.src = thumbnailURL(source, info); preview.append(img, make('span', 'Preview unavailable', 'assembly-thumb-error'));
        card.append(preview, make('strong', roleLabel(source)), make('span', leaf(source.game_rel), 'assembly-texture-name'),
          chip(ownership(source.game_rel, source.custom), source.custom || !!projectRecord(source.game_rel)));
        card.setAttribute('aria-label', `${source.slot}: ${leaf(source.game_rel)}. ${ownership(source.game_rel, source.custom)}`);
        cards.append(card); imageObserver.observe(img);
      }
    }
    renderTextureActions();
  }

  function renderTextureActions() {
    const host = $('assembly-texture-actions'); host.replaceChildren(); host.hidden = !texture;
    if (!texture) return;
    const info = selectedInfo(), selected = api.state().selected;
    host.append(make('span', `${texture.slot} · ${textureUsers(api.state().data, texture).length} material slot(s)`, 'assembly-texture-usage'));
    const preview = button('Preview', () => window.AtelierLibraryTools?.previewImage({label:leaf(texture.game_rel), path:texture.game_rel,
      src:api.url(texture.url), caption:`${texture.slot} · ${ownership(texture.game_rel, texture.custom)}`}, preview));
    host.append(preview);
    if (texture.custom) host.append(button('Edit texture slot', () => api.editMaterial(selected, texture.slot)));
    else {
      const source = texture;
      const replace = button('Replace texture', () => api.replaceTexture(source));
      replace.disabled = !projectRecord(source.game_rel);
      replace.title = replace.disabled ? 'Edit this texture to add it to the project before replacing it.' : 'Replace this project texture using the existing image workflow';
      host.append(button('Edit texture', () => api.editTexture(source)), replace);
    }
    if (info?.game_rel) host.append(button('Edit material slot', () => api.editMaterial(selected, texture.slot)));
    const path = make('span', texture.game_rel, 'assembly-texture-path'); path.title = texture.game_rel; host.append(path);
  }

  function updateRelationships() {
    const {data, selected} = api.state(), info = data[selected], picked = currentSection();
    const names = new Set(texture ? textureUsers(data, texture) : verifiedBinding(info) ? relatedMaterials(data, info.game_rel) : []);
    for (const row of $('assembly-sections').querySelectorAll('[data-material]')) row.classList.toggle('is-related', names.has(row.dataset.material));
    for (const card of $('assembly-texture-cards').children) if (card.dataset.asset) {
      const chosen = !!texture && assetKey(card.dataset.asset) === assetKey(texture.game_rel) && card.dataset.slot === texture.slot;
      card.setAttribute('aria-pressed', String(chosen));
    }
    api.highlight(active && selected ? texture || materialFocus ? {names} : {names:new Set([selected]), section:picked} : null);
    selection.replaceChildren();
    if (!selected) {
      selection.append(make('span', 'ASSEMBLY', 'assembly-eyebrow'), make('strong', 'Every surface has a story.'), make('span', 'Select a part to follow its resources.'));
    } else {
      selection.append(make('strong', api.label(selected)), make('span', '→', 'assembly-connection-arrow'),
        make('span', verifiedBinding(info) ? leaf(info.game_rel) : 'Reference unverified'),
        make('span', '→', 'assembly-connection-arrow'), make('span', texture ? `${texture.slot} · ${names.size} slot(s)` : `${boundTextures(info).length} textures`));
    }
  }

  function renderEffects() {
    const section = currentSection(), info = selectedInfo();
    const key = JSON.stringify([api.state().project, section?.mesh_game_rel, verifiedBinding(info) ? info.game_rel : null]);
    if (key !== effectsKey) { effectsRequest?.abort(); effectsRequest = null; effectsKey = key; }
    const host = $('assembly-effect-content'); host.replaceChildren(); $('assembly-effect-count').textContent = '';
    const result = effectResults.get(key);
    if (result) {
      $('assembly-effect-count').textContent = String(result.effects.length);
      for (const effect of result.effects) {
        const open = button(effect.name, () => api.effect(effect)); open.title = `${effect.game_rel}\nReferenced by ${effect.sources.join(', ')}`; host.append(open);
      }
      if (!result.effects.length) host.append(make('p', 'No direct VFX references found for this selection.', 'assembly-empty'));
      for (const warning of result.warnings) host.append(make('p', warning, 'assembly-reference-warning'));
      host.append(make('p', result.scope, 'assembly-empty')); return;
    }
    host.append(make('p', 'Inspect the selected mesh and material’s package references. Effects that refer to a material from another asset are not indexed.', 'assembly-empty'));
    const inspect = button(effectsRequest ? 'Reading references…' : 'Inspect references', async () => {
      const controller = new AbortController(); effectsRequest = controller; renderEffects();
      try {
        const response = await api.fetch('/api/assembly_references', {method:'POST', signal:controller.signal,
          headers:{'Content-Type':'application/json'}, body:JSON.stringify({mesh_game_rel:section.mesh_game_rel, material_game_rel:verifiedBinding(info) ? info.game_rel : ''})});
        const result = await response.json();
        if (!response.ok || !result.ok) throw Error(result.error || 'References unavailable');
        if (key !== effectsKey || controller.signal.aborted) return;
        effectResults.set(key, result); effectsRequest = null; renderEffects();
      } catch (error) {
        if (controller.signal.aborted || key !== effectsKey) return;
        effectsRequest = null; renderEffects(); host.append(make('p', error.message, 'assembly-reference-warning'));
      }
    });
    inspect.disabled = !section?.mesh_game_rel || !!effectsRequest; host.append(inspect);
  }

  function pulse() {
    if (!active || !surface || !verifiedBinding(selectedInfo())) return;
    clearTimeout(linkTimer); links.classList.remove('is-linking');
    if (window.AtelierMotionPolicy?.allows(1) === false || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const bounds = new THREE.Box3().setFromObject(surface.object), point = bounds.getCenter(new THREE.Vector3()).project(api.camera);
    if (![point.x, point.y, point.z].every(Number.isFinite) || point.z < -1 || point.z > 1 || Math.abs(point.x) > 1 || Math.abs(point.y) > 1) return;
    const w = stage.clientWidth, h = stage.clientHeight, x = (point.x + 1)*w/2, y = 58 + (1-point.y)*(h-58)/2;
    links.setAttribute('viewBox', `0 0 ${w} ${h}`);
    const paths = links.querySelectorAll('path');
    paths[0].setAttribute('d', `M${x},${y} C${x+40},${y} ${w-60},${h*.5} ${w},${h*.5}`);
    paths[1].setAttribute('d', `M${x},${y} C${x},${y+40} ${w*.5},${h-20} ${w*.5},${h}`);
    links.querySelector('circle').setAttribute('cx', x); links.querySelector('circle').setAttribute('cy', y);
    void links.getBoundingClientRect(); links.classList.add('is-linking');
    linkTimer = setTimeout(() => links.classList.remove('is-linking'), 620);
  }

  function sync() {
    if (!active) return;
    const state = api.state(); sections = modelSections(state.objects, state.metadata);
    if (state.selected !== lastMaterial) { if (surface?.name !== state.selected) surface = null; texture = null; materialFocus = false; lastMaterial = state.selected; }
    if (surface && !hitSection(sections, surface)) surface = null;
    renderGeometry(); renderMaterial(); renderTextures(); renderEffects(); updateRelationships();
    window.AtelierIcons?.createIcons({nodes:[geometry, context]});
  }
  function schedule() { if (!active || syncFrame) return; syncFrame = requestAnimationFrame(() => { syncFrame = 0; sync(); }); }
  function layout() {
    box.classList.toggle('assembly-geometry-collapsed', geometryCollapsed);
    box.classList.toggle('assembly-textures-collapsed', texturesCollapsed);
    $('assembly-geometry-collapse').setAttribute('aria-expanded', String(!geometryCollapsed));
    $('assembly-textures-collapse').setAttribute('aria-expanded', String(!texturesCollapsed));
    $('assembly-textures-collapse').setAttribute('aria-label', `${texturesCollapsed ? 'Expand' : 'Collapse'} textures`);
    geometryResize.setAttribute('aria-valuenow', Math.round(geometry.getBoundingClientRect().width));
    resourceResize.setAttribute('aria-valuenow', Math.round($('viewport-materials').getBoundingClientRect().width));
    api.resize();
  }
  $('assembly-search').addEventListener('input', event => { query = event.target.value.toLowerCase().trim(); renderGeometry(); updateRelationships(); });
  $('assembly-geometry-collapse').addEventListener('click', () => { geometryCollapsed = true; layout(); });
  focusPanel.addEventListener('click', () => { geometryCollapsed = false; layout(); });
  $('assembly-textures-collapse').addEventListener('click', () => { texturesCollapsed = !texturesCollapsed; layout(); renderTextures(true); });
  function mountResize(handle, property, minimum, maximum, direction) {
    const set = value => { const clamped = Math.round(Math.max(minimum, Math.min(maximum, value))); box.style.setProperty(property, `${clamped}px`); handle.setAttribute('aria-valuenow', clamped); api.resize(); };
    handle.setAttribute('aria-valuemin', minimum); handle.setAttribute('aria-valuemax', maximum);
    handle.addEventListener('pointerdown', event => {
      if (event.button !== 0) return;
      const width = handle === geometryResize ? geometry.getBoundingClientRect().width : $('viewport-materials').getBoundingClientRect().width;
      resizeState = {x:event.clientX, width}; handle.setPointerCapture(event.pointerId); event.preventDefault();
    });
    handle.addEventListener('pointermove', event => { if (handle.hasPointerCapture(event.pointerId) && resizeState) set(resizeState.width + direction*(event.clientX-resizeState.x)); });
    handle.addEventListener('pointerup', event => { if (handle.hasPointerCapture(event.pointerId)) handle.releasePointerCapture(event.pointerId); resizeState = null; });
    handle.addEventListener('keydown', event => {
      if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return; event.preventDefault();
      const width = handle === geometryResize ? geometry.offsetWidth : $('viewport-materials').offsetWidth;
      set(event.key === 'Home' ? minimum : event.key === 'End' ? maximum : width + direction*(event.key === 'ArrowRight' ? 16 : -16));
    });
  }
  mountResize(geometryResize, '--assembly-geometry-width', 160, 300, 1);
  mountResize(resourceResize, '--assembly-material-width', 260, 460, -1);
  function setActive(value) {
    active = !!value; box.classList.toggle('is-assembly', active);
    geometry.hidden = shelf.hidden = context.hidden = resourceResize.hidden = selection.hidden = links.hidden = focusPanel.hidden = !active;
    if (!active) { clearThumbnailWork(); effectsRequest?.abort(); effectsRequest = null; api.highlight(null); }
    else { shelfSignature = ''; layout(); sync(); }
  }
  function reset() {
    surface = texture = null; materialFocus = false; lastMaterial = null; sections = []; effectsKey = ''; effectResults.clear();
    effectsRequest?.abort(); effectsRequest = null; query = ''; $('assembly-search').value = '';
    releaseThumbnails(); shelfSignature = ''; clearTimeout(linkTimer); links.classList.remove('is-linking'); api.highlight(null); schedule();
  }
  window.addEventListener('atelier:project-assets', schedule);
  window.addEventListener('pagehide', () => { reset(); cancelAnimationFrame(syncFrame); });
  setActive(false);
  return {setActive, sync:schedule, reset, surfacePicked(hit) { surface = hit; texture = null; materialFocus = false; lastMaterial = hit.name; schedule(); requestAnimationFrame(pulse); },
    invalidateReferences() {effectsRequest?.abort();effectsRequest=null;effectResults.clear();},
    active:() => active, selectedSurface:() => hitSection(sections, surface) ? surface : currentSection()};
}
