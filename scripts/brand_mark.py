#!/usr/bin/env python3
"""The Atelier A mark, drawn in Krackle.

The mark is drawn here once, from geometry, and written to every file that carries
it, so the vector, the interface raster and the application icons cannot drift:

    python scripts/brand_mark.py          # rewrite the files
    python scripts/brand_mark.py --check  # fail if anything is out of date

Krackle rules (docs/DESIGN_SYSTEM.md): energy defines the silhouette and bubbles give it
texture. The A is one solid silhouette of energy; its counter is the largest bubble,
and one composed mass of bubbles gathers in the right foot (the shadow side), thinning
into satellites up the leg. Bubbles are true holes, so the surface shows through
them and the header's monochrome filter keeps them. No outlines, gradients, glints or
symbols. Every bubble sits at least CLEAR units inside the silhouette.

Small sizes are drawn, not shrunk: 'micro' (24px and below) keeps only the counter,
'mid' (32-64px, and the interface raster) keeps the two largest bubbles, and 'full'
(128px and up) has the whole mass.
"""
import argparse
import io
import math
import sys
from math import acos, atan2, cos, hypot, pi, sin, sqrt, tan
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
BLUE = (0x54, 0x87, 0xdb)          # the mark's colour outside the interface

# ── geometry, on a 100-unit square, y down ───────────────────────────────────
X0, X1 = 5.0, 95.0                 # outer corners of the feet
BASE = 87.5                        # foot baseline: whole pixels at 16, 24, 32 and 48px
SLOPE = 0.53                       # dx per dy of the outer edges
APEX_R, FOOT_R = 8.5, 6.0
LEG = 24.5                         # horizontal leg width
BAR = 68.75                        # underside of the crossbar: whole pixels at 16, 32 and 48px
K = math.sqrt(1 + SLOPE * SLOPE)
APEX_Y = BASE - (50 - X0) / SLOPE  # apex vertex, above the visible curve
CLEAR = 2.2                        # bubble clearance from any edge
COUNTER = {'micro': (50, 48.4, 9.2), 'mid': (50, 48.2, 8.2), 'full': (50, 48.2, 8.2)}
# Bubbles in right-leg coordinates: u up the leg from the foot, v across it
# (+ is the outer, shadow side), r radius.
MASS = {
    'micro': [],
    'mid': [(12.8, 1.4, 5.2), (22.4, -2.2, 3.5)],
    'full': [(12.6, 1.9, 4.6), (19.3, -3.0, 3.3), (20.2, 5.0, 2.3), (7.0, -3.9, 2.1),
             (26.0, 0.9, 1.6), (33.6, -2.6, 1.15), (39.4, 2.4, .8), (13.4, -7.1, .8)],
}
ICON_SIZES = {16: 'micro', 24: 'micro', 32: 'mid', 48: 'mid', 64: 'mid', 128: 'full', 256: 'full'}


def n(v):
    """Compact number for SVG attributes."""
    s = ('%.2f' % v).rstrip('0').rstrip('.')
    return '0' if s in ('-0', '') else s


def inner_left(y):
    return X0 + LEG + (BASE - y) * SLOPE


def inner_right(y):
    return X1 - LEG - (BASE - y) * SLOPE


def outline():
    """The A as (vertex, corner radius) pairs, clockwise from the apex."""
    return [((50, APEX_Y), APEX_R), ((X1, BASE), FOOT_R), ((inner_right(BASE), BASE), 1.2),
            ((inner_right(BAR), BAR), 2.2), ((inner_left(BAR), BAR), 2.2),
            ((inner_left(BASE), BASE), 1.2), ((X0, BASE), FOOT_R)]


def corners(poly):
    """Tangent points, centre, radius and sweep for every rounded corner."""
    out = []
    for i, (p1, r) in enumerate(poly):
        p0, p2 = poly[i - 1][0], poly[(i + 1) % len(poly)][0]
        a = math.atan2(p0[1] - p1[1], p0[0] - p1[0])
        b = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
        half = abs((a - b + math.pi) % (2 * math.pi) - math.pi) / 2
        t, c = r / math.tan(half), r / math.sin(half)
        bis = math.atan2(math.sin(a) + math.sin(b), math.cos(a) + math.cos(b))
        cross = (p1[0] - p0[0]) * (p2[1] - p1[1]) - (p1[1] - p0[1]) * (p2[0] - p1[0])
        out.append({'start': (p1[0] + math.cos(a) * t, p1[1] + math.sin(a) * t),
                    'end': (p1[0] + math.cos(b) * t, p1[1] + math.sin(b) * t),
                    'centre': (p1[0] + math.cos(bis) * c, p1[1] + math.sin(bis) * c),
                    'r': r, 'sweep': 1 if cross > 0 else 0})
    return out


