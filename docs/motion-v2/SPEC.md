# Motion system v2: specification

Every number here comes from `reference/motion-prototype.html` (the approved
behaviour) and `../brand/Atelier_Brand_Bible_v1.2.pdf`. Where this file and the
prototype disagree, the prototype wins: tell Thiago and fix this file. Where bible
v1.2 draws the mark or describes the click differently (p.3, p.4, p.9, p.10), this
file wins until the bible is updated (D14, D15).

Units: `u` = design units of the 480 × 400 glyph canvas (centre 240, 200). The
master A is 260u tall. Angles in degrees, SVG convention (positive = clockwise).

## 1. Invariants

These are the rules the whole system exists to keep. Every task's acceptance
check includes them.

1. **Three opaque pieces.** Texture tile (blue), mesh block (teal), material
   disc (copper). No transparency, blending, gradients, glow, bevels or
   outlines. The one exception is the loaders' flat, opaque colours and cuts on a
   piece while it works (§4.7, D16).
2. **Fixed layer order.** Tile at the back, mesh in the middle, disc in front,
   always. Nothing ever re-stacks, fades through, or dissolves.
3. **The halo.** Every piece is drawn with a stroke in the colour of the surface
   behind it: `stroke-width: 28u` (2 × 14u), `paint-order: stroke`,
   `stroke-linejoin: round`. Pieces never visually merge, even when they're all
   the same colour. The tile and mesh carry their notch and bites in the A and the
   wrong fits, so the animated A is the brand mark exactly, and flatten into plain
   bars for the `!` and X.
4. **Physical motion.** Pieces travel one at a time along planned curves that
   keep 14u clear of everything else, measured on the outlines actually drawn. In
   the rare move with no clear path, the fixed layer order means one piece simply
   passes in front of another. The two exceptions to one at a time are Complete's
   brisk move into the A (§4.3, D15) and the brisk opening out of an outcome (§4.1,
   D16).
5. **The A is earned.** Only a confirmed success (`job.state === 'succeeded'`
   with nothing skipped) forms the A. Never a timer, never a guess. The one exception
   is the header logo's entrance (§4.8, D8), which isn't a status: it never turns
   green or clicks.
6. **Moves land.** A move in flight always finishes (at most 640 ms) before a
   new state takes over. Status *text* updates immediately.
7. **Shape first, then colour.** A status colour only arrives after its shape
   has formed.
