"""MR dyeing / ID-mask preview.

Skins are recoloured by a "dyeing" system, not by editing the diffuse. The material's DyeingTexture
slot holds a T_*_ColorID mask whose ALPHA is a REGION INDEX quantised into 7 steps of 255/7 (~36.43)
-> the MI's "Region 1..7 - ColorA/ColorB/ColorGChannel/ColorBChannel" params. It ships DXT5
(independent alpha block), Filter=TF_Nearest and SRGB=false so a sample snaps to an exact step.

The shader HUE-CORRECTS the diffuse rather than replacing it, so the composite here keeps the
diffuse's relative light-and-shade and takes colour from the dye params. Verified against the game
by the user on 1060300 (Coastal Kumiho).

Preview only — nothing here ships into a mod. Region colours are ordinary VectorParameterValues and
are edited/shipped through the normal material path (material.save_material / stage_material).
"""
import os, json, collections
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from atelier.config import _CACHE, PAKS, WORK_IMPORT_ROOT, project_base
from atelier.tools import uat
from atelier.handlers import material as M
from atelier.handlers import texture as TX
from atelier.paths import pak_game_path

STEP = 255.0 / 7.0            # alpha per region step; region = round(alpha / STEP), 0 = undyed
DYE_BASE = 0.35               # OPTION-3 fixed base (t12 stand-in): scales the region toward [0,1]
                             # before clip+gamma so HDR params don't blow white. Tune 0.4–0.8.
MASK_SLOT = "DyeingTexture"
DIFF_SLOT = "BaseColor"
_CACHE_DYE = os.path.join(_CACHE, "dye")

# ── ID-mask / colour-region overlay ───────────────────────────────────────────────────────────
# "Which colour do I edit to change THIS part?" is the most-asked question in the corpus (muimifu,
# finngmin, paillettelebeau, norskpl, leagueofthearcane), and the answers on record are "eyeball the
# ColorID defaults" and "trial and error a LOT". The mask already answers it exactly: `reg` below is
# a per-texel region index, and each index is one "Region N - Color*" parameter on the MI. Colouring
# `reg` by index instead of by dye parameter turns that into a labelled picture.
#
# Preview only, like everything else in this module — the overlay is never staged into a mod.
REGION_COLORS = {
    0: (142, 142, 147),   # undyed — the dye system does not touch these texels at all
    1: (255,  59,  48),
    2: (255, 149,   0),
    3: (255, 214,  10),
    4: ( 52, 199,  89),
    5: ( 50, 173, 230),
    6: (175,  82, 222),
    7: (255,  45, 149),
}
OVERLAY_MIX = 0.55            # floor of the diffuse shading multiplier (0.55..1.0): how much
                              # texture detail survives without washing the region hue out


def region_hex(idx):
    r, g, b = REGION_COLORS.get(int(idx), (200, 200, 200))
    return "#%02x%02x%02x" % (r, g, b)


def dye_slots(game_rel):
    """(mask_game_rel, diffuse_game_rel) for a dyeing MI, or (None, None)."""
    try:
        d = json.load(open(M.mat_json(game_rel), encoding="utf-8-sig"))
    except Exception:
        return None, None
    tex = M._mat_textures(d) or {}
    return tex.get(MASK_SLOT), tex.get(DIFF_SLOT)


def is_dyeable(game_rel):
    return bool(dye_slots(game_rel)[0])


def dye_regions(game_rel):
    """{region_idx: {'ColorA': rgba, 'ColorB': rgba, 'ColorGChannel': rgba, ...}} from the MI."""
    r = M.read_material(game_rel)
    out = collections.defaultdict(dict)
    for c in (r.get("colors") or []):
        n = c.get("name") or ""
        if not n.startswith("Region "):
            continue
        try:
            idx = int(n.split()[1])
        except Exception:
            continue
        out[idx][n.split("-", 1)[1].strip()] = c["rgba"]
    return dict(out)


_IMCACHE = {}     # game_rel -> (stamp, PIL image). Live colour picking re-composites on every drag;
                  # decoding both textures each time costs ~1.3s and makes it unusable, while the
                  # numpy composite itself is milliseconds. Hold the decoded sources.


