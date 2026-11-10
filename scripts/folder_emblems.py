#!/usr/bin/env python3
"""Folder icons in the three-piece language (D9, SPEC section 3.5). Standard library only, apart
from what brand_mark.py imports.

    python scripts/folder_emblems.py          # rewrite the files
    python scripts/folder_emblems.py --check  # fail if anything is out of date

Writes gui/brand/emblems/<class>-master.svg (for 32 px and up) and -small.svg (below 32 px) for all
17 icons, gui/folder-emblems.js, which icons.js inlines, and the plain folder's template in
gui/index.html.

Grid is 24 units. Master: gap 1.4, corner 2.2.
Small: every piece inset .5 so gaps grow to 2.4, corner 3.0.
Every piece is one outline, so nothing can have an enclosed hole.
Textures and Meshes come straight from the mark's construction in brand_mark.py.
"""
import argparse
import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import brand_mark as mark

ROOT = Path(__file__).resolve().parents[1]
EMBLEMS = ROOT / 'gui' / 'brand' / 'emblems'

# Solid emblem colours from SPEC section 2. Other themes fit these for 3:1 contrast
# on the cards and thumbnails while keeping the hue.
EMBLEM_INKS = {
    'texture': {'dark': '#4F80CC', 'light': '#5182CD'},
    'mesh': {'dark': '#45AB91', 'light': '#3A8F7A'},
    'material': {'dark': '#EB9A72', 'light': '#D75B1E'},
    'character': {'dark': '#62B6CC', 'light': '#267E96'},
    'ui': {'dark': '#AA98E8', 'light': '#755CB4'},
    'vfx': {'dark': '#D98BCB', 'light': '#A95199'},
    'neutral': {'dark': '#778BA3', 'light': '#6A7C90'},
}
ROLES = {
    'texture-folder-icon': 'texture',
    'mesh-folder-icon': 'mesh',
    'material-folder-icon': 'material',
    'char-icon': 'character',
    'ui-folder-icon': 'ui',
    'vfx-folder-icon': 'vfx',
}

G = 1.4
MASTER = dict(d=0.0, k=2.2, f=.55)
SMALL = dict(d=.5, k=3.0, f=.85)


# ---- geometry -----------------------------------------------------------------------------
def area(p):
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(p, p[1:] + p[:1])) / 2
def orient(p):
    p = list(p)
    return p if area(p) > 0 else p[::-1]
def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])
def inside(pt, ring):
    x, y, hit = pt[0], pt[1], False
    for a, b in zip(ring, ring[1:] + ring[:1]):
        if (a[1] > y) != (b[1] > y) and x < a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1]):
            hit = not hit
    return hit

def inset(pts, d):
    if not d:
        return pts
    p, n, out = orient(pts), len(pts), []
    for i in range(n):
        a, b, c = p[i - 1], p[i], p[(i + 1) % n]
        e1, e2 = (b[0] - a[0], b[1] - a[1]), (c[0] - b[0], c[1] - b[1])
        l1, l2 = math.hypot(*e1), math.hypot(*e2)
        n1, n2 = (-e1[1] / l1, e1[0] / l1), (-e2[1] / l2, e2[0] / l2)
        den = e1[0] * e2[1] - e1[1] * e2[0]
        if abs(den) < 1e-6:
            out.append((b[0] + n1[0] * d, b[1] + n1[1] * d))
            continue
        p1, p2 = (a[0] + n1[0] * d, a[1] + n1[1] * d), (b[0] + n2[0] * d, b[1] + n2[1] * d)
        t = ((p2[0] - p1[0]) * e2[1] - (p2[1] - p1[1]) * e2[0]) / den
        out.append((p1[0] + e1[0] * t, p1[1] + e1[1] * t))
    return out