8. **Working poses never look like an A, an exclamation mark or an X.**
9. **Only `busy` loops.** Results animate once and hold. (Exception: the
   warning's gentle wobble continues while the warning stands; see §4.4.)
10. **The brand mark is not the status glyph.** The app icon, header logo,
    lockups and installer art always use category colours and the master A. They're
    still, apart from the header logo's single entrance on launch (§4.8, D8).

## 2. Colour

| Role | Hex | Use |
| --- | --- | --- |
| Texture / blue | `#6C98CA` | Tile; texture asset type |
| Mesh / teal | `#5AAA9A` | Mesh block; mesh asset type |
| Material / copper | `#DF8F6B` | Disc; material asset type |
| Charcoal | `#0D151F` | Dark canvas; ink on light UI |
| Surface | `#172331` | Cards, panels |
| Paper | `#F4F6F8` | Primary text on dark; light canvas |
| Mist | `#B4C0CE` | Body text on dark (9.9:1 on Charcoal) |
| Guide | `#778BA3` | Rules, captions, Working status (not body text) |
| Complete green | `#7CC47F` | Success (hue 122°; mesh teal is 168°) |
| Warning amber | `#E6C35C` | Warning (hue 45°; copper is 19°) |
| Error rose | `#EC6A86` | Error (hue 347°) |
| Loader plates | `#6C98CA`, `#5CB4D6`, `#9686D6`, `#5F6FD0`, `#B57FD0` | Texture loader's bands only (§4.7) |
| Loader shine | `#F0BEA6` | Material loader's band of light only (§4.7) |

Category colours never appear on progress bars, buttons or links. Status
colours never appear on the brand mark outside the status glyph. Status is
always icon + sentence + colour; colour is the third cue.

Only texture, mesh and material carry colour in the interface (D2). Every other
category is neutral and told apart by shape. The brand mark and the glyph's
pieces always use the exact hexes above, in every theme, and only a working loader
adds the plates or the shine. Small UI icons use these
values, because the exact hexes only reach 2.3–2.8:1 on Paper:

| Small UI icon | Dark UI | Light UI, thin glyph (4.5:1) | Light UI, solid emblem (3:1) |
| --- | --- | --- | --- |
| Texture | `#6C98CA` | `#38679D` | `#5084C0` |
| Mesh | `#5AAA9A` | `#386D63` | `#498D80` |
| Material | `#DF8F6B` | `#A24B23` | `#D0602D` |
| Any other category | Mist `#B4C0CE` (thin), Guide `#778BA3` (solid) | `#4E5F73` | `#6A7C90` |

Themes (D3): the three piece colours never change with the theme, and the halo
always equals the surface behind it. Status hues stay fixed and `theme.js` moves
only their lightness, with no minimum distance from the accent. Presets and custom
palettes keep their own accents. Progress bars use the theme's text colour, never
the accent. The Atelier preset uses these values; derive any other role at P1.3,
and it must pass `tests/design_checks.py`.

| Atelier preset | Dark | Light |
| --- | --- | --- |
| Canvas | Charcoal `#0D151F` | Paper `#F4F6F8` |
| Lowest surface | `#0A1018` | `#FFFFFF` |
| Card | Surface `#172331` | `#FFFFFF` |
| Container | `#1C2936` | `#EEF1F4` |
| Raised | `#212E3B` | `#E6EAEF` |
| Highest | `#2A3847` | `#DDE3EA` |
| Rules | `#24323F` | `#DDE3EA` |
| Text | Paper `#F4F6F8` | Charcoal `#0D151F` |
| Muted text | Mist `#B4C0CE` | `#4E5F73` |
| Hints and captions | Guide `#778BA3` | `#6A7C90` |
| Accent | Paper `#F4F6F8` | Charcoal `#0D151F` |
| Text on accent | Charcoal `#0D151F` | Paper `#F4F6F8` |
| Info text | Mist `#B4C0CE` | `#4E5F73` |
| Status sentences: complete, warning, error | `#7CC47F`, `#E6C35C`, `#EC6A86` | `#337136`, `#7A6013`, `#C5193E` |
| Status icons and glyph: complete, warning, error | `#7CC47F`, `#E6C35C`, `#EC6A86` | `#419145`, `#9E7C18`, `#E74165` |

In dark, rose sentences reach only 3.97:1 on Highest, so status sentences stay off
that surface. Guide reaches only 3.96:1 on Raised, so it is never body text.

## 3. Geometry

### 3.1 Static mark (SVG assets in `assets/`)

Generated by `assets/brand_mark_v2.py`. Treat the SVGs as canonical; never
redraw by hand.

| | Master (≥ 32 px) | Small (< 32 px) |
| --- | --- | --- |
| Box | 401.84 × 260 | 400.41 × 260 |
| Disc centre, r | (208,146), 50 | (208,146), 40 |
| Gap g | 14 | 32 (2 px at 16 px) |
| Bite radius R = r + g | 64, concentric with disc | 72 |
| Tile corners: top, notch, bite lips, lower right | 10.5, 7, 23.5 and 25.5, 40.5 | 14, 9, 26 and 26, 42 |
| Mesh corners: top left, top right, lower right, lower left | 9.5, 38, 15, 14.5 | 14, 40, 18, 18 |
| Mesh bite lips | 12.5 and 13 | 14 and 14 |

Both sizes share the rest of the drawing: tile right edge at x 181.5, notch 43.5 ×
44.5 at the top left, large lower-right corner of radius 57; mesh top from x 206.5
to 305, bottom from x 292 to 409. The tile and mesh are lines and tangent arcs only.
The script's `MASTER` and `SMALL` hold every value.

Clearspace = r on every side. Wordmark: Inter Display SemiBold, +110 tracking,
outlined; the A is a crossbarless Λ with a copper disc (r = 0.118 cap height,
centre 28.5% of cap height above the baseline). Minimum wordmark cap height 12 px.

### 3.2 Animated pieces (in the engine)

| Piece | Parameters (master) | Shape |
| --- | --- | --- |
| Tile (`blue`) | w 181.5, h 260, m 1 | At `m` 1, the mark's tile. At `m` 0, a plain bar: `{w, h, k, taper}`, with the right edge narrowing by `taper` towards the bottom |
| Mesh (`teal`) | w 189.5, h 260, m 1 | At `m` 1, the mark's mesh. At `m` 0, a plain bar: `{w, h, k, dx}`, with the bottom edge offset by `dx` |
| Disc (`disc`) | r 50 | Circle |

Each piece also has `x, y` (centre) and `rot`. Master pose on the canvas: tile
(129.83, 200), mesh (346.17, 200), disc (247.08, 216), all `rot` 0.

The `m` 1 outlines are sampled from `assets/atelier-mark-pieces.json`, generated
with the mark, so the static and animated A match. Each outline is cut into named
sections, and a plain bar is sampled to the same counts, so a piece morphs section
by section as `m` moves between 0 and 1. The bites are drawn on the pieces, and the
halo only separates them. Clearance is always measured on these drawn outlines,
never on a coarse hull. The gap under the bites (86u) is narrower than the disc
(100u), which is why the disc can't reach its seat with the mesh in place (§4.1).

### 3.3 Poses

- **Master (complete, brand):** above.
- **Warning (balancing stack):** dot r 40 at the bottom; mesh `{w 80, h 140,
  dx 0, k 20, m 0}` standing on it; tile `{w 128, taper 18, h 110, k 20, m 0}` on
  top. 14u from dot to stem, 18u from stem to tile, because the tile sits at an
  angle and its near corner must clear the stem's halo as it sways. Rest pose is
  deliberately off true: stem lean `th = 2.5°`, tile tip `ph = -4.5°` relative to
  the stem, tile shifted 12u along the stem's top. Whole stack vertically centred
  (362u tall).
- **Error (crossing X):** both bars `{w 96, h 340, k 24, m 0}` (mesh `dx 0`, tile
  `taper 0`), scaled 0.92, crossing at the centre at tile −42°, mesh +42°;
  disc r 46 × 0.92 pinned at the crossing, in front.
- **At rest (`info`, D4, and the base of every loader, D16):** pieces still, in a row
  on one baseline, in the order mesh, tile, disc, in category colours. Any other order
  reads as an A. Built at 0.66 scale, with the notch and bites (`m` 1), 30u between
  neighbours on the drawn outlines, and the row centred on the canvas. _The prototype
  has this size and spacing; Thiago signs them off at P2.8._

Scale is baked into piece dimensions, never applied as a group transform, so
the halo stays 14u everywhere.

### 3.4 Wrong fits (working)

Built at 0.58 scale, with the notch and bites (`m` 1). The anchor is placed at the
centre; each docking piece slides in along `dir` until it sits exactly 16u from what
it docks to, measured on the drawn outlines; the arrangement is then re-centred.
`drift` = rotation added in the apart pose.

| Fit | Rotations (tile, mesh) | Anchor | Docks (piece: direction → onto) |
| --- | --- | --- | --- |
| Head | 0, −28 | tile | disc: −90 → tile · mesh: 0 → tile |
| Bench | 0, 90 | mesh | tile: −90 → mesh · disc: 180 → mesh + tile |
| Ramp | 0, −58 | tile | mesh: 25 → tile · disc: −70 → mesh |

Three fits only (D15). Swap, Totem and Tumble are gone. Each fit has four poses: `contact`, `approach` (docking pieces +16u out along
their direction), `tap` (+9u) and `apart` (+60u, plus drift).

### 3.5 Folder icons (D9)

Generated by `assets/folder_emblems.py` into `assets/emblems/`. Treat those SVGs as
canonical; never redraw by hand. Use `-master` at 32 px and up, `-small` below.

- Each icon is one to four solid pieces in one colour, with no enclosed holes,
  masks, outlines or gradients. No icon may read as an A, an exclamation mark or
  an X.
- On a 24-unit grid, master uses gap 1.4 and corner 2.2. Small insets every piece
  by 0.5, so gaps reach 2.4, and uses corner 3.0.
- A piece next to a disc gets a concentric bite.
- Textures, Meshes and Materials are the mark's own tile, block and disc, taken from
  `assets/brand_mark_v2.py`, so they change only when the mark does. They use the
  colours in §2; every other icon is neutral.
- The plain folder's front piece keeps its tip on hover, in Full motion only. Its
  back piece is opaque.

An icon goes only on a folder a modder would open. These are the complete name
rules for `gui/folder-icons.js`, matched against the whole folder name, ignoring
case. Anything else gets the plain folder.

| Icon | Folder names |
| --- | --- |
| Characters | `characters?`, `npcs?` |
| UI | `ui`, `icons?` |
| Textures | `textures?` |
| Materials | `materials?` |
| Meshes | `mesh`, `meshes` |
| VFX | `vfx`, `effects?` |
| Weapons | `weapons?` |
| Abilities | `abilities`, `ability`, `abilitysystem` |
| Environment | `environment`, `landscapes?`, `foliage` |
| Blueprints | `blueprints?` |
| Plugins | `plugins?` |
| Nameplates | `nameplates?` |
| Data | `data` |
| Text | `text`, `stringtables?` |
| Languages | `l10n`, `locali[sz]ation` |
| Maps | `maps?` |

## 4. Choreography

### 4.1 Opening and assembly

**The opening (D16).** The first move out of an outcome, into the at-rest row or the
first Working fit, is one brisk move: 420 ms, `move`, all three together. If the mesh
and tile swap sides, the mesh hops over the tile, `y − 70u·sin(πe)` and the tile
`y + 30u·sin(πe)`. A piece may pass in front of another here (invariant 4).

A glyph freshly mounted in `busy` or a loader starts in that state's first pose, the
row or a fit. It never opens from an A, because that would show an A before any success
(invariant 5).

**The assembly** is used to or from Bench and into the `!`, the X and the Brand mark:

0. **Open the A:** if the pieces are seated in the A, the mesh first moves to its
   stand-off, 30u right and 60u up. The disc then leaves through that room, down and
   to the right.
1. **Come apart:** every piece slides straight out from the group's centre
   towards the canvas edge (stopping 8u inside it, at most 140u). All at once
   over 380 ms (`move`) if that's collision-free, otherwise one at a time.
2. **Swing to sides:** each piece that will dock moves (one at a time) to the
   canvas edge on the side it will dock from, turned to its new angle, keeping
   clear of anything still in place. Among the sides that fit, it takes the one
   with the most clearance from where the others are now and, at half weight, from
   where they're going, minus a charge for straying from its docking direction.
3. **Come in:** the anchor moves to the middle, then each docking piece comes
   straight in.

Per-piece move duration: `clamp(220 + pathLength × 0.95, 300, 640)` ms, easing
`move`, with 40 ms between pieces. Paths are charged for leaving the canvas as well
as for coming within 14u of another piece.

| Outcome | Order (anchor first) | Docks from |
| --- | --- | --- |
| Brand mark (A) | tile, mesh, disc | mesh goes to its stand-off and waits · disc comes in · mesh closes last |
| Warning (!) | disc, mesh, tile | mesh: above · tile: above |
| Error (X) | tile, mesh, disc | mesh: right · disc: above |

### 4.2 Working loop

Pick a random fit (never the previous one) → get to its `approach` pose → dock
(`contact`, 200 ms, `out`) → test the fit (`tap`, 120 ms, `windup`) → tap
(`contact`, 110 ms, `snap`) → hold 180 ms → repeat.

How it gets to `approach` depends on where it's coming from (D15):

- **The first attempt:** the opening (§4.1), 420 ms.
- **Between Head and Ramp:** straight across, one piece at a time, along planned
  curves. These are the only fits with a fully clear move between them. About 1.8 s
  an attempt.
- **To or from Bench:** the full assembly (§4.1). About 3.4 s an attempt.

After the opening, no piece passes over another while Working runs. Don't add a
straight move to or from Bench to shorten the loop: all four cross a piece.

### 4.3 Complete (the click)

About a second from the result to rest (median 720 ms to the click, at most 1.2 s;
about 1 s from a loader, §4.7). It doesn't use the assembly. All three pieces travel
together, so a piece may briefly pass in front of another (invariant 4). From the
row, where the mesh starts left of the tile, the first step takes 380 ms and the mesh
hops over the tile as in §4.1.

| Step | Duration | Easing | Detail |
| --- | --- | --- | --- |
| To the seats | 340 ms | `move` | All together: tile to its seat, disc 8u right of its seat, mesh 46u right and 60u up of its seat |
| Mesh in | 110 ms | `out` | Mesh to 16u right of its seat, already wound up. The disc stays |
| Snap | 80 ms | `snap` | Mesh presses 3u past its seat; disc to its seat. The click runs sideways, because the disc has no room to move below its seat |
| Impact | 0 | | Starts the effects below, in parallel |
| Recoil | 110 ms | `recoil` | Mesh back to 1u out of its seat, disc 0.5u |
| Rest | 130 ms | `rest` | Home |

Impact effects (never cancelled once started):

- Disc squash: scale (0.88, 1.12) → (1, 1) over 300 ms, `punchBack`. The disc is
  squeezed between the tile and mesh, so it gives upwards and downwards.
- Glyph punch: scale 1 → 1.045 over 70 ms (`punchOut`), back over 260 ms
  (`punchBack`).
- Ripple: a circle behind the pieces at the disc's centre; radius 60 → 200u
  (`out`, 620 ms), stroke width `12 × (1 − p)^0.6`, opacity `(1 − p)^1.4`,
  Complete green.
- Colour: to Complete green over 220 ms (`colour`), disc at 0 ms, tile +60 ms,
  mesh +120 ms.
- Sound (if enabled): see §6.

Back to the brand colours (D15): 160 ms after the effects finish, the pieces return
to category colours over 380 ms (`colour`). The status sentence stays green. Micro
stays green (§5). The A is otherwise at rest, and this is the end of Complete.

### 4.4 Warning (balance)

Assemble bottom-up → amber over 200 ms → **catch the balance:** 1600 ms where
`sway(t) = 5·e^(−2.4t)·sin(2π·1.3t)`, windowed by `(1 − p)²`; stem
`th = 2.5 + sway(t)`, tile `ph = −4.5 − 0.6·sway(t − 0.1)` → **wobble** in a
loop for as long as the warning stands: period 2600 ms, `th = 2.5 + 1.2·sin a`,
`ph = −4.5 − 0.7·sin(a − 0.5)`, with amplitude ramping in over the first cycle.
The stem pivots about the point where it meets the dot; the tile pivots about
its contact with the stem.

### 4.5 Error (cross)

Assemble into the open X (tile −48°, mesh +48°) → clamp shut to ±42° in 150 ms
(`out`) → rose over 200 ms. No shaking, no particles. The mesh bar is meant to
slide over the tile bar here.

### 4.6 Leaving an outcome

Any state that starts while the pieces are green, amber or rose fades them
back to category colours as they start moving (`colour`; 240 ms into Working or the
brand mark or a loader, 200 ms into the others). Colour and movement run together
here; nothing waits for the fade. Into Working or a loader, the pieces take the opening
(§4.1). Into the `!`, the X or the Brand mark, the mesh opens the A first.

### 4.7 Per-asset loaders (D16)

A loader is a `busy` glyph that knows the asset type (§7). It loops like Working, and
says the same to the user: work is running. The row (§3.3) is the base, one piece works
and the other two stay still, and there's no click on the way back. Everything on the
piece is flat and opaque, a pop and never a blend. Lifted pieces rise 18u.

| Loader | Lift | Loop |
| --- | --- | --- |
| Mesh | Mesh, 120 ms `out` | Pick an arrangement (never the last): 110 ms `snap` to a lean of ±3.5° and 6u sideways, the direction flipping each time, as cuts open to the halo's width over 110 ms `out`; hold 250 ms; cuts close, 70 ms `windup` |
| Texture | Tile, 120 ms `out` | Five bands part by 9u (60 ms `out`). Two rounds: tones pop, bands slide (90 ms `snap`, ±14u at most), hold 170 ms. Then back into register top to bottom, 45 ms stagger, 90 ms `snap`, each landing on the tile's own blue. Gaps close (60 ms `windup`), hold 220 ms |
| Material | None | The disc rolls 38u along the baseline over 520 ms `move`, turning by distance ÷ radius, as a band of shine crosses it; hold 110 ms at one end and 240 ms at the other |

- **Mesh cuts:** in the halo's colour, clipped to the block, as fractions of its box
  (x1, y1, x2, y2), so they follow the lean. Quarters: (.22, −.05, .72, 1.05) and
  (−.05, .52, 1.05, .52). Courses: (−.05, .36, 1.05, .36) and (−.05, .68, 1.05, .68).
  Corner to corner: (−.05, .18, 1.05, .86). Staggered: (.22, −.05, .72, 1.05),
  (−.05, .26, .50, .26) and (.48, .74, 1.05, .74).
- **Texture bands:** cut through the tile's outline at 0, .171, .378, .585, .792 and 1
  of its height. The first cut sits on the notch's shoulder, so no sliver forms.
- **Material band:** shine, with a thin second glint, clipped to a circle 18% inside the
  disc's radius, so the rim stays whole on every surface (P2.8).
- **Leaving:** a new state lets the current step land, then the mesh or tile drops back
  to the row in 100 ms `rest`. The disc stops where it is. A result reaches the next
  state within 640 ms (invariant 6). Median from result to click: mesh 980 ms, texture
  1220 ms, material 940 ms.
- **Clearance:** 30u gaps leave at least 16u around every loader while it loops (the
  lowest measured is 26.36u, not counting the bands' slide).

Framing at Inline: the row is framed at 440 × 216u from (38, 84), the
A at 440 × 300u from (20, 50), and anything else on the whole canvas. At Inline, `!` and
X tighten to their own bounds plus 8u over 280 ms once formed. The frame moves over
280 ms `move`, alongside the opening. Stage stays on the whole canvas.

### 4.8 Logo entrance (D8)

The header logo builds the A once on launch, by the Brand mark route in §4.1: the tile
settles, the mesh waits at its stand-off, the disc comes in, and the mesh closes. Then
it hands over to the static mark, with no visible jump, and stays still. SPEC takes
priority over bible p.10 and p.14 here.

- It's a brand moment, not a status. It isn't the `success` state: category colours
  only, with no green, click, punch, ripple or sound.
- At 32 px it's a shorter route, in about 1.2 s inside the mark's own 50 × 32 px box, so
  nothing shifts. The pieces start at 66% on one baseline (tile left, disc in the middle, mesh
  right) and grow as they arrive, one at a time on planned curves, at durations × 0.8. It ends
  on the master mark exactly.
- Full motion only, and never while the window is hidden. In Calm and Off the still
  logo is simply there.
- Once per launch. It can't be replayed, and the logo isn't a button.
- It waits for the startup splash to clear, never delays start-up, and doesn't shift
  the header's layout.

### 4.9 Easing curves (cubic-bezier)

| Name | Curve |
| --- | --- |
| move | 0.65, 0, 0.35, 1 |
| approach / out | 0.16, 1, 0.3, 1 |
| windup / rest / tip | 0.45, 0, 0.55, 1 |
| snap | 0.9, 0, 1, 0.5 |
| recoil | 0.2, 0.9, 0.4, 1 |
| land | 0.34, 1.32, 0.64, 1 |
| colour | 0.4, 0, 0.2, 1 |
| punchOut | 0.2, 0.8, 0.3, 1 |
| punchBack | 0.3, 1.6, 0.5, 1 |

## 5. Tiers and the Motion setting

The tier is picked from the host's rendered height, with no gaps (D12).

| Tier | Height | Working | Outcomes |
| --- | --- | --- | --- |
| Stage | ≥ 96 px | Head, Bench, Ramp (§4.2) | Full (§4) |
| Inline | 32–95 px | The same fits, durations × 0.8, from 48 px. From 32 to 47 px, the row with Micro's nudge (D19) | Same shapes; no ripple; one sway of about 600 ms instead of the wobble loop |
| Micro | < 32 px | Small-mark geometry. The row, with each piece nudging 1.5 px out and back in turn, never forming a shape (D19) | Static result shape, one 200 ms settle, with the colour arriving from 100 ms. The A stays green (D15), because three colours at this size read as the logo |

Thiago signed off these behaviours at P2.8. They aren't in the prototype, apart from Micro's
green.

Loaders (§4.7) run at Stage and Inline, down to 32 px. Micro keeps its nudge whatever
the asset type.

Small sizes. The 480 × 400 canvas wastes a small host: the A comes out only 15.6 px tall
at 24 px and 20.8 px at 32 px.

- Frame each shape to its own bounds, not the whole canvas. The poses are 260u (A),
  365u (`!`) and 292u (X) tall.
- A 24 px A needs a slot 37 × 24 px. In a 24 px square it stays about 15.5 px tall.
- Under 32 px, the `!` opens its gaps: tile 18u up, disc 18u down.
- The X keeps its normal gap. A wider halo breaks it into four diamonds under 32 px.

| Motion setting | Behaviour |
| --- | --- |
| Full | Each glyph uses its tier |
| Calm | At most Inline; durations as the host's size gives them; no punch, ripple, squash, wobble loop or sound. Loaders don't lift, lean, slide or change colour: mesh cuts open 240 ms, hold 700 ms, close 240 ms, rest 420 ms; texture bands part in the same rhythm; material's band crosses a still disc in 620 ms, rest 980 ms |
| Off, or OS reduced motion | No travel. Each state is a still pose, and a loader is the still row; the whole glyph cross-fades between poses (150 ms out, 150 ms in). This is the only fade allowed, and only for accessibility. Complete still changes colour: it cross-fades to the A in category colours, turns green over 240 ms after 120 ms, then returns as in §4.3. |

## 6. Sound (optional, off by default, Full motion only)

Played once, on the success impact only. Goes through `gui/motion/foley.js` (its
toggle becomes "Motion sounds").

- Tick: 30 ms noise burst, decaying `(1 − i/n)^4`, bandpass 3200 Hz, Q 1.2.
- Thump: sine 180 → 70 Hz exponential over 120 ms; gain attack 4 ms to 0.9,
  decay to 0.0001 by 160 ms.
- Chime: triangle 880 Hz at +160 ms and 1318.5 Hz at +240 ms; each attacks to
  0.18 in 10 ms and decays over 500 ms.
- Master gain 0.5.

## 7. Status mapping

| Job state (server) | Glyph state | Draws |
| --- | --- | --- |
| `queued`, `running`, `cancelling` | `busy` | Working loop, or a loader when the asset type is known (below) |
| `succeeded`, nothing skipped | `success` | Complete |
| `succeeded` with `result.skipped` | `warning` | Warning, with "Succeeded with warnings" |
| `cancelled` | `info` | At rest (D4) |
| anything else | `error` | Error, with `job.error` as text |

A busy state that follows another busy state carries on with the current
attempt instead of restarting.

Choosing a loader (D16). The surface says which, and only when it truly knows:

| Where | Loader |
| --- | --- |
| Viewport, while the model loads | Mesh |
| Model appearance loading (D10) | Texture, Inline in a corner |
| Material save | Material, Inline |
| A job whose `kind` alone names one asset type, such as `mesh-replace` | That asset's loader |
| Anything else, including a job that handles several types | Working |

Jobs carry `kind` and a free-text `stage`, with no asset-type field. Never read a loader
from `stage`, and never hand from one loader to another on a timer: each change needs
its own real event. The status sentence doesn't change with the loader.
