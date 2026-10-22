// UV X-Ray is CPU-only and loaded on demand. Geometry and shared Three textures remain borrowed.
import * as THREE from 'three';

const $ = id => document.getElementById(id);
const mapSlots = {basecolor:'map', emissive:'emissiveMap', opacity:'alphaMap', normal:'normalMap', orm:'roughnessMap'};
const attributeName = channel => channel === 0 ? 'uv' : `uv${channel}`;

export function uvChannels(geometry) {
  return Object.keys(geometry?.attributes || {}).filter(name => /^uv(?:[1-9]\d*)?$/.test(name))
    .map(name => name === 'uv' ? 0 : Number(name.slice(2))).sort((a,b) => a-b);
}

export function uvSection(surface) {
  const geometry = surface.object.geometry;
  const count = geometry.index?.count ?? geometry.attributes.position?.count ?? 0;
  let start = 0, end = count, section = null;
  // Three ignores groups for a single material. With an array, inspect only the hit group,
  // including when several separate groups happen to share the same material index.
  if (Array.isArray(surface.object.material)) {
    section = geometry.groups.findIndex(group => group.materialIndex === surface.face?.materialIndex
      && surface.faceIndex * 3 >= group.start && surface.faceIndex * 3 < group.start + group.count);
    if (section < 0) throw Error('The clicked triangle could not be matched to a material section.');
    const group = geometry.groups[section]; start = group.start; end = Math.min(count, start + group.count);
  }
  start = Math.max(start, geometry.drawRange.start);
  end = Math.min(end, geometry.drawRange.start + geometry.drawRange.count);
  if (!Number.isInteger(start) || !Number.isInteger(end) || start % 3 || end % 3 || end <= start)
    throw Error('This section does not contain a supported triangle layout.');
  return {start, end, section};
}

export function uvPoint(surface, channel) {
  const uv = surface.object.geometry.getAttribute(attributeName(channel)), face = surface.face, weights = surface.barycoord;
  if (!uv || !face || !weights || [face.a,face.b,face.c].some(vertex => vertex < 0 || vertex >= uv.count)) return null;
  const point = {u:uv.getX(face.a)*weights.x + uv.getX(face.b)*weights.y + uv.getX(face.c)*weights.z,
    v:uv.getY(face.a)*weights.x + uv.getY(face.b)*weights.y + uv.getY(face.c)*weights.z};
  return Number.isFinite(point.u) && Number.isFinite(point.v) ? point : null;
}

export function buildUVLayout(surface, channel, flipY = false) {
  const geometry = surface.object.geometry, attribute = geometry.getAttribute(attributeName(channel));
  if (!attribute || attribute.itemSize !== 2) throw Error(`UV${channel} has no supported two-component mesh coordinates.`);
  if (geometry.morphAttributes[attributeName(channel)]?.length) throw Error('Animated UV attributes are unsupported in v1.');
  const range = uvSection(surface), index = geometry.index;
  for (let i = range.start; i < range.end; i++) {
    const vertex = index ? index.getX(i) : i;
    if (!Number.isInteger(vertex) || vertex < 0 || vertex >= attribute.count) throw Error('UV data is incomplete for this section.');
    const u = attribute.getX(vertex), v = attribute.getY(vertex);
    if (!Number.isFinite(u) || !Number.isFinite(v)) throw Error('This UV channel contains invalid coordinates.');
    if (u < 0 || u > 1 || v < 0 || v > 1)
      throw Error('UVs extend outside the 0–1 tile. Repeating, mirrored and UDIM layouts are unsupported in v1; no wrapped approximation is shown.');
  }
  return {...range, attribute, index, flipY, triangles:(range.end-range.start)/3, point:uvPoint(surface,channel)};
}

export function drawUVLayout(context, layout, width, height) {
  const {attribute, index, start, end, flipY} = layout;
  context.strokeStyle = '#ffffff'; context.lineWidth = 1; context.lineJoin = 'round';
  context.beginPath();
  for (let i = start; i < end; i += 3) {
    for (let corner = 0; corner < 4; corner++) {
      const vertex = index ? index.getX(i + corner % 3) : i + corner % 3;
      const x = attribute.getX(vertex)*width, v = attribute.getY(vertex), y = (flipY ? 1-v : v)*height;
      if (corner === 0) context.moveTo(x,y); else context.lineTo(x,y);
    }
    // Bound temporary canvas paths on very large sections.
    if ((i-start) % 30000 === 29997) { context.stroke(); context.beginPath(); }
  }
  context.stroke();
}

