import * as THREE from 'three';
import { createViewportEffects } from './viewport-effects.js';

const $ = id => document.getElementById(id);
const directions = {perspective:[.32,.10,1], front:[0,0,1], back:[0,0,-1], left:[-1,0,0], right:[1,0,0], top:[0,1,0]};

// Presentation owns disposable variants, never the model's editable materials or project files.
export function createViewportInspection(api) {
  const {renderer, scene, camera, controls, grid, modelRoot, lights} = api;
  let view = 'perspective', fitOnResize = true, wireframe = false, showGrid = true;
  let lighting = 'studio', comparison = 'edited', regions = false, hovered = null;
  let revision = 0, requestedMode = 0, originalPromise = null, regionPromise = null, capture = null;
  const originals = new Map(), overlays = new Map(), variants = new Map(), textures = new Set();
  const replacedCopy=new THREE.MeshBasicMaterial({visible:false});
  const originalTextures = new Set();
  const raycaster = new THREE.Raycaster(), pointer = new THREE.Vector2();
  let down = null, opener = null, assetsLoading = false;
  const reducedMotion = (window.AtelierMotionPolicy?.query() || matchMedia('(prefers-reduced-motion: reduce)'));
  const effects = createViewportEffects({renderer,scene,camera,modelRoot,grid,reduced:reducedMotion});
  let cameraMove = null;
  // Showcase keeps its own floor toggle so its default look stays floorless.
  let showcaseMode=false,showcaseColors=null,showcaseBackdrop=null,showcaseGrid=false;
  // Inspection overlays would leak into Showcase captures, so Showcase disables them with a reason.
  const inspectOnly=new Map(['viewport-wireframe','viewport-regions','viewport-edited','viewport-original','viewport-wipe'].map(id=>[id,$(id).title]));
  const toonGradient=new THREE.DataTexture(new Uint8Array([0,90,180,255]),4,1,THREE.RedFormat);
  toonGradient.minFilter=toonGradient.magFilter=THREE.NearestFilter;toonGradient.needsUpdate=true;
  function showcaseInks(){return window.AtelierShowcaseArt.palette(showcaseColors||palette());}
  // The default backdrop is the mode's own; plain colour and transparent replace the art.
  const showcaseArt=()=>showcaseMode&&$('viewport-backdrop').value==='gradient';
  function drawShowcase(){
    if(!showcaseArt()){showcaseBackdrop?.remove();showcaseBackdrop=null;return;}
    if(!showcaseBackdrop){showcaseBackdrop=document.createElement('canvas');showcaseBackdrop.className='vp-showcase-backdrop';showcaseBackdrop.setAttribute('aria-hidden','true');$('viewport-stage').prepend(showcaseBackdrop);}
    const width=Math.max(1,$('viewport-stage').clientWidth),height=Math.max(1,$('viewport-stage').clientHeight-58);
    showcaseBackdrop.width=width;showcaseBackdrop.height=height;
    const context=showcaseBackdrop.getContext('2d');if(context)window.AtelierShowcaseArt.draw(context,width,height,showcaseInks());
  }
  function setShowcase(value){
    showcaseMode=!!value;$('viewport-showcase').setAttribute('aria-pressed',String(showcaseMode));$('viewport-inspect').setAttribute('aria-pressed',String(!showcaseMode));
    $('viewport-stage').classList.toggle('vp-showcase',showcaseMode);showcaseBackdrop?.remove();showcaseBackdrop=null;
    $('viewport-backdrop').options[0].textContent=showcaseMode?'Showcase art':'Studio';
    $('viewport-showcase-note').hidden=!showcaseMode;
    if(showcaseMode){
      clearHover();drawShowcase();const skin=api.context?.().skin,stamp=revision;
      if(skin){const image=new Image();image.src='/api/catalogue/thumbnail/'+encodeURIComponent(skin);image.decode().then(()=>{if(stamp!==revision||!showcaseMode)return;showcaseColors=window.AtelierPolish?.samplePalette(image)||null;drawShowcase();}).catch(()=>{});}
    }
    updateRegions();refresh();
    $('viewport-comparison').hidden=comparison!=='wipe' || showcaseMode;
  }
  $('viewport-showcase').addEventListener('click',()=>setShowcase(true));$('viewport-inspect').addEventListener('click',()=>setShowcase(false));
  // The reveal is one last Krackle sweep (viewport-effects.js) that leaves the loaded appearance behind it.
  let revealStart = null, reveal = 1;
  const scanAllowed=()=>!document.hidden && !reducedMotion.matches && window.AtelierMotionPolicy?.allows(2)!==false;
  function materialize() { revealStart = scanAllowed() ? performance.now() : null;if(showcaseMode){showcaseColors=null;setShowcase(true);} }
  reducedMotion.addEventListener('change', () => { if (reducedMotion.matches) { revealStart = null; reveal = 1; finishCamera(); } });
  window.addEventListener('pagehide', () => {toonGradient.dispose();replacedCopy.dispose();}, {once:true});

  function worldBoxes() {
    const boxes = [];
    modelRoot.updateMatrixWorld(true);
    modelRoot.traverseVisible(mesh => {
      if (!mesh.isMesh) return;
      if (mesh.isSkinnedMesh) mesh.computeBoundingBox();
      else if (!mesh.geometry.boundingBox) mesh.geometry.computeBoundingBox();
      const box = mesh.isSkinnedMesh ? mesh.boundingBox : mesh.geometry.boundingBox;
      if (box && !box.isEmpty()) boxes.push(box.clone().applyMatrix4(mesh.matrixWorld));
    });
    return boxes;
  }
  const bounds = () => worldBoxes().reduce((box,part)=>box.union(part),new THREE.Box3());

  function frame(keepDirection = false, smooth = false, focusBox = null) {
    const parts = focusBox ? [focusBox] : worldBoxes();
    const box = parts.reduce((box,part)=>box.union(part),new THREE.Box3());
    if (box.isEmpty()) return;
    const center = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3());
    const scale = Math.max(size.x, size.y, size.z) || 1;
    const direction = keepDirection || view === 'custom'
      ? camera.position.clone().sub(controls.target).normalize()
      : new THREE.Vector3(...directions[view]).normalize();
    if (!direction.lengthSq()) direction.set(0,0,1);
    const up = view === 'top' ? new THREE.Vector3(0,0,-1) : new THREE.Vector3(0,1,0);
    const right = new THREE.Vector3().crossVectors(up, direction).normalize();
    // A free orbit can approach the pole. Preserve a valid basis for both framing and lookAt.
    if (right.lengthSq() < 1e-8) { up.set(0,0,-1); right.crossVectors(up, direction).normalize(); }
    const vertical = new THREE.Vector3().crossVectors(direction, right).normalize();
    const tanV = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
    const tanH = tanV * camera.aspect;
    let distance = scale * .1;
    // Frame each part's bounds, avoiding empty corners of the combined box around tails/weapons.
    for (const part of parts) for (const x of [part.min.x, part.max.x]) for (const y of [part.min.y, part.max.y]) for (const z of [part.min.z, part.max.z]) {
      const corner = new THREE.Vector3(x,y,z).sub(center);
      distance = Math.max(distance, corner.dot(direction) + Math.max(Math.abs(corner.dot(right)) / tanH, Math.abs(corner.dot(vertical)) / tanV) * 1.08);
    }
    finishCamera(false);
    const damping = controls.enableDamping;
    controls.enableDamping = false; controls.update();
    const position = center.clone().addScaledVector(direction, distance);
    if (smooth && !reducedMotion.matches && !document.hidden) {
      cameraMove = {start:performance.now(),from:camera.position.clone(),to:position,
        fromTarget:controls.target.clone(),target:center,fromUp:camera.up.clone(),up,damping};
    } else {
      camera.up.copy(up); controls.target.copy(center); camera.position.copy(position);
      controls.update(); controls.enableDamping = damping;
    }
    camera.near = Math.max(scale / 1000, .00001); camera.far = distance + scale * 100;
    controls.minDistance = scale * .01; controls.maxDistance = distance + scale * 50;
    camera.updateProjectionMatrix();
    if (!focusBox) { grid.position.set(center.x, box.min.y - scale * .001, center.z); grid.scale.setScalar(scale / 200); }
    fitOnResize = true;
  }

  function finishCamera(complete = true) {
    if (!cameraMove) return;
    if (complete) { camera.position.copy(cameraMove.to); camera.up.copy(cameraMove.up); controls.target.copy(cameraMove.target); controls.update(); }
    controls.enableDamping = cameraMove.damping; cameraMove = null;
  }
  function updateCamera() {
    if (!cameraMove) return;
    const t = Math.min(1,(performance.now()-cameraMove.start)/260), eased = 1-(1-t)**3;
    camera.position.lerpVectors(cameraMove.from,cameraMove.to,eased);
    controls.target.lerpVectors(cameraMove.fromTarget,cameraMove.target,eased);
    camera.up.lerpVectors(cameraMove.fromUp,cameraMove.up,eased).normalize(); controls.update();
    if (t===1) finishCamera();
  }
  function updateAxes() {
    const inverse = camera.quaternion.clone().invert();
    for (const [name,axis] of Object.entries({x:[1,0,0],y:[0,1,0],z:[0,0,1]})) {
      const vector = new THREE.Vector3(...axis).applyQuaternion(inverse);
      const line = $('viewport-axis-'+name), text = $('viewport-axis-label-'+name);
      line.setAttribute('x2',String(36+vector.x*23)); line.setAttribute('y2',String(36-vector.y*23));
      text.setAttribute('x',String(36+vector.x*29)); text.setAttribute('y',String(39-vector.y*29));
      line.style.opacity = text.style.opacity = String(.6+(vector.z+1)*.2);
    }
  }

  function refresh() {
    const objects = api.objects(), visible = objects.filter(o => o.root.visible);
    let triangles = 0;
    for (const object of visible) object.root.traverseVisible(mesh => {
      if (mesh.isMesh) triangles += Math.floor((mesh.geometry.index?.count || mesh.geometry.attributes.position?.count || 0) / 3);
    });
    $('viewport-stats').textContent = objects.length ? `${visible.length} / ${objects.length} objects · ${triangles.toLocaleString()} triangles` : 'No model loaded';
    $('viewport-hidden').hidden = !objects.length || !!visible.length;
    const floor = showcaseMode ? showcaseGrid : showGrid;
    grid.visible = floor && !!visible.length; $('viewport-grid').setAttribute('aria-pressed', String(floor));
    for (const id of ['viewport-fit','viewport-view','viewport-wireframe','viewport-poster','viewport-turntable']) $(id).disabled = !visible.length;
    for (const id of ['viewport-poster','viewport-turntable']) $(id).disabled ||= !api.ready();
    for (const id of ['viewport-edited','viewport-original','viewport-wipe']) $(id).disabled = !Object.keys(api.materials().data).length;
    $('viewport-regions').disabled = !Object.values(api.materials().data).some(d => d.dyeable);
    for (const [id,title] of inspectOnly) {
      $(id).disabled ||= showcaseMode;
      $(id).title = showcaseMode ? 'Inspect mode only: Showcase shows the finished look' : title;
    }
    $('viewport-show-all').disabled = objects.every(o => o.root.visible);
  }

  function setComparison(mode) {
    comparison = mode;
    for (const value of ['edited','original','wipe']) $('viewport-' + value).setAttribute('aria-pressed', String(value === mode));
    $('viewport-comparison').hidden = mode !== 'wipe';
  }

  async function loadTexture(url, stamp, original = true) {
    if (stamp !== revision) throw new DOMException('Preview changed', 'AbortError');
    const texture = await api.texture(url);
    if (stamp !== revision) { texture.dispose(); throw Error('Preview changed'); }
    texture.colorSpace = THREE.SRGBColorSpace; texture.flipY = false;
    texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
    texture.anisotropy = renderer.capabilities.getMaxAnisotropy();
    textures.add(texture);
    if (original) originalTextures.add(texture);
    return texture;
  }

  async function loadOriginals() {
    if (originalPromise) return originalPromise;
    const stamp = revision, {data, byName} = api.materials();
    const jobs = Object.entries(byName).map(async ([name, materials]) => {
      const info = data[name];
      if (!info?.game_rel) {
        // Unmatched slots cannot be edited in this studio; retain their unmodified decoded form.
        for (const material of materials) originals.set(material,material.clone());
        return;
      }
      const result = await api.fetch(`/api/material_original?game_rel=${encodeURIComponent(info.game_rel)}`).then(r => r.json());
      if (stamp !== revision) throw new DOMException('Preview changed', 'AbortError');
      if (!result.ok) throw Error(result.error || 'Original material unavailable');
      const tex = result.textures || {}, roles=api.textureRoles(result);
      const map = tex.DyeingTexture
        ? await loadTexture(`/api/dye_texture?game_rel=${encodeURIComponent(info.game_rel)}&original=1`, stamp)
        : roles.basecolor ? await loadTexture(`/api/texture_png?game_rel=${encodeURIComponent(roles.basecolor)}&original=1`, stamp) : null;
      const emissiveMap = roles.emissive ? await loadTexture(`/api/texture_png?game_rel=${encodeURIComponent(roles.emissive)}&original=1`, stamp) : null;
      const alphaMap=roles.opacity ? await loadTexture(`/api/texture_png?game_rel=${encodeURIComponent(roles.opacity)}&original=1`,stamp) : null;
      if(alphaMap)alphaMap.colorSpace=THREE.NoColorSpace;
      if (stamp !== revision) return;
      for (const material of materials) {
        const original = material.clone(); original.map = map; original.emissiveMap = emissiveMap;original.alphaMap=alphaMap;
        api.applySurface(original,result);
        api.tintOriginal(original, result);
        originals.get(material)?.dispose(); originals.set(material, original);
      }
    });
    originalPromise = Promise.allSettled(jobs).then(results => {
      const failure = results.find(r => r.status === 'rejected');
      if (failure) {
        if (stamp === revision) {
          originalPromise = null;
          for (const material of originals.values()) material.dispose(); originals.clear();
          for (const texture of originalTextures) { textures.delete(texture); texture.dispose(); } originalTextures.clear();
        }
        throw failure.reason;
      }
      if (stamp !== revision) throw Error('Preview changed');
    });
    return originalPromise;
  }

  async function chooseComparison(mode) {
    const request = ++requestedMode, stamp = revision;
    if (mode === 'edited') { setComparison(mode); return; }
    $('viewport-status').textContent = 'Loading original game materials…';
    $('viewport-status').dataset.kind = 'info';
    try {
      await loadOriginals();
      if (request !== requestedMode || stamp !== revision) return;
      setComparison(mode); $('viewport-status').textContent = mode === 'wipe' ? 'Original ← drag divider → Edited' : 'Original game textures and materials';
    } catch (error) {
      if (stamp === revision && request === requestedMode) api.notify(`Comparison unavailable: ${error.message}`, 'warning');
    }
  }

  async function toggleRegions() {
    if (regions) { regions = false; updateRegions(); return; }
    const stamp = revision;
    $('viewport-regions').disabled = true;
    try {
      if (!regionPromise) regionPromise = Promise.all(Object.entries(api.materials().data).filter(([,d]) => d.dyeable).map(async ([name, info]) => {
        const texture = await loadTexture(`/api/dye_overlay?game_rel=${encodeURIComponent(info.game_rel)}&size=1024&v=${encodeURIComponent(info.dye_ver || '0')}`, stamp, false);
        if (stamp === revision) overlays.set(name, texture);
      }));
      await regionPromise;
      if (stamp !== revision) return;
      regions = true; updateRegions();
    } catch (error) {
      if (stamp === revision) { regionPromise = null; api.notify(`Dye regions unavailable: ${error.message}`, 'warning'); }
    } finally { if (stamp === revision) refresh(); }
  }

  function updateRegions() {
    $('viewport-regions').setAttribute('aria-pressed', String(regions));
    $('viewport-region-legend').hidden = !regions || showcaseMode;
  }

  // three.js rebuilds a shader on its own for only a few changes. Texture slots, side and blending
  // also select the shader variant, so a display copy compiled before its source's maps arrived
  // must be rebuilt: otherwise a late black emissive mask leaves the whole part glowing white.
  const variantSlots=['map','alphaMap','emissiveMap','normalMap','bumpMap','aoMap','lightMap','roughnessMap','metalnessMap','displacementMap','specularMap','gradientMap'];
  const shaderVariant=m=>variantSlots.map(key=>m[key]?1:0).join('')+[m.side,m.transparent,m.blending,m.vertexColors,m.flatShading,m.alphaHash,m.premultipliedAlpha,m.toneMapped].join();
  function displayMaterial(source, original, showcase,comic=false) {
    if (!source.visible) return source;
    const base = original ? originals.get(source) || source : source;
    const overlay = !showcase && regions && overlays.get(source.name);
    const flat = lighting === 'flat' || lighting === 'emissive' || !!overlay;
    let pair = variants.get(base);
    if (!pair) {
      pair = {standard:base.clone(), flat:new THREE.MeshBasicMaterial(),toon:new THREE.MeshToonMaterial({gradientMap:toonGradient})}; variants.set(base, pair);
    }
    if(comic){
      const toon=pair.toon,oldMap=toon.map,oldAlpha=toon.alphaTest,variant=shaderVariant(toon);
      toon.color.copy(base.color||new THREE.Color(0xffffff));toon.emissive.copy(base.emissive||new THREE.Color(0));
      for(const key of ['map','alphaMap','emissiveMap','normalMap','bumpMap','aoMap','displacementMap'])toon[key]=base[key]||null;
      for(const key of ['side','transparent','opacity','alphaTest','depthWrite','depthTest','blending','emissiveIntensity','normalMapType','bumpScale','aoMapIntensity','displacementScale','displacementBias'])if(base[key]!==undefined)toon[key]=base[key];
      if(base.normalScale)toon.normalScale.copy(base.normalScale);toon.wireframe=false;toon.clippingPlanes=null;toon.visible=source.visible;
      if(oldMap!==toon.map||oldAlpha!==toon.alphaTest||variant!==shaderVariant(toon))toon.needsUpdate=true;
      return toon;
    }
    const material = flat ? pair.flat : pair.standard;
    const oldMap = material.map, oldWireframe = material.wireframe, variant = shaderVariant(material);
    if (flat) {
      material.map = overlay || (lighting === 'emissive' ? base.emissiveMap : base.map);
      material.color.copy(lighting === 'emissive' && !overlay ? base.emissive : overlay ? new THREE.Color(0xffffff) : base.color);
      if (lighting === 'emissive' && !overlay) material.color.multiplyScalar(base.emissiveIntensity || 0);
      material.side = base.side; material.transparent = base.transparent; material.opacity = base.opacity;
      material.alphaTest = base.alphaTest; material.alphaMap = base.alphaMap; material.depthWrite = base.depthWrite;
      material.toneMapped = lighting === 'emissive' && !overlay;
    } else material.copy(base);
    material.wireframe = !showcase && wireframe;material.visible=source.visible;
    // Tween disposable display colors in linear space, preserving exact saved values.
    if (!overlay) effects.tint(material,base,showcase,lighting==='emissive');
    if (oldMap !== material.map || oldWireframe !== material.wireframe || variant !== shaderVariant(material)) material.needsUpdate = true;
    return material;
  }

  // Showcase honours View settings; the canonical mod-card poster ignores them.
  function renderPass(original = false, showcase = false, comic=false,canonical=false) {
    const restore = [];
    const gridVisible=grid.visible,toon=comic&&(canonical||lighting==='studio');
    try {
    if(canonical)grid.visible=false;
    modelRoot.traverse(mesh => {
      if (!mesh.isMesh) return;
      restore.push([mesh, mesh.material]);
      const shown = m => m.userData?.heldDuplicate ? replacedCopy : !m.visible ? m : displayMaterial(m, original, showcase,toon);
      mesh.material = Array.isArray(mesh.material) ? mesh.material.map(shown) : shown(mesh.material);
    });
      renderer.render(scene, camera);
      if (!canonical && lighting !== 'flat' && !(regions && !showcase)) effects.drawBloom();
    }
    finally { for (const [mesh, material] of restore) mesh.material = material;grid.visible=gridVisible; }
  }

  function render(showcase = false,comic=showcaseMode,canonical=false) {
    const captured=showcase;
    showcase ||= comic;
    if (!captured) { updateCamera(); updateAxes(); }
    if (!captured) {
      if(!scanAllowed()){revealStart=null;effects.stopLoading();}
      reveal = revealStart === null ? 1 : Math.min(1, (performance.now() - revealStart) / 420);
      if (reveal === 1) revealStart = null;
      if (!assetsLoading && reveal===1) effects.stopLoading();
    }
    if (comparison !== 'wipe' || showcase) {
      renderPass(!showcase && comparison === 'original', showcase,comic,canonical);
      if (!captured && scanAllowed() && (assetsLoading || reveal < 1)) effects.drawLoading(bounds(), assetsLoading ? null : reveal);
      else if (!showcase) effects.drawOutline(hovered);
      return;
    }
    const size = renderer.getSize(new THREE.Vector2());
    const divider = Math.round(size.x * Number($('viewport-wipe-range').value) / 100);
    renderer.setScissorTest(true);
    try {
      renderer.setScissor(0, 0, divider, size.y); renderPass(true); effects.drawOutline(hovered);
      renderer.setScissor(divider, 0, size.x - divider, size.y); renderPass(false); effects.drawOutline(hovered);
    } finally { renderer.setScissorTest(false); }
    if (scanAllowed() && (assetsLoading || reveal<1)) effects.drawLoading(bounds(),assetsLoading?null:reveal);
  }

  function pick(event) {
    const rect = renderer.domElement.getBoundingClientRect();
    pointer.set((event.clientX - rect.left) / rect.width * 2 - 1, -(event.clientY - rect.top) / rect.height * 2 + 1);
    raycaster.setFromCamera(pointer, camera);
    modelRoot.updateMatrixWorld(true);
    modelRoot.traverseVisible(mesh => { if (mesh.isSkinnedMesh) mesh.computeBoundingSphere(); });
    const hits = raycaster.intersectObjects(modelRoot.children, true);
    for (const hit of hits) {
      let visible = true;
      for (let node = hit.object; node && node !== modelRoot; node = node.parent) visible &&= node.visible;
      if (!visible || !hit.object.isMesh) continue;
      const material = Array.isArray(hit.object.material) ? hit.object.material[hit.face?.materialIndex || 0] : hit.object.material;
      if (material?.visible) return {name:material.name,object:hit.object};
    }
    return null;
  }

  function clearHover() { hovered = null; $('viewport-hover').hidden = true; }
  renderer.domElement.addEventListener('pointermove', event => {
    if (event.buttons || capture) { clearHover(); return; }
    hovered = pick(event)?.name || null;
    const hint = $('viewport-hover'); hint.hidden = !hovered;
    hint.textContent = hovered ? `${api.label(hovered)} · Click to edit · Double-click to frame` : '';
  });
  renderer.domElement.addEventListener('pointerleave', clearHover);
  renderer.domElement.addEventListener('pointerdown', event => { down = {x:event.clientX, y:event.clientY, button:event.button}; });
  renderer.domElement.addEventListener('pointerup', event => {
    if (!capture && down?.button === 0 && Math.hypot(event.clientX-down.x, event.clientY-down.y) < 5) {
      const hit = pick(event); if (hit) api.pickMaterial(hit.name, false);
    }
    down = null;
  });
  renderer.domElement.addEventListener('dblclick', event => {
    if (capture || event.button !== 0) return;
    const hit = pick(event); if (!hit) return;
    hit.object.updateWorldMatrix(true,false);
    if (hit.object.isSkinnedMesh) hit.object.computeBoundingBox();
    frame(true,true,new THREE.Box3().setFromObject(hit.object));
    event.preventDefault();
  });
  controls.addEventListener('start', () => { finishCamera(false); fitOnResize = false; view = 'custom'; $('viewport-view').value = view; clearHover(); });

  function chooseView(value) { view = value; $('viewport-view').value = value; frame(); }
  $('viewport-view').addEventListener('change', event => chooseView(event.target.value));
  $('viewport-fit').addEventListener('click', () => frame(true,true));
  $('viewport-wireframe').addEventListener('click', () => { wireframe = !wireframe; $('viewport-wireframe').setAttribute('aria-pressed', String(wireframe)); });
  $('viewport-grid').addEventListener('click', () => { if (showcaseMode) showcaseGrid = !showcaseGrid; else showGrid = !showGrid; refresh(); });
  $('viewport-lighting').addEventListener('change', event => {
    lighting = event.target.value;
    lights.forEach((light,i) => { light.intensity = [.45,1.4,.5][i]; });
    scene.environmentIntensity = .45;
  });
  $('viewport-bloom').addEventListener('click', event => {
    const enabled = event.currentTarget.getAttribute('aria-pressed') !== 'true';
    try { effects.setBloom(enabled); event.currentTarget.setAttribute('aria-pressed',String(enabled)); }
    catch (error) { effects.setBloom(false); event.currentTarget.setAttribute('aria-pressed','false'); api.notify('Bloom unavailable on this renderer','warning'); }
  });
  function backdrop() {
    const mode = $('viewport-backdrop').value;
    $('viewport-stage').dataset.backdrop = mode;
    $('viewport-backdrop-color').hidden = mode !== 'solid';
    $('viewport-stage').style.setProperty('--viewport-backdrop', $('viewport-backdrop-color').value);
    drawShowcase();
  }
  $('viewport-backdrop').addEventListener('change',backdrop);
  $('viewport-backdrop-color').addEventListener('input',backdrop); backdrop();
  for (const mode of ['edited','original','wipe']) $('viewport-' + mode).addEventListener('click', () => chooseComparison(mode));
  $('viewport-regions').addEventListener('click', toggleRegions);
  $('viewport-wipe-range').addEventListener('input', event => $('viewport-comparison').style.setProperty('--wipe', event.target.value + '%'));
  const wipeLine = $('viewport-wipe-line');
  const moveWipe = event => {
    const rect = $('viewport-stage').getBoundingClientRect();
    const percent = Math.round(Math.max(0,Math.min(100,(event.clientX-rect.left)/rect.width*100)));
    $('viewport-wipe-range').value = String(percent); $('viewport-comparison').style.setProperty('--wipe',percent+'%');
  };
  wipeLine.addEventListener('pointerdown',event=>{wipeLine.setPointerCapture(event.pointerId);moveWipe(event);event.preventDefault();});
  wipeLine.addEventListener('pointermove',event=>{if(wipeLine.hasPointerCapture(event.pointerId)) moveWipe(event);});
  wipeLine.addEventListener('pointerup',event=>{if(wipeLine.hasPointerCapture(event.pointerId)) wipeLine.releasePointerCapture(event.pointerId);});
  $('viewport-expand').addEventListener('click', () => {
    const expanded = $('viewport-box').classList.toggle('expanded');
    $('viewport-expand').setAttribute('aria-pressed', String(expanded));
    $('viewport-expand').setAttribute('aria-label', expanded ? 'Restore workspace size' : 'Expand workspace');
    $('viewport-expand').title = expanded ? 'Restore workspace size' : 'Expand workspace';
  });

  function palette() {
    return [...new Set(Object.entries(api.materials().data).flatMap(([name,d]) => (d.colors || []).filter(c => !/emiss|glow/i.test(c.name)).map(c => api.hex(api.materials().edited[name]?.[c.name] || c.rgba))))].slice(0,8);
  }

  function posterCanvas(size, footer = 96,art=showcaseArt()) {
    const output = document.createElement('canvas'); output.width = size; output.height = size + footer;
    const context = output.getContext('2d');
    context.fillStyle = '#101217'; context.fillRect(0,size,size,footer);
    const mode = $('viewport-backdrop').value;
    if(art)window.AtelierShowcaseArt.draw(context,size,size,showcaseInks());
    else if (mode !== 'checker') {
      const style = getComputedStyle($('viewport-stage'));
      const gradient = context.createLinearGradient(0,0,size,size);
      gradient.addColorStop(0,style.getPropertyValue('--viewport-gradient-top').trim() || '#253142');
      gradient.addColorStop(1,style.getPropertyValue('--viewport-gradient-bottom').trim() || '#101217');
      context.fillStyle = mode === 'solid' ? $('viewport-backdrop-color').value : gradient;
      context.fillRect(0,0,size,size);
    }
    context.drawImage(renderer.domElement, 0,0,size,size);
    if(footer<=0)return output;
    context.fillStyle = '#e5e2e4'; context.font = `500 ${Math.round(size*.025)}px Roboto, sans-serif`;
    context.fillText(($('viewport-capture-name').value.trim() || $('viewport-title').textContent).slice(0,100), size*.035, size+footer*.38, size*.85);
    palette().forEach((color,i) => { context.fillStyle = color; context.fillRect(size*.035 + i*size*.045, size+footer*.6, size*.032, footer*.18); });
    return output;
  }

  const toBlob = (canvas, type) => new Promise((resolve,reject) => canvas.toBlob(blob => blob ? resolve(blob) : reject(Error('Image encoding failed')), type, .88));
  function cardPoster(size=1000) {
    if(capture||bounds().isEmpty()||!api.ready())return null;
    finishCamera();
    const dimensions=renderer.getSize(new THREE.Vector2()),ratio=renderer.getPixelRatio();
    const saved={position:camera.position.clone(),up:camera.up.clone(),target:controls.target.clone(),aspect:camera.aspect,near:camera.near,far:camera.far,min:controls.minDistance,max:controls.maxDistance,fit:fitOnResize,damping:controls.enableDamping};
    const animationState=api.pauseAnimation?.();
    try{renderer.setPixelRatio(1);renderer.setSize(size,size,false);camera.aspect=1;camera.updateProjectionMatrix();frame(true);render(true,true,true);return posterCanvas(size,0,true);}
    finally{controls.enableDamping=false;camera.position.copy(saved.position);camera.up.copy(saved.up);controls.target.copy(saved.target);camera.aspect=saved.aspect;camera.near=saved.near;camera.far=saved.far;controls.minDistance=saved.min;controls.maxDistance=saved.max;controls.update();controls.enableDamping=saved.damping;fitOnResize=saved.fit;camera.updateProjectionMatrix();renderer.setPixelRatio(ratio);renderer.setSize(dimensions.x,dimensions.y,false);api.resumeAnimation?.(animationState);api.resize();}
  }
  function download(blob, extension) {
    const url = URL.createObjectURL(blob), anchor = document.createElement('a');
    anchor.href = url; anchor.download = ($('viewport-capture-name').value.trim() || $('viewport-title').textContent).replace(/[<>:"/\\|?*\x00-\x1f]/g,'_').slice(0,100) + extension;
    anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 30000);
  }

  async function captureShowcase(turntable) {
    if (capture || bounds().isEmpty() || !api.ready()) return;
    finishCamera();
    const controller = new AbortController(); capture = controller;
    $('viewport-capture-menu').open = false; $('viewport-capture-cancel').hidden = false;
    $('viewport-tools').inert = true; $('viewport-inspect-tools').inert = true;
    $('viewport-materials').inert = true;
    $('viewport-playback').inert = true; $('viewport-capture-menu').inert = true;
    $('viewport-fit').disabled = true; api.refreshEdits?.();
    const blenderDisabled = $('viewport-blender-btn').disabled;
    $('viewport-blender-btn').disabled = true; $('viewport-expand').disabled = true;
    const size = renderer.getSize(new THREE.Vector2()), ratio = renderer.getPixelRatio();
    const saved = {position:camera.position.clone(), up:camera.up.clone(), target:controls.target.clone(), aspect:camera.aspect,
      near:camera.near, far:camera.far, fitOnResize, enabled:controls.enabled, min:controls.minDistance, max:controls.maxDistance};
    const animationState = api.pauseAnimation?.();
    controls.enabled = false; clearHover();
    try {
      const width = turntable ? 720 : 1400;
      renderer.setPixelRatio(1); renderer.setSize(width,width,false); camera.aspect = 1; camera.updateProjectionMatrix(); frame(true);
      const offset = camera.position.clone().sub(controls.target);
      if (turntable) {
        const radius = bounds().getBoundingSphere(new THREE.Sphere()).radius;
        offset.setLength(Math.max(offset.length(),radius / Math.sin(THREE.MathUtils.degToRad(camera.fov/2))*1.12));
      }
      const header = new Uint8Array(8); header.set([65,84,67,49]); new DataView(header.buffer).setUint32(4,48,true);
      const frames = [header];
      for (let i=0; i<(turntable ? 48 : 1); i++) {
        if (controller.signal.aborted) throw new DOMException('Capture cancelled', 'AbortError');
        if (turntable) camera.position.copy(controls.target).add(offset.clone().applyAxisAngle(new THREE.Vector3(0,1,0), i*Math.PI*2/48));
        camera.lookAt(controls.target); render(true);
        const blob = await toBlob(posterCanvas(width, turntable ? 80 : 120), turntable ? 'image/webp' : 'image/png');
        if (turntable) {
          const length = new Uint8Array(4); new DataView(length.buffer).setUint32(0,blob.size,true);
          frames.push(length,blob);
        } else download(blob, '.png');
        $('viewport-status').textContent = `Capturing ${i+1} / ${turntable ? 48 : 1} frames…`;
        await new Promise(requestAnimationFrame);
      }
      if (turntable) {
        $('viewport-status').textContent = 'Encoding turntable…';
        const result = await api.fetch('/api/showcase_webp', {method:'POST', headers:{'Content-Type':'application/octet-stream'}, body:new Blob(frames), signal:controller.signal});
        if (!result.ok) throw Error((await result.json()).error || 'Turntable encoding failed');
        const blob = await result.blob();
        if (!controller.signal.aborted) download(blob, '.webp');
      }
    } catch (error) { if (error.name !== 'AbortError') api.notify(error.message, 'warning'); }
    finally {
      const damping = controls.enableDamping; controls.enableDamping = false; controls.update();
      camera.position.copy(saved.position); camera.up.copy(saved.up); controls.target.copy(saved.target);
      camera.aspect = saved.aspect; camera.near = saved.near; camera.far = saved.far;
      controls.minDistance = saved.min; controls.maxDistance = saved.max; controls.update(); controls.enableDamping = damping;
      camera.updateProjectionMatrix(); controls.enabled = saved.enabled; fitOnResize = saved.fitOnResize;
      renderer.setPixelRatio(ratio); renderer.setSize(size.x,size.y,false);
      capture = null; api.resumeAnimation?.(animationState);
      $('viewport-tools').inert = false; $('viewport-inspect-tools').inert = false;
      $('viewport-materials').inert = false;
      $('viewport-playback').inert = false; $('viewport-capture-menu').inert = false;
      $('viewport-blender-btn').disabled = blenderDisabled; $('viewport-expand').disabled = false;
      $('viewport-capture-cancel').hidden = true; api.refreshEdits?.(); refresh(); api.resize();
      $('viewport-status').textContent = controller.signal.aborted ? 'Capture cancelled' : 'Capture finished';
    }
  }
  $('viewport-poster').addEventListener('click', () => captureShowcase(false));
  $('viewport-turntable').addEventListener('click', () => captureShowcase(true));
  $('viewport-capture-cancel').addEventListener('click', () => capture?.abort());

  function clearMaterials() {
    effects.clear(); finishCamera(false);
    revision++; requestedMode++;
    for (const pair of variants.values()) { pair.standard.dispose(); pair.flat.dispose();pair.toon.dispose(); }
    for (const material of originals.values()) material.dispose();
    for (const texture of textures) texture.dispose();
    variants.clear(); originals.clear(); overlays.clear(); textures.clear(); originalTextures.clear();
    originalPromise = regionPromise = null; regions = false; updateRegions(); setComparison('edited'); clearHover();
  }
  function reset() {
    setShowcase(false);showcaseColors=null;
    setLoading(false);
    revealStart = null; reveal = 1;
    capture?.abort(); clearMaterials(); view = 'perspective'; $('viewport-view').value = view;
    fitOnResize = true; $('viewport-capture-name').value = $('mod-name-input')?.value.trim() || $('viewport-title').textContent;
    $('viewport-capture-menu').open = false; refresh();
  }
  function show() {
    if (!$('viewport-overlay').classList.contains('active')) opener = document.activeElement;
    $('viewport-overlay').classList.add('active');
    requestAnimationFrame(() => { if ($('viewport-overlay').classList.contains('active')) renderer.domElement.focus({preventScroll:true}); });
  }
  function closed() { capture?.abort(); finishCamera(false); if (opener?.isConnected) opener.focus({preventScroll:true}); }
  function keydown(event) {
    if (event.defaultPrevented || document.querySelector('#material-overlay.active')) return;
    if (event.key === 'Tab') {
      const focusable = [...$('viewport-box').querySelectorAll('button:not(:disabled), select:not(:disabled), input:not(:disabled), summary, [tabindex="0"]')].filter(el => el.checkVisibility() && !el.closest('[inert]'));
      const first = focusable[0], last = focusable.at(-1);
      if (event.shiftKey && document.activeElement === first) { last?.focus(); event.preventDefault(); }
      else if (!event.shiftKey && document.activeElement === last) { first?.focus(); event.preventDefault(); }
      return;
    }
    if (capture) return;
    if (event.ctrlKey || event.metaKey || event.altKey || event.target.closest('input,select,textarea,[contenteditable="true"]')) return;
    const key = event.key.toLowerCase(), shortcuts = {f:'viewport-fit',w:'viewport-wireframe',g:'viewport-grid'};
    if (shortcuts[key]) { event.preventDefault(); $(shortcuts[key]).click(); }
    else if (['1','3','7'].includes(key) && !bounds().isEmpty()) { event.preventDefault(); chooseView({'1':'front','3':'right','7':'top'}[key]); }
  }
  function setLoading(value) {
    assetsLoading=!!value;
    revealStart=null;reveal=1;effects.stopLoading();
    renderer.domElement.setAttribute('aria-busy',String(assetsLoading));
    $('viewport-stage').classList.toggle('vp-assets-loading',assetsLoading);
  }
  return {frame, refresh, render, reset, clearMaterials, show, closed, keydown, materialize, setLoading,cardPoster,
    retireTexture:effects.retireTexture, presentationState:()=>({...effects.state(),moving:!!cameraMove,reveal,assetsLoading,showcase:showcaseMode,grid:grid.visible}),
    resized:() => { if (fitOnResize && !capture && !cameraMove) frame(true);drawShowcase(); }, capturing:() => !!capture};
}