def round_corners(pts, k):
    p, n, out = orient(pts), len(pts), []
    for i in range(n):
        a, v, c = p[i - 1], p[i], p[(i + 1) % n]
        l1, l2 = dist(a, v), dist(v, c)
        u1, u2 = ((a[0] - v[0]) / l1, (a[1] - v[1]) / l1), ((c[0] - v[0]) / l2, (c[1] - v[1]) / l2)
        phi = math.acos(max(-1, min(1, u1[0] * u2[0] + u1[1] * u2[1])))
        if phi > math.radians(175):
            out.append(v)
            continue
        convex = (v[0] - a[0]) * (c[1] - v[1]) - (v[1] - a[1]) * (c[0] - v[0]) > 0
        r = (k * min(1, math.degrees(phi) / 100)) if convex else k * .35
        t = min(r / math.tan(phi / 2), .48 * l1, .48 * l2)
        r = t * math.tan(phi / 2)
        bx, by = u1[0] + u2[0], u1[1] + u2[1]
        bl = math.hypot(bx, by)
        cen = (v[0] + bx / bl * r / math.sin(phi / 2), v[1] + by / bl * r / math.sin(phi / 2))
        t1, t2 = (v[0] + u1[0] * t, v[1] + u1[1] * t), (v[0] + u2[0] * t, v[1] + u2[1] * t)
        a1, a2 = math.atan2(t1[1] - cen[1], t1[0] - cen[0]), math.atan2(t2[1] - cen[1], t2[0] - cen[0])
        delta = (a2 - a1 + math.pi) % (2 * math.pi) - math.pi
        segs = max(2, math.ceil(abs(delta) / math.radians(10)))
        out += [(cen[0] + r * math.cos(a1 + delta * s / segs), cen[1] + r * math.sin(a1 + delta * s / segs)) for s in range(segs + 1)]
    return out

def circle(cx, cy, r, n=96):
    return [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n)) for i in range(n)]

def bite(ring, cx, cy, R):
    ring, verts = orient(ring), []
    state = lambda q: 'in' if dist(q, (cx, cy)) < R - 1e-9 else 'out'
    for a, b in zip(ring, ring[1:] + ring[:1]):
        verts.append((a, state(a)))
        dx, dy, fx, fy = b[0] - a[0], b[1] - a[1], a[0] - cx, a[1] - cy
        A, B, C = dx * dx + dy * dy, 2 * (fx * dx + fy * dy), fx * fx + fy * fy - R * R
        disc = B * B - 4 * A * C
        if A == 0 or disc <= 0:
            continue
        ts = sorted(t for t in ((-B - math.sqrt(disc)) / (2 * A), (-B + math.sqrt(disc)) / (2 * A)) if 1e-9 < t < 1 - 1e-9)
        pts = [(a[0] + dx * t, a[1] + dy * t) for t in ts]
        for i, q in enumerate(pts):
            verts.append((q, 'on'))
            if i == 0 and len(pts) == 2:
                verts.append((((pts[0][0] + pts[1][0]) / 2, (pts[0][1] + pts[1][1]) / 2), 'in'))
    if not any(s == 'in' for _, s in verts):
        return ring
    start = next(i for i, (_, s) in enumerate(verts) if s != 'in')
    verts = verts[start:] + verts[:start]
    out, i = [], 0
    while i < len(verts):
        q, s = verts[i]
        if s != 'in':
            out.append(q)
            i += 1
            continue
        j = i
        while j < len(verts) and verts[j][1] == 'in':
            j += 1
        a, b = out[-1], verts[j % len(verts)][0]
        aa, ab = math.atan2(a[1] - cy, a[0] - cx), math.atan2(b[1] - cy, b[0] - cx)
        ccw = (ab - aa) % (2 * math.pi)
        cw = ccw - 2 * math.pi
        delta = ccw if inside((cx + R * math.cos(aa + ccw / 2), cy + R * math.sin(aa + ccw / 2)), ring) else cw
        segs = max(3, math.ceil(abs(delta) / math.radians(8)))
        out += [(cx + R * math.cos(aa + delta * t / segs), cy + R * math.sin(aa + delta * t / segs)) for t in range(1, segs)]
        i = j
    return out

def fillet(ring, f, thresh=30):
    n = len(ring)
    turn = []
    for i in range(n):
        a, v, c = ring[i - 1], ring[i], ring[(i + 1) % n]
        turn.append(abs((math.atan2(c[1] - v[1], c[0] - v[0]) - math.atan2(v[1] - a[1], v[0] - a[0]) + math.pi) % (2 * math.pi) - math.pi))
    sharp = [i for i in range(n) if math.degrees(turn[i]) > thresh]
    if not sharp:
        return ring
    seg = [dist(ring[i], ring[(i + 1) % n]) for i in range(n)]
    cum = [0]
    for s in seg:
        cum.append(cum[-1] + s)
    total = cum[-1]
    removed, inserts = [False] * n, {}
    for pos, s in enumerate(sharp):
        nxt, prv = sharp[(pos + 1) % len(sharp)], sharp[pos - 1]
        gap_n = (cum[nxt] - cum[s]) % total or total
        gap_p = (cum[s] - cum[prv]) % total or total
        t = min(f * 1.3, .45 * gap_n, .45 * gap_p)
        def walk(step):
            d, j = 0, s
            while True:
                k = (j + step) % n
                L = dist(ring[j], ring[k])
                if d + L >= t:
                    u = (t - d) / L
                    return (ring[j][0] + (ring[k][0] - ring[j][0]) * u, ring[j][1] + (ring[k][1] - ring[j][1]) * u)
                d += L
                j = k
                removed[j] = True
        p0, p2 = walk(-1), walk(1)
        v = ring[s]
        inserts[s] = [((1 - u) ** 2 * p0[0] + 2 * u * (1 - u) * v[0] + u * u * p2[0], (1 - u) ** 2 * p0[1] + 2 * u * (1 - u) * v[1] + u * u * p2[1]) for u in (x / 6 for x in range(7))]
        removed[s] = True
    out = []
    for i in range(n):
        if i in inserts:
            out += inserts[i]
        elif not removed[i]:
            out.append(ring[i])
    return out

