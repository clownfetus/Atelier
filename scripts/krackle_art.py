#!/usr/bin/env python3
"""Krackle artwork for gui/motion.

Every Krackle illustration is drawn here once. The script writes the standalone SVG
files and the copies embedded in the motion controllers and index.html, so the two
never drift. Run it after changing any geometry:

    python scripts/krackle_art.py          # rewrite files
    python scripts/krackle_art.py --check  # fail if anything is out of date

Language rules (see the Krackle design doc): no outlines and no gradients. Energy is
a solid silhouette in currentColor; bubbles are holes punched into it, painted with
--krackle-hole so they show the surface colour behind. Results never draw a symbol:
success is a starburst, warning a cracked ring with its fallen chunk, error a splat.
"""
import argparse
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOTION = ROOT / 'gui' / 'motion'


def n(v):
    """Compact number for SVG attributes."""
    s = ('%.2f' % v).rstrip('0').rstrip('.')
    return '0' if s in ('-0', '') else s


def circle(cx, cy, r, cls, extra=''):
    return f'<circle class="{cls}" cx="{n(cx)}" cy="{n(cy)}" r="{n(r)}"{extra} />'


def path(d, cls, extra=''):
    return f'<path class="{cls}" d="{d}"{extra} />'


def poly(points):
    return 'M' + ' L'.join(f'{n(x)} {n(y)}' for x, y in points) + ' Z'


def arc_path(cx, cy, r, a0, a1):
    """Clockwise arc from angle a0 to a1 (radians, SVG y-down)."""
    x0, y0 = cx + math.cos(a0) * r, cy + math.sin(a0) * r
    x1, y1 = cx + math.cos(a1) * r, cy + math.sin(a1) * r
    large = 1 if (a1 - a0) % (2 * math.pi) > math.pi else 0
    return f'M{n(x0)} {n(y0)} A{n(r)} {n(r)} 0 {large} 1 {n(x1)} {n(y1)}'


def teardrop(cx, cy, r, tip_y):
    """A drop of ink: round belly at (cx, cy), point at tip_y above it."""
    k = (cy - tip_y)
    return (f'M{n(cx)} {n(tip_y)} C{n(cx + r * .42)} {n(tip_y + k * .42)} {n(cx + r)} {n(cy - r * .62)} '
            f'{n(cx + r)} {n(cy)} A{n(r)} {n(r)} 0 1 1 {n(cx - r)} {n(cy)} '
            f'C{n(cx - r)} {n(cy - r * .62)} {n(cx - r * .42)} {n(tip_y + k * .42)} {n(cx)} {n(tip_y)} Z')


def starburst(cx, cy, outer, inner, spikes, rot, jitter=()):
    pts = []
    for k in range(spikes * 2):
        a = rot + k * math.pi / spikes
        r = outer if k % 2 == 0 else inner
        if jitter:
            r *= jitter[k % len(jitter)]
        pts.append((cx + math.cos(a) * r, cy + math.sin(a) * r))
    return poly(pts)


# ── micro glyphs (24-unit viewBox) ───────────────────────────────────────────
# Shared by export feedback, material save and the generic Krackle glyph set.
RING6 = [(12 + math.cos(math.radians(-90 + 60 * k)) * 8.2,
          12 + math.sin(math.radians(-90 + 60 * k)) * 8.2) for k in range(6)]
GAP = 0.32 * math.pi          # warning: the ring breaks open at the lower right
ARC_C, ARC_R = (12, 10.8), 7.2
CHUNK_REST = (17.4, 20.9)
CHUNK_GAP = (ARC_C[0] + math.cos(GAP) * ARC_R, ARC_C[1] + math.sin(GAP) * ARC_R)
SPLAT_BODY = [(0, 0, .23), (-.17, .08, .13), (.16, -.1, .13), (.12, .15, .11), (-.1, -.15, .1)]
SPLAT_SATS = [(-.4, -.18, .06), (.42, .1, .055), (-.3, .34, .05), (.33, -.36, .05), (.36, .36, .04)]
FLECKS = [math.radians(a) for a in (-62, 30, 118, 208)]


def micro_busy(p, extra_cls=''):
    dots = ''.join(circle(x, y, 2.15, f'{p}-energy {p}-dot {p}-dot-{k}') for k, (x, y) in enumerate(RING6))
    holes = ''.join(circle(x, y, 1.05, f'{p}-hole {p}-dot-hole {p}-dot-hole-{k}') for k, (x, y) in enumerate(RING6))
    return f'<g class="{p}-busy{extra_cls}">{dots}{holes}</g>'


