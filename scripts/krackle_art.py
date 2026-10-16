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


def micro_success(p):
    burst = path(starburst(12, 12, 11.2, 6.4, 10, 0.2), f'{p}-energy {p}-burst')
    hole = circle(12.6, 12.4, 2.35, f'{p}-hole {p}-burst-hole')
    flecks = ''.join(circle(12 + math.cos(a) * 9.6, 12 + math.sin(a) * 9.6, 1.05, f'{p}-energy {p}-fleck')
                     for a in FLECKS)
    return f'<g class="{p}-outcome {p}-outcome-success">{burst}{hole}<g class="{p}-flecks">{flecks}</g></g>'


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
    body = micro_drop_tray(p) + micro_busy(p) + micro_success(p) + micro_warning(p) + micro_error(p)
    return svg(f'{p}-svg', 24, body, extra=' fill="currentColor"')


def material_save():
    p = 'am-material-save'
    saving = micro_busy(p, f' {p}-saving-ring').replace('</g>', micro_swatch(p, 3.3, f'-mini').replace(f'{p}-idle-mini', f'{p}-mini') + '</g>', 1)
    body = micro_swatch(p) + saving + micro_success(p) + micro_warning(p) + micro_error(p)
    return svg(f'{p}-svg', 24, body, extra=' fill="currentColor"')


def krackle_glyph():
    p = 'am-krackle-glyph'
    body = micro_busy(p) + micro_info(p) + micro_success(p) + micro_warning(p) + micro_error(p)
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


# ── folder flap (96-unit viewBox, ~102px slot) ────────────────────────────────
def folder_flap():
    p = 'am-folder-flap'
    back = path('M6 13.5 Q6 11 8.5 11 H32.5 L39.5 18 H87.5 Q90 18 90 20.5 V80 H6 Z', f'{p}-energy {p}-panel')
    back_holes = ''.join(circle(x, y, r, f'{p}-hole') for x, y, r in ((80.5, 25.2, 1.5), (73.6, 24.6, 0.9)))
    front_body = path('M6 31 H90 V77.5 Q90 80 87.5 80 H8.5 Q6 80 6 77.5 Z', f'{p}-energy {p}-panel')
    bumps = ''.join(circle(x, 31.2, r, f'{p}-energy') for x, r in
                    ((10.5, 3.1), (19, 2.4), (27.5, 3.3), (37, 2.2), (46, 3.0), (55.5, 2.5), (64.5, 3.2), (74, 2.3), (83, 3.0), (88.2, 1.9)))
    # One overlapping mass in the lower right, a trail of satellites, and clean energy elsewhere.
    front_holes = ''.join(circle(x, y, r, f'{p}-hole') for x, y, r in
                          ((72, 65, 5.6), (64.5, 69.5, 4.2), (78.5, 58.5, 3.6), (68.5, 58.5, 2.6), (80.5, 69.5, 3.0),
                           (56, 72.5, 2.0), (59.5, 61.5, 1.5), (83.5, 50.5, 1.6), (51.5, 66.5, 1.1), (46, 72.5, 1.0),
                           (76.5, 47.5, 1.0), (40.5, 74, 0.8)))
    specks = circle(70.2, 63.2, 1.3, f'{p}-speck') + circle(63.4, 68.3, .8, f'{p}-speck')
    body = (f'<g class="{p}-back" opacity="1">{back}{back_holes}</g>'
            f'<g class="{p}-front" opacity="1">{front_body}{bumps}{front_holes}{specks}</g>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" class="card-icon folder-icon studio-icon {p}" viewBox="0 0 96 96" '
            f'width="96" height="96" fill="currentColor" aria-hidden="true" focusable="false">{body}</svg>')


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
def mask_uri(body, view=24):
    raw = f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {view} {view}'>{body}</svg>"
    return "url(\"data:image/svg+xml," + raw.replace('<', '%3C').replace('>', '%3E').replace('#', '%23').replace('"', "'") + "\")"


def spinner_masks():
    base = ''.join(f"<circle cx='{n(x)}' cy='{n(y)}' r='2.15'/>" for x, y in RING6)
    x0, y0 = RING6[0]
    x5, y5 = RING6[5]
    crest = f"<circle cx='{n(x0)}' cy='{n(y0)}' r='3.6'/><circle cx='{n(x5)}' cy='{n(y5)}' r='2.75'/>"
    return mask_uri(base), mask_uri(crest)


# ── writing ───────────────────────────────────────────────────────────────────
HEADER = {
    'export-feedback': 'Krackle export feedback: drop and tray (idle), six-dot charge ring (busy), starburst, cracked ring and splat.',
    'material-save': 'Krackle material save: shaded swatch (idle), charge ring around a small swatch (saving), starburst, cracked ring and splat.',
    'krackle-glyph': 'Krackle micro glyphs for notifications: charge ring, ink drop (info), starburst, cracked ring and splat.',
    'viewport-loader': 'Krackle viewport loader: twelve-dot charge ring around a boiling ball, resting bubbles (empty) and a knocked-out splat (error).',
    'folder-flap': 'Krackle folder: energy panels with one composed mass of bubbles. The front panel tips open on hover/focus.',
    'empty-assets': 'Krackle empty tray: a tray of energy holding a few loose bubbles, with a drop of ink waiting above it.',
    'empty-state': 'Krackle grid empty states: a tray with two bubbles (empty folder), three loose bubbles (no matches) and a splat (failed to load).',
}
ART = {'export-feedback': export_feedback, 'material-save': material_save, 'krackle-glyph': krackle_glyph,
       'viewport-loader': viewport_loader, 'folder-flap': folder_flap, 'empty-assets': empty_assets,
       'empty-state': empty_state}


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
        if name == 'folder-flap':
            out.setdefault(ROOT / 'gui' / 'index.html', []).append((name, markup, 'html'))
        elif name != 'empty-assets':
            out.setdefault(MOTION / f'{name}.js', []).append((name, f'  var SVG_MARKUP = {js_literal(markup)};', 'js'))
        else:
            inner = markup[markup.index('>') + 1:markup.rindex('</svg>')]
            out.setdefault(MOTION / f'{name}.js', []).append((name, f'  var SVG_INNER = {js_literal(inner)};', 'js'))
    base, crest = spinner_masks()
    out.setdefault(MOTION / 'krackle.css', []).append(('spinner', f'  --krackle-ring-mask: {base};\n  --krackle-crest-mask: {crest};', 'css'))
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
                file.write_text(wanted, encoding='utf-8')
    if args.check and stale:
        print('Out of date: ' + ', '.join(map(str, stale)))
        return 1
    print(('Up to date' if not stale else 'Wrote ' + ', '.join(map(str, stale))) if not args.check else 'Up to date')
    return 0


if __name__ == '__main__':
    sys.exit(main())
