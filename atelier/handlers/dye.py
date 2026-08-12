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
from PIL import Image

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


_IMCACHE = {}     # game_rel -> (mtime, PIL image). Live colour picking re-composites on every drag;
                  # decoding both textures each time costs ~1.3s and makes it unusable, while the
                  # numpy composite itself is milliseconds. Hold the decoded sources.

def _tex_image(game_rel):
    """Extract + decode a texture to a PIL image. decode_dds first: MR strips the top mip, and
    UAssetTool maps mip[i]->DataResource[i], so with mip0 absent it degrades to the 4x4 tail."""
    hit = _IMCACHE.get(game_rel)
    if hit is not None:
        return hit
    im = _tex_image_uncached(game_rel)
    if im is not None:
        _IMCACHE[game_rel] = im
    return im

def _tex_image_uncached(game_rel):
    import atelier.asset_cache as _ac
    from atelier.tools import tex_semaphore
    # Same swarm hazard as the viewport's albedo path: dye previews extract+decode a mask AND a
    # diffuse, fired concurrently. Gate the heavy work so we don't pile up UAssetTool processes /
    # full-res textures in RAM (the thing that crashes the viewport on big skins).
    with tex_semaphore:
        cb = _ac.cache_base(game_rel) or TX.find_extracted(game_rel)
        if not cb or not os.path.exists(cb + ".uasset"):
            os.makedirs(WORK_IMPORT_ROOT, exist_ok=True)
            uat(["extract_iostore_legacy", PAKS, os.path.abspath(WORK_IMPORT_ROOT),
                 "--filter", os.path.basename(pak_game_path(game_rel))])
            cb = TX.find_extracted(game_rel)
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


def dye_preview(game_rel, overrides=None, size=1024, out_path=None):
    """Composite a dye preview. `overrides` = {region_idx: {param: rgba}} applied over the MI's own
    values so the UI can preview an unsaved colour pick. Returns the PNG path."""
    mask_gr, diff_gr = dye_slots(game_rel)
    if not mask_gr:
        raise RuntimeError("not a dyeing material (no %s slot): %s" % (MASK_SLOT, game_rel))
    mask_im = _tex_image(mask_gr)
    if mask_im is None:
        raise RuntimeError("could not decode the ColorID mask: " + mask_gr)
    diff_im = _tex_image(diff_gr) if diff_gr else None
    if diff_im is None:                                  # dye-only preview if the diffuse is missing
        diff_im = Image.new("RGB", mask_im.size, (128, 128, 128))
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
    return {"dyeable": True, "mask": mask_gr, "diffuse": diff_gr,
            "regions": {str(k): v for k, v in sorted(regions.items())},
            "used": {str(k): v for k, v in sorted(used.items())},
            "step": STEP}