# The ink key: a key whose bow is the Krackle drop lying on its side, its point running into the
# blade, drawn in a 400-unit design box and cropped to KEY_VIEW. A glyph mounted with
# found: 'key' shows it in place of the starburst (the setup page's Unlock key row).
KEY_VIEW = (50, 124, 300, 152)          # x, y, width, height of the crop
# The key is half as tall as it is wide, so it runs 20% past the glyph's sides to keep its weight:
# 24px wide at the setup rows' 20px, still inside their 24-28px glyph column.
KEY_SPAN = 28.8


def micro_key(p):
    x, y, w, h = KEY_VIEW
    k = KEY_SPAN / w                     # centred on the glyph both ways
    place = f'translate({n((24 - KEY_SPAN) / 2)} {n((24 - h * k) / 2)}) scale({k:.4g}) translate({n(-x)} {n(-y)}) translate(200 200) skewX(-8) translate(-200 -200)'
    body = (path(teardrop(0, 0, 6, -13), f'{p}-energy', ' transform="translate(132 200) rotate(90) scale(11)"') +
            '<rect class="%s-energy" x="226" y="187" width="110" height="26" rx="13" />' % p +
            '<rect class="%s-energy" x="294" y="200" width="24" height="50" rx="12" />' % p +
            '<rect class="%s-energy" x="254" y="200" width="22" height="36" rx="11" />' % p +
            circle(128, 200, 27, f'{p}-hole {p}-key-hole') + circle(166, 232, 7, f'{p}-hole') +
            circle(98, 170, 8, f'{p}-glint'))
    return f'<g class="{p}-found {p}-key"><g transform="{place}">{body}</g></g>'


# The code file (the Mapping file row): a sheet with its top-right corner cut off and four code
# lines in the surface colour, drawn in a 20-unit box scaled to fill the glyph.
FILE_LINES = [(6, 7.4, 5), (7.8, 10.2, 6), (7.8, 13, 4.2), (6, 15.8, 7.5)]


def micro_file(p):
    body = poly([(3.5, 1), (12, 1), (16.5, 5.5), (16.5, 19), (3.5, 19)])
    lines = ''.join(f'<rect class="{p}-hole {p}-file-line" x="{n(x)}" y="{n(y)}" width="{n(w)}" height="1.6" rx="0.8" />'
                    for x, y, w in FILE_LINES)
    return f'<g class="{p}-found {p}-file"><g transform="scale(1.2)">{path(body, f"{p}-energy")}{lines}</g></g>'


# The folder (the Game folder row): a back with a tab, and a front panel that flips open. A
# surface-coloured halo behind the front keeps it a separate flap without an outline.
FOLDER_BACK = 'M2 4.6A1.6 1.6 0 0 1 3.6 3H7.4L9.2 5H16.4A1.6 1.6 0 0 1 18 6.6V15.4A1.6 1.6 0 0 1 16.4 17H3.6A1.6 1.6 0 0 1 2 15.4Z'


def micro_folder(p):
    flap = (f'<g class="{p}-folder-flap"><rect class="{p}-hole" x="1.4" y="7.4" width="17.2" height="10.2" rx="1.9" />'
            f'<rect class="{p}-energy" x="2" y="8.2" width="16" height="8.8" rx="1.6" /></g>')
    return f'<g class="{p}-found {p}-folder"><g transform="scale(1.2)">{path(FOLDER_BACK, f"{p}-energy")}{flap}</g></g>'


def micro_success(p, key=False):
    burst = path(starburst(12, 12, 11.2, 6.4, 10, 0.2), f'{p}-energy {p}-burst')
    hole = circle(12.6, 12.4, 2.35, f'{p}-hole {p}-burst-hole')
    flecks = ''.join(circle(12 + math.cos(a) * 9.6, 12 + math.sin(a) * 9.6, 1.05, f'{p}-energy {p}-fleck')
                     for a in FLECKS)
    return f'<g class="{p}-outcome {p}-outcome-success">{burst}{hole}{micro_key(p) + micro_file(p) + micro_folder(p) if key else ""}<g class="{p}-flecks">{flecks}</g></g>'


def micro_warning(p):
    half = 0.62
    arc = (f'<g class="{p}-ring">' + path(arc_path(*ARC_C, ARC_R, GAP + half, GAP - half + 2 * math.pi), f'{p}-arc') +
           circle(5.05, 9.15, 1.2, f'{p}-hole {p}-arc-hole') + '</g>')
    hole = ''
    chunk = (f'<g class="{p}-chunk">' + circle(*CHUNK_REST, 2.2, f'{p}-energy') +
             circle(CHUNK_REST[0] + .5, CHUNK_REST[1] + .3, .75, f'{p}-hole') + '</g>')
    return f'<g class="{p}-outcome {p}-outcome-warning">{arc}{hole}{chunk}</g>'