export function textureSources(info, material) {
  if (info?.texture_sources?.length) return info.texture_sources;
  const roles = info?.texture_roles || {};
  const sources = Object.entries(info?.textures || {}).map(([slot,game_rel]) => {
    const role = Object.keys(roles).find(key => roles[key] === game_rel);
    return {slot, game_rel, role, texture_class:info.texture_classes?.[slot],
      url:info.texture_urls?.[role] || `/api/texture_png?game_rel=${encodeURIComponent(game_rel)}&v=${encodeURIComponent(info.tex_ver?.[game_rel] || '0')}`};
  });
  if (!sources.length) for (const [role,slot] of Object.entries(mapSlots)) {
    const texture = material?.[slot];
    if (texture?.image) sources.push({slot:`Embedded ${role}`, role, embedded:true, texture_class:texture.isCubeTexture ? 'TextureCube' : 'Texture2D'});
  }
  return sources;
}

export function mappingIssue(source, info, texture) {
  if (source.texture_class && source.texture_class !== 'Texture2D')
    return `${source.texture_class} mapping is unsupported. UV X-Ray v1 supports 2D mesh UV textures.`;
  if (!source.texture_class && !texture) return 'The texture type is unavailable; a 2D UV mapping cannot be verified.';
  if (info?.eye_preview) return 'Layered eye shader mapping is unsupported in v1. A source texture can be viewed, but its UV overlay and export are unavailable.';
  if (/triplanar|world[ _-]?(?:aligned|project)/i.test(info?.surface?.parent || ''))
    return 'World-projected or triplanar mapping is unsupported in v1.';
  if (texture) {
    if (texture.mapping !== THREE.UVMapping || texture.isCubeTexture || texture.isDataArrayTexture || texture.isData3DTexture)
      return 'This texture does not use a supported 2D mesh UV mapping.';
    if (texture.rotation !== 0 || texture.offset.x !== 0 || texture.offset.y !== 0 || texture.repeat.x !== 1 || texture.repeat.y !== 1
      || !texture.matrixAutoUpdate && !texture.matrix.equals(new THREE.Matrix3()))
      return 'Transformed texture coordinates are unsupported in v1. No untransformed overlay is substituted.';
  }
  return '';
}

