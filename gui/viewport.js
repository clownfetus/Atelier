// 3D viewport — loads a skin's meshes (decoded to glTF by AtelierMesh/CUE4Parse), renders them
// in rest pose with three.js, and tints each part from its MI material params with live recolor.
// glTF labels are matched to cooked mesh slots through their import table. Body and weapon
// sections keep separate identities even when their labels or material assets are shared.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader }    from 'three/addons/loaders/GLTFLoader.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { createViewportInspection } from './viewport-inspection.js';
import { createViewportAnimation } from './viewport-animation.js';
import { createViewportFloor } from './viewport-effects.js';
import { textureRoles, applySurface, emissiveColorIndex as pickEmissiveIdx, applyEmissive } from './viewport-materials.js';
import { attachmentRig, bindWeapon, updateWeapon, pairedWeapon, embeddedWeaponMaterials, weaponSide } from './viewport-attachments.js';
import { createAssemblyView } from './assembly.js';
import { verifiedBinding } from './assembly-data.js';

const $ = id => document.getElementById(id);
// The server says why a model is unavailable in the JSON body; three.js only reports the status
// line ("responded with 404: Not Found") and keeps the Response on the error, unread.
async function loadErrorText(e) {
  const response = e && e.response;
  if (response && typeof response.clone === 'function') {
    try {
      const body = await response.clone().json();
      if (body && body.error) return String(body.error);
    } catch (_) { /* not JSON: fall back to the loader's own message */ }
  }
  return String(e && e.message || e);
}
const loader    = new GLTFLoader();
const texLoader = new THREE.TextureLoader();
const texCache  = new Map();   // texGameRel -> THREE.Texture, shared/reused across opens (never re-uploaded)
const texPending = new Map();

let renderer, scene, camera, controls, grid, modelRoot;
let raf = 0, inited = false;
let inspection, soloSnapshot = null, soloTarget = null, materialReturnObserver = null;
let animation, lastFrame = 0;
let materialTask = null;
let materialLoad = null;
let modelLoad = null, modelLoading = false;
const visibilityBusy = new Set();
let meshSlots = [];
let heroId = '';
let selectedMaterial = null;
let assembly, workspaceMode = 'inspect', connectedEditorPending = false, assemblyRefreshTimer = 0;
let preserveAnimationCamera = false;
try { if (localStorage.getItem('atelier.assembly') === '1') workspaceMode = 'assembly'; } catch (_) {}

function updateHeroLogo(id = heroId) {
  heroId = id;
  const logo = $('viewport-hero-logo');
  logo.hidden = true;
  logo.onload = () => { logo.hidden = false; };
  logo.onerror = () => { logo.hidden = true; };
  if (id) logo.src = `/api/catalogue/hero/${encodeURIComponent(id)}/logo`;
  else logo.removeAttribute('src');
}
window.addEventListener('atelier:catalogue-updated', () => { if (heroId) updateHeroLogo(); });
let generation = 0;   // bumped on every clear/open; async texture loads bail if it changed under them
let materialGeneration = 0, saving = false, viewportProject = '';
const liveDyeTextures = new Map(), baselineMaps = new Map();
const projectUrl = url => url + (url.includes('?') ? '&' : '?') + '_project=' + encodeURIComponent(viewportProject);
const projectFetch = (url, opts = {}, project = viewportProject) =>
  window.atelierFetch ? window.atelierFetch(url, opts, project) : fetch(url, opts);

function cancelMaterialLoad() {
  const load = materialLoad;
  materialLoad = null;
  materialTask = null;
  inspection?.setLoading(modelLoading);
  if (!load) return;
  materialGeneration++;
  for (const timer of Object.values(_dyeMeshTimer)) clearTimeout(timer);
  load.controller.abort();
  load.spinner?.remove();
  // A separate request also stops native work already accepted by the backend.
  projectFetch('/api/viewport_cancel', {method:'POST', keepalive:true,
    headers:{'Content-Type':'application/json'}, body:JSON.stringify({id:load.id})}, load.project).catch(() => {});
}

function materialFetch(url, options = {}, load = materialLoad) {
  return projectFetch(url, load ? {...options, signal:options.signal ? AbortSignal.any([options.signal, load.controller.signal]) : load.controller.signal,
    headers:{...options.headers, 'X-Atelier-Preview':load.id}} : options, load?.project ?? viewportProject);
}

function sceneFetch(url,options={}) {
  const load=modelLoad;
  return projectFetch(url,load?{...options,headers:{...options.headers,'X-Atelier-Preview':load.id}}:options,load?.project??viewportProject);
}

async function materialTexture(url, load = materialLoad) {
  const response = await materialFetch(url, {}, load);
  if (!response.ok) throw Error('Texture unavailable');
  const blob = await response.blob();
  load?.controller.signal.throwIfAborted();
  const objectUrl = URL.createObjectURL(blob);
  let texture;
  try {
    texture = await texLoader.loadAsync(objectUrl);
    load?.controller.signal.throwIfAborted();
    return texture;
  } catch (error) { texture?.dispose(); throw error; }
  finally { URL.revokeObjectURL(objectUrl); }
}

async function canLeave() {
  if (inspection?.capturing()) { note('Cancel the capture or wait for it to finish before leaving.', 'warning'); return false; }
  if (saving) { note('Wait for the save to finish before leaving this preview.', 'warning'); return false; }
  if (visibilityBusy.size) { note('Wait for the section visibility change to finish.', 'warning'); return false; }
  if (!Object.keys(edited).length) return true;
  const gen = generation, project = viewportProject;
  return await window.AtelierDialog.confirm({title:'Discard preview recolours?', body:'Discard unsaved preview recolors?', tone:'danger', confirmLabel:'Discard'})
    && gen === generation && project === viewportProject && !saving;
}

function clearLiveDyes() {
  for (const [name, tex] of liveDyeTextures) {
    for (const mat of matsByName[name] || []) {
      if (mat.map === tex) { mat.map = baselineMaps.get(name) || null; mat.needsUpdate = true; }
    }
    tex.dispose();
  }
  liveDyeTextures.clear();
}

function trimTextureCache() {
  const used = new Set(Object.values(matsByName).flatMap(ms => ms.flatMap(m => [m.map, m.emissiveMap, m.alphaMap])));
  for (const tex of baselineMaps.values()) used.add(tex);
  for (const [key, tex] of texCache) {
    if (texCache.size <= 64) break;
    if (!used.has(tex)) { texCache.delete(key); tex.dispose(); }
  }
}

// ── material state (per open) ─────────────────────────────────────────────────
let matsByName = {};   // "MI_..." -> [THREE.Material, ...]   (mesh materials sharing that slot)
let matData    = {};   // "MI_..." -> {game_rel, colors:[{name,rgba}], scalars, baseIdx}
let edited      = {};  // "MI_..." -> { paramName: [r,g,b,a] }  (unsaved session edits)
let currentSkin = null;
let objects     = [];  // [{ name, root: THREE.Object3D }] — one entry per top-level mesh added to modelRoot
let meshMeta    = [];  // [{ name, game_rel }] parallel to objects — source path for "Edit In Blender"

const clamp01 = v => Math.min(1, Math.max(0, v));
// ACES filmic tonemap (Narkowicz), per channel. UE material colours are LINEAR and often HDR (>1,
// up to ~10 for dye/emissive). Hard-clamping each channel to 1 renders them PURE WHITE and kills the
// hue; this rolls the highlights off smoothly into [0,1] instead. Matches the dye composite's tonemap
// so a colour reads the same on a swatch, as a mesh tint, and in the baked dye.
const aces = v => { v = Math.max(0, v); return Math.min(1, (v * (2.51 * v + 0.03)) / (v * (2.43 * v + 0.59) + 0.14)); };

// UE material colors are LINEAR floats; <input type=color> is sRGB. Convert via THREE.Color.
function linToHex(rgba) {
  const c = new THREE.Color();
  c.setRGB(aces(rgba[0]), aces(rgba[1]), aces(rgba[2]), THREE.LinearSRGBColorSpace);
  return '#' + c.getHexString(THREE.SRGBColorSpace);
}
function hexToLin(hex) {
  const c = new THREE.Color().setStyle(hex, THREE.SRGBColorSpace);
  // Reverse the display curve too: a chosen hex must survive selection and saving unchanged.
  // Saved Unreal parameters stay linear/HDR; opening or restoring never rewrites them.
  const inverseAces = value => {
    const a=2.51-value*2.43,b=.03-value*.59;
    return value<=0 ? 0 : (-b+Math.sqrt(b*b+4*a*value*.14))/(2*a);
  };
  return [c.r,c.g,c.b].map(inverseAces);
}

function pickBaseIdx(colors) {
  if (!colors || !colors.length) return -1;
  const score = n => {
    n = (n || '').toLowerCase();
    if (/emissive|glow|spec|rim|fresnel|subsurf|sss|ambient|shadow|_ao\b/.test(n)) return -10;
    // A global tint takes precedence over colours for a named material effect,
    // e.g. Venom's VenousGrowthBaseColor must not replace its white BaseTint.
    if (/^(?:base[ _-]?(?:color|tint)|albedo|diffuse)(?:[ _-]?color)?$/.test(n)) return 8;
    if (/base.?color|albedo|diffuse/.test(n)) return 6;
    if (/main.?color|body.?color|skin.?color/.test(n)) return 5;
    if (/^color$|_color\b|tint/.test(n)) return 4;
    if (/color/.test(n)) return 2;
    return 0;
  };
  let bi = 0, bs = score(colors[0].name);
  for (let i = 1; i < colors.length; i++) { const s = score(colors[i].name); if (s > bs) { bs = s; bi = i; } }
  return bs >= 4 ? bi : -1;   // only tint from a genuine base/tint/color param; else leave the map/grey
}

// The emissive glow is Emissive-mask-texture × EmissiveColor param × EmissiveStrength scalar — a
// separate channel from base colour. Recolouring the glow means changing EmissiveColor, applied
// through the emissive map, NOT multiplying the whole part's albedo.
const EMISSIVE_RE = /emiss|glow/i;
function paramRgb(name, idx) {
  const d = matData[name];
  if (!d || idx < 0 || !d.colors[idx]) return null;
  const p = d.colors[idx];
  const rgba = (edited[name] && edited[name][p.name]) || p.rgba;
  return rgba.slice(0,3).map(value=>Math.max(0,value)); // The renderer applies filmic tone mapping once.
}