def micro_error(p):
    s = 24
    body = ''.join(circle(12 + x * s, 12 + y * s, r * s, f'{p}-energy') for x, y, r in SPLAT_BODY)
    sats = ''.join(circle(12 + x * s, 12 + y * s, r * s, f'{p}-energy {p}-sat') for x, y, r in SPLAT_SATS)
    drip = (f'<g class="{p}-drip">' + path('M8.64 16.32 V20.64', f'{p}-drip-line') +
            circle(8.64, 21.6, 1.68, f'{p}-energy') + '</g>')
    holes = circle(12.48, 11.76, 2.16, f'{p}-hole') + circle(8.4, 13.68, 1.08, f'{p}-hole')
    dizzy = (f'<g class="{p}-dizzy">' + circle(7.6, 3.3, 1.45, f'{p}-energy') +
             circle(7.9, 3.4, .62, f'{p}-hole') + '</g>')
    return (f'<g class="{p}-outcome {p}-outcome-error"><g class="{p}-splat">{body}{holes}</g>'
            f'<g class="{p}-sats">{sats}</g>{drip}{dizzy}</g>')


def micro_drop_tray(p):
    """Export idle: a drop of ink above a tray of energy."""
    tray = path('M5.7 17.4 H18.3 A1.7 1.7 0 0 1 18.3 20.8 H5.7 A1.7 1.7 0 0 1 5.7 17.4 Z', f'{p}-energy {p}-well')
    tray_holes = circle(8.2, 19.1, .85, f'{p}-hole') + circle(15.6, 19.1, .6, f'{p}-hole')
    drop = path(teardrop(12, 10.4, 3.7, 2.6), f'{p}-energy {p}-drop')
    drop_hole = circle(13.1, 11.3, 1.25, f'{p}-hole')
    return f'<g class="{p}-idle"><g class="{p}-tray">{tray}{tray_holes}</g><g class="{p}-drop-group">{drop}{drop_hole}</g></g>'


def micro_swatch(p, r=8.6, cls_extra=''):
    """Material idle: a ball of energy, shaded by bubbles, with a glint."""
    k = r / 8.6
    parts = [circle(12, 12, r, f'{p}-energy {p}-swatch'),
             circle(12 - 2.9 * k, 12 - 3.1 * k, 2.3 * k, f'{p}-glint'),
             circle(12 + 3.3 * k, 12 + 3.1 * k, 2.1 * k, f'{p}-hole'),
             circle(12 - .2 * k, 12 + 4.7 * k, 1.2 * k, f'{p}-hole'),
             circle(12 + 4.4 * k, 12 - .5 * k, 1.0 * k, f'{p}-hole')]
    return f'<g class="{p}-idle{cls_extra}">' + ''.join(parts) + '</g>'


def micro_info(p):
    drop = path(teardrop(12, 14.2, 5.4, 2.2), f'{p}-energy {p}-drop')
    hole = circle(13.7, 15.4, 1.7, f'{p}-hole')
    speck = circle(10.1, 12.9, .7, f'{p}-glint')
    return f'<g class="{p}-outcome {p}-outcome-info">{drop}{hole}{speck}</g>'


def svg(cls, view, body, size=None, extra=''):
    w = h = size or view
    return (f'<svg xmlns="http://www.w3.org/2000/svg" class="{cls}" viewBox="0 0 {view} {view}" width="{w}" height="{h}"'
            f' aria-hidden="true" focusable="false"{extra}>{body}</svg>')


def export_feedback():
    p = 'am-export-feedback'
    falling='<g class="am-export-feedback-fall">'+path(teardrop(12,12,4.5,1),p+'-energy')+circle(13,13,1.4,p+'-hole')+'</g>'
    body = micro_drop_tray(p) + falling + micro_busy(p) + micro_success(p) + micro_warning(p) + micro_error(p)
    return svg(f'{p}-svg', 24, body, extra=' fill="currentColor"')


def material_save():
    p = 'am-material-save'
    saving = micro_busy(p, f' {p}-saving-ring').replace('</g>', micro_swatch(p, 3.3, f'-mini').replace(f'{p}-idle-mini', f'{p}-mini') + '</g>', 1)
    body = micro_swatch(p) + saving + micro_success(p) + micro_warning(p) + micro_error(p)
    return svg(f'{p}-svg', 24, body, extra=' fill="currentColor"')


def krackle_glyph():
    p = 'am-krackle-glyph'
    body = micro_busy(p) + micro_info(p) + micro_success(p, key=True) + micro_warning(p) + micro_error(p)
    return svg(f'{p}-svg', 24, body, extra=' fill="currentColor"')