def outline_path():
    cs = corners(outline())
    d = [f'M{n(cs[-1]["end"][0])} {n(cs[-1]["end"][1])}']
    for c in cs:
        d.append(f'L{n(c["start"][0])} {n(c["start"][1])}')
        d.append(f'A{n(c["r"])} {n(c["r"])} 0 0 {c["sweep"]} {n(c["end"][0])} {n(c["end"][1])}')
    return ' '.join(d) + ' Z'


def outline_points(steps=64):
    pts = []
    for c in corners(outline()):
        cx, cy = c['centre']
        a0 = math.atan2(c['start'][1] - cy, c['start'][0] - cx)
        a1 = math.atan2(c['end'][1] - cy, c['end'][0] - cx)
        span = (a1 - a0) % (2 * math.pi) if c['sweep'] else -((a0 - a1) % (2 * math.pi))
        pts += [(cx + math.cos(a0 + span * k / steps) * c['r'], cy + math.sin(a0 + span * k / steps) * c['r'])
                for k in range(steps + 1)]
    return pts


def leg_point(u, v):
    fx = X1 - LEG / 2
    return (fx + (-SLOPE * u + v) / K, BASE + (-u - SLOPE * v) / K)


def bubbles(detail):
    """Counter first, then the mass, as (cx, cy, r); validates the Krackle clearances."""
    holes = [COUNTER[detail]] + [leg_point(u, v) + (r,) for u, v, r in MASS[detail]]
    dx, dy = X1 - 50, BASE - APEX_Y
    for i, (x, y, r) in enumerate(holes):
        # outer edges (mirror the left side), the foot baseline and, below the bar, the inner leg edge
        outer = abs(dy * (abs(x - 50)) - dx * (y - APEX_Y)) / math.hypot(dx, dy) - r
        room = [outer, BASE - y - r]
        if y + r > BAR:
            room.append((x - inner_right(y)) / K - r if x > 50 else (inner_left(y) - x) / K - r)
        if min(room) < CLEAR:
            raise ValueError(f'{detail} bubble {i} sits {min(room):.2f} from an edge (needs {CLEAR})')
        for j in range(i):
            px, py, pr = holes[j]
            if math.hypot(x - px, y - py) - r - pr < 0.35:
                raise ValueError(f'{detail} bubbles {j} and {i} touch')
    return holes


def svg(detail='full'):
    holes = ''.join(f' M{n(x - r)} {n(y)} a{n(r)} {n(r)} 0 1 0 {n(2 * r)} 0 a{n(r)} {n(r)} 0 1 0 {n(-2 * r)} 0 Z'
                    for x, y, r in bubbles(detail))
    color = '#%02x%02x%02x' % BLUE
    return ('<!-- Atelier mark: an A of Krackle energy; the counter and the bubble mass are holes.\n'
            '     Generated by scripts/brand_mark.py; edit the script, not this file. -->\n'
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100" height="100">\n'
            f'<title>Atelier</title>\n<path fill="{color}" fill-rule="evenodd" d="{outline_path()}{holes}" />\n'
            '</svg>\n')