function init() {
  if (inited) return;
  const canvas = $('viewport-canvas');
  renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1;

  scene  = new THREE.Scene();
  const room = new RoomEnvironment(), pmrem = new THREE.PMREMGenerator(renderer);
  // One small, offline studio environment shared by every model open.
  const environment = pmrem.fromScene(room, .04);
  scene.environment = environment.texture;
  scene.environmentIntensity = .45;
  room.dispose(); pmrem.dispose();
  window.addEventListener('pagehide', () => environment.dispose(), {once:true});
  camera = new THREE.PerspectiveCamera(40, 1, 0.1, 1e6);

  controls = new OrbitControls(camera, canvas);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;

  const hemisphere = new THREE.HemisphereLight(0xffffff, 0x404050, .45); scene.add(hemisphere);
  const key  = new THREE.DirectionalLight(0xffffff, 1.4); key.position.set(1, 2, 1.5);   scene.add(key);
  const fill = new THREE.DirectionalLight(0xaaccff, 0.5); fill.position.set(-1.5, 0.6, -1); scene.add(fill);

  grid = createViewportFloor();
  scene.add(grid);

  modelRoot = new THREE.Group();
  scene.add(modelRoot);
  animation = createViewportAnimation({objects:()=>objects.filter(object=>object.root.visible && object.kind !== 'weapon'), fetch:sceneFetch, frame:()=>{if(!preserveAnimationCamera)frameCamera();}, notify:note, changed:()=>inspection?.refresh()});
  inspection = createViewportInspection({renderer, scene, camera, controls, grid, modelRoot,
    lights:[hemisphere,key,fill], objects:() => objects,
    materials:() => ({data:matData, byName:matsByName, edited}),
    context:()=>({project:viewportProject,skin:currentSkin||meshSkin}),
    fetch:(url, options) => materialFetch(url, options), texture:materialTexture, url:projectUrl, hex:linToHex,
    tintOriginal, textureRoles, applySurface, pickMaterial, label:materialLabel, notify:note, resize:onResize,
    ready:()=>!modelLoading && !materialTask && !animation.loading() && !saving && !visibilityBusy.size, refreshEdits:refreshFoot,
    pauseAnimation:()=>animation.pause(), resumeAnimation:state=>animation.resume(state)});
  assembly = createAssemblyView({
    state:()=>({data:matData, edited, selected:selectedMaterial, objects, metadata:meshMeta, project:viewportProject, loading:modelLoading || !!materialTask}),
    camera, label:materialLabel, swatch:materialChipColor, fetch:projectFetch, url:projectUrl,
    sectionControl:name=>matData[name] ? sectionEye(name) : null,
    projectAssets:()=>window.AtelierAssetEditors?.projectAssets() || [],
    choose:(name,surface)=>{inspection.selectSurface(surface);pickMaterial(name,false,surface);},
    highlight:value=>inspection.setRelated(value),
    resize:()=>{inspection.preserveFraming();requestAnimationFrame(onResize);},
    uv:surface=>inspection.inspectSurface(surface),
    editMaterial:(name,slot)=>pickMaterial(name,true,null,slot),
    editTexture:source=>editAssemblyTexture(source),
    replaceTexture:source=>replaceAssemblyTexture(source),
    blender:gameRel=>{if(!hasPendingEdits())window.meshBlendExtract?.(gameRel,gameRel.split('/').pop());else focusPendingEdits();},
    replaceMesh:editAssemblyMesh,
    effect:effect=>openConnectedEditor('vfx-overlay',()=>window.openVfxEditor?.(effect), false),
  });
  for (const mode of ['inspect','assembly','showcase']) $('viewport-'+mode).addEventListener('click',()=>setWorkspaceMode(mode, true));

  $('viewport-mat-save').addEventListener('click', saveEdits);
  $('viewport-mesh-edit').addEventListener('click',async()=>{
    const index=objects.findIndex(object=>object.root.visible);
    if(index>=0 && assembly?.active()){editAssemblyMesh(meshMeta[index].game_rel);return;}
    if(index>=0 && await canLeave())window.AtelierMeshEdit?.add(meshMeta[index]);
  });
  $('viewport-mat-reset').addEventListener('click', revertEdits);
  $('viewport-back').addEventListener('click', close);
  $('viewport-material-search').addEventListener('input', filterMaterials);
  $('viewport-model-choice').addEventListener('change', event => {
    const value = event.target.value;
    const targets=objects.filter((object,index)=>value==='all' || object.kind!=='weapon' && index===Number(value));
    changeObjects(targets,()=>{
      for (const [index, object] of objects.entries()) {
        if (object.kind === 'weapon') { if (value === 'all') object.enabled=true; }
        else object.root.visible = object.loaded && (value === 'all' || index === Number(value));
      }
      soloSnapshot = soloTarget = null;
      selectedMaterial = null;
    },{automatic:true});
    $('viewport-model-menu').open = false;
  });
  $('viewport-blender-btn').addEventListener('click', editInBlender);
  $('viewport-blender-send').addEventListener('click', sendToBlenderLive);
  $('viewport-show-all').addEventListener('click', showAllObjects);
  $('viewport-show-hidden').addEventListener('click', showAllObjects);

  window.addEventListener('resize', onResize);
  new ResizeObserver(onResize).observe($('viewport-stage'));
  inited = true;
}

function setWorkspaceMode(mode, animate = false) {
  if (inspection?.capturing()) return;
  const changed = workspaceMode !== mode;
  workspaceMode = mode;
  inspection?.setShowcase(mode === 'showcase');
  assembly?.setActive(mode === 'assembly');
  for (const value of ['inspect','assembly','showcase']) $('viewport-'+value).setAttribute('aria-pressed',String(value === mode));
  $('viewport-workspace-label').textContent = mode === 'assembly' ? 'Assembly View' : 'Model Studio';
  try { localStorage.setItem('atelier.assembly',mode === 'assembly' ? '1' : '0'); } catch (_) {}
  requestAnimationFrame(onResize);
  if (animate && changed) window.AtelierMotion?.workflow?.workspace($('viewport-modes'), mode);
}

// Only one transient menu is open; Escape returns focus before it can leave the workspace.
for (const menu of document.querySelectorAll('#viewport-box .vp-menu')) {
  menu.addEventListener('toggle', () => {
    if (!menu.open) return;
    for (const other of document.querySelectorAll('#viewport-box .vp-menu[open]')) if (other !== menu) other.open = false;
  });
}
document.addEventListener('pointerdown', event => {
  if (!$('viewport-overlay').classList.contains('active')) return;
  for (const menu of document.querySelectorAll('#viewport-box .vp-menu[open]')) if (!menu.contains(event.target)) menu.open = false;
});

function onResize() {
  if (!renderer) return;
  if (inspection?.capturing()) return;
  const c = $('viewport-canvas');
  const w = c.clientWidth, h = c.clientHeight;
  if (!w || !h) return;
  const size = renderer.getSize(new THREE.Vector2());
  if (size.x === w && size.y === h && camera.aspect === w / h) return;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
  inspection?.resized();
}

function animate() {
  raf = requestAnimationFrame(animate);
  const now = performance.now();
  animation.update(lastFrame ? Math.min((now-lastFrame)/1000,.05) : 0); lastFrame = now;
  for (const object of objects) if (object.kind === 'weapon') {
    if(object.paired)object.paired.root.visible=object.root.visible && object.hand==='both' && !!object.paired.binding;
    if(object.root.visible)updateWeapon(object, object.binding);
    if(object.paired?.root.visible)updateWeapon(object.paired,object.paired.binding);
  }
  controls.update();
  inspection.render();
}

function disposeTree(obj) {
  // The glTF owns skeleton bone textures and may contain embedded maps of its own.
  // Retain shared cached maps, but release every resource allocated by this model load.
  const keep = new Set(texCache.values()), disposed = new Set();
  for (const tex of baselineMaps.values()) keep.add(tex);
  const dispose = resource => {
    if (resource && !disposed.has(resource)) { disposed.add(resource); resource.dispose(); }
  };
  obj.traverse(o => {
    dispose(o.geometry);
    dispose(o.skeleton);
    if (o.material) (Array.isArray(o.material) ? o.material : [o.material]).forEach(m => {
      for (const value of Object.values(m)) {
        if (value?.isTexture && !keep.has(value)) dispose(value);
      }
      dispose(m);
    });
  });
}

// The loader is optional presentation. Its errors must never block model decoding.
let viewportLoaderMotion = null;
let viewportLoadingBorder = null;

function destroyViewportLoader() {
  const motion = viewportLoaderMotion;
  viewportLoaderMotion = null;
  try { motion?.destroy(); } catch (e) { console.warn('viewport: loader cleanup failed', e); }
  const host = $('viewport-loading-motion-host');
  host?.replaceChildren();
  for (const attr of ['data-atelier-motion', 'data-am-state', 'data-am-reduced']) host?.removeAttribute(attr);
  $('viewport-loading-slot')?.removeAttribute('data-am-mounted');
}

function setViewportLoaderFallback(state) {
  const slot = $('viewport-loading-slot');
  if (!slot) return;
  slot.dataset.amState = state;
  const fallback = slot.querySelector('.am-viewport-loader-fallback');
  if (!fallback) return;
  const icon = state === 'error' ? 'alert-triangle' : 'box';
  if (fallback.dataset.icon === icon) return;
  fallback.dataset.icon = icon;
  fallback.innerHTML = `<i data-lucide="${icon}" size="72"></i>`;
  try { window.AtelierIcons?.createIcons({nodes: [fallback]}); } catch (_) {}
}

function startViewportLoader() {
  viewportLoadingBorder?.();
  const gen = generation, project = viewportProject;
  try {
    viewportLoadingBorder = window.AtelierMotion?.working?.begin($('viewport-box'), {
      kind: 'loading', anchor: $('viewport-loading-motion-host'),
      current: () => gen === generation && project === viewportProject && $('viewport-overlay').classList.contains('active')
    });
  } catch (_) { viewportLoadingBorder = null; }
  setViewportLoaderFallback('loading');
  const host = $('viewport-loading-motion-host');
  if (!host || !window.AtelierMotion?.viewportLoader) return;
  try {
    viewportLoaderMotion = window.AtelierMotion.viewportLoader.mount(host, {state: 'loading'});
    $('viewport-loading-slot').dataset.amMounted = 'true';
  } catch (e) {
    destroyViewportLoader();
    console.warn('viewport: loader unavailable', e);
  }
}

function setViewportLoaderState(state) {
  if (state !== 'loading') {
    try { viewportLoadingBorder?.(state === 'ready' ? 'success' : state === 'empty' ? 'warning' : 'error'); } catch (_) {}
    viewportLoadingBorder = null;
  }
  setViewportLoaderFallback(state);
  try { viewportLoaderMotion?.setState(state); }
  catch (e) {
    destroyViewportLoader();
    console.warn('viewport: loader unavailable', e);
  }
}

function clearModel() {
  try { viewportLoadingBorder?.(); } catch (_) {}
  viewportLoadingBorder = null;
  connectedEditorPending = false; clearTimeout(assemblyRefreshTimer);
  modelLoading=false;
  if (modelLoad) {
    const load=modelLoad;modelLoad=null;
    projectFetch('/api/viewport_cancel',{method:'POST',keepalive:true,headers:{'Content-Type':'application/json'},body:JSON.stringify({id:load.id})},load.project).catch(()=>{});
  }
  cancelMaterialLoad();
  animation?.reset(); lastFrame = 0;
  materialReturnObserver?.disconnect(); materialReturnObserver = null;
  inspection?.clearMaterials();
  destroyViewportLoader();
  generation++;   // invalidate any in-flight texture loads from the previous model
  materialGeneration++;
  for (const timer of Object.values(_dyeMeshTimer)) clearTimeout(timer);
  clearLiveDyes();
  baselineMaps.clear();
  for (const ch of [...modelRoot.children]) { modelRoot.remove(ch); disposeTree(ch); }
  matsByName = {}; matData = {}; edited = {}; currentSkin = null; objects = []; meshMeta = []; meshSlots=[];
  selectedMaterial = null;
  $('viewport-material-search').value = '';
  $('viewport-material-editor').replaceChildren(); $('viewport-material-editor').hidden = true;
  $('viewport-material-empty').hidden = false;
  $('viewport-mat-count').textContent = '';
  $('viewport-model-choice').replaceChildren(); $('viewport-model-label').textContent = 'Model';
  for (const menu of document.querySelectorAll('#viewport-box details')) menu.open = false;
  soloSnapshot = soloTarget = null;
  const list = $('viewport-mat-list'); if (list) list.innerHTML = '';
  const objList = $('viewport-obj-list'); if (objList) objList.innerHTML = '';
  updateSidebarVisibility();
  refreshBlenderBtn();
  trimTextureCache();
  inspection?.reset();
  refreshFoot();
  assembly?.reset();
  setWorkspaceMode(workspaceMode === 'assembly' ? 'assembly' : 'inspect');
}

// The studio exports the selected body and visible held weapons as one portable
// Blender scene. The mesh card's editing route keeps its per-mesh round trip.