# ── viewport loader (48-unit viewBox, 72px) ───────────────────────────────────
def viewport_loader():
    p = 'am-viewport-loader'
    ring = [(24 + math.cos(math.radians(-90 + 30 * k)) * 16.5, 24 + math.sin(math.radians(-90 + 30 * k)) * 16.5)
            for k in range(12)]
    dots = ''.join(circle(x, y, 1.95, f'{p}-energy {p}-dot') for x, y in ring)
    dot_holes = ''.join(circle(x, y, .95, f'{p}-hole {p}-dot-hole') for x, y in ring)
    sphere = (f'<g class="{p}-sphere">' + circle(24, 24, 8.6, f'{p}-energy {p}-hull') +
              circle(21.1, 20.9, 2.4, f'{p}-glint') +
              ''.join(circle(x, y, r, f'{p}-hole {p}-boil') for x, y, r in
                      ((27.4, 27.3, 2.15), (23.4, 29.6, 1.3), (29.7, 22.9, 1.15), (26.3, 23.9, .8))) + '</g>')
    loose = ''.join(f'<g class="{p}-loose">' + circle(x, y, r, f'{p}-rift') + circle(x + r * .2, y + r * .15, r * .45, f'{p}-hole') + '</g>'
                    for x, y, r in ((6.4, 9.2, 1.55), (41.6, 11.6, 1.25), (41.2, 39.4, 1.45)))
    empty = (f'<g class="{p}-outcome {p}-outcome-empty">' +
             ''.join(f'<g class="{p}-rest">' + circle(x, y, r, f'{p}-energy') + circle(x + r * .25, y + r * .2, r * .45, f'{p}-hole') + '</g>'
                     for x, y, r in ((17.6, 39.6, 2.6), (24.6, 40.6, 1.9), (30.6, 39.8, 2.25))) + '</g>')
    s = 40.8
    cx, cy = 24, 27.5
    splat = ''.join(circle(cx + x * s, cy + y * s, r * s, f'{p}-energy') for x, y, r in SPLAT_BODY)
    sats = ''.join(circle(cx + x * s, cy + y * s, r * s, f'{p}-energy {p}-sat') for x, y, r in SPLAT_SATS)
    drip = (f'<g class="{p}-drip">' + path(f'M{n(cx - .14 * s)} {n(cy + .18 * s)} V{n(cy + .36 * s)}', f'{p}-drip-line') +
            circle(cx - .14 * s, cy + .4 * s, .07 * s, f'{p}-energy') + '</g>')
    holes = (circle(cx + .02 * s, cy - .01 * s, .09 * s, f'{p}-hole') + circle(cx - .15 * s, cy + .07 * s, .045 * s, f'{p}-hole') +
             circle(cx + .1 * s, cy + .12 * s, .035 * s, f'{p}-hole'))
    dizzy = ''.join(f'<g class="{p}-dizzy {p}-dizzy-{k}">' + circle(24 + math.cos(a) * 6.2, 8.6 + math.sin(a) * 1.9, 1.35, f'{p}-energy') +
                    circle(24 + math.cos(a) * 6.2 + .3, 8.6 + math.sin(a) * 1.9 + .2, .55, f'{p}-hole') + '</g>'
                    for k, a in enumerate((math.radians(200), math.radians(320), math.radians(80))))
    error = (f'<g class="{p}-outcome {p}-outcome-error"><g class="{p}-splat">{splat}{holes}</g>'
             f'<g class="{p}-sats">{sats}</g>{drip}{dizzy}</g>')
    body = (f'<g class="{p}-loading"><g class="{p}-ring">{dots}{dot_holes}</g>{sphere}{loose}</g>' + empty + error)
    return svg(f'{p}-svg', 48, body, size=72, extra=' fill="currentColor"')