def edited_png(game_rel):
    """The user's own PNG for this texture in the active project, or None.

    The preview has to start from this, not from the vanilla texture. finngmin's whole complaint is
    that a painted texture never shows — "the material overlay trumps the texture PNG" — and a
    preview built from vanilla reproduces that complaint instead of answering it: paint the
    diffuse, and the dye preview would keep showing the skin you did not edit."""
    from atelier.config import project_base_legacy
    for base in (project_base(game_rel), project_base_legacy(game_rel)):
        png = base + ".png"
        if os.path.exists(png):
            return png
    return None


def _stamp(game_rel):
    """Cache identity for a decoded source: which file it came from and when it last changed."""
    png = edited_png(game_rel)
    if not png:
        return ("vanilla",)
    try:
        return ("edit", png, int(os.path.getmtime(png)))
    except OSError:
        return ("edit", png, 0)


def _tex_image(game_rel):
    """Extract + decode a texture to a PIL image. decode_dds first: MR strips the top mip, and
    UAssetTool maps mip[i]->DataResource[i], so with mip0 absent it degrades to the 4x4 tail."""
    stamp = _stamp(game_rel)
    hit = _IMCACHE.get(game_rel)
    if hit is not None and hit[0] == stamp:
        return hit[1]
    im = _tex_image_uncached(game_rel)
    if im is not None:
        _IMCACHE[game_rel] = (stamp, im)
    return im

def _tex_image_uncached(game_rel):
    import atelier.asset_cache as _ac
    from atelier.tools import tex_semaphore
    # Same swarm hazard as the viewport's albedo path: dye previews extract+decode a mask AND a
    # diffuse, fired concurrently. Gate the heavy work so we don't pile up UAssetTool processes /
    # full-res textures in RAM (the thing that crashes the viewport on big skins).
    edited = edited_png(game_rel)
    if edited:
        im = Image.open(edited); im.load()
        return im
    with tex_semaphore:
        cb = TX.ensure_work_base(game_rel)      # retoc or UAssetTool per host; caches the result
        if not cb or not os.path.exists(cb + ".uasset"):
            return None
        base = project_base(game_rel, _CACHE_DYE)
        os.makedirs(os.path.dirname(base), exist_ok=True)
        p = TX.decode_dds(base, cb)
        if not p:
            TX.decode_png(base, cb)
            p = base + ".png"
        if not os.path.exists(p):
            return None
        im = Image.open(p); im.load()
        return im


