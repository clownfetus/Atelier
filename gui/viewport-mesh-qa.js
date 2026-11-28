/**
 * Lazy-loaded Pre-Flight Mesh QA for Model Studio:
 *   1. Geometry & skin-weight health audit (triangles, vertices, sections, unweighted verts)
 *   2. Original vanilla silhouette ghost overlay (?original=1)
 *   3. Flipped-normal / backface highlight overlay
 *   4. One-click pose stress-test cycle
 */

export function analyseMeshObjects(objects = []) {
  let triangles = 0;
  let vertices = 0;
  let sections = 0;
  let bones = 0;
  let unweighted = 0;
  let skinnedMeshes = 0;

  for (const obj of objects) {
    if (!obj?.root?.visible) continue;
    const seenBones = new Set();
    obj.root.traverse(node => {
      if (node.isBone) { seenBones.add(node.uuid); return; }
      if (!node.isMesh || !node.geometry) return;
      sections++;
      const geo = node.geometry;
      const pos = geo.attributes?.position;
      if (pos) vertices += pos.count;
      if (geo.index) triangles += Math.floor(geo.index.count / 3);
      else if (pos) triangles += Math.floor(pos.count / 3);

      const weights = geo.attributes?.skinWeight;
      if (node.isSkinnedMesh && weights && weights.itemSize >= 4) {
        skinnedMeshes++;
        const arr = weights.array;
        for (let i = 0; i < weights.count; i++) {
          const base = i * weights.itemSize;
          const sum = (arr[base] || 0) + (arr[base + 1] || 0) + (arr[base + 2] || 0) + (arr[base + 3] || 0);
          if (sum < 0.01) unweighted++;
        }
      }
    });
    bones += seenBones.size;
  }

  const warnings = [];
  if (unweighted > 0) {
    warnings.push(`${unweighted.toLocaleString()} unweighted ${unweighted === 1 ? 'vertex' : 'vertices'} (may stretch in game)`);
  }
  if (triangles > 150000) {
    warnings.push(`High triangle count (${triangles.toLocaleString()} tris)`);
  }
  return {
    triangles,
    vertices,
    sections,
    bones,
    skinnedMeshes,
    unweighted,
    healthy: warnings.length === 0,
    warnings,
  };
}

