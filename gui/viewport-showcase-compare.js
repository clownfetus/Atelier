/**
 * Lazy-loaded Showcase 2.0 helpers:
 *   1. Side-by-side Original vs Edited two-model comparison inside Showcase
 *   2. Client-side WebM turntable video capture (Discord / Nexus ready)
 */

export function computeDuoOffsets(boxWidth, minGap = 0.28) {
  const safeWidth = Number.isFinite(boxWidth) && boxWidth > 0 ? boxWidth : 1.0;
  const halfShift = safeWidth * 0.56 + Math.max(0.05, minGap) * 0.5;
  return {
    originalX: -halfShift,
    editedX: halfShift,
    totalSpan: halfShift * 2 + safeWidth,
  };
}

export function pickWebmMimeType(recorderCtor = globalThis.MediaRecorder) {
  if (!recorderCtor || typeof recorderCtor.isTypeSupported !== 'function') return '';
  for (const candidate of ['video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm']) {
    if (recorderCtor.isTypeSupported(candidate)) return candidate;
  }
  return '';
}

export function createShowcaseDuo({
  THREE,
  GLTFLoader,
  modelRoot,
  objects,
  primaryMeshRel,
  materials,
  textureRoles,
  applySurface,
  loadTexture,
  frame,
  notify,
  onChanged,
}) {
  const loader = new GLTFLoader();
  let active = false;
  let loading = false;
  let duoGroup = null;
  let ownedTextures = [];
  const savedPositions = new Map();

  function restoreEditedPositions() {
    for (const [root, x] of savedPositions) {
      root.position.x = x;
    }
    savedPositions.clear();
  }

  function clear() {
    active = false;
    loading = false;
    restoreEditedPositions();
    if (duoGroup) {
      duoGroup.removeFromParent();
      const mats = new Set();
      duoGroup.traverse(node => {
        if (node.isMesh) {
          node.geometry?.dispose?.();
          const m = node.material;
          if (Array.isArray(m)) m.forEach(x => mats.add(x));
          else if (m) mats.add(m);
        }
      });
      mats.forEach(m => m.dispose?.());
      duoGroup = null;
    }
    for (const tex of ownedTextures) tex.dispose?.();
    ownedTextures = [];
    onChanged?.();
  }

  async function enable() {
    const rel = primaryMeshRel?.();
    if (!rel) {
      notify?.('Load a character mesh before comparing side by side.', 'warning');
      return false;
    }
    clear();
    active = true;
    loading = true;
    onChanged?.();

    const visibleObjects = (objects() || []).filter(o => o?.root?.visible);
    const box = new THREE.Box3();
    for (const o of visibleObjects) {
      o.root.updateMatrixWorld(true);
      box.expandByObject(o.root);
    }
    const width = box.isEmpty() ? 1.0 : box.getSize(new THREE.Vector3()).x;
    const { originalX, editedX } = computeDuoOffsets(width);

    try {
      const gltf = await loader.loadAsync(`/api/model_gltf?game_rel=${encodeURIComponent(rel)}&original=1`);
      if (!active) {
        gltf.scene.traverse(n => { if (n.isMesh) { n.geometry?.dispose?.(); n.material?.dispose?.(); } });
        return false;
      }

      const matData = materials()?.data || {};
      const byName = new Map();
      for (const [slotName, info] of Object.entries(matData)) {
        byName.set(slotName.toLowerCase(), info);
      }

      const texTasks = [];
      gltf.scene.traverse(node => {
        if (!node.isMesh) return;
        const slotList = Array.isArray(node.material) ? node.material : [node.material];
        const nextMats = slotList.map(origMat => {
          const name = (origMat?.name || '').toLowerCase();
          const info = byName.get(name);
          const std = new THREE.MeshStandardMaterial({
            color: 0xffffff,
            roughness: 0.55,
            metalness: 0.08,
            vertexColors: false,
          });
          if (info) {
            applySurface?.(std, info);
            const roles = textureRoles?.(info) || {};
            if (roles.basecolor && loadTexture) {
              texTasks.push(
                loadTexture(`/api/texture_png?game_rel=${encodeURIComponent(roles.basecolor)}&original=1`)
                  .then(tex => {
                    if (!active) { tex.dispose(); return; }
                    tex.colorSpace = THREE.SRGBColorSpace;
                    tex.flipY = false;
                    tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
                    ownedTextures.push(tex);
                    std.map = tex;
                    std.needsUpdate = true;
                  })
                  .catch(() => {})
              );
            }
            if (roles.emissive && loadTexture) {
              texTasks.push(
                loadTexture(`/api/texture_png?game_rel=${encodeURIComponent(roles.emissive)}&original=1`)
                  .then(tex => {
                    if (!active) { tex.dispose(); return; }
                    tex.colorSpace = THREE.SRGBColorSpace;
                    tex.flipY = false;
                    tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
                    ownedTextures.push(tex);
                    std.emissiveMap = tex;
                    std.emissive.setHex(0xffffff);
                    std.emissiveIntensity = 1;
                    std.needsUpdate = true;
                  })
                  .catch(() => {})
              );
            }
          }
          origMat?.dispose?.();
          return std;
        });
        node.material = Array.isArray(node.material) ? nextMats : nextMats[0];
        node.raycast = () => {};
      });

      for (const o of visibleObjects) {
        if (!savedPositions.has(o.root)) savedPositions.set(o.root, o.root.position.x);
        o.root.position.x = savedPositions.get(o.root) + editedX;
      }

      duoGroup = gltf.scene;
      duoGroup.name = '__atelier_showcase_duo__';
      duoGroup.position.x = originalX;
      modelRoot.add(duoGroup);
      await Promise.allSettled(texTasks);
      if (!active) { clear(); return false; }
      loading = false;
      frame?.(true, true);
      onChanged?.();
      notify?.('Side-by-side comparison ready (Original left · Edited right)', 'success');
      return true;
    } catch (error) {
      clear();
      notify?.(`Side-by-side comparison unavailable: ${error.message}`, 'warning');
      return false;
    }
  }

  return {
    toggle: async () => (active ? (clear(), frame?.(true, true), false) : enable()),
    clear,
    state: () => ({ active, loading }),
  };
}