def composite(mask_im, diff_im, regions, size=1024):
    """The verified recipe:
         region = round(alpha / (255/7))
         target = lerp(ColorA, ColorB, R), blended toward ColorGChannel by G and ColorBChannel by B
         shade  = diffuse_luminance / that region's MEAN diffuse luminance
         out    = (target * shade) gamma-encoded ; region 0 = diffuse untouched

    The per-region normalisation is the crux. Multiplying the dye by the diffuse's ABSOLUTE
    luminance comes out far too dark (region 1's diffuse mean is 0.288 -> crushes the dye to 29%);
    normalising per region makes the diffuse contribute only its DEVIATION, so folds/weave/AO stay
    while the region's overall brightness comes from the dye where it belongs.
    """
    mask = np.asarray(mask_im.convert("RGBA").resize((size, size), Image.NEAREST), dtype=np.float32)
    diff = np.asarray(diff_im.convert("RGB").resize((size, size), Image.BILINEAR), dtype=np.float32)
    reg = np.rint(mask[..., 3] / STEP).astype(np.int32)
    R, G, B = mask[..., 0] / 255.0, mask[..., 1] / 255.0, mask[..., 2] / 255.0
    lum = (0.2126 * diff[..., 0] + 0.7152 * diff[..., 1] + 0.0722 * diff[..., 2]) / 255.0
    diff_lin = (diff / 255.0) ** 2.2                    # sRGB PNG -> linear, for the HDR-dye branch
    # NOTE: the shader (base pass PS 671431, target 5) proves BaseColor = Saturate(dye_color *
    # diffuse.rgb) per-channel in LINEAR space — see reference-mr-dyeing-idmask-system. But the
    # shader's `dye_color` is built by an un-reversed chain (region-blend lerp + fresnel Exp +
    # MC_Shade + a strength gain, lines ~1440-1483) and is brighter/HDR-boosted vs the raw ColorA/B
    # we read; feeding raw ColorA into `dye*diffuse` comes out too dark (Kumiho/Head). Until that
    # chain is reversed, keep the empirically-tuned alpha-region composite (Kumiho verified correct):
    # HDR-AWARE: accumulate LINEAR values (which can exceed 1 for HDR dye) and only collapse to
    # displayable range at the very end via an ACES tonemap. Hard-clipping mid-pipeline (the old bug)
    # killed every value >1 to pure white before anything could normalise it. Region 0 base is the
    # sRGB texture -> linearise it so it's in the same space as the dyed regions.
    out = (diff / 255.0) ** 2.2                          # ALPHA 0 = base texture (linearised)
    vec = lambda v: np.array((v or [1, 1, 1, 1])[:3], dtype=np.float32)
    # ── decide the shading branch ONCE PER MATERIAL, not per region ──────────────────────────────
    # A per-region branch created visible SEAMS: two same-hue regions straddling the cutoff render in
    # different modes → two shades where there should be one (e.g. 1060100 Equip_02 R1 peak1.25→dark
    # vs R2 peak0.72→norm, both rose). Regions of one material share a surface type, so pick the mode
    # for the whole material: DARK if ANY region's dye is HDR, or the material's overall base is dark.
    mat_peak = 0.0
    for _i, _p in regions.items():
        if _i == 0:
            continue
        mm = reg == _i
        if mm.any():
            mat_peak = max(mat_peak, float(vec(_p.get("ColorA")).max()), float(vec(_p.get("ColorB")).max()))
    mat_mean = float(lum[reg > 0].mean()) if (reg > 0).any() else 1.0
    # peak cutoff 1.6 (not 1.2): Kumiho fabric has one HDR accent at peak 1.5 and must stay NORMAL
    # (mint); metallic Ultron parts peak ~1.7+ and go DARK. mat_mean catches genuinely dark bases.
    material_dark = (mat_mean < 0.25) or (mat_peak > 1.6)
    for idx, prm in regions.items():
        if idx == 0:
            continue
        m = reg == idx
        if not m.any():
            continue
        ca, cb = vec(prm.get("ColorA")), vec(prm.get("ColorB"))
        tgt = ca + (cb - ca) * R[m][:, None]
        if "ColorGChannel" in prm:
            cg = vec(prm["ColorGChannel"]); tgt = tgt + (cg - tgt) * G[m][:, None]
        if "ColorBChannel" in prm:
            cbb = vec(prm["ColorBChannel"]); tgt = tgt + (cbb - tgt) * B[m][:, None]
        # Shader law: BaseColor = Saturate(region_color * t12). t12 back-solves per skin:
        #  - LDR dye (<=~1.5, artist picked the final albedo): t12 = diffuse/region_avg (~white on
        #    average) → the region's AVERAGE output IS the dye colour, with per-pixel shading from the
        #    diffuse's deviation. Mean-normalised. (Coastal Kumiho verified.)
        #  - HDR dye (>~1.5, an impossible albedo → it's a MULTIPLIER for the absolute dark diffuse):
        #    t12 = the diffuse RGB as-is. region*dark_diffuse lands at a sane dark albedo, and using
        #    the diffuse's own RGB keeps skin/base colour (Head's pink) instead of greying it.
        # The dye REPLACES colour — the region param's RGB is the hue; the diffuse supplies only
        # SHADING as GREYSCALE (never its own RGB, which would bleed the base skin's colours in — e.g.
        # Kumiho's orange _D would muddy the green). Discriminate the shading by DIFFUSE DARKNESS
        # (not dye HDR-ness — Head & Phantom are both HDR yet Head=light, Phantom=dark):
        # OPTION 3: a fixed base multiplier standing in for the un-found t12 base. HDR region params
        # (up to 10) otherwise clip every channel to 1 and gamma washes them white; scaling the region
        # by DYE_BASE brings it toward [0,1] BEFORE gamma so the hue survives instead of blowing out.
        # Greyscale shading factor (LINEAR, may leave the product >1 for HDR dye — that's fine now,
        # the tonemap handles it). Dark/metallic base multiplies the region down absolutely; a normal
        # neutral base mean-normalises so the region AVERAGE == the dye colour.
        mean = float(lum[m].mean())
        # ONE branch for the whole material (see material_dark above) so regions never seam.
        if material_dark:
            shade = lum[m][:, None] ** 2.2                          # absolute, linearised
        else:
            shade = np.clip(lum[m] / mean, 0.0, 1.3)[:, None] * DYE_BASE
        out[m] = tgt * shade                                        # LINEAR, unclamped (HDR ok)
    # collapse HDR -> displayable: ACES filmic tonemap (Narkowicz), then sRGB gamma. This rolls the
    # highlights off smoothly instead of the old hard clip that flattened everything >1 to white.
    x = np.maximum(out, 0.0)
    a, b, c, d, e = 2.51, 0.03, 2.43, 0.59, 0.14
    tm = np.clip((x * (a * x + b)) / (x * (c * x + d) + e), 0.0, 1.0)
    srgb = tm ** (1 / 2.2)
    return Image.fromarray(np.clip(srgb * 255.0, 0, 255).astype(np.uint8), "RGB")