let blenderExportPending = false;
function refreshBlenderBtn() {
  for (const id of ['viewport-blender-btn','viewport-blender-send']) {
    const btn = $(id);
    if (btn) btn.disabled = blenderExportPending || modelLoading || !objects.some(object=>object.loaded!==false && object.kind!=='weapon');
  }
}
async function blenderSelection() {
  const bodies = objects.filter(object=>object.loaded!==false && object.root.visible && object.kind !== 'weapon');
  if (bodies.length !== 1) {
    note(bodies.length?'Choose one body form from Model before sending or exporting to Blender.':'Show one body form from Model before sending or exporting to Blender.','info');
    return null;
  }
  const gen = generation, project = viewportProject;
  const target = meshMeta[objects.indexOf(bodies[0])];
  if (!target || !(await canLeave()) || blenderExportPending ||
      gen !== generation || project !== viewportProject) return null;
  const weapons = objects.flatMap((object,index) => object.loaded!==false && object.kind === 'weapon' && object.root.visible
    ? [{game_rel:meshMeta[index].game_rel,hand:object.hand || 'auto'}] : []);
  return {target,weapons,gen,project};
}
async function sendToBlenderLive() {
  if (blenderExportPending) return;
  const selection = await blenderSelection();
  if (!selection || blenderExportPending) return;
  const {target,weapons,gen,project}=selection;
  const current=()=>gen===generation && project===viewportProject;
  blenderExportPending=true;refreshBlenderBtn();
  note('Sending model to the running Blender session…','info');
  try {
    const result=await window.AtelierJobs.run('/api/model_blender_send',{
      method:'POST',project,headers:{'Content-Type':'application/json'},
      body:JSON.stringify({game_rel:target.game_rel,weapons})
    });
    if(!result.ok)throw Error(result.error || 'Blender live import failed');
    if(!current())return;
    note('Sent '+result.meshes+' mesh(es) into Blender. Save the Blender project to keep the edits.'+
      (result.warnings?.length ? ' '+result.warnings.length+' warning(s); see Activity.' : ''),
      result.warnings?.length?'warning':'success');
  } catch(error) {if(current())note(error.message,'warning');}
  finally {blenderExportPending=false;refreshBlenderBtn();}
}
async function editInBlender() {
  if (blenderExportPending) return;
  const selection=await blenderSelection();
  if(!selection || blenderExportPending)return;
  const {target,weapons,gen,project}=selection;
  const current=()=>gen===generation && project===viewportProject;
  blenderExportPending=true;refreshBlenderBtn();
  note('Preparing model, materials and textures for a portable Blender scene…','info');
  async function openSaved() {
    const response=await projectFetch('/api/model_blender_open',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({game_rel:target.game_rel})
    },project);
    const payload=await response.json();
    if(!response.ok || !payload.ok)throw Error(payload.error || 'Blender could not be opened');
  }
  try {
    const result=await window.AtelierJobs.run('/api/model_blender_export',{
      method:'POST',project,headers:{'Content-Type':'application/json'},
      body:JSON.stringify({game_rel:target.game_rel,weapons})
    });
    if(!result.ok)throw Error(result.error||'Export failed; existing edits remain intact');
    let launchError=null;
    try {await openSaved();}catch(error){launchError=error;}
    if(!current())return;
    note(launchError ? 'Scene saved, but Blender did not open: '+launchError.message :
      `Blender launched · ${result.meshes} meshes · ${result.materials} materials · ${result.textures} packed textures`,
      launchError||result.warnings?.length?'warning':'success');
    const label=document.createElement('span');label.textContent=' Saved at: '+result.blend;
    const button=document.createElement('button');button.type='button';
    button.textContent='Open in Blender';
    button.addEventListener('click',async()=>{
      try {await openSaved();}catch(error){if(current())note(error.message,'warning');}
    });
    $('viewport-status').append(label,' ',button);
    if(result.material_issues?.length){
      const details=document.createElement('details');
      const heading=document.createElement('summary');
      heading.textContent='Unresolved material/texture inputs';
      const body=document.createElement('pre');
      body.textContent=result.material_issues.join('\n');
      details.append(heading,body);$('viewport-status').append(details);
    }
  }catch(error){if(current())note(error.message,'warning');}
  finally{blenderExportPending=false;refreshBlenderBtn();}
}

// Sidebar shows the Objects panel and/or Materials panel independently, and hides itself entirely
// (full canvas width) only when there's nothing to show in either.
function updateSidebarVisibility() {
  const hasObjects = objects.length > 0;
  const hasMats    = Object.keys(matData).length > 0;
  $('viewport-obj-section').style.display = hasObjects ? 'block' : 'none';
  $('viewport-model-menu').querySelector('summary').setAttribute('aria-disabled', String(!hasObjects));
  $('viewport-material-search').disabled = !hasMats;
  inspection?.refresh();
}

function showAllObjects() {
  return changeObjects(objects,()=>{
    for (const object of objects) { object.root.visible = !!object.loaded; if (object.kind==='weapon') object.enabled=true; }
    soloSnapshot = soloTarget = null;
  });
}

// Keep alternate forms and unused attachments in the picker without decoding them.
// Their empty roots give every object a stable identity until it is selected.
async function loadObject(object, gen=generation) {
  if(object.loaded)return true;
  if(object.loading)return object.loading;
  const meta=meshMeta[objects.indexOf(object)];
  if(!meta)return false;
  object.loading=(async()=>{
    try {
      const gltf=await loader.loadAsync(`/api/model_gltf?game_rel=${encodeURIComponent(meta.game_rel)}`);
      if(gen!==generation){disposeTree(gltf.scene);return false;}
      collectMats(gltf.scene,meta,gltf.parser);
      gltf.scene.visible=object.root.visible;
      modelRoot.remove(object.root);
      object.root=gltf.scene;object.animations=gltf.animations;object.rig=attachmentRig(gltf);
      object.loaded=true;object.loadError=null;modelRoot.add(object.root);
      return true;
    } catch(error) {
      if(gen!==generation)return false;
      object.loadError=await loadErrorText(error);
      console.warn('viewport: mesh load failed',object.name,object.loadError);
      return false;
    } finally {object.loading=null;}
  })();
  return object.loading;
}

function weaponMatchesBody(weapon, body) {
  const weaponPath=meshMeta[objects.indexOf(weapon)]?.game_rel || '';
  const form=/\/Weapons\/(\d{4,5})\//i.exec(weaponPath)?.[1];
  if(!form)return true;
  const bodyPath=meshMeta[objects.indexOf(body)]?.game_rel || '';
  const bodyForm=/\/Meshes\/(\d{4,5})\//i.exec(bodyPath)?.[1] || /\/SK_(\d{4,5})_/i.exec(bodyPath)?.[1];
  return bodyForm===form;
}

async function loadAutomaticWeapons(gen=generation) {
  syncAttachments();
  const held=objects.filter(object=>object.kind==='weapon').sort((a,b)=>Number(b.enabled===true)-Number(a.enabled===true));
  for(const weapon of held) {
    if(gen!==generation)return;
    if(weapon.enabled===false || weapon.autoEquip===false && weapon.enabled!==true)continue;
    if(weapon.enabled!==true && !objects.some(body=>body.kind!=='weapon' && body.root.visible && weaponMatchesBody(weapon,body)))continue;
    const side=weaponSide(weapon.name,weapon.hand || 'auto');
    if(weapon.enabled!==true && held.some(other=>other.root.visible && other.binding?.side===side))continue;
    await loadObject(weapon,gen);
    if(gen!==generation)return;
    syncAttachments();
  }
}

async function changeObjects(targets, apply, {automatic=false, attachments=true}={}) {
  if(modelLoading || saving || visibilityBusy.size || inspection?.capturing()){buildObjectPanel();return;}
  const gen=generation;
  const pending=targets.filter(object=>!object.loaded);
  const before=new Set(Object.keys(matsByName));
  modelLoading=true;inspection?.setLoading(true);refreshBlenderBtn();
  if(pending.length) {
    note(`Loading ${pending.length===1?pending[0].name:'selected mesh parts'}…`,'info');
  }
  buildObjectPanel();
  try {
    // Finish the current batch before adding materials. Existing recolour drafts,
    // dye maps and texture requests stay valid while another part is decoded.
    if(materialTask)await materialTask;
    if(gen!==generation)return;
    for(const object of pending) {
      await loadObject(object,gen);
      if(gen!==generation)return;
    }
    if(targets.length && !targets.some(object=>object.loaded)) {
      note('The selected mesh could not load. Select it again to retry.','warning');return;
    }
    apply();
    if(automatic)await loadAutomaticWeapons(gen);
    if(gen!==generation)return;
    if(attachments)syncAttachments();
    inspection?.clearMaterials();
    buildObjectPanel();buildPanel();frameCamera();syncPreviewAnimation();
    const names=Object.keys(matsByName).filter(name=>!before.has(name));
    if(names.length)await loadMaterials(currentSkin || meshSkin,{names,meshes:meshSlots.filter(mesh=>mesh.slots.some(slot=>names.includes(slot.key)))});
  } catch(error) {
    if(gen===generation)note('The selected part could not load: '+error.message,'warning');
  } finally {
    if(gen===generation){modelLoading=false;inspection?.setLoading(!!materialTask);refreshBlenderBtn();buildObjectPanel();}
  }
}

function syncPreviewAnimation() {
  animation.reset();
  for (const object of objects) if (object.root.visible && object.kind !== 'weapon') animation.register({scene:object.root, animations:object.animations || []});
  const index = objects.findIndex(object=>object.root.visible && object.kind !== 'weapon');
  if (index >= 0) animation.discover(meshMeta[index].game_rel);
}

function syncAttachments() {
  const held=objects.filter(object=>object.kind==='weapon' && object.loaded);
  for(const materials of Object.values(matsByName))for(const material of materials)material.userData.heldDuplicate=false;
  const bodies=objects.filter(object=>object.kind!=='weapon' && object.loaded && object.root.visible);
  const occupied=new Set();
  for (const weapon of held.sort((a,b)=>Number(b.enabled===true)-Number(a.enabled===true))) {
    const choices=bodies.filter(body=>weapon.enabled===true || weaponMatchesBody(weapon,body))
      .map(body=>bindWeapon(weapon,body,weapon.hand==='both'?'right':weapon.hand || 'auto')).filter(Boolean)
      .sort((a,b)=>(b.joints?.length || 0)-(a.joints?.length || 0));
    weapon.binding=choices[0] || null;
    const side=weapon.binding?.side || 'r',automatic=weapon.autoEquip!==false && !occupied.has(side);
    weapon.root.visible=!!weapon.binding && (weapon.enabled ?? automatic);
    if(weapon.root.visible)occupied.add(side);
    if (weapon.root.visible) updateWeapon(weapon,weapon.binding);
    if(weapon.hand==='both' && weapon.binding) {
      if(!weapon.paired){weapon.paired=pairedWeapon(weapon);modelRoot.add(weapon.paired.root);}
      weapon.paired.binding=bindWeapon(weapon.paired,weapon.binding.body,'left');
      weapon.paired.root.visible=weapon.root.visible && !!weapon.paired.binding;
      if(weapon.paired.root.visible){updateWeapon(weapon.paired,weapon.paired.binding);occupied.add('l');}
    } else if(weapon.paired)weapon.paired.root.visible=false;
  }
  for(const body of objects.filter(object=>object.kind!=='weapon' && object.loaded)){
    for(const material of embeddedWeaponMaterials(body,held.filter(weapon=>weapon.root.visible)))material.userData.heldDuplicate=true;
  }
}

// One row per top-level mesh loaded into modelRoot. Toggling hides/shows that mesh and re-frames
// the camera — some skins carry extra objects (unused attachments, effects meshes, etc.) that are
// wildly oversized or offset, which blows up the auto-framed scale and makes orbit/pan feel broken.
function buildObjectPanel() {
  const list = $('viewport-obj-list');
  list.innerHTML = '';
  for (const o of objects) {
    const row = document.createElement('div');
    row.className = 'vp-obj' + (o.root.visible ? '' : ' hidden-obj');
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = o.root.visible;
    cb.disabled = modelLoading;
    cb.addEventListener('change', () => {
      const checked=cb.checked;
      changeObjects(checked?[o]:[],()=>{
        soloSnapshot = soloTarget = null;
        o.root.visible = checked;
        if (o.kind==='weapon') o.enabled=checked;
      });
    });
    const lbl = document.createElement('span');
    lbl.textContent = (o.kind==='weapon' ? 'Weapon · ' : '') + (o.name || 'Object');
    lbl.title = o.name || '';
    const label = document.createElement('label'); label.append(cb, lbl); row.appendChild(label);
    if (o.kind==='weapon') {
      const hand=document.createElement('select');hand.className='vp-weapon-hand';hand.setAttribute('aria-label','Attach '+o.name);
      hand.replaceChildren(...[['auto','Match weapon rig'],['right','Right hand'],['left','Left hand'],['both','Both hands']].map(([value,label])=>new Option(label,value)));
      hand.disabled=modelLoading;
      hand.value=o.hand || 'auto';hand.addEventListener('change',()=>{const value=hand.value;changeObjects([o],()=>{o.hand=value;o.enabled=true;});});
      row.append(hand);
      if (!o.loaded) cb.title='Loads when selected.';
      else if (!o.binding) cb.title='No compatible hand socket was found on the visible body.';
    }
    const solo = document.createElement('button'); solo.className = 'vp-solo'; solo.textContent = 'Solo';
    solo.setAttribute('aria-label', `Isolate ${o.name || 'object'}`);
    solo.setAttribute('aria-pressed', String(soloTarget === o));
    solo.disabled = modelLoading || objects.length < 2;
    solo.addEventListener('click', () => {
      changeObjects([o],()=>{
      if (soloTarget === o) {
        for (const object of objects) object.root.visible = soloSnapshot.get(object) ?? true;
        soloSnapshot = soloTarget = null;
      } else {
        if (!soloSnapshot) soloSnapshot = new Map(objects.map(object => [object,object.root.visible]));
        soloTarget = o; for (const object of objects) object.root.visible = object === o;
      }
      },{attachments:false});
    });
    row.appendChild(solo);
    list.appendChild(row);
  }
  $('viewport-obj-count').textContent = objects.length + (objects.length === 1 ? ' object' : ' objects');
  const bodies=objects.flatMap((object,index)=>object.kind==='weapon'?[]:[index]);
  const visible = bodies.filter(index=>objects[index].root.visible);
  if (!visible.length && !modelLoading) $('viewport-model-menu').open=false;
  const select = $('viewport-model-choice');
  select.disabled=modelLoading;
  $('viewport-chroma').disabled=modelLoading;
  select.replaceChildren(...objects.flatMap((object,index) => object.kind==='weapon' ? [] : [new Option(`Mesh ${index + 1} · ${object.name}`, String(index))]),
    new Option('All mesh parts', 'all'), new Option('Custom visibility', 'custom'));
  select.querySelector('[value="custom"]').hidden = true;
  select.value = visible.length === 1 ? String(visible[0]) : visible.length === bodies.length ? 'all' : 'custom';
  $('viewport-model-label').textContent = bodies.length > 1
    ? visible.length === 1 ? `Model ${bodies.indexOf(visible[0]) + 1} of ${bodies.length}` : `${visible.length} body forms` : 'Model';
  $('viewport-model-hint').textContent = objects.length > 1
    ? 'Choose a body form. Compatible weapons follow its rig; use the controls below for other parts.' : 'This preview contains one mesh.';
  updateSidebarVisibility();
}

