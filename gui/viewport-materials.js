import * as THREE from 'three';

const aliases = {
  basecolor:['basecolor','base','diffuse','albedo','basecolormap','basecolortexture','diffusemap'],
  emissive:['emissive','emissivemap','emission','emissivetexture','emissivecolor'],
  opacity:['opacity','opacitymap','opacitymask','opacitytexture','alphamap','alphamask'],
};

export function textureRoles(info) {
  const roles = {...info.texture_roles};
  for (const [name,path] of Object.entries(info.textures || {})) {
    const canon = name.toLowerCase().replace(/[^a-z0-9]/g,'');
    for (const [role,names] of Object.entries(aliases)) if (!roles[role] && names.includes(canon)) roles[role]=path;
  }
  return roles;
}

export function applySurface(material, info) {
  const surface=info.surface;
  if (!surface) return;
  material.transparent=/translucent|additive|alphacomposite/i.test(surface.blend_mode || '');
  material.opacity=surface.opacity ?? 1;
  material.alphaTest=/masked/i.test(surface.blend_mode || '') ? surface.mask_clip ?? .3333 : 0;
  material.depthWrite=!material.transparent;
  material.side=surface.two_sided ? THREE.DoubleSide : THREE.FrontSide;
  material.blending=/additive/i.test(surface.blend_mode || '') ? THREE.AdditiveBlending : THREE.NormalBlending;
  material.needsUpdate=true;
}