# ── empty edited-assets tray (112-unit viewBox) ───────────────────────────────
def empty_assets():
    p = 'am-empty-assets'
    guides = ''.join(circle(x, y, r, f'{p}-svg__guide-dot') for x, y, r in
                     ((14, 18, 2.1), (19.5, 18, 1.4), (24, 18, .8), (14, 23.5, 1.4), (14, 28, .8),
                      (98, 18, 2.1), (92.5, 18, 1.4), (88, 18, .8), (98, 23.5, 1.4), (98, 28, .8)))
    drop = path(teardrop(56, 33, 6.4, 14.5), f'{p}-svg__drop')
    drop_hole = circle(57.9, 34.6, 2.1, f'{p}-svg__hole')
    bubbles = ''.join(f'<g class="{p}-svg__bubble">' + circle(x, y, r, f'{p}-svg__charge') +
                      circle(x + r * .25, y + r * .2, r * .44, f'{p}-svg__hole') + '</g>'
                      for x, y, r in ((40.5, 60.5, 5.2), (55, 57.5, 6.6), (69.5, 61.5, 4.4), (79, 64.5, 2.6)))
    well = path('M17 56 H95 L104 68 H8 Z', f'{p}-svg__well')
    face = path('M8 68 H104 L97.5 93.5 Q97 96 94.5 96 H17.5 Q15 96 14.5 93.5 Z', f'{p}-svg__face')
    bumps = ''.join(circle(x, 68.4, r, f'{p}-svg__face') for x, r in
                    ((12.5, 3.0), (22, 2.4), (32, 3.2), (43, 2.3), (54, 3.1), (65, 2.4), (76, 3.3), (87, 2.4), (98.5, 2.9)))
    face_holes = ''.join(circle(x, y, r, f'{p}-svg__hole') for x, y, r in
                         ((82, 85, 5.0), (75, 88.5, 3.6), (88, 79, 3.0), (76.5, 80, 2.2), (89.5, 87, 2.4),
                          (66, 89, 1.8), (70, 77, 1.3), (58, 86, 1.1), (93, 73.5, 1.0)))
    specks = circle(80.6, 83.7, 1.2, f'{p}-svg__speck') + circle(74, 87.5, .7, f'{p}-svg__speck')
    body = (f'<g class="{p}-plane {p}-plane--guides">{guides}</g>'
            f'<g class="{p}-plane {p}-plane--deck"><g class="{p}-svg__drop-group">{drop}{drop_hole}</g>{bubbles}</g>'
            f'<g class="{p}-plane {p}-plane--tray">{well}{face}{bumps}{face_holes}{specks}</g>')
    return svg(f'{p}-svg', 112, body, extra=' fill="none"')


# ── grid empty states (64-unit viewBox) ───────────────────────────────────────
def empty_state():
    p = 'am-empty-state'
    def bubble(x, y, r, cls):
        return f'<g class="{p}-bubble {cls}">' + circle(x, y, r, f'{p}-energy') + circle(x + r * .24, y + r * .2, r * .44, f'{p}-hole') + '</g>'
    tray = (path('M10 40 H54 L59 47 H5 Z', f'{p}-energy {p}-well') +
            path('M5 47 H59 L55.5 60 Q55 62 53 62 H11 Q9 62 8.5 60 Z', f'{p}-energy {p}-face') +
            ''.join(circle(x, 47.3, r, f'{p}-energy {p}-face') for x, r in ((9, 2), (17, 1.6), (25, 2.1), (33, 1.5), (41, 2.0), (49, 1.6), (56.5, 1.9))) +
            ''.join(circle(x, y, r, f'{p}-hole') for x, y, r in ((46, 56, 2.8), (41.5, 58.5, 2.0), (50, 52.5, 1.8), (36, 57, 1.1), (53, 57.5, 1.2))))
    empty = (f'<g class="{p}-kind {p}-kind-empty"><g class="{p}-tray">{tray}</g>' +
             bubble(26, 37, 3.6, f'{p}-drop-a') + bubble(36.5, 35.5, 4.6, f'{p}-drop-b') + '</g>')
    none = (f'<g class="{p}-kind {p}-kind-none">' + bubble(18, 44, 5.4, f'{p}-drop-a') + bubble(34, 47, 3.8, f'{p}-drop-b') +
            bubble(46.5, 41, 4.7, f'{p}-drop-c') +
            ''.join(circle(x, 55.5, r, f'{p}-floor') for x, r in ((12, .9), (17, 1.3), (22, .9), (30, .7), (35, 1.1), (40, .7), (46, 1.2), (51, .8))) + '</g>')
    s = 52
    cx, cy = 32, 33
    splat = ''.join(circle(cx + x * s, cy + y * s, r * s, f'{p}-energy') for x, y, r in SPLAT_BODY)
    sats = ''.join(circle(cx + x * s, cy + y * s, r * s, f'{p}-energy {p}-sat') for x, y, r in SPLAT_SATS)
    drip = (f'<g class="{p}-drip">' + path(f'M{n(cx - .14 * s)} {n(cy + .18 * s)} V{n(cy + .34 * s)}', f'{p}-drip-line') +
            circle(cx - .14 * s, cy + .38 * s, .065 * s, f'{p}-energy') + '</g>')
    holes = circle(cx + .02 * s, cy - .01 * s, .09 * s, f'{p}-hole') + circle(cx - .15 * s, cy + .07 * s, .045 * s, f'{p}-hole')
    error = f'<g class="{p}-kind {p}-kind-error"><g class="{p}-splat">{splat}{holes}</g><g class="{p}-sats">{sats}</g>{drip}</g>'
    return svg(f'{p}-svg', 64, empty + none + error, extra=' fill="currentColor"')