def build(piece, spec):
    d, k, f = spec['d'], spec['k'], spec['f']
    if piece['t'] == 'd':
        cx, cy = piece['c']
        r = piece['r'] - d
        if not piece['bites']:
            return {'circle': (cx, cy, r), 'ring': circle(cx, cy, r)}
        ring = circle(cx, cy, r)
    elif piece['t'] == 'p':
        ring = round_corners(inset(piece['pts'], d), k * piece['k'])
    else:
        ring = fillet(orient(piece['fn'](d)), f * 1.6)
    for cx, cy, R in piece['bites']:
        ring = bite(ring, cx, cy, R + d)
    if piece['bites']:
        ring = fillet(ring, f)
    return {'ring': ring}

def path_d(ring):
    # Measured against the last point kept, so a smooth arc can't lose every point one small step at a time.
    keep = [ring[0]]
    n = len(ring)
    for i in range(1, n):
        a, v, c = keep[-1], ring[i], ring[(i + 1) % n]
        L = dist(a, c) or 1
        if abs((c[0] - a[0]) * (a[1] - v[1]) - (a[0] - v[0]) * (c[1] - a[1])) / L > .01:
            keep.append(v)
    return 'M' + 'L'.join(f'{x:.2f} {y:.2f}' for x, y in keep) + 'Z'


# ---- pieces -------------------------------------------------------------------------------
def P(pts, bites=(), k=1.0):
    return dict(t='p', pts=list(pts), bites=list(bites), k=k)
def D(x, y, r, bites=()):
    return dict(t='d', c=(x, y), r=r, bites=list(bites))
def Rg(fn, bites=()):
    return dict(t='r', fn=fn, bites=list(bites))