export async function createMeshQa({ THREE, GLTFLoader, modelRoot, objects, primaryMeshRel, notify, onChanged }) {
  const loader = new GLTFLoader();
  let ghostGroup = null;
  let ghostMeshRel = '';
  let ghostLoading = false;
  let ghostOn = false;
  let backfaceGroup = null;
  let backfacesOn = false;
  let stressTimer = 0;
  let stressStep = 0;

  function disposeGroup(group) {
    if (!group) return;
    group.removeFromParent();
    const mats = new Set();
    group.traverse(node => {
      if (node.isMesh) {
        if (node.userData?.qaOwnsGeo) node.geometry?.dispose?.();
        const m = node.material;
        if (Array.isArray(m)) m.forEach(x => mats.add(x));
        else if (m) mats.add(m);
      }
    });
    mats.forEach(m => m.dispose?.());
  }

  function clearGhost() {
    disposeGroup(ghostGroup);
    ghostGroup = null;
    ghostMeshRel = '';
    ghostOn = false;
    ghostLoading = false;
  }

  function clearBackfaces() {
    disposeGroup(backfaceGroup);
    backfaceGroup = null;
    backfacesOn = false;
  }

  function stopStress() {
    if (stressTimer) {
      clearInterval(stressTimer);
      stressTimer = 0;
    }
    stressStep = 0;
  }

  async function setGhost(enabled) {
    const want = !!enabled;
    if (!want) {
      clearGhost();
      onChanged?.();
      return false;
    }
    const rel = primaryMeshRel?.();
    if (!rel) {
      notify?.('Load a character mesh before showing the original silhouette.', 'warning');
      return false;
    }
    if (ghostOn && ghostMeshRel === rel) return true;
    clearGhost();
    ghostLoading = true;
    ghostOn = true;
    onChanged?.();
    try {
      const gltf = await loader.loadAsync(`/api/model_gltf?game_rel=${encodeURIComponent(rel)}&original=1`);
      if (!ghostOn) {
        gltf.scene.traverse(n => { if (n.isMesh) { n.geometry?.dispose?.(); n.material?.dispose?.(); } });
        return false;
      }
      const ghostMat = new THREE.MeshBasicMaterial({
        color: 0x45ab91,
        wireframe: true,
        transparent: true,
        opacity: 0.36,
        depthWrite: false,
      });
      gltf.scene.traverse(node => {
        if (!node.isMesh) return;
        node.userData.qaOwnsGeo = true;
        node.material = ghostMat;
        node.renderOrder = 2;
        node.raycast = () => {};
      });
      ghostGroup = gltf.scene;
      ghostGroup.name = '__atelier_qa_ghost__';
      ghostMeshRel = rel;
      modelRoot.add(ghostGroup);
      ghostLoading = false;
      onChanged?.();
      return true;
    } catch (error) {
      clearGhost();
      notify?.(`Original silhouette unavailable: ${error.message}`, 'warning');
      onChanged?.();
      return false;
    }
  }

  function setBackfaces(enabled) {
    clearBackfaces();
    if (!enabled) { onChanged?.(); return false; }
    const group = new THREE.Group();
    group.name = '__atelier_qa_backfaces__';
    const mat = new THREE.MeshBasicMaterial({
      color: 0xec6a86,
      side: THREE.BackSide,
      transparent: true,
      opacity: 0.72,
      depthWrite: false,
      polygonOffset: true,
      polygonOffsetFactor: -1,
      polygonOffsetUnits: -1,
    });
    let added = 0;
    for (const obj of objects() || []) {
      if (!obj?.root?.visible) continue;
      obj.root.updateWorldMatrix(true, true);
      obj.root.traverse(node => {
        if (!node.isMesh || !node.geometry) return;
        let overlay;
        if (node.isSkinnedMesh && node.skeleton) {
          overlay = new THREE.SkinnedMesh(node.geometry, mat);
          overlay.bind(node.skeleton, node.bindMatrix);
        } else {
          overlay = new THREE.Mesh(node.geometry, mat);
        }
        overlay.matrixAutoUpdate = false;
        overlay.matrix.copy(node.matrixWorld);
        overlay.renderOrder = 3;
        overlay.raycast = () => {};
        group.add(overlay);
        added++;
      });
    }
    if (!added) {
      mat.dispose();
      onChanged?.();
      return false;
    }
    backfaceGroup = group;
    backfacesOn = true;
    modelRoot.add(group);
    onChanged?.();
    return true;
  }

  function toggleStress(selectEl, scrubEl) {
    if (stressTimer) {
      stopStress();
      onChanged?.();
      return false;
    }
    const opts = [...(selectEl?.options || [])].filter(o => o.value);
    if (!opts.length) {
      notify?.('No compatible poses available for stress testing.', 'warning');
      return false;
    }
    const nonIdle = opts.filter(o => !/idle/i.test(o.textContent || ''));
    const pool = nonIdle.length ? nonIdle.slice(0, 6) : opts.slice(0, 4);
    const step = () => {
      if (pool.length > 1) {
        const chosen = pool[stressStep % pool.length];
        if (selectEl.value !== chosen.value) {
          selectEl.value = chosen.value;
          selectEl.dispatchEvent(new Event('change'));
        }
      } else if (scrubEl && !scrubEl.closest('[hidden]')) {
        const max = Number(scrubEl.max) || 1;
        const frac = [0, 0.25, 0.5, 0.75][stressStep % 4];
        scrubEl.value = String((max * frac).toFixed(3));
        scrubEl.dispatchEvent(new Event('input'));
      }
      stressStep++;
    };
    step();
    stressTimer = setInterval(step, 1800);
    onChanged?.();
    return true;
  }

  function clearAll() {
    stopStress();
    clearGhost();
    clearBackfaces();
    onChanged?.();
  }

  return {
    analyse: () => analyseMeshObjects(objects() || []),
    setGhost,
    setBackfaces,
    toggleStress,
    clearAll,
    state: () => ({
      ghost: ghostOn,
      ghostLoading,
      backfaces: backfacesOn,
      stress: !!stressTimer,
    }),
  };
}