// Make a mesh material matte (glTF's default is fully metallic → renders black w/o env map) and
// register it under its MI slot name so we can tint it from material params later.
function prepMaterial(m, meta, parser) {
  if (!m || !m.isMeshStandardMaterial) return;
  // Lobby meshes include a separate Unreal rim shell. Rendering it as an opaque
  // standard material hides the textured character underneath.
  if (/(?:^|_)rim(?:light)?(?:_|$)/i.test(m.name || '')) { m.visible=false; return; }
  m.metalness = 0.0;
  m.roughness = 0.85;
  m.color.setHex(0xb8b8c0);
  // MR meshes carry COLOR_0 vertex colors that are mostly (0,0,0) mask/data channels — NOT display
  // colors. GLTFLoader auto-enables vertexColors, so the shader multiplies texture × tint × black =
  // pure black. Ignore them so the albedo map and tint actually show.
  m.vertexColors = false;
  m.needsUpdate = true;
  const index=parser?.associations?.get(m)?.materials;
  const sourceName=parser?.json?.materials?.[index]?.name || m.name || '';
  m.userData.slotName=sourceName;
  const nm=meta?.game_rel && Number.isInteger(index) ? `${meta.game_rel}::${index}` : sourceName;
  m.name=nm;
  if (meta?.game_rel && Number.isInteger(index)) {
    let binding=meshSlots.find(item=>item.game_rel===meta.game_rel);
    if (!binding) {binding={game_rel:meta.game_rel,slots:[]};meshSlots.push(binding);}
    if (!binding.slots.some(slot=>slot.key===nm)) binding.slots.push({key:nm,name:sourceName,material_index:index});
  }
  if (nm) (matsByName[nm] || (matsByName[nm] = [])).push(m);
}

function collectMats(root, meta, parser) {
  root.traverse(o => {
    if (!o.isMesh) return;
    o.frustumCulled = false;
    for (const m of (Array.isArray(o.material) ? o.material : [o.material])) {
      if (!Object.values(matsByName).some(ms=>ms.includes(m))) prepMaterial(m,meta,parser);
    }
  });
}

// Set each part's color: the base/tint param if there is one (multiplies over the map), else white
// when a texture map is present, else the matte grey placeholder.
function retint(name) {
  const d = matData[name]; if (!d) return;
  const chip = [...document.querySelectorAll('.vp-mat')].find(row=>row.dataset.material===name)?.querySelector('.vp-material-chip');
  if (chip) chip.style.background=materialChipColor(name,d);
  const baseRgb = d.eye_preview ? null : paramRgb(name, d.baseIdx);
  const emiRgb  = paramRgb(name, d.emiIdx);
  for (const m of (matsByName[name] || [])) {
    // albedo tint (base colour param, else white over the map / grey placeholder)
    if (baseRgb) m.color.setRGB(baseRgb[0], baseRgb[1], baseRgb[2], THREE.LinearSRGBColorSpace);
    else m.color.setHex(m.map ? 0xffffff : 0xb8b8c0);
    applyEmissive(m, d, emiRgb);
  }
}

async function applyMatTexture(name, texGameRel, slot = 'map', ver = '0', url = null) {
  // Textures are big (2048²) and expensive to upload — load each once, cache, and reuse across opens.
  // Both the model and material-set generation must still match before applying a texture.
  // The cache key + URL include `ver` (edited-PNG mtime): unedited textures stay cached across opens,
  // but once the user edits one its stamp changes → we refetch and show the edit.
  ver = ver || '0';
  const gen = generation, matGen = materialGeneration;
  const key = viewportProject + ':' + (slot==='alphaMap'?'data:':'color:') + (url || texGameRel) + '@' + ver;
  let tex = texCache.get(key);
  if (!tex) {
    const pendingKey=gen+':'+matGen+':'+key;
    let pending=texPending.get(pendingKey);
    if(!pending) {
      const load=materialLoad;
      pending=(async()=>{
        const decoded=await materialTexture(url || `/api/texture_png?game_rel=${encodeURIComponent(texGameRel)}&v=${encodeURIComponent(ver)}`,load);
        if(gen!==generation || matGen!==materialGeneration){decoded.dispose();return null;}
        decoded.colorSpace = slot === 'alphaMap' ? THREE.NoColorSpace : THREE.SRGBColorSpace;
        decoded.flipY = false;
        decoded.wrapS = decoded.wrapT = THREE.RepeatWrapping;
        if(renderer)decoded.anisotropy=renderer.capabilities.getMaxAnisotropy();
        texCache.set(key,decoded);
        return decoded;
      })().finally(()=>texPending.delete(pendingKey));
      texPending.set(pendingKey,pending);
    }
    try {
      tex = await pending;
    } catch (e) { if (e.name !== 'AbortError') console.warn('viewport: texture load failed', name, slot, texGameRel, e); return false; }
    if(!tex)return;
  }
  if (gen !== generation || matGen !== materialGeneration) { trimTextureCache(); return; }
  const mats = matsByName[name] || [];
  if (!mats.length) return;   // the current model has no slot of this name (user switched meshes)
  const live = slot === 'map' ? liveDyeTextures.get(name) : null;
  for (const m of mats) { m[slot] = live || tex; m.needsUpdate = true; }
  if (slot === 'map') baselineMaps.set(name, tex);
  retint(name);   // re-derive colour/emissive now that the map exists
  trimTextureCache();
  return true;
}

function frameCamera() {
  inspection?.frame();
}

function tintOriginal(material, data) {
  const base = data.eye_preview ? null : data.colors?.[pickBaseIdx(data.colors)];
  if (base) material.color.setRGB(...base.rgba.slice(0,3).map(v=>Math.max(0,v)), THREE.LinearSRGBColorSpace);
  else material.color.setHex(material.map ? 0xffffff : 0xb8b8c0);
  applyEmissive(material, data);
}

function pickMaterial(name, openEditor = true, surface = null, textureSlot = null) {
  if (surface) assembly?.surfacePicked(surface);
  if (!matData[name]) {
    selectedMaterial=assembly?.active() && matsByName[name] ? name : null;
    buildPanel();note('This part has no editable material parameters.', 'warning');return;
  }
  selectedMaterial = name;
  $('viewport-material-search').value = '';
  buildPanel();
  const row = [...document.querySelectorAll('#viewport-mat-list .vp-mat')].find(row => row.dataset.material === name);
  row?.scrollIntoView({block:'nearest', inline:'nearest'});
  if (!openEditor) return;
  const info = matData[name];
  if (!info?.game_rel) { note('Material parameters are unavailable for this section.', 'warning'); return; }
  if (assembly?.active() && !verifiedBinding(info)) { note('This material assignment is unverified. Inspect mode retains the preview controls.', 'warning'); return; }
  if (hasPendingEdits()) { note('Save or revert your studio changes before opening the full editor.', 'warning'); $('viewport-mat-save').focus(); return; }
  if (typeof window.openMaterialEditor !== 'function') { $('viewport-material-editor').querySelector('input')?.focus(); return; }
  openConnectedEditor('material-overlay',()=>window.AtelierAssetEditors?.material({name:info.game_rel.split('/').pop(),game_rel:info.game_rel},textureSlot)
    || window.openMaterialEditor({name,game_rel:info.game_rel}));
}

// Keep one scene alive while the established editor owns its ordinary modal.
// Returning refreshes material metadata while retaining camera, part and rig pose.
async function openConnectedEditor(overlayId, openEditor, refresh = true) {
  if (connectedEditorPending) return;
  if (modelLoading) {note('Wait for the model to finish loading before opening an editor.','info');return;}
  if (inspection?.capturing()) {note('Wait for the capture to finish before opening an editor.','info');return;}
  if (hasPendingEdits()) { note('Save or revert your studio changes before opening another editor.','warning');focusPendingEdits();return; }
  const gen = generation, project = viewportProject;
  connectedEditorPending = true;
  const playing = animation.pause();
  // Discard residual orbit inertia at the exact pose handed to the editor.
  // Otherwise the first resumed frames continue a drag made before the handoff.
  const position = camera.position.clone(), target = controls.target.clone(), damping = controls.enableDamping;
  controls.enableDamping = false; controls.update();
  camera.position.copy(position); controls.target.copy(target); controls.update();
  controls.enableDamping = damping;
  inspection.preserveFraming(); cancelMaterialLoad();
  $('viewport-overlay').classList.remove('active');
  if (raf) { cancelAnimationFrame(raf); raf = 0; }
  let returned = false, opened = false;
  materialReturnObserver?.disconnect();
  const resume = async () => {
    const overlay = $(overlayId);
    if (returned || overlay?.classList.contains('active') || !opened) return;
    returned = true; connectedEditorPending = false;
    materialReturnObserver?.disconnect(); materialReturnObserver = null;
    if (gen !== generation || project !== (window.atelierProject?.() || '')) return;
    $('viewport-overlay').classList.add('active'); requestAnimationFrame(onResize);
    if (!raf) animate();
    try {
      if (typeof refresh === 'function') await refresh();
      else if (refresh) {assembly?.invalidateReferences();await loadMaterials(chromaSkin || meshSkin);}
    } catch(error) {if(gen===generation)note(error.message || 'The preview could not refresh.','warning');}
    finally {
      if (gen === generation) {animation.resume(playing);inspection.selectSurface(assembly?.selectedSurface());assembly?.sync();$('viewport-canvas').focus();}
    }
  };
  materialReturnObserver = new MutationObserver(resume);
  materialReturnObserver.observe(document.body, {subtree:true,attributes:true,attributeFilter:['class']});
  try { await openEditor(); }
  catch (error) { note(error.message || 'The editor could not be opened.','warning'); }
  finally { opened = true; resume(); }
}

function editAssemblyMesh(gameRel) {
  const changed = new Set();
  return openConnectedEditor('mesh-edit-overlay',()=>window.AtelierMeshEdit?.add(
    {game_rel:gameRel,name:gameRel.split('/').pop()}, {preserveViewport:true,onChanged:path=>changed.add(path)}),
    ()=>changed.size ? refreshAssemblyMeshes(changed) : undefined);
}

async function refreshAssemblyMeshes(changed) {
  const gen = generation, selection = matData[selectedMaterial];
  const replacements = [];
  modelLoading = true;inspection.setLoading(true);refreshBlenderBtn();
  preserveAnimationCamera = true;
  try {
    // Decode first so a failed replacement leaves the current scene inspectable.
    for (const [index, object] of objects.entries()) if (object.loaded && changed.has(meshMeta[index]?.game_rel)) {
      const gltf = await loader.loadAsync('/api/model_gltf?game_rel='+encodeURIComponent(meshMeta[index].game_rel));
      if(gen!==generation){disposeTree(gltf.scene);return;}
      replacements.push({object,meta:meshMeta[index],gltf});
    }
    if(!replacements.length)return;
    animation.reset();inspection.clearMaterials();clearLiveDyes();
    for(const {object,meta,gltf} of replacements) {
      const old=object.root, materials=new Set();
      old.traverse(mesh=>{if(mesh.isMesh)for(const material of Array.isArray(mesh.material)?mesh.material:[mesh.material])materials.add(material);});
      for(const [key,list] of Object.entries(matsByName)) {
        matsByName[key]=list.filter(material=>!materials.has(material));
        if(!matsByName[key].length){delete matsByName[key];delete matData[key];baselineMaps.delete(key);}
      }
      meshSlots=meshSlots.filter(record=>record.game_rel!==meta.game_rel);
      collectMats(gltf.scene,meta,gltf.parser);
      gltf.scene.visible=old.visible;modelRoot.remove(old);
      if(object.paired){modelRoot.remove(object.paired.root);disposeTree(object.paired.root);object.paired=null;}
      object.root=gltf.scene;object.animations=gltf.animations;object.rig=attachmentRig(gltf);object.binding=null;
      modelRoot.add(gltf.scene);disposeTree(old);
      replacements.find(record=>record.gltf===gltf).installed=true;
    }
    replacements.length=0;
    for(const object of objects) if(object.loaded)animation.register({scene:object.root,animations:object.animations});
    syncAttachments();assembly?.invalidateReferences();await loadMaterials(chromaSkin || meshSkin);
    if(gen!==generation)return;
    if(selection && Number.isInteger(selection.slot_index)) {
      const match=Object.keys(matData).find(key=>matData[key].mesh_game_rel===selection.mesh_game_rel && matData[key].slot_index===selection.slot_index);
      selectedMaterial=match || null;
    }
    const body=objects.findIndex(object=>object.root.visible && object.kind!=='weapon');
    if(body>=0)await animation.discover(meshMeta[body].game_rel);
    if(gen===generation){buildObjectPanel();buildPanel();note('Replacement loaded · camera preserved','success');}
  } finally {
    for(const {gltf,installed} of replacements)if(!installed)disposeTree(gltf.scene);
    preserveAnimationCamera=false;
    if(gen===generation){modelLoading=false;inspection.setLoading(!!materialTask);refreshBlenderBtn();buildObjectPanel();assembly?.sync();}
  }
}

