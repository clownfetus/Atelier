"""Derived viewport surfaces; authored material documents remain untouched."""
import math
import re

import numpy as np
from PIL import Image


def inherited_opacity(params, read_parent, find_parent, visited=()):
    """Resolve a missing opacity parameter through unambiguous MI parents only.

    Parameters stay owned by their original material, so inherited settings are
    never offered as new editable fields or written into a child document.
    """
    surface = params.get('surface') or {}
    if not re.search('translucent|additive|alphacomposite', surface.get('blend_mode', ''), re.I):
        return params
    if any(re.sub(r'[^a-z]', '', scalar.get('name', '').lower()) in ('opacity', 'opacitymultiplier')
           for scalar in params.get('scalars', [])):
        return params
    name = surface.get('parent', '')
    if not name.lower().startswith('mi_'):
        return params
    matches = [surface['parent_path']] if surface.get('parent_path') else list(dict.fromkeys(find_parent(name)))
    if len(matches) != 1:
        return params
    parent = matches[0]
    if parent.casefold() in visited or len(visited) >= 16:
        raise ValueError('Material opacity has a recursive parent chain')
    inherited = inherited_opacity(read_parent(parent), read_parent, find_parent, (*visited, parent.casefold()))
    has_opacity = any(re.sub(r'[^a-z]', '', scalar.get('name', '').lower()) in ('opacity', 'opacitymultiplier')
                      for scalar in inherited.get('scalars', []))
    inherited_surface = inherited.get('surface') or {}
    if not has_opacity and not inherited_surface.get('opacity_source'):
        return params
    opacity = inherited_surface.get('opacity')
    if not isinstance(opacity, (int, float)) or not math.isfinite(opacity):
        raise ValueError('Inherited material opacity is invalid')
    return {**params, 'surface': {**surface, 'opacity': max(0, min(1, opacity)),
                                  'opacity_source': inherited_surface.get('opacity_source') or parent}}


def eye_material(params):
    textures = params.get('textures') or {}
    return bool(textures.get('IrisBaseColor') and textures.get('ScleraBaseColor') and not textures.get('BaseColor'))


def eye_layers(params, find_texture):
    """Supply the shared eye-master defaults already used by Blender porting.

    Resolve the exact common packages; a costume's same-named texture must never
    become the default. Derived layers do not add editable source parameters.
    """
    textures = params.get('textures') or {}
    parent = (params.get('surface') or {}).get('parent', '')
    if textures.get('BaseColor') or not re.search(r'(?:^|_)eyes?(?:_|$)', parent, re.I):
        return params
    result, defaults = dict(textures), []
    for slot, name in (('IrisBaseColor', 'T_Common_Eyes_03_D'), ('ScleraBaseColor', 'T_EyeSclera_D')):
        expected = 'Characters/Common/Textures/Eyes/' + name
        if slot not in result:
            matches = [path for path in find_texture(name) if path.casefold() == expected.casefold()]
            if len(matches) == 1:
                result[slot] = matches[0]
                defaults.append(slot)
    return {**params, 'textures': result, 'eye_defaults': defaults} if defaults else params


def effect_surface(params, read_parent, find_parent, visited=()):
    """Keep inactive/unsupported animated effects from becoming opaque sheets.

    Flipbooks and layered VFX need the game's animated shader. Omitting their
    preview is explicit metadata; it never hides a section in an exported mod.
    """
    surface = params.get('surface') or {}
    if not re.search('translucent|additive|alphacomposite', surface.get('blend_mode', ''), re.I):
        return params
    textures = params.get('textures') or {}
    scalars = {row['name'].casefold(): row['value'] for row in params.get('scalars', [])}
    reason = None
    if not textures.get('BaseColor'):
        if scalars.get('alpha') == 0:
            reason = 'Disabled game effect'
        elif surface.get('parent', '').casefold() in ('m_bpstdmoani', 'm_stdadv'):
            reason = 'Animated game effect'
        elif surface.get('parent', '').lower().startswith('mi_'):
            matches = [surface['parent_path']] if surface.get('parent_path') else list(dict.fromkeys(find_parent(surface['parent'])))
            if len(matches) == 1 and matches[0].casefold() not in visited and len(visited) < 16:
                parent = effect_surface(read_parent(matches[0]), read_parent, find_parent, (*visited, matches[0].casefold()))
                reason = (parent.get('surface') or {}).get('preview_omitted')
                # A child can explicitly turn its parent's uniform alpha on.
                if reason == 'Disabled game effect' and scalars.get('alpha', 0) != 0:
                    reason = None
    return {**params, 'surface': {**surface, 'opacity': 0, 'preview_omitted': reason}} if reason else params


def eye_image(iris, sclera, params, size=512):
    """Static eye colour preview using the authored iris radius and sclera tint.

    The game adds view-dependent refraction and parallax; this composite supplies
    the missing colour layers without replacing the original editable textures.
    """
    if type(size) is not int or not 8 <= size <= 1024:
        raise ValueError('Eye preview size must be between 8 and 1024')
    scalars = {item['name']: item['value'] for item in params.get('scalars', [])}
    colors = {item['name']: item['rgba'] for item in params.get('colors', [])}
    radius = scalars.get('IrisUVRadius', .12)
    brightness = scalars.get('IrisBrightness', 1)
    tint = colors.get('ScleraTint', [1, 1, 1, 1])[:3]
    if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in [radius, brightness, *tint]):
        raise ValueError('Eye material contains invalid colour parameters')
    radius = max(0, min(.5, radius))
    def linear(pixels):
        return np.where(pixels <= .04045, pixels / 12.92, ((pixels + .055) / 1.055) ** 2.4)
    def srgb(pixels):
        pixels = np.clip(pixels, 0, 1)
        return np.where(pixels <= .0031308, pixels * 12.92, 1.055 * pixels ** (1 / 2.4) - .055)
    base = linear(np.asarray(sclera.convert('RGB').resize((size, size), Image.Resampling.BILINEAR), dtype=np.float64) / 255)
    base *= np.maximum(tint, 0)
    source = linear(np.asarray(iris.convert('RGB'), dtype=np.float64) / 255)
    uv = (np.arange(size) + .5) / size
    u, v = np.meshgrid(uv, uv)
    # Fit the complete iris image inside its authored small circle. Sampling it
    # with unmodified globe UVs displays just its dark central pupil instead.
    x = np.clip(((u - .5) / max(2 * radius, 1e-6) + .5) * source.shape[1] - .5, 0, source.shape[1] - 1)
    y = np.clip(((v - .5) / max(2 * radius, 1e-6) + .5) * source.shape[0] - .5, 0, source.shape[0] - 1)
    x0, y0 = x.astype(int), y.astype(int)
    x1, y1 = np.minimum(x0 + 1, source.shape[1] - 1), np.minimum(y0 + 1, source.shape[0] - 1)
    fx, fy = (x - x0)[..., None], (y - y0)[..., None]
    sample = (source[y0, x0] * (1 - fx) + source[y0, x1] * fx) * (1 - fy) + (source[y1, x0] * (1 - fx) + source[y1, x1] * fx) * fy
    feather = max(1 / size, .001)
    mask = np.clip((radius - np.hypot(u - .5, v - .5)) / feather + .5, 0, 1)[..., None] if radius else np.zeros((size, size, 1))
    pixels = base * (1 - mask) + sample * max(0, brightness) * mask
    return Image.fromarray(np.rint(srgb(pixels) * 255).astype('uint8'), 'RGB')