# ── spinner and Activity masks (CSS data URIs) ────────────────────────────────
# ── setup check (identity v1.0): the launch check draws the Projects header rule ──
# Each part is drawn about its own anchor; setup-check.js measures the header and moves
# them onto the rule. The preview below lays them out along one 520-unit band.
SETUP_FLECKS = [(-30, -22, 2.6), (-31, 20, 2.2), (22, -27, 2), (24, 26, 2.4)]
SETUP_SATS = [(-28, -12, 2.9), (29, 7, 2.6), (-21, 24, 2.4), (23, -25, 2.4), (25, 25, 1.9)]


def setup_check():
    p = 'am-setup-check'
    e, h, g = f'{p}-energy', f'{p}-hole', f'{p}-glint'
    track = path('M44 36 H320', f'{p}-track')
    pour = path('M44 36 H320', f'{p}-pour', ' pathLength="1"')
    # The reservoir: a drop resting on the rule, its bubbles massed low on the channel side.
    drop = (f'<g class="{p}-drop" transform="translate(22 36)"><g class="{p}-drop-ink">' + circle(0, 0, 18, e) +
            circle(4, 5, 4.2, h) + circle(-2.5, 10.5, 1.9, h) + circle(9, -3, 1.6, h) + circle(-6.5, -7, 1.6, g) + '</g></g>')
    # The latch: a receiver open towards the channel, anchored on its right edge.
    latch = (f'<g class="{p}-latch" transform="translate(356 36)"><g class="{p}-latch-ink">' +
             path('M-26 -22 H-10 Q0 -22 0 -12 V12 Q0 22 -10 22 H-26 Q-36 22 -36 12 V10 H-12 V-10 H-36 V-12 Q-36 -22 -26 -22 Z', e) +
             circle(-6, 15, 2.2, h) + '</g></g>')
    # Results replace the latch, anchored on its centre.
    burst = path(starburst(0, 0, 24, 12.6, 8, -math.pi / 2), f'{e} {p}-burst')
    flecks = ''.join(circle(x, y, r, f'{e} {p}-fleck') for x, y, r in SETUP_FLECKS)
    success = (f'<g class="{p}-result {p}-success" transform="translate(400 36)"><g class="{p}-burst-ink">' + burst +
               circle(4, 5, 2.8, h) + circle(-6, -7, 1.6, g) + f'</g><g class="{p}-flecks">{flecks}</g></g>')
    ring = (f'<g class="{p}-ring">' + path(arc_path(0, 0, 15, GAP + .55, GAP - .55 + 2 * math.pi), f'{p}-arc') +
            circle(-14.1, -5.1, 1.6, h) + circle(-5.1, -14.1, 1.3, g) + '</g>')
    chunk = f'<g class="{p}-chunk">' + path('M14 26 L23 24.5 L24.5 31 L15 32.5 Z', e) + circle(19.2, 28.6, 1.3, h) + '</g>'
    warning = f'<g class="{p}-result {p}-warning" transform="translate(452 36)">{ring}{chunk}</g>'
    body = ''.join(circle(x * 64, y * 64, r * 64, e) for x, y, r in SPLAT_BODY)
    sats = ''.join(circle(x, y, r, f'{e} {p}-sat') for x, y, r in SETUP_SATS)
    drip = f'<g class="{p}-drip">' + path('M-9 11.5 V21.5', f'{p}-drip-line') + circle(-9, 23.5, 3.4, e) + '</g>'
    dizzy = f'<g class="{p}-dizzy">' + circle(-10, -22, 2.9, e) + circle(-9.4, -21.8, 1.2, h) + '</g>'
    error = (f'<g class="{p}-result {p}-error" transform="translate(500 36)"><g class="{p}-splat">{body}' +
             circle(1.28, -.64, 5.5, h) + circle(-9.6, 4.5, 2.9, h) + circle(-5.3, -6.7, 2, g) +
             f'</g><g class="{p}-sats">{sats}</g>{drip}{dizzy}</g>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" class="{p}-svg" viewBox="0 0 520 72" width="520" height="72"'
            f' aria-hidden="true" focusable="false" fill="currentColor">{track}{pour}{drop}{latch}{success}{warning}{error}</svg>')