async function editAssemblyTexture(source) {
  if (hasPendingEdits()) { focusPendingEdits();return; }
  const gen = generation, project = viewportProject;
  await window.AtelierAssetEditors?.texture(source.game_rel);
  if (gen === generation && project === viewportProject) assembly?.sync();
}

function replaceAssemblyTexture(source) {
  if (hasPendingEdits()) { focusPendingEdits();return; }
  window.AtelierAssetEditors?.replaceTexture(source.game_rel);
}

window.addEventListener('atelier:asset-updated', event => {
  if (!assembly?.active() || !inited || event.detail?.project !== viewportProject || connectedEditorPending) return;
  const path = event.detail.game_rel;
  if (!Object.values(matData).some(info=>Object.values(info.textures || {}).some(texture=>texture.toLowerCase() === path?.toLowerCase()))) return;
  clearTimeout(assemblyRefreshTimer);
  assemblyRefreshTimer = setTimeout(()=>{
    if (!$('viewport-overlay').classList.contains('active')) return;
    if (hasPendingEdits()) {note('A connected texture changed. Save or revert studio colours before refreshing.','info');return;}
    loadMaterials(chromaSkin || meshSkin);
  },300);
});

// ── materials: fetch params, tint mesh parts, build the recolor panel ─────────
// Runs fully in the background: the mesh is already up and orbitable (viewport-loading is long
// gone by the time this is called), so we surface progress with a toast spinner — same as every
// other long-running job in the app — instead of the blocking mesh-load overlay. The sidebar
// (#viewport-materials) appears as soon as params are back; textures fill in live on whatever
// model is current, no reopen needed — this just keeps the user informed while that happens.
// ── "materials from" picker ───────────────────────────────────────────────────
// A chroma/recolour has no mesh of its own — and there's NO reliable way to spot one: some ship a
// full mesh set, some are textures-only, some materials-only, and sibling IDs under a character
// aren't necessarily variants of each other. So don't classify: list what exists under the character
// and let the user point at the material set they want, applied to whatever mesh is loaded.
let chromaSkin = null;      // the skin whose materials are currently applied (null = the mesh's own)
let meshSkin   = null;      // the skin the loaded mesh came from

async function buildChromaPicker(skinId, meshGameRel) {
  const gen = generation;
  const row = $('viewport-chroma-row'), sel = $('viewport-chroma');
  if (!row || !sel) return;
  // Walk up from the LOADED MESH's real path to the folder holding the skin folders, rather than
  // deriving it from the id — the folder schema isn't reliably a skin id (e.g. 1060CommonMaterial).
  const parts = String(meshGameRel || '').split('/');    // Characters/<char>/<skin>/.../SK_x
  if (parts.length < 3) { row.style.display = 'none'; return; }
  const parent = parts.slice(0, 2).join('/');            // Characters/<char>
  let list = [];
  try {
    const d = await projectFetch(`/api/browse_material_dirs?path=${encodeURIComponent(parent)}`).then(r => r.json());
    if (gen !== generation) return;
    list = (d && d.dirs) || [];
  } catch (e) { if (gen === generation) row.style.display = 'none'; return; }
  list = list.filter(s => s.materials > 0);
  if (list.length < 2) { row.style.display = 'none'; return; }
  sel.replaceChildren(...list.map(s => {
    const label = s.label ? `${s.label} (${s.name})` : s.name;   // "COASTAL KUMIHO (1060501)"
    const option = document.createElement('option'); option.value = s.name;
    option.selected = s.name === (chromaSkin || skinId);
    option.textContent = label + `${s.name === skinId ? ' — this skin' : ''} · ${s.materials} mat`
      + `${s.meshes ? `, ${s.meshes} mesh` : ', no mesh'}`;
    return option;
  }));
  sel.onchange = async () => {
    if (!(await canLeave())) { sel.value = chromaSkin || skinId; return; }
    chromaSkin = sel.value;
    $('viewport-status').textContent = `Materials: ${sel.selectedOptions[0]?.textContent || chromaSkin}`;
    loadMaterials(chromaSkin);
  };
  row.style.display = '';
}

// Chroma MI names carry their OWN skin id: the base mesh's slot is MI_10600_1060300_Equip_01 but
// the chroma ships MI_10600_1060301_Equip_01 — same material, different digits. So slot matching
// ignores the six/seven-digit skin identifier, preserving the five-digit rig identifier.
// Transformed forms such as 10290 and 10291 have separate slots and must never share a key.
const _canonName = n => String(n || '').toLowerCase().replace(/\d{6,}/g, '#');

function loadMaterials(skinId, additions=null) {
  if(!additions) {
    cancelMaterialLoad();
    for (const timer of Object.values(_dyeMeshTimer)) clearTimeout(timer);
  }
  const load = additions && materialLoad && !materialLoad.controller.signal.aborted ? materialLoad
    : {id:crypto.randomUUID(), controller:new AbortController(), project:viewportProject, spinner:null};
  materialLoad = load;
  inspection?.setLoading(true);
  const task = loadMaterialSet(skinId, load, additions).finally(() => load.spinner?.remove()); materialTask = task; inspection?.refresh();
  const settled = result => { if (materialTask === task) { materialTask = null; inspection?.setLoading(modelLoading); if(result!==false)inspection?.materialize(); inspection?.refresh(); } };
  task.then(settled,()=>settled(false)); return task;
}

async function loadMaterialSet(skinId, load, additions=null) {
  if (!skinId && !meshSlots.length) return;
  currentSkin = skinId;
  window.AtelierViewportIdentity?.show(skinId,heroId);
  const gen = generation;
  const matGen = additions ? materialGeneration : ++materialGeneration;
  if(!additions) {
    inspection?.clearMaterials();
    clearLiveDyes(); baselineMaps.clear();
    matData = {}; edited = {};
  }
  const pendingSelection = selectedMaterial;
  buildPanel();
  const slots = additions?.names || Object.keys(matsByName);
  const bindings = additions?.meshes || meshSlots;
  const foreign = !!(meshSkin && skinId !== meshSkin);   // applying another skin's materials
  const spinner = document.createElement('span'); spinner.className = 'vp-load-status';
  spinner.innerHTML = '<span>Loading materials…</span>';
  $('viewport-status').replaceChildren(spinner);
  $('viewport-status').dataset.kind = 'info';
  load.spinner = spinner;
  const spinnerMsg = spinner ? spinner.querySelector('span') : null;

  let res;
  try {
    const readSet = names => materialFetch('/api/skin_materials', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      // a foreign skin's MI names won't equal the slot names, so the server-side name filter would
      // drop everything — fetch all of them and match canonically here instead
      body: JSON.stringify({ skin_id: skinId, names, ...(bindings.length ? {meshes:bindings} : {}) }),
    }, load).then(r => r.json());
    res = await readSet(foreign ? [] : slots);
    // Recolour meshes can retain the base skin's MI slot names. Let the canonical matching
    // below pair the selected skin's materials when the exact-name filter finds none.
    if (!foreign && slots.length && res?.ok && res.materials && Object.keys(res.materials).length < slots.length) {
      res = await readSet([]);
    }
  } catch (e) {
    if (e.name !== 'AbortError') console.warn('viewport: skin_materials request failed', e);
    if (spinner) spinner.remove();
    if (e.name !== 'AbortError' && gen === generation && matGen === materialGeneration) note('Materials could not be loaded. Reopen the preview to retry.', 'warning');
    return false;
  }
  if (gen !== generation || matGen !== materialGeneration) { if (spinner) spinner.remove(); return; }
  if (!res || !res.ok || !res.materials) {
    console.warn('viewport: skin_materials bad response', res);
    if (spinner) spinner.remove();
    note('Materials could not be loaded. Reopen the preview to retry.', 'warning');
    return false;
  }

  // Keep only materials that appear as slots on the loaded mesh; wire each part. `matName` is the
  // material's own name, `name` is the MESH SLOT it drives — identical for the skin's own materials,
  // but for a foreign chroma they differ by embedded skin id (resolved canonically).
  const slotCanon = {};                                  // canonical slot name -> real slot name
  for (const s of Object.keys(matsByName)) slotCanon[_canonName(s)] = s;
  const resolveSlot = mn => (matsByName[mn] ? mn : slotCanon[_canonName(mn)] || null);
  let matched = 0;
  const texJobs = [];
  for (const [matName, info] of Object.entries(res.materials)) {
    const name = resolveSlot(matName);
    if (!name || !slots.includes(name)) continue;
    matched++;
    info.baseIdx = info.eye_preview ? -1 : pickBaseIdx(info.colors);
    info.emiIdx  = pickEmissiveIdx(info.colors);
    matData[name] = info;
    // Unknown cooked slots keep their decoded appearance and remain read-only.
    if(!info.game_rel)continue;
    for (const material of matsByName[name] || []) {
      material.visible=!info.hidden;applySurface(material,info);
      material.map=null;material.emissiveMap=null;material.alphaMap=null;
    }
    retint(name);
    const tex = info.textures || {};
    const roles=textureRoles(info);
    const ver = info.tex_ver || {};
    const urls = info.texture_urls || {};
    // Dyeing materials (CHROMAS): the skin's colour lives in the MI's "Region N" params applied
    // through the ColorID mask, NOT in the diffuse — every chroma of a skin shares one diffuse, so
    // loading BaseColor renders them all identically. Ask for the server-side composite instead.
    if (info.eye_preview) {
      texJobs.push(applyMatTexture(name, tex.ScleraBaseColor, 'map', info.eye_ver,
        `/api/eye_texture?game_rel=${encodeURIComponent(info.game_rel)}&v=${info.eye_ver}`));
    } else if (info.dyeable) {
      texJobs.push(applyMatTexture(name, tex.BaseColor || info.game_rel, 'map', info.dye_ver || '0',
        `/api/dye_texture?game_rel=${encodeURIComponent(info.game_rel)}&v=${encodeURIComponent(info.dye_ver || '0')}`));
    } else if (roles.basecolor) {
      texJobs.push(applyMatTexture(name, roles.basecolor, 'map', ver[roles.basecolor], urls.basecolor));
    }
    if (roles.emissive) texJobs.push(applyMatTexture(name, roles.emissive, 'emissiveMap', ver[roles.emissive], urls.emissive));
    if (roles.opacity) texJobs.push(applyMatTexture(name, roles.opacity, 'alphaMap', ver[roles.opacity], urls.opacity));
  }
  selectedMaterial = pendingSelection;
  buildPanel();   // parameters are ready; textures may still be in flight

  if (!texJobs.length) {
    if (spinner) spinner.remove();
    // Materials are matched to the mesh by NAME (glTF slot == MI name). A chroma authored with
    // different MI names matches nothing — say so instead of failing silently, since the picker
    // makes that a normal thing for the user to hit.
    if (gen === generation && matGen === materialGeneration && !matched) {
      $('viewport-status').textContent = (chromaSkin && chromaSkin !== meshSkin)
        ? `${chromaSkin}: no materials match this mesh's slot names`
        : 'no materials matched';
    } else if (gen === generation && matGen === materialGeneration) {
      $('viewport-status').textContent = 'Materials ready'; $('viewport-status').dataset.kind = 'success';
    }
    return;
  }

  // All texture fetches are already in flight together (fired above, not awaited one at a time) —
  // the spinner just reports on that single batch as it lands, part-by-part, until every texture
  // for this model has been decoded and applied.
  const total = texJobs.length;
  let done = 0;
  const tick = () => { if (spinnerMsg && gen === generation && matGen === materialGeneration) spinnerMsg.textContent = `Loading textures… ${done}/${total}`; };
  tick();
  const results=await Promise.allSettled(texJobs.map(p => p.finally(() => { done++; tick(); })));
  if (spinner) spinner.remove();
  if (gen === generation && matGen === materialGeneration) {
    const failed=results.filter(result=>result.status==='rejected'||result.value===false).length;
    $('viewport-status').textContent = failed ? `${failed} texture${failed===1?'':'s'} could not load. Reopen the preview to retry.` : 'Materials ready';
    $('viewport-status').dataset.kind = failed ? 'warning' : 'success';
    return !failed;
  }
}

