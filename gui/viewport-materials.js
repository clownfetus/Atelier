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

export function emissiveColorIndex(colors = []) {
  colors = colors || [];
  // BaseGlowColor is a different effect on skin materials. The emissive mask
  // uses EmissiveColor even when the unrelated glow colour is listed first.
  const exact = colors.findIndex(color => /^emissive(?:color|tint)$/i.test((color.name || '').replace(/[^a-z0-9]/gi, '')));
  if (exact >= 0) return exact;
  const emissive = colors.findIndex(color => /emiss/i.test(color.name || ''));
  return emissive >= 0 ? emissive : colors.findIndex(color => /glow/i.test(color.name || ''));
}

export function applyEmissive(material, info, rgb) {
  material.emissive.setHex(0x000000);
  material.emissiveIntensity = 0;
  if (!material.emissiveMap) return;
  const color = rgb ?? info.colors?.[emissiveColorIndex(info.colors)]?.rgba ?? [1, 1, 1];
  material.emissive.setRGB(...color.slice(0, 3).map(value => Math.max(0, value)), THREE.LinearSRGBColorSpace);
  const scalar = info.scalars?.find(scalar => /^emissivestrength$/i.test((scalar.name || '').replace(/[^a-z0-9]/gi, '')))
    ?? info.scalars?.find(scalar => /emiss.*stre|glow.*stre/i.test(scalar.name || ''));
  const strength = scalar?.value;
  // Zero disables emission. A minimum brightness turns unused skin masks into
  // white tattoos, and also brightens effects authored with a small strength.
  material.emissiveIntensity = Number.isFinite(strength) ? Math.max(0, strength) : 1;
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
