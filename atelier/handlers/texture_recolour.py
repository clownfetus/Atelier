"""Recolour a part by baking a colour into its base-colour texture with a blend mode.

The game's shader applies a material colour one fixed way (it multiplies over the map), so any
other blend has to be baked into the texture for the game to show what Atelier shows. The result
is an ordinary edited PNG in the project: it ships, compares and restores like any texture edit.

Every bake starts from the game's original texture, never from the project's edited copy, so
adjusting a recolour replaces it instead of stacking on top of the last one. The recipe is kept in
project.json with the PNG's stamp; a PNG that no longer matches its recipe was changed some other
way (painted, replaced) and is not overwritten without the caller saying so.

Blend formulas follow the W3C Compositing and Blending spec, in sRGB, as image editors apply them.
An optional curve then remaps the result's brightness, the same on every channel, through a monotone
cubic (Fritsch-Carlson) so it never overshoots between points; gui/viewport-recolour.js draws it
with the same maths.
"""
import hashlib
import os
import re

import numpy as np

MODES = ("multiply", "screen", "overlay", "soft_light", "hue", "color")
PREVIEW_SIZE = 1024
MAX_CURVE_POINTS = 8
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def recipe(colour, mode, strength, curve=None):
    """A validated recipe, or ValueError naming what is wrong. A curve that changes nothing is left out."""
    if not isinstance(colour, str) or not _HEX.match(colour):
        raise ValueError("Choose a colour as #RRGGBB")
    if mode not in MODES:
        raise ValueError("Choose a blend mode")
    if isinstance(strength, bool) or not isinstance(strength, (int, float)) or not 0 <= strength <= 1:
        raise ValueError("Strength runs from 0 to 1")
    spec = {"colour": colour.upper(), "mode": mode, "strength": round(float(strength), 3)}
    points = _curve(curve)
    if points:
        spec["curve"] = points
    return spec


def _number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 1


def _curve(points):
    if points is None:
        return None
    if not isinstance(points, list) or not 2 <= len(points) <= MAX_CURVE_POINTS:
        raise ValueError(f"A curve has 2 to {MAX_CURVE_POINTS} points")
    if not all(isinstance(p, (list, tuple)) and len(p) == 2 and all(map(_number, p)) for p in points):
        raise ValueError("Curve points run from 0 to 1")
    points = [[round(float(x), 3), round(float(y), 3)] for x, y in points]
    xs = [x for x, _ in points]
    if xs[0] != 0 or xs[-1] != 1 or any(b <= a for a, b in zip(xs, xs[1:])):
        raise ValueError("Curve points run left to right from 0 to 1")
    return None if all(x == y for x, y in points) else points


def curve_lut(points):
    """256 output levels (0..1) for the curve through `points`."""
    xs = np.array([p[0] for p in points], dtype=np.float64)
    ys = np.array([p[1] for p in points], dtype=np.float64)
    n = len(xs)
    d = np.diff(ys) / np.diff(xs)
    m = np.empty(n)
    m[0], m[-1] = d[0], d[-1]
    m[1:-1] = np.where(d[:-1] * d[1:] > 0, (d[:-1] + d[1:]) / 2, 0)
    for k in range(n - 1):
        if d[k] == 0:
            m[k] = m[k + 1] = 0
            continue
        a, b = m[k] / d[k], m[k + 1] / d[k]
        if a * a + b * b > 9:
            t = 3 / np.sqrt(a * a + b * b)
            m[k], m[k + 1] = t * a * d[k], t * b * d[k]
    x = np.linspace(0, 1, 256)
    k = np.clip(np.searchsorted(xs, x, side="right") - 1, 0, n - 2)
    h = xs[k + 1] - xs[k]
    t = (x - xs[k]) / h
    y = ((2 * t ** 3 - 3 * t ** 2 + 1) * ys[k] + (t ** 3 - 2 * t ** 2 + t) * h * m[k]
         + (3 * t ** 2 - 2 * t ** 3) * ys[k + 1] + (t ** 3 - t ** 2) * h * m[k + 1])
    return np.clip(y, 0, 1).astype(np.float32)


def _lum(c):
    return c[..., 0:1] * .3 + c[..., 1:2] * .59 + c[..., 2:3] * .11