def raster(size, detail):
    """Exact-coverage raster: supersampled silhouette with the bubbles punched out."""
    ss = max(4, 2048 // size)
    s = size * ss / 100
    mask = Image.new('L', (size * ss, size * ss), 0)
    draw = ImageDraw.Draw(mask)
    draw.polygon([(x * s, y * s) for x, y in outline_points()], fill=255)
    for x, y, r in bubbles(detail):
        draw.ellipse([(x - r) * s, (y - r) * s, (x + r) * s, (y + r) * s], fill=0)
    im = Image.new('RGBA', mask.size, BLUE + (0,))
    im.putalpha(mask)
    return im.reduce(ss)


def png_bytes(im):
    buf = io.BytesIO()
    im.save(buf, 'PNG', optimize=True)
    return buf.getvalue()


def ico_bytes():
    images = [raster(size, detail) for size, detail in ICON_SIZES.items()]
    buf = io.BytesIO()
    images[-1].save(buf, 'ICO', sizes=[im.size for im in images], append_images=images[:-1])
    return buf.getvalue()


# ── the three-piece mark (D14, SPEC section 3.1) ─────────────────────────────
# Lines and tangent arcs only: H = 260, y down, bite radius R = r + g, concentric with the disc.
# scripts/folder_emblems.py draws the Textures and Meshes icons from these. P1.4 makes them the
# files this script writes, and removes the Krackle mark above.
TEXTURE_COLOUR, MESH_COLOUR, MATERIAL_COLOUR = "#6C98CA", "#5AAA9A", "#DF8F6B"

MASTER = dict(
    cx=208.0, cy=146.0, r=50.0, g=14.0,
    tile_xr=181.5, notch_x=43.5, notch_y=44.5, tile_k=10.5, notch_in=7.0, tile_f1=23.5,
    tile_rb=57.0, tile_cbx=116.0, tile_f2=25.5, tile_kb=40.5,
    mesh_lt=206.5, mesh_su=.498, mesh_lb=292.0, mesh_sl=.514, mesh_rt=305.0, mesh_rb=409.0,
    mesh_ktl=9.5, mesh_ktr=38.0, mesh_kbr=15.0, mesh_kbl=14.5, mesh_f1=12.5, mesh_f2=13.0,
)
# Small-size mark (<=24px): smaller disc and a wider gap so the separations survive
# at 16px (gap 32u = 2px at 16px), softer corners, same pieces.
SMALL = dict(
    MASTER, r=40.0, g=32.0, tile_k=14.0, notch_in=9.0, tile_f1=26.0, tile_f2=26.0, tile_kb=42.0,
    mesh_ktl=14.0, mesh_ktr=40.0, mesh_kbr=18.0, mesh_kbl=18.0, mesh_f1=14.0, mesh_f2=14.0,
)

TILE_ORDER = ["top", "tr", "side", "bottom", "bl", "left", "notch"]
MESH_ORDER = ["top", "tr", "right", "br", "bottom", "bl", "side", "tl"]
# Points per section in the engine's outlines. Plain bars are sampled to the same counts.
TILE_N = dict(top=10, tr=12, side=96, bottom=10, bl=20, left=14, notch=60)
MESH_N = dict(top=8, tr=24, right=16, br=14, bottom=8, bl=14, side=84, tl=10)


def _arc(c, r, a0, a1, step=1.2):
    """Points on a circle from a0 to a1 (radians, signed sweep)."""
    n = max(2, int(abs(a1 - a0) * r / step) + 1)
    return [(c[0] + r * cos(a0 + (a1 - a0) * i / n), c[1] + r * sin(a0 + (a1 - a0) * i / n)) for i in range(n + 1)]


def _ang(c, p):
    return atan2(p[1] - c[1], p[0] - c[0])


def _sweep(a0, a1, cw):
    """Shortest sweep in the stated direction. On screen with y down, clockwise means increasing angle."""
    d = a1 - a0
    if cw:
        while d < 0:
            d += 2 * pi
    else:
        while d > 0:
            d -= 2 * pi
    return a0 + d


def corner(p, v, q, r):
    """Round the corner at v between p and q. Returns the arc as points, convex or concave alike."""
    ax, ay = p[0] - v[0], p[1] - v[1]
    bx, by = q[0] - v[0], q[1] - v[1]
    la, lb = hypot(ax, ay), hypot(bx, by)
    ax, ay, bx, by = ax / la, ay / la, bx / lb, by / lb
    half = 0.5 * acos(max(-1, min(1, ax * bx + ay * by)))
    t = r / tan(half)
    s, e = (v[0] + ax * t, v[1] + ay * t), (v[0] + bx * t, v[1] + by * t)
    mx, my = ax + bx, ay + by
    ml = hypot(mx, my)
    d = r / sin(half)
    c = (v[0] + mx / ml * d, v[1] + my / ml * d)
    cross = (v[0] - p[0]) * (q[1] - v[1]) - (v[1] - p[1]) * (q[0] - v[0])
    a0, a1 = _ang(c, s), _ang(c, e)
    return _arc(c, r, a0, _sweep(a0, a1, cross > 0))


def _fillet_line_bite(a, b, c, R, f, inside_sign):
    """Convex fillet f between line a-b and the concave bite (centre c, radius R).
    inside_sign picks which side of the line holds the shape. Picks the solution nearer to a.
    Returns the fillet centre, its tangent point on the line and its tangent point on the bite."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = hypot(dx, dy)
    ux, uy = dx / L, dy / L
    nx, ny = -uy * inside_sign, ux * inside_sign
    ox, oy = a[0] + nx * f, a[1] + ny * f
    wx, wy = ox - c[0], oy - c[1]
    B = wx * ux + wy * uy
    C = wx * wx + wy * wy - (R + f) ** 2
    disc = B * B - C
    if disc < 0:
        raise ValueError("fillet does not reach the bite")
    t = -B - sqrt(disc)
    fc = (ox + ux * t, oy + uy * t)
    k = R / (R + f)
    return fc, (fc[0] - nx * f, fc[1] - ny * f), (c[0] + (fc[0] - c[0]) * k, c[1] + (fc[1] - c[1]) * k)


def _fillet_circle_bite(c2, R2, c, R, f):
    """Convex fillet f between a large convex arc (centre c2, radius R2, shape inside) and the concave bite."""
    d1, d2 = R2 - f, R + f
    dx, dy = c[0] - c2[0], c[1] - c2[1]
    D = hypot(dx, dy)
    a = (d1 * d1 - d2 * d2 + D * D) / (2 * D)
    h = sqrt(max(0, d1 * d1 - a * a))
    px, py = c2[0] + dx / D * a, c2[1] + dy / D * a
    # the solution on the lower side of the centre line is the lip under the disc
    fc = max([(px + dy / D * h, py - dx / D * h), (px - dy / D * h, py + dx / D * h)], key=lambda p: p[1])
    k1, k2 = R2 / d1, R / d2
    return fc, (c2[0] + (fc[0] - c2[0]) * k1, c2[1] + (fc[1] - c2[1]) * k1), (c[0] + (fc[0] - c[0]) * k2, c[1] + (fc[1] - c[1]) * k2)


def tile(P):
    """The tile's sections, clockwise from the top of the raised part."""
    H, c, R = 260.0, (P["cx"], P["cy"]), P["r"] + P["g"]
    xr, nx, ny, k = P["tile_xr"], P["notch_x"], P["notch_y"], P["tile_k"]
    inner = corner((0, ny), (nx, ny), (nx, 0), P["notch_in"])
    top_left = corner((nx, ny), (nx, 0), (xr, 0), k)
    tr = corner((nx, 0), (xr, 0), (xr, H), k)
    # upper lip: right edge into the bite
    fc1, l1, b1 = _fillet_line_bite((xr, 0), (xr, H), c, R, P["tile_f1"], 1)
    a0, a1 = _ang(fc1, l1), _ang(fc1, b1)
    lip1 = _arc(fc1, P["tile_f1"], a0, _sweep(a0, a1, True))
    # lower big corner, tangent to the bottom edge, and its fillet into the bite
    c2 = (P["tile_cbx"], H - P["tile_rb"])
    fc2, on_c2, b2 = _fillet_circle_bite(c2, P["tile_rb"], c, R, P["tile_f2"])
    a0, a1 = _ang(c, b1), _ang(c, b2)
    bite = _arc(c, R, a0, _sweep(a0, a1, False), step=.9)
    a0, a1 = _ang(fc2, b2), _ang(fc2, on_c2)
    lip2 = _arc(fc2, P["tile_f2"], a0, _sweep(a0, a1, True))
    a0 = _ang(c2, on_c2)
    big = _arc(c2, P["tile_rb"], a0, _sweep(a0, pi / 2, True))
    bl = corner((c2[0], H), (0, H), (0, ny), P["tile_kb"])
    shoulder = corner((0, H), (0, ny), (nx, ny), k)
    return dict(
        top=[top_left[-1], tr[0]], tr=tr,
        side=[tr[-1]] + lip1 + bite + lip2 + big,
        bottom=[big[-1], bl[0]], bl=bl,
        left=[bl[-1], shoulder[0]],
        notch=shoulder + inner + top_left,
    )


def mesh(P):
    """The mesh's sections, clockwise from the top edge."""
    H, c, R = 260.0, (P["cx"], P["cy"]), P["r"] + P["g"]
    lt, lu = (P["mesh_lt"], 0.0), (P["mesh_lt"] + P["mesh_su"] * H, H)    # upper left line
    lb, ll = (P["mesh_lb"], H), (P["mesh_lb"] - P["mesh_sl"] * H, 0.0)    # lower left line
    rt, rb = (P["mesh_rt"], 0.0), (P["mesh_rb"], H)
    tr = corner(lt, rt, rb, P["mesh_ktr"])
    br = corner(rt, rb, lb, P["mesh_kbr"])
    bl = corner(rb, lb, ll, P["mesh_kbl"])
    tl = corner(lu, lt, rt, P["mesh_ktl"])
    # going up the left side, from the lower lip to the upper lip
    fc1, l1, b1 = _fillet_line_bite(lb, ll, c, R, P["mesh_f1"], 1)
    a0, a1 = _ang(fc1, l1), _ang(fc1, b1)
    lip1 = _arc(fc1, P["mesh_f1"], a0, _sweep(a0, a1, True))
    fc2, l2, b2 = _fillet_line_bite(lt, lu, c, R, P["mesh_f2"], -1)
    a0, a1 = _ang(fc2, b2), _ang(fc2, l2)
    lip2 = _arc(fc2, P["mesh_f2"], a0, _sweep(a0, a1, True))
    a0, a1 = _ang(c, b1), _ang(c, b2)
    bite = _arc(c, R, a0, _sweep(a0, a1, False), step=.9)
    return dict(
        top=[tl[-1], tr[0]], tr=tr,
        right=[tr[-1], br[0]], br=br,
        bottom=[br[-1], bl[0]], bl=bl,
        side=[bl[-1]] + lip1 + bite + lip2 + [tl[0]], tl=tl,
    )


def ring(sections, order):
    """One closed outline from named sections, with repeated points removed."""
    pts = []
    for name in order:
        for p in sections[name]:
            if not pts or hypot(p[0] - pts[-1][0], p[1] - pts[-1][1]) > 1e-6:
                pts.append(p)
    return pts


def path_d(pts):
    return "M" + "L".join(f"{x:.2f} {y:.2f}" for x, y in pts) + "Z"


def mark_svg(P):
    tr, mr = ring(tile(P), TILE_ORDER), ring(mesh(P), MESH_ORDER)
    xs, ys = [p[0] for p in tr + mr], [p[1] for p in tr + mr]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0:.2f} {y0:.2f} {x1 - x0:.2f} {y1 - y0:.2f}">'
        f'<path id="texture" fill="{TEXTURE_COLOUR}" d="{path_d(tr)}"/><path id="mesh" fill="{MESH_COLOUR}" d="{path_d(mr)}"/>'
        f'<circle id="material" fill="{MATERIAL_COLOUR}" cx="{P["cx"]}" cy="{P["cy"]}" r="{P["r"]}"/></svg>'
    ), (x0, y0, x1, y1), tr, mr