def R(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
def halo(x, y, r, g=G):
    return (x, y, r + g)
def place(pts, deg, s=1.0, cx=12, cy=12):
    a = math.radians(deg)
    return [(cx + s * (x * math.cos(a) - y * math.sin(a)), cy + s * (x * math.sin(a) + y * math.cos(a))) for x, y in pts]

def slab(rx, ry, c_top, c_bottom, cap=False, cx=12):
    def fn(d):
        w, steps = rx - d, 20
        xs = [-w + 2 * w * i / steps for i in range(steps + 1)]
        low = lambda x, c: c + (ry - (d if cap else 0)) * math.sqrt(max(0, 1 - (x / w) ** 2))
        up = lambda x, c: c - (ry - d) * math.sqrt(max(0, 1 - (x / w) ** 2))
        if cap:
            return [(cx + x, up(x, c_top)) for x in xs] + [(cx + x, low(x, c_top)) for x in xs[::-1]][1:-1]
        return [(cx + x, low(x, c_top + d)) for x in xs] + [(cx + x, low(x, c_bottom - d)) for x in xs[::-1]]
    return fn

BODY = [(6.5, 12), (17.5, 12), (21.5, 23), (2.5, 23)]
sword = lambda pts: place(pts, 45, .95)

def mark_piece(make, order, height):
    """The mark's own tile or mesh, centred on the grid. The small icon uses the small mark's softer drawing."""
    def fn(d):
        pts = mark.ring(make(mark.SMALL if d else mark.MASTER), order)
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        cx, cy, s = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, (height - 2 * d) / 260
        return [(12 + (x - cx) * s, 12 + (y - cy) * s) for x, y in pts]
    return fn

# Textures, Meshes and Materials are the mark's own pieces. Keys match the classes in gui/folder-icons.js.
CORE_PIECES = {
    'texture-folder-icon': [Rg(mark_piece(mark.tile, mark.TILE_ORDER, 21))],
    'mesh-folder-icon': [Rg(mark_piece(mark.mesh, mark.MESH_ORDER, 22))],
    'material-folder-icon': [D(12, 12, 10)],
}

OTHER_FOLDERS = [
    ('folder-icon', 'Folder', [P([(2, 3), (9.2, 3), (11.8, 5.6), (22, 5.6), (22, 9), (2, 9)], k=.8), P([(2, 10.4), (22, 10.4), (20.4, 21.5), (2, 21.5)])]),
    ('char-icon', 'Characters', [D(12, 6.6, 4.8), P(BODY, [halo(12, 6.6, 4.8)])]),
    ('ui-folder-icon', 'UI', [P(R(2, 2.5, 9.2, 21.5)), P(R(10.6, 2.5, 22, 9.5)), P(R(10.6, 10.9, 22, 21.5))]),
    ('vfx-folder-icon', 'VFX', [P([(10.6, 3.4), (13.3, 10.5), (20.4, 13.2), (13.3, 15.9), (10.6, 23), (7.9, 15.9), (.8, 13.2), (7.9, 10.5)], k=.7), D(19, 5, 2.9)]),
    ('text-folder-icon', 'Text', [P(R(2.5, 2.5, 21.5, 8)), P(R(9, 9.4, 15, 21.5))]),
    ('nameplate-folder-icon', 'Nameplates', [D(6.6, 12, 4.8), P(R(6, 6.5, 22.5, 17.5), [halo(6.6, 12, 4.8)])]),
    ('plugin-folder-icon', 'Plugins', [P(R(7.5, 1.5, 10.3, 7.2), k=.5), P(R(13.7, 1.5, 16.5, 7.2), k=.5), P([(4.5, 8.6), (19.5, 8.6), (19.5, 12.6), (15.5, 18.4), (8.5, 18.4), (4.5, 12.6)]), P(R(10.2, 19.8, 13.8, 23), k=.5)]),
    ('weapon-folder-icon', 'Weapons', [P(sword([(0, -14.6), (3.1, -10.4), (3.1, 3.6), (-3.1, 3.6), (-3.1, -10.4)]), k=.7), P(sword(R(-7.4, 5, 7.4, 8.2)), k=.6), P(sword(R(-1.9, 9.6, 1.9, 14.6)), k=.6)]),
    ('map-folder-icon', 'Maps', [P([(1.5, 5.5), (7.3, 2.5), (7.3, 18.5), (1.5, 21.5)], k=.7), P([(8.7, 2.5), (15.3, 5.5), (15.3, 21.5), (8.7, 18.5)], k=.7), P([(16.7, 5.5), (22.5, 2.5), (22.5, 18.5), (16.7, 21.5)], k=.7)]),
    ('blueprint-folder-icon', 'Blueprints', [P([(12, 1.2), (23, 10.4), (1, 10.4)], k=.7), P(R(3.5, 11.8, 20.5, 22.5))]),
    ('ability-folder-icon', 'Abilities', [P([(13.6, 1), (3.6, 13.6), (10.4, 13.6), (8.4, 23), (20.4, 9.6), (13.4, 9.6), (17.2, 1)], k=.5)]),
    ('data-folder-icon', 'Data', [Rg(slab(9.6, 3.2, 4.9, 4.9, cap=True)), Rg(slab(9.6, 3.2, 6.7, 11.7)), Rg(slab(9.6, 3.2, 13.5, 18.5))]),
    ('environment-folder-icon', 'Environment', [P([(12, 1), (18.5, 9.6), (5.5, 9.6)], k=.6), P([(6.3, 11), (17.7, 11), (21.5, 18), (2.5, 18)], k=.6), P(R(9.6, 19.4, 14.4, 23), k=.5)]),
    ('language-folder-icon', 'Languages', [P([(1.5, 2), (15.5, 2), (15.5, 12.5), (7.5, 12.5), (3, 16.6), (3, 12.5), (1.5, 12.5)], k=.8), P([(16.9, 6), (22.5, 6), (22.5, 18.5), (21, 18.5), (21, 22.5), (17, 18.5), (8.8, 18.5), (8.8, 13.9), (16.9, 13.9)], k=.8)]),
]
LABELS = {'texture-folder-icon': 'Textures', 'mesh-folder-icon': 'Meshes', 'material-folder-icon': 'Materials'}
ALL = [(c, LABELS[c], CORE_PIECES[c]) for c in LABELS] + OTHER_FOLDERS


def svg(pieces, spec):
    parts = []
    for piece in pieces:
        built = build(piece, spec)
        if 'circle' in built:
            parts.append('<circle cx="%.2f" cy="%.2f" r="%.2f"/>' % built['circle'])
        else:
            parts.append(f'<path d="{path_d(built["ring"])}"/>')
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor">{"".join(parts)}</svg>\n'


def inner(pieces, spec):
    markup = svg(pieces, spec)
    return markup[markup.index('>') + 1:markup.rindex('</svg>')]


def script():
    marks = {cls: {'master': inner(pieces, MASTER), 'small': inner(pieces, SMALL)} for cls, _label, pieces in ALL}
    roles = {cls: ROLES.get(cls, 'neutral') for cls, _label, _pieces in ALL}
    entries = ',\n'.join(f'  {json.dumps(cls)}:{json.dumps(sizes)}' for cls, sizes in marks.items())
    return ('// Generated by scripts/folder_emblems.py; edit the script, not this file.\n'
            '// Folder icons (SPEC section 3.5). Trusted generated markup, inlined by icons.js so the theme\'s colour reaches it.\n'
            '(()=>{\nconst marks={\n' + entries + '\n};\nconst roles=' + json.dumps(roles) + ';\nconst inks=' + json.dumps(EMBLEM_INKS) + ';\n'
            '// Each ink has to read at 3:1 on the card and on its thumb. Only its lightness moves.\n'
            'function fit(){const root=document.documentElement,css=getComputedStyle(root),mode=root.dataset.theme===\'dark\'?\'dark\':\'light\';\n'
            "  const surfaces=['--bg3','--bg2'].map(name=>css.getPropertyValue(name).trim()).filter(Boolean);\n"
            '  for(const [role,ink] of Object.entries(inks)){let color=ink[mode];\n'
            '    try{color=AtelierColourFit.fit(color,surfaces);}catch(_){}\n'
            "    root.style.setProperty('--studio-emblem-'+role,color);}}\n"
            "fit();window.addEventListener('atelier:inks',fit);\n"
            'window.AtelierFolderEmblems=Object.freeze({names:Object.freeze(Object.keys(marks)),roles:Object.freeze(roles),inks:Object.freeze(inks),\n'
            "  markup:(cls,size)=>marks[cls][size>=32?'master':'small']});\n})();\n")


def plain_folder():
    """The plain folder as card artwork, standing still in its category colour."""
    _cls, _label, (back, front) = next(entry for entry in ALL if entry[0] == 'folder-icon')
    part = lambda piece: f'<path d="{path_d(build(piece, MASTER)["ring"])}"/>'
    return ('<svg xmlns="http://www.w3.org/2000/svg" class="card-icon folder-icon studio-icon" viewBox="0 0 24 24" '
            'width="96" height="96" fill="currentColor" aria-hidden="true" focusable="false">'
            f'{part(back)}{part(front)}</svg>')


def targets():
    out = {}
    for cls, _label, pieces in ALL:
        out[EMBLEMS / f'{cls}-master.svg'] = svg(pieces, MASTER)
        out[EMBLEMS / f'{cls}-small.svg'] = svg(pieces, SMALL)
    out[ROOT / 'gui' / 'folder-emblems.js'] = script()
    page = ROOT / 'gui' / 'index.html'
    pattern = re.compile(r'(<!-- folder-emblems:plain:begin -->\n)(.*?)(\n<!-- folder-emblems:plain:end -->)', re.S)
    current = page.read_bytes().decode('utf-8').replace('\r\n', '\n')
    if not pattern.search(current):
        raise SystemExit('missing folder-emblems:plain markers in gui/index.html')
    out[page] = pattern.sub(lambda m: m.group(1) + plain_folder() + m.group(3), current)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--check', action='store_true', help='fail if a generated file is out of date')
    args = parser.parse_args()
    stale = []
    for path, wanted in targets().items():
        current = path.read_bytes().decode('utf-8').replace('\r\n', '\n') if path.exists() else None
        if current == wanted:
            continue
        stale.append(str(path.relative_to(ROOT)))
        if not args.check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(wanted.encode('utf-8'))
    if args.check and stale:
        print('Out of date (run scripts/folder_emblems.py): ' + ', '.join(stale), file=sys.stderr)
        return 1
    if not args.check and stale:
        print('Wrote ' + ', '.join(stale))
    return 0


if __name__ == '__main__':
    sys.exit(main())