# The first-run drop: one drop of ink that runs down a dotted line through the setup rows' glyph
# column and falls into the export review's ink-well (gui/motion/ink-well.js), whose label is the
# page's own Open Atelier button. The drop sits belly-down on its anchor, point up; the dot is one
# dot of the line it follows.
# The well's lid is a status, not decoration: shut in the energy ink while rows need the person,
# open in the done colour once every row is valid. A pill over the mouth, 8px past the rim on
# each side and 4px above it, with a 24x10 knob on top; it swings about its left cap's centre
# (8, 15 in its own box). Drawn for the page's 240px well (rim 91.5px); other sizes scale it.
LID = (108, 16, 24, 10)                  # pill width and height, knob width and height


def setup_drop():
    p = 'am-setup-drop'
    drop = (f'<g class="{p}-drop">' + path(teardrop(0, 0, 6, -13), f'{p}-energy') + circle(-2.2, -1.6, 1.3, f'{p}-glint') + '</g>')
    w, h, kw, kh = LID
    kx = (w - kw) / 2
    knob = f'M{n(kx)} {n(kh)} V6 Q{n(kx)} 0 {n(kx + 6)} 0 H{n(kx + kw - 6)} Q{n(kx + kw)} 0 {n(kx + kw)} 6 V{n(kh)} Z'
    lid = (f'<svg class="{p}-lid" viewBox="0 0 {w} {h + kh - 3}" width="{w}" height="{h + kh - 3}" x="14" y="-14" overflow="visible">'
           f'<g class="{p}-lid-swing">' + path(knob, f'{p}-lid-energy') +
           f'<rect class="{p}-lid-energy" x="0" y="{n(kh - 3)}" width="{w}" height="{h}" rx="{n(h / 2)}" /></g></svg>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" class="{p}-svg" viewBox="-7 -14 {w + 22} 30" width="{w + 22}" height="30"'
            f' aria-hidden="true" focusable="false" fill="currentColor">{drop}' + circle(0, 12, 1.8, f'{p}-dot') + lid + '</svg>')


def mask_uri(body, view=24):
    raw = f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {view} {view}'>{body}</svg>"
    return "url(\"data:image/svg+xml," + raw.replace('<', '%3C').replace('>', '%3E').replace('#', '%23').replace('"', "'") + "\")"


def spinner_masks():
    base = ''.join(f"<circle cx='{n(x)}' cy='{n(y)}' r='2.15'/>" for x, y in RING6)
    x0, y0 = RING6[0]
    x5, y5 = RING6[5]
    crest = f"<circle cx='{n(x0)}' cy='{n(y0)}' r='3.6'/><circle cx='{n(x5)}' cy='{n(y5)}' r='2.75'/>"
    return mask_uri(base), mask_uri(crest)


def fluid_spinner_masks():
    """A source, continuous S-shaped conduit and catch plate with true holes."""
    conduit = 'M5 5C5 9 10 7 10 11C10 15 16 12 16 18'
    source = 'M1.5 4C1.5 1 5.5 .7 7.5 2.6C9 4.2 7.1 7 5.2 7.5C3 8 1.2 6.4 1.5 4Z'
    receiver = 'M10 18C10 15.8 13.1 15 16 15C19 15 22.5 16.3 22.5 18.2C22.5 20.8 18.5 22 15.5 21.5C12 21.4 9.5 20.1 10 18Z'
    holes = ("<defs><mask id='h' maskUnits='userSpaceOnUse' x='0' y='0' width='24' height='24'>"
             "<rect width='24' height='24' fill='white'/><circle cx='4.5' cy='3.8' r='.85' fill='black'/>"
             "<circle cx='16.8' cy='18.4' r='1.15' fill='black'/><circle cx='12.9' cy='18.8' r='.55' fill='black'/>"
             "</mask></defs>")
    def silhouette(width):
        return mask_uri(holes + "<g mask='url(#h)' fill='white'>"
                        + f"<path d='{conduit}' fill='none' stroke='white' stroke-width='{width}' stroke-linecap='round' stroke-linejoin='round'/>"
                        + f"<path d='{source}'/><path d='{receiver}'/></g>")
    return silhouette(3.8), silhouette(6.4)