def _clip(c):
    l = _lum(c)
    n = c.min(axis=-1, keepdims=True)
    x = c.max(axis=-1, keepdims=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        c = np.where(n < 0, l + (c - l) * l / np.where(l - n == 0, 1, l - n), c)
        c = np.where(x > 1, l + (c - l) * (1 - l) / np.where(x - l == 0, 1, x - l), c)
    return c


def _set_lum(c, l):
    return _clip(c + (l - _lum(c)))


def _sat(c):
    return c.max(axis=-1, keepdims=True) - c.min(axis=-1, keepdims=True)


def _set_sat(c, s):
    # Scale the colour's spread to s while keeping its channel order (the spec's min/mid/max form).
    n = c.min(axis=-1, keepdims=True)
    spread = c.max(axis=-1, keepdims=True) - n
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(spread > 0, (c - n) * s / np.where(spread == 0, 1, spread), 0.0)


def blend(backdrop, colour, mode):
    """Blend one colour over an (H, W, 3) array in 0..1."""
    b = backdrop
    s = np.broadcast_to(np.asarray(colour, dtype=np.float32), b.shape)
    if mode == "multiply":
        return b * s
    if mode == "screen":
        return b + s - b * s
    if mode == "overlay":
        return np.where(b <= .5, 2 * b * s, 1 - 2 * (1 - b) * (1 - s))
    if mode == "soft_light":
        d = np.where(b <= .25, ((16 * b - 12) * b + 4) * b, np.sqrt(b))
        return np.where(s <= .5, b - (1 - 2 * s) * b * (1 - b), b + (2 * s - 1) * (d - b))
    if mode == "hue":
        return _set_lum(_set_sat(s, _sat(b)), _lum(b))
    if mode == "color":
        return _set_lum(s, _lum(b))
    raise ValueError(mode)


def bake(image, spec):
    """The recoloured copy of a PIL image. Alpha is kept as it was."""
    from PIL import Image
    rgba = np.asarray(image.convert("RGBA"), dtype=np.float32) / 255
    rgb, alpha = rgba[..., :3], rgba[..., 3:]
    colour = [int(spec["colour"][i:i + 2], 16) / 255 for i in (1, 3, 5)]
    mixed = rgb + (np.clip(blend(rgb, colour, spec["mode"]), 0, 1) - rgb) * spec["strength"]
    if spec.get("curve"):
        mixed = curve_lut(spec["curve"])[np.rint(mixed * 255).astype(np.intp)]
    out = np.concatenate([mixed, alpha], axis=-1)
    return Image.fromarray(np.rint(out * 255).astype(np.uint8), "RGBA")


def preview(source_png, spec, cache_dir, size=PREVIEW_SIZE):
    """Path of a reduced-size preview, cached by source stamp and recipe."""
    from PIL import Image
    st = os.stat(source_png)
    key = hashlib.sha256(repr((os.path.realpath(source_png), st.st_mtime_ns, st.st_size, size,
                               sorted(spec.items()))).encode()).hexdigest()
    os.makedirs(cache_dir, exist_ok=True)
    target = os.path.join(cache_dir, key + ".png")
    if not os.path.isfile(target):
        with Image.open(source_png) as source:
            source.thumbnail((size, size), Image.Resampling.LANCZOS)
            result = bake(source, spec)
        temporary = target + ".tmp"
        result.save(temporary, "PNG", compress_level=1)
        os.replace(temporary, target)
        _trim(cache_dir, keep=target)
    return target


def _trim(cache_dir, keep, limit=24):
    files = sorted((os.path.join(cache_dir, f) for f in os.listdir(cache_dir) if f.endswith(".png")),
                   key=lambda p: os.path.getmtime(p), reverse=True)
    for path in files[limit:]:
        if path != keep:
            try:
                os.remove(path)
            except OSError:
                pass


def stamp(path):
    st = os.stat(path)
    return [st.st_mtime_ns, st.st_size]


def save(source_png, target_png, spec):
    """Write the full-size bake to the project PNG atomically; returns its stamp."""
    from PIL import Image
    with Image.open(source_png) as source:
        result = bake(source, spec)
    os.makedirs(os.path.dirname(target_png), exist_ok=True)
    temporary = target_png + ".recolour.tmp"
    result.save(temporary, "PNG")
    os.replace(temporary, target_png)
    return stamp(target_png)