function materialChipColor(name, data) {
  const color = data.colors?.[data.baseIdx] || data.colors?.find(c=>!EMISSIVE_RE.test(c.name)) || data.colors?.[0];
  return color ? linToHex(edited[name]?.[color.name] || color.rgba) : '#b8b8c0';
}

function buildPanel() {
  const list = $('viewport-mat-list');
  list.replaceChildren();
  const visible = new Set();
  for (const object of objects) if (object.root.visible) object.root.traverseVisible(mesh => {
    if (mesh.isMesh) for (const material of Array.isArray(mesh.material) ? mesh.material : [mesh.material]) visible.add(material.name);
  });
  const names = Object.keys(matData).filter(name => !objects.length || visible.has(name)).sort((a,b)=>materialGroup(a).localeCompare(materialGroup(b)) || materialLabel(a).localeCompare(materialLabel(b)));
  if (!names.includes(selectedMaterial) && !(assembly?.active() && visible.has(selectedMaterial))) selectedMaterial = null;
  const groups = new Map();
  for (const name of names) {const group=materialGroup(name);if(!groups.has(group))groups.set(group,[]);groups.get(group).push(name);}
  for (const [label,group] of groups) {
    const name = group.includes(selectedMaterial) ? selectedMaterial : group[0];
    const wrap = document.createElement('div'); wrap.className = 'vp-mat'; wrap.dataset.material = name;
    wrap.dataset.search = `${label} ${group.map(materialLabel).join(' ')} ${group.join(' ')}`;
    wrap.classList.toggle('is-picked', name === selectedMaterial);
    const button = document.createElement('button'); button.type = 'button'; button.className = 'vp-material-select';
    button.setAttribute('aria-pressed', String(name === selectedMaterial)); button.setAttribute('aria-controls','viewport-material-editor');
    button.title = name;
    const chip = document.createElement('span'); chip.className = 'vp-material-chip'; chip.setAttribute('aria-hidden','true');
    chip.style.background = materialChipColor(name,matData[name]);
    const text = document.createElement('span'); text.className = 'vp-material-name'; text.textContent = label;
    const marker = document.createElement('span'); marker.className = 'vp-draft-marker'; marker.textContent = 'Edited'; marker.hidden = !group.some(name=>edited[name]);
    wrap.dataset.group = label;
    button.append(chip,text,marker); button.addEventListener('click',()=>{
      const query=$('viewport-material-search').value.trim().toLowerCase();
      pickMaterial(query ? group.find(name=>(name+' '+materialLabel(name)).toLowerCase().includes(query)) || name : name,false);
    });
    wrap.append(button);
    if (group.length===1) wrap.append(sectionEye(name));
    else {
      const sections=document.createElement('div');sections.className='vp-material-sections';
      for (const part of group) {
        const row=document.createElement('div');row.className='vp-section-row';row.dataset.section=part;
        const choose=document.createElement('button');choose.className='vp-section-select';choose.textContent=materialLabel(part);
        choose.addEventListener('click',()=>pickMaterial(part,false));
        row.append(choose,sectionEye(part));sections.append(row);
      }
      wrap.append(sections);
    }
    wrap.classList.toggle('has-hidden-section',group.some(part=>matData[part].hidden));
    list.append(wrap);
  }
  $('viewport-mat-count').textContent = names.length ? String(names.length) : '';
  buildMaterialInspector(names); filterMaterials();
  updateSidebarVisibility();
  refreshFoot();
  window.AtelierIcons?.createIcons({nodes:[list]});
  assembly?.sync();
}

function sectionEye(name) {
  const info=matData[name],button=document.createElement('button');
  button.type='button';button.className='vp-section-eye';button.dataset.section=name;
  const label=materialLabel(name),hidden=!!info.hidden;
  button.setAttribute('aria-label',`${hidden?'Show':'Hide'} ${label}`);
  button.setAttribute('aria-pressed',String(hidden));
  button.disabled=visibilityBusy.has(name) || !Number.isInteger(info.slot_index) || !!info.mapping_error;
  button.title=info.mapping_error || info.visibility_warning || (!Number.isInteger(info.slot_index) ? 'Section export mapping is unavailable for this model.' : hidden ? 'Show this section in the preview and exported mod' : 'Hide this section in the preview and exported mod');
  if(matsByName[name]?.some(material=>material.userData.heldDuplicate))button.title+=' · Its built-in copy is represented by the held weapon in this preview.';
  const icon=document.createElement('i');icon.dataset.lucide=hidden?'eye-off':'eye';button.append(icon);
  button.addEventListener('click',()=>toggleSection(name));
  return button;
}

async function toggleSection(name) {
  const info=matData[name],gen=generation,project=viewportProject;
  if (!info || visibilityBusy.size || saving || modelLoading) return;
  const hidden=!info.hidden;
  if (hidden && !(await window.AtelierDialog.confirm({title:`Hide ${materialLabel(name)}?`,
    body:'This part will be invisible in-game after you export the mod. You can restore it later with the eye button. Other sections using this material stay visible.',
    confirmLabel:'Hide part'}))) return;
  if (gen!==generation || project!==viewportProject) return;
  const setPreview=value=>{
    for(const [key,data] of Object.entries(matData))if(data.mesh_game_rel===info.mesh_game_rel && data.slot_index===info.slot_index){data.hidden=value;for(const material of matsByName[key] || [])material.visible=!value;}
  };
  setPreview(hidden);
  visibilityBusy.add(name);buildPanel();inspection.refresh();
  note(`Saving ${materialLabel(name)} visibility…`,'info');
  try {
    const result=await projectFetch('/api/mesh_visibility',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({game_rel:info.mesh_game_rel,slot_index:info.slot_index,slot_name:info.slot_name,hidden})},project).then(r=>r.json());
    if (!result.ok) throw Error(result.error || 'Could not save section visibility');
    if (gen!==generation || project!==viewportProject) return;
    await window.loadSidebar?.();
    note(`${materialLabel(name)} ${hidden?'hidden':'shown'} · saved for export`,'success');
  } catch(error) { if(gen===generation){setPreview(!hidden);note(error.message,'warning');} }
  finally {visibilityBusy.delete(name);if(gen===generation){buildPanel();inspection.refresh();}}
}

function materialLabel(name) {
  name=matData[name]?.slot_name || matsByName[name]?.[0]?.userData?.slotName || name;
  const words = String(name).replace(/^(?:MI|M|Mat)[_-]/i,'').split(/[_-]+/).filter(word=>word && !/^\d{4,}$/.test(word));
  return (words.join(' ').replace(/([a-z])([A-Z])/g,'$1 $2') || 'Material').replace(/\b\w/g,letter=>letter.toUpperCase());
}

function materialGroup(name) {
  const label = materialLabel(name);
  const mesh = matData[name]?.mesh_game_rel;
  const object = mesh && objects[meshMeta.findIndex(meta=>meta.game_rel===mesh)];
  if (object?.kind === 'weapon') return 'Weapon · '+label;
  if (/^Equip\b/i.test(label)) return 'Equipment';
  if (/^Hair\b/i.test(label)) return 'Hair';
  if (/^(Head|Face|Eyes?|Tooth|Teeth|Mouth)\b/i.test(label)) return 'Face';
  if (/^Weapons?\b/i.test(label)) return 'Weapons';
  return label;
}

function filterMaterials() {
  const search = $('viewport-material-search').value.trim().toLowerCase();
  for (const row of $('viewport-mat-list').querySelectorAll('.vp-mat')) row.hidden = !row.dataset.search.toLowerCase().includes(search);
  let empty = $('viewport-material-no-results');
  if (!empty) { empty = document.createElement('p'); empty.id = 'viewport-material-no-results'; empty.textContent = 'No matching materials'; $('viewport-mat-list').append(empty); }
  empty.hidden = !search || [...$('viewport-mat-list').querySelectorAll('.vp-mat')].some(row=>!row.hidden);
}

function buildMaterialInspector(names = Object.keys(matData)) {
  const editor = $('viewport-material-editor'), info = matData[selectedMaterial];
  const advancedOpen = editor.querySelector('.vp-advanced')?.open && editor.dataset.material === selectedMaterial;
  editor.replaceChildren(); editor.hidden = !info; $('viewport-material-empty').hidden = !!info;
  editor.dataset.material = selectedMaterial || '';
  if (!info) return;
  const name = selectedMaterial;
  const heading = document.createElement('div'); heading.className = 'vp-editor-title';
  const title = document.createElement('h3'); title.textContent = materialGroup(name);
  const dismiss = document.createElement('button'); dismiss.type = 'button'; dismiss.className = 'vp-editor-dismiss';
  dismiss.setAttribute('aria-label','Deselect material'); dismiss.title = 'Deselect material'; dismiss.innerHTML = '<i data-lucide="x" size="17"></i>';
  dismiss.addEventListener('click',()=>{selectedMaterial=null;buildPanel();$('viewport-canvas').focus();});
  heading.append(title,dismiss); editor.append(heading);
  if (info.surface?.preview_omitted) {
    const hint=document.createElement('p');hint.className='vp-inspector-hint';
    hint.textContent=info.surface.preview_omitted==='Animated game effect'
      ? 'This animated effect is omitted from the preview. Its material edits still apply in-game.'
      : 'This effect is disabled by its material settings.';
    editor.append(hint);
  }
  const siblings=names.filter(other=>materialGroup(other)===materialGroup(name));
  if (siblings.length>1) {
    const field=document.createElement('label');field.className='vp-part-picker';field.textContent='Material part';
    const select=document.createElement('select');select.setAttribute('aria-label','Material part');
    select.replaceChildren(...siblings.map(other=>new Option(materialLabel(other),other)));select.value=name;
    select.addEventListener('change',()=>pickMaterial(select.value,false));field.append(select);editor.append(field);
  }
  const colors = info.colors || [];
  const primary = info.baseIdx >= 0 ? info.baseIdx : colors.findIndex(color=>/^Region\s+\d+\s*-\s*ColorA$/i.test(color.name));
  const common = new Set([primary,info.emiIdx].filter(index=>index >= 0));
  if (!common.size) {
    const hint = document.createElement('p'); hint.className = 'vp-inspector-hint';
    hint.textContent = 'This material uses shader-specific colours. Open Advanced parameters to edit them.'; editor.append(hint);
  }
  for (const index of common) {
    const label = index === info.emiIdx ? 'Glow colour' : index === info.baseIdx ? 'Main colour' : colors[index].name.replace(/\s*-\s*ColorA$/i,' colour');
    editor.append(colorField(name,colors[index],label,true));
  }
  const advanced = document.createElement('details'); advanced.className = 'vp-advanced'; advanced.open = !!advancedOpen;
  const summary = document.createElement('summary'); summary.innerHTML = 'Advanced parameters <i data-lucide="chevron-right" size="18"></i>'; advanced.append(summary);
  const hint = document.createElement('p'); hint.textContent = 'Exact shader parameters. Some colours are saved for the game and may not have a faithful live preview.'; advanced.append(hint);
  for (const [index,color] of colors.entries()) if (!common.has(index)) advanced.append(colorField(name,color,color.name,false));
  const source = document.createElement('p'); source.className = 'vp-source-name'; source.textContent = name; source.title = info.game_rel;
  advanced.append(source);
  const full = document.createElement('button'); full.type = 'button'; full.className = 'vp-material-edit'; full.textContent = 'Open full material editor';
  full.addEventListener('click',()=>pickMaterial(name,true)); advanced.append(full);
  if (info.dyeable) {
    const download = document.createElement('button'); download.type = 'button'; download.className = 'vp-mat-dl';
    download.textContent = 'Download dyed texture'; download.addEventListener('click',()=>dyeDownloadMesh(name)); advanced.append(download);
  }
  editor.append(advanced);
  const reset = document.createElement('button'); reset.type = 'button'; reset.className = 'vp-revert-material'; reset.textContent = 'Revert material';
  reset.disabled = saving || !edited[name]; reset.addEventListener('click',()=>revertMaterial(name)); editor.append(reset);
  window.AtelierIcons?.createIcons({nodes:[editor]});
}