def _resample(poly, n):
    """n points by arc length, from the start up to just before the end (the next section starts at the end)."""
    seg = [hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(poly, poly[1:])]
    total = sum(seg)
    out, i, run = [], 0, 0.0
    for k in range(n):
        target = total * k / n
        while i < len(seg) - 1 and run + seg[i] < target:
            run += seg[i]
            i += 1
        u = 0 if seg[i] == 0 else (target - run) / seg[i]
        out.append((poly[i][0] + (poly[i + 1][0] - poly[i][0]) * u, poly[i][1] + (poly[i + 1][1] - poly[i][1]) * u))
    return out


def pieces(P):
    """The tile and mesh as the engine draws them: centred on their own boxes, height 260, in named sections."""
    _, box, tr, mr = mark_svg(P)
    tx1 = max(p[0] for p in tr)
    mx0, mx1 = min(p[0] for p in mr), max(p[0] for p in mr)

    def local(sections, order, counts, x0, x1):
        cx = (x0 + x1) / 2
        pts = []
        for name in order:
            pts += [[round(x - cx, 2), round(y - 130, 2)] for x, y in _resample(sections[name], counts[name])]
        return pts

    return dict(
        tile=local(tile(P), TILE_ORDER, TILE_N, 0.0, tx1), mesh=local(mesh(P), MESH_ORDER, MESH_N, mx0, mx1),
        tw=round(tx1, 2), mw=round(mx1 - mx0, 2), h=260, W=round(box[2] - box[0], 2),
        tcx=round(tx1 / 2, 2), mcx=round((mx0 + mx1) / 2, 2),
        tn=[TILE_N[k] for k in TILE_ORDER], mn=[MESH_N[k] for k in MESH_ORDER],
        cx=P["cx"], cy=P["cy"], r=P["r"],
    )