export function createUVInspector(api) {
  const host = api.host;
  host.innerHTML = `
    <div class="vp-uv-heading"><h3>UV X-Ray <small>v1 · Read-only</small></h3></div>
    <p id="viewport-uv-empty">Click a mesh surface to inspect its material section, source texture and UV coordinates.</p>
    <div id="viewport-uv-content" hidden>
      <dl class="vp-uv-identity"><dt>Mesh / section</dt><dd id="viewport-uv-mesh"></dd><dt>Material</dt><dd id="viewport-uv-material"></dd></dl>
      <label class="vp-uv-field">Project source texture<select id="viewport-uv-source"></select></label>
      <p id="viewport-uv-source-path" class="vp-uv-path"></p>
      <div class="vp-uv-controls"><label class="vp-uv-field">UV channel<select id="viewport-uv-channel"></select></label>
        <label class="vp-uv-field">Zoom<select id="viewport-uv-zoom"><option value="1">Fit</option><option value="2">2×</option><option value="4">4×</option><option value="8">8×</option></select></label></div>
      <label class="vp-uv-opacity">Overlay opacity <output id="viewport-uv-opacity-value">80%</output><input id="viewport-uv-opacity" type="range" min="0" max="100" value="80" title="Preview opacity; exported UV lines are opaque"></label>
      <p id="viewport-uv-point" class="vp-uv-coordinate"></p>
      <p id="viewport-uv-status" role="status" aria-live="polite"></p>
      <div id="viewport-uv-scroll" tabindex="0" aria-label="Texture with mesh UV wireframe. Scroll to pan when zoomed."><div id="viewport-uv-sheet" hidden><canvas id="viewport-uv-image" aria-label="Source texture"></canvas><canvas id="viewport-uv-wire" aria-label="Mesh UV wireframe"></canvas></div></div>
      <p id="viewport-uv-resolution"></p>
      <button id="viewport-uv-export" disabled>Export UV layout PNG</button>
      <p class="vp-uv-note">Exports white UV lines on transparency at the source image’s exact resolution. The texture and click marker are excluded.</p>
      <p id="viewport-uv-mapping-note" class="vp-uv-note"></p>
    </div>`;
  let surface = null, info = null, sources = [], image = null, objectURL = null, layout = null;
  let revision = 0, controller = null, exporting = false, previewFrame = 0;
  const imageCanvas = $('viewport-uv-image'), wireCanvas = $('viewport-uv-wire');
  const sourceSelect = $('viewport-uv-source'), channelSelect = $('viewport-uv-channel');
  const dimensions = () => ({width:image?.naturalWidth || image?.width || 0, height:image?.naturalHeight || image?.height || 0});
  const selectedSource = () => sources[Number(sourceSelect.value)];
  function exportSizeSupported() {
    const {width,height} = dimensions();
    return width > 0 && height > 0 && width <= 16384 && height <= 16384 && width*height <= 67108864;
  }
  function refreshExport() {
    $('viewport-uv-export').disabled = exporting || !layout || !exportSizeSupported();
  }
  function sourceMap(source) {
    // Dye/eye maps are generated composites, not the source image identified by a texture slot.
    if (source?.role === 'basecolor' && (info?.dyeable || info?.eye_preview)) return null;
    const role = source && 'preview_role' in source ? source.preview_role : source?.role;
    // Only these slots are assigned from project metadata by Model Studio. Other maps can
    // still belong to the imported glTF, so borrowing them would misidentify the source.
    if (!source?.embedded && !['basecolor','emissive','opacity'].includes(role)) return null;
    return surface?.material?.[mapSlots[role]] || null;
  }
  function status(text, error = false) {
    $('viewport-uv-status').textContent = text; $('viewport-uv-status').dataset.kind = error ? 'warning' : 'info';
  }
  function releaseImage() {
    image = null;
    if (objectURL) URL.revokeObjectURL(objectURL);
    objectURL = null; imageCanvas.width = imageCanvas.height = wireCanvas.width = wireCanvas.height = 1;
    $('viewport-uv-sheet').hidden = true;
  }
  function clear() {
    revision++; controller?.abort(); controller = null; surface = info = layout = null; sources = [];
    cancelAnimationFrame(previewFrame); releaseImage();
    sourceSelect.replaceChildren(); channelSelect.replaceChildren();
    for (const id of ['viewport-uv-source-path','viewport-uv-point','viewport-uv-resolution','viewport-uv-status','viewport-uv-mapping-note']) $(id).textContent = '';
    $('viewport-uv-empty').hidden = false; $('viewport-uv-content').hidden = true; $('viewport-uv-export').disabled = true;
  }
  function render() {
    if (!image || host.hidden) return;
    const {width,height} = dimensions(), scroll = $('viewport-uv-scroll'), sheet = $('viewport-uv-sheet');
    const fit = Math.min(Math.max(1,scroll.clientWidth-20)/width, Math.max(160,scroll.clientHeight-20)/height, 1);
    const zoom = Number($('viewport-uv-zoom').value), cssWidth = Math.max(1,Math.round(width*fit*zoom)), cssHeight = Math.max(1,Math.round(height*fit*zoom));
    // Preview backing stores are capped; export gets its own full-resolution canvas only on demand.
    const scale = Math.min(window.devicePixelRatio || 1, 1536/Math.max(cssWidth,cssHeight));
    for (const canvas of [imageCanvas,wireCanvas]) {
      canvas.width = Math.max(1,Math.round(cssWidth*scale)); canvas.height = Math.max(1,Math.round(cssHeight*scale));
    }
    sheet.style.width = `${cssWidth}px`; sheet.style.height = `${cssHeight}px`; sheet.hidden = false;
    const context = imageCanvas.getContext('2d'); context?.drawImage(image,0,0,imageCanvas.width,imageCanvas.height);
    const wire = wireCanvas.getContext('2d');
    if (layout && wire) {
      drawUVLayout(wire,layout,wireCanvas.width,wireCanvas.height);
      if (layout.point) {
        const x = layout.point.u*wireCanvas.width, y = (layout.flipY ? 1-layout.point.v : layout.point.v)*wireCanvas.height;
        wire.strokeStyle = '#000'; wire.lineWidth = 4; wire.beginPath(); wire.arc(x,y,5*scale,0,Math.PI*2); wire.stroke();
        wire.strokeStyle = '#ffcf45'; wire.lineWidth = 2; wire.stroke();
      }
    }
  }
  function scheduleRender() { cancelAnimationFrame(previewFrame); previewFrame = requestAnimationFrame(render); }
  function updatePoint() {
    if (!surface) return;
    const channel = Number(channelSelect.value), point = uvPoint(surface,channel);
    $('viewport-uv-point').textContent = point ? `Clicked UV${channel}: U ${point.u.toFixed(6)} · V ${point.v.toFixed(6)}` : 'Clicked coordinates unavailable for this channel.';
  }
  function updateLayout() {
    layout = null; $('viewport-uv-export').disabled = true; $('viewport-uv-resolution').textContent = '';
    updatePoint();
    if (!surface || !image) return;
    const source = selectedSource(), texture = sourceMap(source), channel = Number(channelSelect.value);
    const {width,height} = dimensions();
    $('viewport-uv-resolution').textContent = `${width.toLocaleString()} × ${height.toLocaleString()} px · ${source.custom ? 'Project custom texture' : source.embedded ? 'Embedded model image' : 'Project / decoded source image'}`;
    let issue = mappingIssue(source,info,texture);
    if (!uvChannels(surface.object.geometry).length) issue = 'This mesh has no decoded UV channels. Overlay and export are unavailable.';
    if (!issue) try { layout = buildUVLayout(surface,channel,texture?.flipY ?? false); } catch (error) { issue = error.message; }
    if (issue) status(issue,true);
    else {
      status(`${layout.triangles.toLocaleString()} triangle${layout.triangles === 1 ? '' : 's'} · Mesh UV layout. Cooked shader mapping unavailable.`);
      refreshExport();
      if (!exportSizeSupported()) status('This source exceeds the v1 export limit (16,384 px per side / 64 megapixels). Its resolution will not be reduced.',true);
    }
    $('viewport-uv-mapping-note').textContent = `${texture && channel !== texture.channel ? `UV${channel} is selected for inspection; the viewport texture uses UV${texture.channel}. ` : ''}This is the decoded mesh UV layout. Cooked shader UV transformations are unavailable and are not reconstructed.`;
    render();
  }
  async function loadSource() {
    const stamp = ++revision; controller?.abort(); controller = new AbortController();
    releaseImage(); layout = null; $('viewport-uv-export').disabled = true;
    $('viewport-uv-point').textContent = ''; $('viewport-uv-resolution').textContent = '';
    const source = selectedSource();
    if (!surface) return;
    const texture = sourceMap(source), channels = uvChannels(surface.object.geometry);
    channelSelect.replaceChildren(...channels.map(channel => new Option(`UV${channel}`,String(channel))));
    channelSelect.disabled = channels.length < 2;
    channelSelect.value = String(channels.includes(texture?.channel) ? texture.channel : channels[0] ?? '');
    updatePoint();
    if (!source) { status(info?.mapping_error || 'This section has no identifiable source textures. Overlay and export are unavailable.',true); return; }
    $('viewport-uv-source-path').textContent = source.game_rel || 'Embedded model image · no separate project asset identity';
    status('Loading source texture…');
    let pendingURL = null;
    try {
      if (source.texture_class && source.texture_class !== 'Texture2D') { status(mappingIssue(source,info,texture),true); return; }
      const shared = texture?.image;
      if (shared && (shared.naturalWidth || shared.width) && !shared.data) image = shared;
      else {
        if (!source.url) throw Error('The embedded texture has no readable 2D source image.');
        const response = await api.fetch(source.url,{signal:controller.signal});
        if (!response.ok) throw Error(`Source texture unavailable (HTTP ${response.status}).`);
        const blob = await response.blob();
        if (stamp !== revision) return;
        pendingURL = URL.createObjectURL(blob);
        const decoded = new Image(), signal = controller.signal;
        const abortDecode = () => decoded.removeAttribute('src');
        signal.addEventListener('abort',abortDecode,{once:true});
        try { decoded.src = pendingURL; await decoded.decode(); }
        finally { signal.removeEventListener('abort',abortDecode); }
        if (stamp !== revision) return;
        image = decoded; objectURL = pendingURL; pendingURL = null;
      }
      updateLayout();
    } catch (error) { if (stamp === revision && error.name !== 'AbortError') status(error.message,true); }
    finally { if (pendingURL) URL.revokeObjectURL(pendingURL); }
  }
  function select(hit) {
    clear(); surface = hit;
    if (!surface) return;
    info = api.materials().data[hit.name] || {};
    $('viewport-uv-empty').hidden = true; $('viewport-uv-content').hidden = false;
    let section = '';
    try { const range = uvSection(hit); section = range.section === null ? 'Mesh section' : `Geometry section ${range.section}`; } catch (error) { section = error.message; }
    $('viewport-uv-mesh').textContent = `${hit.object.name || 'Mesh'} · ${section}${Number.isInteger(info.slot_index) ? ` · Cooked slot ${info.slot_index}` : ''}${info.mesh_game_rel ? `\n${info.mesh_game_rel}` : ''}`;
    $('viewport-uv-material').textContent = `${api.label(hit.name)}\n${info.game_rel || info.mapping_error || hit.material.userData.slotName || hit.name}`;
    sources = textureSources(info,hit.material);
    sourceSelect.replaceChildren(...sources.map((source,index) => new Option(`${source.slot}${source.custom ? ' · Custom' : ''}`,String(index))));
    sourceSelect.disabled = sources.length < 2;
    sourceSelect.value = String(Math.max(0,sources.findIndex(source => source.role === 'basecolor')));
    $('viewport-uv-zoom').value = '1'; $('viewport-uv-scroll').scrollTo(0,0);
    loadSource();
  }
  async function exportLayout() {
    if (!layout || !image || exporting || $('viewport-uv-export').disabled) return;
    const stamp = revision, {width,height} = dimensions(), source = selectedSource(), canvas = document.createElement('canvas');
    exporting = true; $('viewport-uv-export').disabled = true; status('Exporting transparent UV layout…');
    try {
      canvas.width = width; canvas.height = height;
      const context = canvas.getContext('2d');
      if (!context) throw Error('A canvas at the exact source resolution could not be allocated.');
      drawUVLayout(context,layout,width,height);
      const blob = await new Promise((resolve,reject) => canvas.toBlob(value => value ? resolve(value) : reject(Error('PNG encoding failed at the source resolution.')),'image/png'));
      if (stamp !== revision) return;
      const url = URL.createObjectURL(blob), anchor = document.createElement('a');
      anchor.href = url;
      const name = (source.game_rel?.split('/').pop() || source.slot).replace(/[^a-z0-9_-]/gi,'_');
      anchor.download = `${name}_UV${channelSelect.value}_${width}x${height}.png`; anchor.click();
      setTimeout(() => URL.revokeObjectURL(url),1000);
      status(`Exported ${width} × ${height} transparent PNG.`);
    } catch (error) { if (stamp === revision) status(error.message,true); }
    finally {
      // Encoding cannot be cancelled. Retain the guard across selection/close until this
      // full-resolution canvas is released, then use the current selection's eligibility.
      canvas.width = canvas.height = 1; exporting = false; refreshExport();
    }
  }
  sourceSelect.addEventListener('change',loadSource);
  channelSelect.addEventListener('change',() => { if (image) revision++; updateLayout(); });
  $('viewport-uv-zoom').addEventListener('change',render);
  $('viewport-uv-opacity').addEventListener('input',event => {
    wireCanvas.style.opacity = String(Number(event.target.value)/100); $('viewport-uv-opacity-value').value = `${event.target.value}%`;
  });
  wireCanvas.style.opacity = '.8';
  $('viewport-uv-export').addEventListener('click',exportLayout);
  new ResizeObserver(scheduleRender).observe($('viewport-uv-scroll'));
  return {select,clear};
}