function colorField(name, color, label, references) {
  const row = document.createElement('div'); row.className = 'vp-color-field'; row.dataset.material = name; row.dataset.parameter = color.name;
  const caption = document.createElement('label'); caption.className = 'vp-color-label'; caption.textContent = label; caption.title = color.name;
  const controls = document.createElement('div'); controls.className = 'vp-color-controls';
  const picker = document.createElement('input'); picker.type = 'color'; picker.value = linToHex(edited[name]?.[color.name] || color.rgba);
  picker.setAttribute('aria-label',`${name}: ${color.name}`);
  const hex = document.createElement('input'); hex.type = 'text'; hex.className = 'vp-hex'; hex.value = picker.value.toUpperCase(); hex.maxLength = 7;
  hex.setAttribute('aria-label',`Hex colour for ${color.name}`); hex.pattern = '#[0-9a-fA-F]{6}'; hex.spellcheck = false;
  picker.id = `vp-color-${[...$('viewport-material-editor').querySelectorAll('input[type=color]')].length}-${Math.random().toString(36).slice(2,8)}`;
  caption.htmlFor = picker.id;
  picker.addEventListener('input',()=>{hex.value=picker.value.toUpperCase();onColorInput(name,color.name,picker.value);});
  hex.addEventListener('change',()=>{
    const value = hex.value.startsWith('#') ? hex.value : '#'+hex.value;
    if (/^#[0-9a-f]{6}$/i.test(value)) { hex.setCustomValidity('');picker.value=value;onColorInput(name,color.name,value);hex.value=value.toUpperCase(); }
    else {hex.setCustomValidity('Enter a six-digit hex colour, such as #70459B.');hex.reportValidity();}
  });
  hex.addEventListener('input',()=>hex.setCustomValidity(''));
  controls.append(picker,hex); row.append(caption,controls);
  if (references) {
    const comparison = document.createElement('div'); comparison.className = 'vp-color-references';
    for (const saved of [true,false]) {
      const ref = document.createElement('div'); ref.className = 'vp-color-reference';
      const text = document.createElement('span'); text.textContent = saved ? 'Saved' : 'Current';
      const swatch = document.createElement(saved ? 'button' : 'span'); swatch.className = saved ? 'vp-saved-swatch' : 'vp-current-swatch';
      const code = document.createElement('code'); code.className = saved ? 'vp-saved-hex' : 'vp-current-hex';
      if (saved) {
        swatch.type='button';swatch.title=`Restore saved ${color.name}`;swatch.setAttribute('aria-label',swatch.title);
        swatch.style.setProperty('--vp-saved-color',linToHex(color.rgba));code.textContent=linToHex(color.rgba);
        swatch.addEventListener('click',()=>{
          if (saving) return;
          for(const peer of materialPeers(name)) {
            if (edited[peer]) {delete edited[peer][color.name];if(!Object.keys(edited[peer]).length) delete edited[peer];}
            retint(peer);if(matData[peer].dyeable || matData[peer].eye_preview)dyeRebakeMesh(peer);
          }
          picker.value=linToHex(color.rgba);hex.value=picker.value.toUpperCase();refreshFoot();
        });
      }
      ref.append(text,swatch,code);comparison.append(ref);
    }
    row.append(comparison);
  }
  return row;
}

function revertMaterial(name) {
  if (saving || !edited[name]) return;
  for(const peer of materialPeers(name)) {
    clearTimeout(_dyeMeshTimer[peer]); _dyeMeshRevision[peer] = (_dyeMeshRevision[peer] || 0) + 1;
    delete edited[peer]; retint(peer);
    if (matData[peer].dyeable || matData[peer].eye_preview) dyeRebakeMesh(peer);
  }
  buildPanel(); note('Material restored to saved colours','success');
}

function materialPeers(name) {
  const path=matData[name]?.game_rel;
  return path ? Object.keys(matData).filter(key=>matData[key].game_rel===path) : [name];
}

function onColorInput(matName, paramName, hex) {
  const [r, g, b] = hexToLin(hex);
  const d = matData[matName];
  const orig = (d.colors.find(c => c.name === paramName) || {}).rgba || [r, g, b, 1];
  for(const peer of materialPeers(matName)) {
    (edited[peer] ||= {})[paramName] = [r,g,b,orig[3] ?? 1];retint(peer);
    if(matData[peer].eye_preview || matData[peer].dyeable && /^Region\s+\d+\s*-/.test(paramName))dyeRebakeMesh(peer);
  }
  // retint re-derives the mesh from the params, routing each to its real channel: EmissiveColor →
  // the emissive glow (through the emissive mask), a base/albedo tint → material.color. Editing the
  // emissive swatch recolours the glow; other params are saved but don't have a faithful preview.
  retint(matName);
  // Dyeing materials: the colour lives in the ColorID composite, not a flat tint. A "Region N" edit
  // must re-BAKE the albedo (server-side) and swap it onto the mesh — that's the faithful preview.
  refreshFoot();
}

// Live dye: re-bake this material's ColorID composite with the panel's current Region colours and
// swap it onto the mesh. Reuses /api/dye_preview (the same compositor the material editor uses).
const _dyeMeshTimer = {};
const _dyeMeshRevision = {};
function _dyeOverridesFor(matName) {
  const ov = {};
  for (const [pname, rgba] of Object.entries(edited[matName] || {})) {
    const m = /^Region\s+(\d+)\s*-\s*(.+)$/.exec(pname);
    if (m) (ov[m[1]] = ov[m[1]] || {})[m[2].trim()] = rgba;
  }
  return ov;
}
function dyeRebakeMesh(matName) {
  const d = matData[matName];
  if (!d || (!d.dyeable && !d.eye_preview) || !d.game_rel) return;
  clearTimeout(_dyeMeshTimer[matName]);
  const gen = generation, matGen = materialGeneration, load = materialLoad;
  const revision = (_dyeMeshRevision[matName] || 0) + 1;
  _dyeMeshRevision[matName] = revision;
  _dyeMeshTimer[matName] = setTimeout(async () => {
    let blobUrl;
    try {
      const r = await materialFetch(d.eye_preview ? '/api/eye_preview' : '/api/dye_preview', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ game_rel: d.game_rel, size: 1024, overrides: d.eye_preview ? edited[matName] || {} : _dyeOverridesFor(matName) }),
      }, load);
      if (!r.ok) return;
      blobUrl = URL.createObjectURL(await r.blob());
      const tex = await texLoader.loadAsync(blobUrl);
      if (gen !== generation || matGen !== materialGeneration || revision !== _dyeMeshRevision[matName]) {
        tex.dispose(); return;
      }
      tex.colorSpace = THREE.SRGBColorSpace;
      tex.flipY = false;
      tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
      if (renderer) tex.anisotropy = renderer.capabilities.getMaxAnisotropy();
      for (const mm of (matsByName[matName] || [])) {
        mm.map = tex; mm.color.setHex(0xffffff); mm.needsUpdate = true;
      }
      inspection.retireTexture(liveDyeTextures.get(matName));
      liveDyeTextures.set(matName, tex);
    } catch (e) { /* keep the last good bake */ }
    finally { if (blobUrl) URL.revokeObjectURL(blobUrl); }
  }, 160);
}

async function dyeDownloadMesh(matName) {
  const d = matData[matName];
  if (!d || !d.dyeable || !d.game_rel) return;
  try {
    const r = await projectFetch('/api/dye_download', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ game_rel: d.game_rel, size: 2048, overrides: _dyeOverridesFor(matName) }),
    });
    if (!r.ok) return;
    const u = URL.createObjectURL(await r.blob());
    const a = document.createElement('a');
    a.href = u; a.download = materialLabel(matName).replace(/[^a-z0-9_-]/gi,'_') + '_dyed.png';
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(u), 8000);
  } catch (e) { /* ignore */ }
}

function refreshFoot() {
  const n = Object.values(edited).reduce((a, m) => a + Object.keys(m).length, 0);
  const save = $('viewport-mat-save');
  save.disabled = saving || n === 0 || !!inspection?.capturing();
  save.textContent = saving ? 'Saving…' : 'Save changes';
  const reset = $('viewport-mat-reset');
  reset.textContent = 'Revert all unsaved changes'; reset.title = 'Restore saved colours, preserving existing project edits';
  reset.disabled = saving || n === 0;
  document.querySelectorAll('#viewport-material-editor .vp-color-field').forEach(row => {
    const changed = !!edited[row.dataset.material]?.[row.dataset.parameter];
    row.classList.toggle('is-modified', changed);
    const saved = row.querySelector('.vp-saved-swatch');
    if (saved) saved.disabled = saving || !changed;
    const color = matData[row.dataset.material]?.colors.find(color=>color.name === row.dataset.parameter);
    if (!color) return;
    const value = linToHex(edited[row.dataset.material]?.[color.name] || color.rgba);
    row.querySelector('input[type=color]').value = value;
    const hex = row.querySelector('.vp-hex'); if (document.activeElement !== hex) hex.value = value.toUpperCase();
    const current = row.querySelector('.vp-current-swatch'), code = row.querySelector('.vp-current-hex');
    if (current) current.style.background = value;
    if (code) code.textContent = value;
  });
  for (const row of $('viewport-mat-list').querySelectorAll('.vp-mat')) {
    const marker = row.querySelector('.vp-draft-marker'); if (marker) marker.hidden = !Object.keys(edited).some(name=>materialGroup(name)===row.dataset.group);
  }
  const revert = $('viewport-material-editor').querySelector('.vp-revert-material'); if (revert) revert.disabled = saving || !edited[selectedMaterial];
  const hint = $('viewport-unsaved'); hint.classList.toggle('is-dirty',!!n);
  hint.textContent = n ? `${n} unsaved colour${n === 1 ? '' : 's'}` : 'All changes saved';
  assembly?.sync();
}

async function saveEdits() {
  if (saving || inspection?.capturing()) return;
  const names = Object.keys(edited).filter(n => Object.keys(edited[n]).length);
  if (!names.length) return;
  const draft = edited, gen = generation, project = viewportProject;
  const submitted = JSON.parse(JSON.stringify(edited));
  const targets = Object.fromEntries(names.map(name => [name, matData[name]]));
  const savedPaths=new Set();
  saving = true; refreshFoot();
  let stopWorking;
  try {
    stopWorking = window.AtelierMotion?.working?.begin($('viewport-box'), {
      kind: 'saving', anchor: $('viewport-mat-save'),
      current: () => gen === generation && edited === draft && project === viewportProject
    });
  } catch (_) { /* Optional presentation never blocks saving. */ }
  let ok = 0;
  const failed = [];
  try {
    for (const name of names) {
      const d = targets[name];
      if(savedPaths.has(d.game_rel))continue;
      try {
        const r = await projectFetch('/api/material_save', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ game_rel: d.game_rel, colors: submitted[name], scalars: {} }),
        }, project).then(r => r.json());
        if (!r || !r.ok) throw new Error(r?.error || 'Save failed');
        window.AtelierRoster?.rememberEditor(d.game_rel,'studio',project);
        ok++;savedPaths.add(d.game_rel);
        for(const key of names.filter(key=>targets[key].game_rel===d.game_rel)) {
          const target=targets[key];
          target.colors=r.colors || target.colors.map(col=>({...col,rgba:submitted[key][col.name]?.slice() || col.rgba}));
          if (gen === generation && edited === draft) {
            for (const [param, rgba] of Object.entries(submitted[key])) {
              // A newer edit made during the request is still unsaved.
              if (JSON.stringify(edited[key]?.[param]) === JSON.stringify(rgba)) delete edited[key][param];
            }
            if (!Object.keys(edited[key] || {}).length) delete edited[key];
          }
        }
      } catch (e) { failed.push(name); console.warn('viewport: material_save failed', name, e); }
    }
  } finally {
    const newer = gen === generation && edited === draft && Object.values(edited).some(params => Object.keys(params).length);
    try { stopWorking?.(failed.length && !ok ? 'error' : failed.length || newer ? 'warning' : 'success'); } catch (_) {}
  }
  const ownsView = gen === generation && edited === draft && project === viewportProject;
  const newerEdits = ownsView && Object.values(edited).some(params => Object.keys(params).length);
  const message = failed.length
    ? `Saved ${ok}; ${failed.length} material(s) could not be saved. Unsaved recolors are retained; retry Save.`
    : newerEdits ? 'Submitted changes saved; newer edits remain unsaved.'
    : `Saved recolors to ${ok} material${ok !== 1 ? 's' : ''}`;
  const state = failed.length || newerEdits ? 'warning' : 'success';
  const currentProject = project === (window.atelierProject?.() || '');
  if(currentProject && ok)await window.loadSidebar?.();
  // The singleton saving guard forbids another save until this operation finishes.
  saving = false;
  // Only the originating view owns its controls; old results keep their own notification.
  if (ownsView) {
    if (currentProject) { $('viewport-status').textContent = message; $('viewport-status').dataset.kind = state; }
    buildPanel();
  }
  if (currentProject && $('viewport-overlay').classList.contains('active')) return;
  const toastMessage = currentProject ? message : `${project}: ${message}`;
  try {
    if (typeof window.toastMaterialSave === 'function') {
      window.toastMaterialSave(toastMessage, state, state === 'warning' ? 8000 : 3600);
      return;
    }
  } catch (error) { console.warn('Viewport save feedback unavailable', error); }
  try {
    const escaped = toastMessage.replace(/[&<>]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;'}[c]));
    if (typeof window.toast === 'function') window.toast(escaped, state);
  } catch (error) { console.warn('Viewport save notification unavailable', error); }
}