def _gaps(P, tr, mr):
    c = (P["cx"], P["cy"])
    return dict(
        tile_disc=round(min(hypot(p[0] - c[0], p[1] - c[1]) for p in tr) - P["r"], 2),
        mesh_disc=round(min(hypot(p[0] - c[0], p[1] - c[1]) for p in mr) - P["r"], 2),
        tile_mesh=round(min(hypot(p[0] - q[0], p[1] - q[1]) for p in tr[::2] for q in mr[::2]), 2),
    )


def wordmark(fontpath, text="ΛTELIER", tracking=0.11, fill="#F4F6F8"):
    import uharfbuzz as hb
    from fontTools.pens.boundsPen import BoundsPen
    from fontTools.pens.svgPathPen import SVGPathPen
    from fontTools.pens.transformPen import TransformPen
    from fontTools.ttLib import TTFont

    blob = hb.Blob.from_file_path(fontpath)
    face = hb.Face(blob)
    font = hb.Font(face)
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(font, buf, {"kern": True, "liga": False})
    tt = TTFont(fontpath)
    upem = tt["head"].unitsPerEm
    order = tt.getGlyphOrder()
    gs = tt.getGlyphSet()
    capH = tt["OS/2"].sCapHeight
    x = 0
    paths = []
    lam = None
    for i, (info, pos) in enumerate(zip(buf.glyph_infos, buf.glyph_positions)):
        name = order[info.codepoint]
        pen = SVGPathPen(gs)
        tp = TransformPen(pen, (1, 0, 0, -1, x + pos.x_offset, capH))
        gs[name].draw(tp)
        paths.append(pen.getCommands())
        if i == 0:
            bp = BoundsPen(gs)
            gs[name].draw(bp)
            lam = (x, bp.bounds)
        adv = pos.x_advance
        if i < len(text) - 1:
            adv += tracking * upem
        x += adv
    width = x
    # copper disc in the Lambda's counter, at Inter's crossbar height
    lx, (bx0, by0, bx1, by1) = lam
    cxd = lx + (bx0 + bx1) / 2
    dr = capH * 0.118
    cyd = capH - capH * 0.285  # svg y (down): 27% up from baseline
    d = " ".join(paths)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} {capH}">'
        f'<path fill="{fill}" d="{d}"/>'
        f'<circle fill="{MATERIAL_COLOUR}" cx="{cxd:.1f}" cy="{cyd:.1f}" r="{dr:.1f}"/></svg>'
    )
    return svg, dict(cx=cxd, cy=cyd, r=dr, capH=capH, w=width)


