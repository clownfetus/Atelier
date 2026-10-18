#!/usr/bin/env python3
"""The Atelier A mark, drawn in Krackle.

The mark is drawn here once, from geometry, and written to every file that carries
it, so the vector, the interface raster and the application icons cannot drift:

    python scripts/brand_mark.py          # rewrite the files
    python scripts/brand_mark.py --check  # fail if anything is out of date

Krackle rules (DESIGN_SYSTEM.md): energy defines the silhouette and bubbles give it
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