def dye_preview(game_rel, overrides=None, size=1024, out_path=None, dye_off=False):
    """Composite a dye preview. `overrides` = {region_idx: {param: rgba}} applied over the MI's own
    values so the UI can preview an unsaved colour pick. Returns the PNG path.

    dye_off previews what stage_dye_off() ships: no dyeing at all, the BaseColor exactly as it is
    on disk. That is the whole point of the toggle, so the preview has to show it — a "disabled"
    checkbox next to a still-dyed picture is the same non-answer finngmin already has."""
    mask_gr, diff_gr = dye_slots(game_rel)
    if not mask_gr:
        raise RuntimeError("not a dyeing material (no %s slot): %s" % (MASK_SLOT, game_rel))
    mask_im = _tex_image(mask_gr)
    if mask_im is None:
        raise RuntimeError("could not decode the ColorID mask: " + mask_gr)
    diff_im = _tex_image(diff_gr) if diff_gr else None
    if diff_im is None:                                  # dye-only preview if the diffuse is missing
        diff_im = Image.new("RGB", mask_im.size, (128, 128, 128))
    if dye_off:
        im = diff_im.convert("RGB").resize((size, size), Image.BILINEAR)
        out = out_path or (project_base(game_rel, os.path.join(_CACHE_DYE, "undyed")) + ".png")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        im.save(out)
        return out
    regions = dye_regions(game_rel)
    for k, v in (overrides or {}).items():
        regions.setdefault(int(k), {}).update(v)
    im = composite(mask_im, diff_im, regions, size=size)
    out = out_path or (project_base(game_rel, os.path.join(_CACHE_DYE, "preview")) + ".png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    im.save(out)
    return out


def dye_info(game_rel):
    """What the UI needs: which regions the mask actually uses + their current colours."""
    mask_gr, diff_gr = dye_slots(game_rel)
    if not mask_gr:
        return {"dyeable": False}
    regions = dye_regions(game_rel)
    used = {}
    mask_im = _tex_image(mask_gr)
    if mask_im is not None:
        a = np.asarray(mask_im.convert("RGBA").resize((256, 256), Image.NEAREST))[..., 3]
        reg = np.rint(a.astype(np.float32) / STEP).astype(np.int32)
        vals, cnts = np.unique(reg, return_counts=True)
        used = {int(v): int(c) for v, c in zip(vals, cnts)}
    total = sum(used.values()) or 1
    return {"dyeable": True, "mask": mask_gr, "diffuse": diff_gr,
            "regions": {str(k): v for k, v in sorted(regions.items())},
            "used": {str(k): v for k, v in sorted(used.items())},
            # legend for the region overlay: the colour each index is drawn in, and how much of the
            # texture it covers — so the panel can be built from this one call.
            "overlay":  {str(k): region_hex(k) for k in sorted(used)},
            "coverage": {str(k): round(100.0 * v / total, 1) for k, v in sorted(used.items())},
            "step": STEP}


def _label_font(size):
    try:
        return ImageFont.load_default(size=size)      # Pillow >= 10.1
    except TypeError:
        return ImageFont.load_default()               # older Pillow: fixed tiny bitmap font


_LABEL_GRID = 96       # coarse grid the blob search runs on — full res is far more than it needs
_LABEL_MIN_GAP = 34    # px between two numbers before they are treated as colliding


def _blobs(cell):
    """Connected components of a coarse boolean grid, biggest first: [(size, cy, cx)].

    Pure numpy/BFS rather than scipy.label — one dependency this project does not have, for a grid
    this small. 4-connected is enough: the grid is a downsample, so diagonal-only touches are noise.
    """
    h, w = cell.shape
    seen = np.zeros_like(cell, dtype=bool)
    out  = []
    ys, xs = np.nonzero(cell)
    for y0, x0 in zip(ys.tolist(), xs.tolist()):
        if seen[y0, x0]:
            continue
        stack, pts = [(y0, x0)], []
        seen[y0, x0] = True
        while stack:
            y, x = stack.pop()
            pts.append((y, x))
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ny, nx = y + dy, x + dx
                if 0 <= ny < h and 0 <= nx < w and cell[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        arr = np.array(pts, dtype=np.float32)
        out.append((len(pts), float(arr[:, 0].mean()), float(arr[:, 1].mean())))
    out.sort(key=lambda b: -b[0])
    return out


def _label_anchor(reg, idx, placed):
    """Where to print region `idx`'s number, or None if it has no texels.

    Two failure modes this has to avoid, both seen on real masks (White Fox 1060300 Equip_01):

      * the whole region's centroid can fall OUTSIDE the region — a C-shaped belt or a sleeve trim
        would get its number printed on the neighbouring part, which answers the question wrongly;
      * two INTERLEAVED regions (that skin's leaf pattern, regions 3 and 4) share a centroid area,
        so their numbers land 5px apart and the one drawn second hides the other entirely.

    So: take the region's largest connected BLOB, not the region as a whole, and skip a blob whose
    label would collide with one already placed. Falling back to the plain centroid at the end means
    a number is always drawn — a missing one is worse than a crowded one.
    """
    m = reg == idx
    if not m.any():
        return None
    h, w = reg.shape
    step = max(1, min(h, w) // _LABEL_GRID)
    cell = m[::step, ::step]
    for _size, cy, cx in _blobs(cell)[:6]:              # biggest blobs first
        y, x = cy * step, cx * step
        ys, xs = np.nonzero(m)
        d = (ys - y) ** 2 + (xs - x) ** 2               # snap onto a texel of this region
        i = int(np.argmin(d))
        px, py = int(xs[i]), int(ys[i])
        if all((px - qx) ** 2 + (py - qy) ** 2 >= _LABEL_MIN_GAP ** 2 for qx, qy in placed):
            return px, py
    ys, xs = np.nonzero(m)
    cy, cx = float(ys.mean()), float(xs.mean())
    d = (ys - cy) ** 2 + (xs - cx) ** 2
    i = int(np.argmin(d))
    return int(xs[i]), int(ys[i])


def region_overlay(game_rel, size=1024, out_path=None, numbers=True):
    """Render the ColorID mask as a labelled region map and return the PNG path.

    Each region index gets a fixed colour from REGION_COLORS, laid over the diffuse's own greyscale
    shading so folds and seams still read, with the region number printed inside each region. Region
    0 (undyed) is left grey on purpose: those texels ignore every Region parameter, which is the
    other half of the answer people are missing (thetruedaveed's blank-vs-alpha ColorID confusion)."""
    mask_gr, diff_gr = dye_slots(game_rel)
    if not mask_gr:
        raise RuntimeError("not a dyeing material (no %s slot): %s" % (MASK_SLOT, game_rel))
    mask_im = _tex_image(mask_gr)
    if mask_im is None:
        raise RuntimeError("could not decode the ColorID mask: " + mask_gr)
    diff_im = _tex_image(diff_gr) if diff_gr else None
    if diff_im is None:
        diff_im = Image.new("RGB", mask_im.size, (128, 128, 128))

    mask = np.asarray(mask_im.convert("RGBA").resize((size, size), Image.NEAREST), dtype=np.float32)
    diff = np.asarray(diff_im.convert("RGB").resize((size, size), Image.BILINEAR), dtype=np.float32)
    reg  = np.rint(mask[..., 3] / STEP).astype(np.int32)
    lum  = (0.2126 * diff[..., 0] + 0.7152 * diff[..., 1] + 0.0722 * diff[..., 2]) / 255.0
    # Shading is a narrow multiplier, not a blend: the swatch in the legend has to look like the
    # region on the map, or the picture answers the wrong question. 0.55..1.0 keeps folds and seams
    # visible while leaving every region recognisably its own hue.
    shade = (OVERLAY_MIX + (1.0 - OVERLAY_MIX) * np.clip(lum, 0.0, 1.0))[..., None]

    out = np.zeros((size, size, 3), dtype=np.float32)
    for idx in np.unique(reg):
        m = reg == idx
        col = np.array(REGION_COLORS.get(int(idx), (200, 200, 200)), dtype=np.float32)
        if int(idx) == 0:
            # Undyed: a flat mid-grey that mostly ignores the diffuse. Multiplying the grey by the
            # diffuse's shading like a real region does drives it to near-black wherever the skin is
            # dark (verified on 1060300 Equip_01, 29% region 0), and black reads as "broken", not
            # as "the dye system does not touch this".
            out[m] = col * (0.38 + 0.30 * np.clip(lum[m], 0.0, 1.0))[:, None]
        else:
            out[m] = col * shade[m]

    im = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB")
    if numbers:
        d = ImageDraw.Draw(im)
        font = _label_font(max(14, size // 26))
        placed = []
        for idx in np.unique(reg):
            if int(idx) == 0:
                continue
            spot = _label_anchor(reg, int(idx), placed)
            if spot is None:
                continue
            x, y = spot
            placed.append((x, y))
            try:
                d.text((x, y), str(int(idx)), fill=(255, 255, 255), font=font, anchor="mm",
                       stroke_width=max(2, size // 300), stroke_fill=(0, 0, 0))
            except (TypeError, ValueError):      # very old Pillow: no anchor/stroke support
                d.text((x, y), str(int(idx)), fill=(255, 255, 255), font=font)
    out_png = out_path or (project_base(game_rel, os.path.join(_CACHE_DYE, "regions")) + ".png")
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    im.save(out_png)
    return out_png


# ── turning the dye overlay OFF (#12) ─────────────────────────────────────────
# The most-repeated workflow request in the corpus, and the one thing this module does that is not
# preview-only. finngmin's spec: the dye system recolours the shared diffuse per chroma, so a
# hand-painted BaseColor never shows — it is overpainted by whatever the Region params say, except
# on textures with no ColorID coverage (hair, eyes).
#
# THERE IS NO MATERIAL PARAMETER FOR THIS. The dyeing MIs expose BaseTint, UseDyeingGBChannel and
# the Region N sets, and nothing that switches the system off (checked against real MIs:
# MI_1050103_Body_01 and MI_10600_1060300_Equip_01). PHASES.md's pivot signal for exactly this
# case says to ship the workaround as a one-click action, and that workaround is already circulating
# in #setup-and-guide (leagueofthearcane): replace the ColorID mask with an image whose ALPHA IS
# ZERO. Alpha is the region index — 0 means "undyed" and the shader leaves those texels alone — so
# a zero-alpha mask makes the whole surface undyed and the painted BaseColor ships as painted.
#
# It is worth being precise about why the trick is non-obvious: thetruedaveed tried a BLACK image
# and it still shaded. Black RGB with an opaque alpha is region 7, a perfectly ordinary dyed
# region; it is the ALPHA channel that has to be empty, and nothing in the app said so.
#
# Generated at the mask's own dimensions and injected through the normal texture path, so it is an
# ordinary staged asset in the mod: a uniform image is exact in DXT5 (both alpha endpoints land on
# 0), so nothing here can drift across a region step the way a recompressed real mask can.

def neutral_mask_png(out_png, size):
    """A ColorID mask that dyes nothing: every texel alpha 0, i.e. region 0 everywhere."""
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    w, h = size
    Image.new("RGBA", (max(1, int(w)), max(1, int(h))), (0, 0, 0, 0)).save(out_png)
    return out_png


def dye_off_target(game_rel):
    """The ColorID mask a dye-off would replace, or None if this material has no dyeing slot."""
    return dye_slots(game_rel)[0]


def stage_dye_off(stage, game_rel):
    """Stage a neutral ColorID mask for this material, so its dyeing stops overpainting BaseColor.

    Staged at the MASK's pak path, not the material's — the material is untouched, which is what
    makes the toggle reversible and what keeps any Region colour edits the user also made intact
    (they simply stop showing while the mask is neutral)."""
    mask_gr = dye_off_target(game_rel)
    if not mask_gr:
        raise RuntimeError("not a dyeing material (no %s slot)" % MASK_SLOT)
    cb = TX.ensure_work_base(mask_gr)
    if not cb or not os.path.exists(cb + ".uasset"):
        raise RuntimeError(TX.missing_reason(mask_gr, "ColorID mask"))
    # inject_texture keeps the BASE's pixel format, so a mask in a format with no alpha channel
    # would come back with alpha 255 everywhere — region 7, i.e. the whole skin dyed with one
    # region's colour. That is far worse than not applying the toggle, so refuse instead. Every
    # ColorID mask seen so far is DXT5 precisely because the format has an independent alpha block
    # (see texture.decode_dds), so this is a guard, not an expected path.
    fmt = TX.texture_format(cb)
    if not TX.format_has_alpha(fmt):
        raise RuntimeError("the ColorID mask is %s, which has no alpha channel — a neutral mask "
                           "would read as region 7 and dye the whole surface instead of none of it"
                           % (fmt or "in an unknown format"))
    src = neutral_mask_png(project_base(mask_gr, os.path.join(_CACHE_DYE, "neutral")) + ".png",
                           TX.texture_size(mask_gr, cb))
    pak_gr = pak_game_path(mask_gr)
    out_ua = os.path.join(stage, *pak_gr.split("/")) + ".uasset"
    os.makedirs(os.path.dirname(out_ua), exist_ok=True)
    from atelier.config import USMAP
    r = uat(["inject_texture", os.path.abspath(cb + ".uasset"), os.path.abspath(src),
             os.path.abspath(out_ua), "--usmap", USMAP])
    if not os.path.exists(out_ua):
        raise RuntimeError("neutral mask inject failed: "
                           + (((r.stderr or "") + (r.stdout or "")).strip()[-200:] or "unknown"))
    return os.path.basename(mask_gr)


# ── downloading the whole texture set (#23) ───────────────────────────────────
# chopthememegod asked for the dyed-texture download to cover "the other texture types", answered
# with "noted". The dyed BaseColor on its own is half a starting point: to repaint a skin you need
# the Normal, the ORM and the ColorID beside it, at their real sizes, and you need to know which
# file is which slot — which is the same "how do I know what maps to what" question the region
# overlay answers for colours. So the bundle carries a manifest naming every slot.

def texture_bundle(game_rel, overrides=None, size=None, out_path=None, dye_off=False):
    """Zip every texture this material references, plus the dyed BaseColor, at native size.

    Returns (zip_path, [slot names included]). Slots that cannot be decoded are listed in the
    manifest as unavailable rather than silently dropped — a missing normal map in the zip is
    otherwise indistinguishable from a material that has none."""
    import zipfile
    texs = (M.read_material(game_rel).get("textures") or {})
    if not texs:
        raise RuntimeError("this material references no textures")
    out = out_path or (project_base(game_rel, os.path.join(_CACHE_DYE, "bundle")) + "_textures.zip")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    lines = ["Textures for " + game_rel, ""]
    ok = []
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        if dye_slots(game_rel)[0] and not dye_off:
            try:
                dyed = dye_preview(game_rel, overrides=overrides, size=size or 2048)
                z.write(dyed, os.path.basename(game_rel) + "_BaseColor_dyed.png")
                ok.append("BaseColor (dyed)")
                lines.append("%-18s %s" % ("BaseColor (dyed)",
                                           os.path.basename(game_rel) + "_BaseColor_dyed.png"))
                lines.append("%-18s %s" % ("", "the dye composite — a preview, NOT what ships"))
            except Exception as e:
                lines.append("%-18s unavailable: %s" % ("BaseColor (dyed)", e))
        for slot in sorted(texs):
            gr = texs[slot]
            try:
                im = _tex_image(gr)
                if im is None:
                    raise RuntimeError("could not decode")
            except Exception as e:
                lines.append("%-18s unavailable: %s" % (slot, e))
                continue
            name = "%s__%s.png" % (slot, os.path.basename(gr))
            tmp = project_base(gr, os.path.join(_CACHE_DYE, "bundle_src")) + ".png"
            os.makedirs(os.path.dirname(tmp), exist_ok=True)
            im.convert("RGBA").save(tmp)
            z.write(tmp, name)
            ok.append(slot)
            lines.append("%-18s %s   (%dx%d)  %s" % (slot, name, im.size[0], im.size[1], gr))
        lines += ["", "Edited copies in this project are exported as they are; every other file is",
                  "decoded from the game paks. Re-import a texture in Atelier to edit it."]
        z.writestr("SLOTS.txt", "\n".join(lines) + "\n")
    return out, ok