# ── writing ───────────────────────────────────────────────────────────────────
HEADER = {
    'export-feedback': 'Krackle export feedback: drop and tray (idle), six-dot charge ring (busy), starburst, cracked ring and splat.',
    'material-save': 'Krackle material save: shaded swatch (idle), charge ring around a small swatch (saving), starburst, cracked ring and splat.',
    'krackle-glyph': 'Krackle micro glyphs for notifications: charge ring, ink drop (info), starburst (or the ink key, code file and folder), cracked ring and splat.',
    'viewport-loader': 'Krackle viewport loader: twelve-dot charge ring around a boiling ball, resting bubbles (empty) and a knocked-out splat (error).',
    'empty-assets': 'Krackle empty tray: a tray of energy holding a few loose bubbles, with a drop of ink waiting above it.',
    'empty-state': 'Krackle grid empty states: a tray with two bubbles (empty folder), three loose bubbles (no matches) and a splat (failed to load).',
    'setup-check': 'Krackle setup check: a drop pours along the header rule into a latch (busy), which becomes a starburst, cracked ring or splat.',
    'setup-drop': 'Krackle setup drop: one drop follows a dotted line down the setup rows and falls into the ink-well, whose lid is its status.',
}
ART = {'export-feedback': export_feedback, 'material-save': material_save, 'krackle-glyph': krackle_glyph,
       'viewport-loader': viewport_loader, 'empty-assets': empty_assets,
       'empty-state': empty_state, 'setup-check': setup_check, 'setup-drop': setup_drop}


def standalone(name, markup):
    pretty = re.sub(r'(<g |<circle |<path |</g>|</svg>)', r'\n\1', markup)
    return f'<!-- Atelier — {HEADER[name]}\n     Generated by scripts/krackle_art.py; edit the script, not this file. -->\n{pretty.strip()}\n'


def js_literal(markup):
    return "'" + markup.replace('\\', '\\\\').replace("'", "\\'") + "'"


def replace_region(text, name, payload, kind):
    if kind == 'js':
        pattern = re.compile(r'(// krackle-art:%s:begin\n)(.*?)(\s*// krackle-art:%s:end)' % (name, name), re.S)
    else:
        pattern = re.compile(r'(<!-- krackle-art:%s:begin -->\n)(.*?)(\n<!-- krackle-art:%s:end -->)' % (name, name), re.S)
    if not pattern.search(text):
        raise SystemExit(f'missing krackle-art:{name} markers')
    return pattern.sub(lambda m: m.group(1) + payload + m.group(3), text)


def targets():
    out = {}
    for name, fn in ART.items():
        markup = fn()
        out[MOTION / f'{name}.svg'] = ('whole', standalone(name, markup))
        if name != 'empty-assets':
            out.setdefault(MOTION / f'{name}.js', []).append((name, f'  var SVG_MARKUP = {js_literal(markup)};', 'js'))
        else:
            inner = markup[markup.index('>') + 1:markup.rindex('</svg>')]
            out.setdefault(MOTION / f'{name}.js', []).append((name, f'  var SVG_INNER = {js_literal(inner)};', 'js'))
    base, crest = spinner_masks()
    out.setdefault(MOTION / 'krackle.css', []).append(('spinner', f'  --krackle-ring-mask: {base};\n  --krackle-crest-mask: {crest};', 'css'))
    fluid, pressure = fluid_spinner_masks()
    out.setdefault(MOTION / 'krackle.css', []).append(('fluid-spinner', f'  --krackle-fluid-mask: {fluid};\n  --krackle-fluid-pressure-mask: {pressure};', 'css'))
    corner='M0 0H24V24Z'
    for x,y,r in [(10,3,1.3),(17,4,2),(20,10,1.6)]:
        corner+=f'M{n(x+r)} {y}a{r} {r} 0 1 0 {-2*r} 0a{r} {r} 0 1 0 {2*r} 0Z'
    out.setdefault(MOTION/'krackle.css',[]).append(('edited-corner','  --krackle-edited-mask: '+mask_uri("<path fill-rule='evenodd' d='"+corner+"'/>")+';','css'))
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    stale = []
    for file, job in targets().items():
        current = file.read_text(encoding='utf-8') if file.exists() else ''
        if isinstance(job, tuple):
            wanted = job[1]
        else:
            wanted = current
            for name, payload, kind in job:
                if kind == 'css':
                    pattern = re.compile(r'(/\* krackle-art:%s:begin \*/\n)(.*?)(\n\s*/\* krackle-art:%s:end \*/)' % (name, name), re.S)
                    if not pattern.search(wanted):
                        raise SystemExit(f'missing krackle-art:{name} markers in {file}')
                    wanted = pattern.sub(lambda m: m.group(1) + payload + m.group(3), wanted)
                else:
                    wanted = replace_region(wanted, name, payload, kind)
        if wanted != current:
            stale.append(file.relative_to(ROOT))
            if not args.check:
                file.parent.mkdir(parents=True,exist_ok=True)
                file.write_text(wanted, encoding='utf-8')
    if args.check and stale:
        print('Out of date: ' + ', '.join(map(str, stale)))
        return 1
    print(('Up to date' if not stale else 'Wrote ' + ', '.join(map(str, stale))) if not args.check else 'Up to date')
    return 0


if __name__ == '__main__':
    sys.exit(main())