OUTPUTS = {
    'gui/brand/atelier-mark.svg': lambda: svg('full').encode(),
    # Interface raster: header (32px), launch splash (48px) and favicon.
    'gui/brand/atelier-mark.png': lambda: png_bytes(raster(256, 'mid')),
    # Application icons: installer/executable and the Linux desktop entry.
    'icon.ico': ico_bytes,
    'icon.png': lambda: png_bytes(raster(1024, 'full')),
}


def same_pixels(a, b):
    ia, ib = Image.open(io.BytesIO(a)), Image.open(io.BytesIO(b))
    frames_a = [ia] if ia.format != 'ICO' else [ia.ico.getimage(s) for s in sorted(ia.ico.sizes())]
    frames_b = [ib] if ib.format != 'ICO' else [ib.ico.getimage(s) for s in sorted(ib.ico.sizes())]
    if len(frames_a) != len(frames_b):
        return False
    for fa, fb in zip(frames_a, frames_b):
        fa, fb = fa.convert('RGBA'), fb.convert('RGBA')
        if fa.size != fb.size or max(hi for _, hi in ImageChops.difference(fa, fb).getextrema()) > 2:
            return False
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--check', action='store_true', help='fail if a generated file is out of date')
    args = parser.parse_args()
    stale = []
    for rel, make in OUTPUTS.items():
        path, data = ROOT / rel, make()
        if args.check:
            current = path.read_bytes() if path.exists() else b''
            ok = current == data if rel.endswith('.svg') else bool(current) and same_pixels(current, data)
            if not ok:
                stale.append(rel)
        elif not path.exists() or path.read_bytes() != data:
            path.write_bytes(data)
            print('wrote', rel)
    if stale:
        print('Out of date (run scripts/brand_mark.py):', ', '.join(stale), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
