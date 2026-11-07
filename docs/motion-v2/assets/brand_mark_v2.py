"""Construct the Atelier three-piece mark and outlined wordmark (brand bible v1.2).

Usage:  python brand_mark_v2.py <out_dir> [path/to/InterDisplay-SemiBold.otf]
Needs:  pip install shapely uharfbuzz fonttools
Writes: atelier-mark.svg, atelier-mark-small.svg, atelier-wordmark.svg, atelier-wordmark-ink.svg


Construction (master, units; mark height H = 260):
  disc radius r, gap g, bite radius R = r + g (bites are concentric with the disc)
  texture tile: trapezoid, vertical left edge, right edge leans "/" (A's left leg)
  mesh block: parallelogram leaning "\\" (A's right leg)
  outer corner radius k, bite-junction fillet f
"""
import json, sys
from shapely.geometry import Polygon, Point
from shapely import affinity
import uharfbuzz as hb
from fontTools.ttLib import TTFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen

BLUE, TEAL, COPPER = "#6C98CA", "#5AAA9A", "#DF8F6B"
Q = 24  # arc resolution


def rounded(poly, k):
    return poly.buffer(-k, join_style="round", quad_segs=Q).buffer(k, join_style="round", quad_segs=Q)


def build(spec):
    c = Point(*spec["disc_c"])
    r, g = spec["r"], spec["g"]
    R = r + g
    bite = c.buffer(R, quad_segs=Q * 2)
    tex = rounded(Polygon(spec["tex"]), spec["k"]).difference(bite)
    mesh = rounded(Polygon(spec["mesh"]), spec["k"]).difference(bite)
    tex = rounded(tex, spec["f"])
    mesh = rounded(mesh, spec["f"])
    disc = c.buffer(r, quad_segs=Q * 2)
    return tex, mesh, disc


def path_d(geom):
    geom = geom.simplify(0.04)
    pts = list(geom.exterior.coords)
    d = "M" + " L".join(f"{x:.2f} {y:.2f}" for x, y in pts[:-1]) + " Z"
    return d


MASTER = dict(
    tex=[(0, 12), (172, 12), (146, 260), (0, 260)],
    mesh=[(206, 0), (302, 0), (386, 260), (290, 260)],
    disc_c=(203, 152), r=46, g=14, k=24, f=6,
)
# Small-size mark (<=24px): wider gap and larger fillets so the
# separations survive at 16px (gap 32u = 2px at 16px).
SMALL = dict(
    tex=[(0, 12), (168, 12), (142, 260), (0, 260)],
    mesh=[(214, 0), (314, 0), (398, 260), (298, 260)],
    disc_c=(206, 156), r=38, g=32, k=34, f=10,
)


def mark_svg(spec, pad=0, bg=None):
    tex, mesh, disc = build(spec)
    minx = min(t.bounds[0] for t in (tex, mesh, disc))
    maxx = max(t.bounds[2] for t in (tex, mesh, disc))
    miny = min(t.bounds[1] for t in (tex, mesh, disc))
    maxy = max(t.bounds[3] for t in (tex, mesh, disc))
    w, h = maxx - minx, maxy - miny
    cx, cy = spec["disc_c"]
    vb = f"{minx - pad:.2f} {miny - pad:.2f} {w + 2 * pad:.2f} {h + 2 * pad:.2f}"
    bgrect = f'<rect x="{minx - pad}" y="{miny - pad}" width="{w + 2 * pad}" height="{h + 2 * pad}" fill="{bg}"/>' if bg else ""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}">{bgrect}'
        f'<path id="texture" fill="{BLUE}" d="{path_d(tex)}"/>'
        f'<path id="mesh" fill="{TEAL}" d="{path_d(mesh)}"/>'
        f'<circle id="material" fill="{COPPER}" cx="{cx}" cy="{cy}" r="{spec["r"]}"/></svg>'
    ), (minx, miny, w, h), (tex, mesh, disc)


def wordmark(fontpath, text="ΛTELIER", tracking=0.11, fill="#F4F6F8"):
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
            b = gs[name]
            from fontTools.pens.boundsPen import BoundsPen
            bp = BoundsPen(gs); b.draw(bp)
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
        f'<circle fill="{COPPER}" cx="{cxd:.1f}" cy="{cyd:.1f}" r="{dr:.1f}"/></svg>'
    )
    return svg, dict(cx=cxd, cy=cyd, r=dr, capH=capH, w=width)


if __name__ == "__main__":
    out = sys.argv[1]
    fp = sys.argv[2] if len(sys.argv) > 2 else "gui/vendor/inter/InterDisplay-SemiBold.otf"
    m, box, (tex, mesh, disc) = mark_svg(MASTER)
    s, sbox, (stex, smesh, sdisc) = mark_svg(SMALL)
    open(f"{out}/atelier-mark.svg", "w").write(m)
    open(f"{out}/atelier-mark-small.svg", "w").write(s)
    wm, info = wordmark(fp)
    open(f"{out}/atelier-wordmark.svg", "w").write(wm)
    wmi, _ = wordmark(fp, fill="#0D151F")
    open(f"{out}/atelier-wordmark-ink.svg", "w").write(wmi)
    rep = dict(
        master_box=box, small_box=sbox,
        gaps_master=[round(tex.distance(disc), 2), round(mesh.distance(disc), 2), round(tex.distance(mesh), 2)],
        gaps_small=[round(stex.distance(sdisc), 2), round(smesh.distance(sdisc), 2), round(stex.distance(smesh), 2)],
        wordmark=info,
    )
    print(json.dumps(rep, indent=1))