export async function recordTurntableWebm({ width = 720, totalFrames = 60, fps = 24, drawFrame, signal }) {
  const mimeType = pickWebmMimeType();
  if (!mimeType) throw new Error('WebM video recording is not supported in this browser.');
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = width;
  const ctx = canvas.getContext('2d');
  const stream = canvas.captureStream(fps);
  const chunks = [];
  const recorder = new MediaRecorder(stream, { mimeType, videoBitsPerSecond: 4_500_000 });
  const finished = new Promise((resolve, reject) => {
    recorder.ondataavailable = e => { if (e.data && e.data.size > 0) chunks.push(e.data); };
    recorder.onerror = e => reject(e.error || new Error('Video recording failed'));
    recorder.onstop = () => resolve(new Blob(chunks, { type: mimeType }));
  });
  const onAbort = () => { if (recorder.state !== 'inactive') recorder.stop(); };
  signal?.addEventListener('abort', onAbort, { once: true });
  recorder.start();
  const frameMs = Math.round(1000 / fps);
  try {
    for (let i = 0; i < totalFrames; i++) {
      if (signal?.aborted) throw new DOMException('Capture cancelled', 'AbortError');
      await drawFrame(ctx, i, totalFrames);
      await new Promise(resolve => setTimeout(resolve, frameMs));
    }
    if (recorder.state !== 'inactive') recorder.stop();
    const blob = await finished;
    if (signal?.aborted) throw new DOMException('Capture cancelled', 'AbortError');
    return blob;
  } finally {
    signal?.removeEventListener('abort', onAbort);
    stream.getTracks().forEach(t => t.stop());
  }
}