function revertEdits() {
  if (saving) return;
  for (const name of Object.keys(_dyeMeshTimer)) {
    clearTimeout(_dyeMeshTimer[name]);
    _dyeMeshRevision[name] = (_dyeMeshRevision[name] || 0) + 1;
  }
  clearLiveDyes();
  edited = {};
  for (const name of Object.keys(matData)) {
    retint(name);
    // After a successful save the persisted dye may differ from the original cached map.
    // Rebuild with no draft overrides so Reset shows the last saved material.
    if (matData[name].dyeable || matData[name].eye_preview) dyeRebakeMesh(name);
  }
  buildPanel();                                            // resets the pickers too
  note('Reverted unsaved changes', 'info');
}

function note(msg, kind) {
  if (!$('viewport-overlay').classList.contains('active') && typeof window.toast === 'function') window.toast(String(msg).replace(/[&<>]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])), kind);
  $('viewport-status').textContent = msg;
  $('viewport-status').dataset.kind = kind || 'info';
}

function skinFromGameRel(gr) {
  const m = /characters\/\d+\/(\d+)\//i.exec(gr || '');
  return m ? m[1] : null;
}

function studioTitle(skinId, title) {
  const hero = /^\d{4}/.exec(skinId || '')?.[0];
  const info = window.AtelierRoster?.describe(`Characters/${hero}/${skinId}`);
  if (info?.skin) return `${info.hero.name} / ${info.skin.name}`;
  return title && !/^3D Preview\b/i.test(title) ? title : skinId ? `Skin ${skinId}` : 'Mesh preview';
}

async function open(skinId, title, preferredMesh=null) {
  if (!(await canLeave())) return;
  init();
  viewportProject = window.atelierProject?.() || '';
  loader.setRequestHeader({ 'X-Atelier-Project': encodeURIComponent(viewportProject) });
  meshSkin = skinId; chromaSkin = null;                       // reset the material-set choice
  updateHeroLogo(/^\d{4}/.exec(skinId)?.[0] || '');
  const _cr = $('viewport-chroma-row'); if (_cr) _cr.style.display = 'none';
  $('viewport-title').textContent = studioTitle(skinId,title);
  window.AtelierViewportIdentity?.show(skinId);
  $('viewport-status').textContent = '';
  const posterOrigin = window.AtelierMotion?.viewportPoster?.source();
  inspection.show();
  $('viewport-loading').style.display = 'flex';
  requestAnimationFrame(onResize);
  if (!raf) animate();
  clearModel();
  const gen = generation;
  modelLoading=true;modelLoad={id:crypto.randomUUID(),project:viewportProject};
  loader.setRequestHeader({'X-Atelier-Project':encodeURIComponent(viewportProject),'X-Atelier-Preview':modelLoad.id});
  inspection.setLoading(true);
  window.AtelierMotion?.viewportPoster?.begin({skinId, origin:posterOrigin, stage:$('viewport-stage'), canvas:$('viewport-canvas')});
  $('viewport-loading-msg').textContent = 'Decoding model…';
  startViewportLoader();

  try {
    let meshes = await projectFetch(`/api/skin_meshes?skin_id=${encodeURIComponent(skinId)}`).then(r => r.json());
    if (gen !== generation) return;
    if (!Array.isArray(meshes) || !meshes.length) {
      setViewportLoaderState('empty');
      $('viewport-loading-msg').textContent = 'No meshes found for this skin.';
      return;
    }
    if(preferredMesh&&!meshes.some(mesh=>mesh.game_rel===preferredMesh))meshes.push({name:preferredMesh.split('/').pop(),game_rel:preferredMesh,kind:/\/weapons\//i.test(preferredMesh)?'weapon':'body'});
    const order=mesh=>mesh.kind==='weapon' ? 10+(mesh.game_rel===preferredMesh?-2:/_[lr]$/i.test(mesh.name)?-1:0) : mesh.game_rel===preferredMesh?-1:0;
    meshes.sort((a,b)=>order(a)-order(b));
    for(const mesh of meshes) {
      const kind=mesh.kind || (/\/weapons\//i.test(mesh.game_rel)?'weapon':'body');
      const root=new THREE.Group();root.visible=false;
      objects.push({name:mesh.name,kind,autoEquip:mesh.auto_equip!==false,root,loaded:false,
        ...(kind==='weapon'&&mesh.game_rel===preferredMesh?{enabled:true}:{})});
      meshMeta.push({name:mesh.name,game_rel:mesh.game_rel});
    }
    // Load one body, then only weapons that can occupy an available hand. Hidden
    // forms, duplicate static weapons and optional ability rigs stay on demand.
    let body=null;
    for(const candidate of objects.filter(object=>object.kind!=='weapon')) {
      $('viewport-loading-msg').textContent=`Decoding ${candidate.name}… first time can take a moment`;
      if(await loadObject(candidate,gen)){body=candidate;break;}
      if(gen!==generation)return;
    }
    if(gen!==generation)return;
    if (!body) {
      setViewportLoaderState('error');
      const failed=objects.find(object=>object.loadError);
      $('viewport-loading-msg').textContent = 'Failed to load meshes. '+(failed?`${failed.name}: ${failed.loadError}`:'No body mesh found.');
      return;
    }
    body.root.visible=true;
    frameCamera();
    setViewportLoaderState('ready');destroyViewportLoader();$('viewport-loading').style.display='none';
    note('Loading equipped weapons…','info');
    await loadAutomaticWeapons(gen);
    if(gen!==generation)return;
    modelLoading=false;
    buildObjectPanel();
    refreshBlenderBtn();
    frameCamera();
    setViewportLoaderState('ready');
    destroyViewportLoader();
    $('viewport-loading').style.display = 'none';
    loadMaterials(skinId);
    syncPreviewAnimation();
    // offer other material sets (chromas) for this mesh — keyed off the mesh's real path
    buildChromaPicker(skinId, meshMeta[objects.indexOf(body)].game_rel);
  } catch (e) {
    if (gen !== generation) return;
    setViewportLoaderState('error');
    $('viewport-loading-msg').textContent = 'Error: ' + e.message;
  } finally {
    if(gen===generation) {modelLoading=false;if(!materialTask)inspection.setLoading(false);}
  }
}

async function openMesh(gameRel, name, skinId) {
  const skin=skinId || skinFromGameRel(gameRel);
  if (skin) return open(skin,name,gameRel);
  if (!(await canLeave())) return;
  init();
  viewportProject = window.atelierProject?.() || '';
  loader.setRequestHeader({ 'X-Atelier-Project': encodeURIComponent(viewportProject) });
  const _sk = skinId || skinFromGameRel(gameRel);
  meshSkin = _sk; chromaSkin = null;                         // reset the material-set choice
  updateHeroLogo(/characters\/(\d{4})\//i.exec(gameRel)?.[1] || '');
  const _cr = $('viewport-chroma-row'); if (_cr) _cr.style.display = 'none';
  $('viewport-title').textContent = studioTitle(_sk,name);
  window.AtelierViewportIdentity?.show(_sk, /characters\/(\d{4})\//i.exec(gameRel)?.[1]);
  $('viewport-status').textContent = '';
  const posterOrigin = window.AtelierMotion?.viewportPoster?.source();
  inspection.show();
  $('viewport-loading').style.display = 'flex';
  $('viewport-loading-msg').textContent = `Decoding ${name || 'mesh'}… first time can take a moment`;
  requestAnimationFrame(onResize);
  if (!raf) animate();
  clearModel();
  const gen = generation;
  modelLoading=true;modelLoad={id:crypto.randomUUID(),project:viewportProject};
  loader.setRequestHeader({'X-Atelier-Project':encodeURIComponent(viewportProject),'X-Atelier-Preview':modelLoad.id});
  inspection.setLoading(true);
  window.AtelierMotion?.viewportPoster?.begin({skinId:_sk, origin:posterOrigin, stage:$('viewport-stage'), canvas:$('viewport-canvas')});
  startViewportLoader();
  try {
    const gltf = await loader.loadAsync(`/api/model_gltf?game_rel=${encodeURIComponent(gameRel)}`);
    if (gen !== generation) { disposeTree(gltf.scene); return; }
    collectMats(gltf.scene,{game_rel:gameRel},gltf.parser);
    animation.register(gltf);
    modelRoot.add(gltf.scene);
    objects.push({ name: name || 'Mesh', kind:'body', loaded:true, root: gltf.scene, animations:gltf.animations, rig:attachmentRig(gltf) });
    meshMeta.push({ name: name || 'Mesh', game_rel: gameRel });
    modelLoading=false;
    refreshBlenderBtn();
    buildObjectPanel();
    frameCamera();
    $('viewport-status').textContent = name || '';
    setViewportLoaderState('ready');
    destroyViewportLoader();
    $('viewport-loading').style.display = 'none';
    modelLoading=false;
    loadMaterials(_sk);
    animation.discover(gameRel);
    buildChromaPicker(_sk, gameRel);   // same "materials from" picker as the skin path
  } catch (e) {
    if (gen !== generation) return;
    const reason = await loadErrorText(e);
    if (gen !== generation) return;
    setViewportLoaderState('error');
    $('viewport-loading-msg').textContent = 'Failed to load: ' + reason;
  } finally {
    if(gen===generation){modelLoading=false;if(!materialTask)inspection.setLoading(false);}
  }
}

async function close() {
  if (!(await canLeave())) return;
  if (inited) clearModel();
  window.AtelierMotion?.viewportPoster?.end();
  $('viewport-overlay').classList.remove('active');
  if (raf) { cancelAnimationFrame(raf); raf = 0; }   // stop rendering while hidden (frees the GPU)
  inspection?.closed();
  window.AtelierViewportIdentity?.clear();
}

$('viewport-close').addEventListener('click', close);
$('viewport-overlay').addEventListener('click', e => { if (e.target.id === 'viewport-overlay') close(); });
window.addEventListener('keydown', e => {
  if (e.defaultPrevented || !$('viewport-overlay').classList.contains('active')) return;
  if (e.key === 'Escape') {
    e.preventDefault();
    const menu = document.querySelector('#viewport-box .vp-menu[open]');
    if (menu) {menu.open=false;menu.querySelector('summary').focus();return;}
    close();
  }
  else inspection?.keydown(e);
});

window.addEventListener('beforeunload', event => {
  if (saving || visibilityBusy.size || Object.values(edited).some(params => Object.keys(params).length)) {
    event.preventDefault(); event.returnValue = 'Preview recolors have unsaved changes.';
  }
});
window.addEventListener('pagehide', () => {
  if(inited)clearModel();
  if(raf){cancelAnimationFrame(raf);raf=0;}
  inspection?.closed();window.AtelierViewportIdentity?.clear();
});

function hasPendingEdits() {
  return saving || visibilityBusy.size > 0 || Object.values(edited).some(params => Object.keys(params).length);
}

function focusPendingEdits() {
  if (!hasPendingEdits()) return;
  $('viewport-overlay').classList.add('active');
  const status = $('viewport-status');
  status.textContent = saving || visibilityBusy.size ? 'Preview save in progress. Wait for it to finish before exporting.'
    : 'Save or revert these unsaved preview recolors before exporting.';
  status.setAttribute('role', 'status');
  const save = $('viewport-mat-save');
  if (!saving && !save.disabled && save.getClientRects().length) save.focus();
  else { status.tabIndex = -1; status.focus(); }
  if (inited) {
    requestAnimationFrame(onResize);
    if (!raf) animate();
  }
}

function captureModPoster(context){
  if(!inited||hasPendingEdits()||context.project!==viewportProject||!context.skin||context.skin!==(currentSkin||meshSkin))return null;
  return inspection.cardPoster();
}
window.AtelierViewport = { open, openMesh, close, hasPendingEdits, focusPendingEdits,captureModPoster };
