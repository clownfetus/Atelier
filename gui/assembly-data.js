// Relationship identity is a package path, never a display label or basename.
export const assetKey = path => String(path || '').replaceAll('\\', '/').toLowerCase();

export function verifiedBinding(info) {
  return !!info?.game_rel && info.mapping_via === 'imports' && !info.mapping_error && !info.material_set_override;
}

export function bindingNotice(info) {
  if (info?.material_set_override) return 'Preview material set. This counterpart was matched by name; its mesh assignment is unverified.';
  if (info?.mapping_error) return info.mapping_error;
  if (info?.mapping_via === 'name') return 'Material matched by name. The mesh’s package reference could not be verified.';
  return 'The material reference for this surface is unavailable.';
}

export function boundTextures(info) {
  if (!verifiedBinding(info)) return [];
  // These records retain the exact parameter, package, custom-image URL and type.
  return (info.texture_sources || []).filter(source => source.game_rel && source.url && !source.inferred);
}

export function relatedMaterials(data, path) {
  const key = assetKey(path);
  return Object.keys(data).filter(name => verifiedBinding(data[name]) && assetKey(data[name].game_rel) === key);
}

export function textureUsers(data, source) {
  const key = assetKey(source?.game_rel);
  if (!key) return [];
  return Object.keys(data).filter(name => boundTextures(data[name]).some(texture => assetKey(texture.game_rel) === key));
}

// A single material can appear in multiple primitives or multiple geometry groups.
// Keep the clicked group distinct even when all of them sample the same material.
export function modelSections(objects, metadata) {
  const sections = [];
  for (const [index, owner] of objects.entries()) {
    if (!owner.root.visible || owner.loaded === false) continue;
    owner.root.traverseVisible(mesh => {
      if (!mesh.isMesh) return;
      const geometry = mesh.geometry;
      const count = geometry.index?.count ?? geometry.attributes.position?.count ?? 0;
      const groups = Array.isArray(mesh.material) ? geometry.groups : [{start:0, count, materialIndex:0}];
      for (const [groupIndex, group] of groups.entries()) {
        const material = Array.isArray(mesh.material) ? mesh.material[group.materialIndex] : mesh.material;
        if (!material || material.userData?.heldDuplicate) continue;
        const start = Math.max(group.start, geometry.drawRange.start);
        const end = Math.min(group.start + group.count, geometry.drawRange.start + geometry.drawRange.count, count);
        if (end <= start) continue;
        sections.push({id:`${mesh.uuid}:${groupIndex}`, owner, object:mesh, material, name:material.name,
          mesh_game_rel:metadata[index]?.game_rel, groupIndex, start, end, triangles:Math.floor((end-start)/3),
          face:{materialIndex:group.materialIndex}, faceIndex:Math.floor(start/3)});
      }
    });
  }
  return sections;
}

export function hitSection(sections, hit) {
  if (!hit) return null;
  return sections.find(section => section.object === hit.object && section.face.materialIndex === (hit.face?.materialIndex || 0)
    && hit.faceIndex * 3 >= section.start && hit.faceIndex * 3 < section.end) || null;
}
