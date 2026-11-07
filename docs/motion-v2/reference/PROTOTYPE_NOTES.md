# Reading the prototype

`motion-prototype.html` is the approved behaviour, not production code. It's
one self-contained page: demo UI on top, everything else in one `<script>`. Open
it in a browser to see every state (buttons: Working, Load mesh, Load textures, Save
material, Complete, Warning, Error, Brand mark, Simulate build or failure, Reduced
motion, Light UI, Sound).

## Where each part should go

| Prototype section / functions | Production module (`gui/motion/assembly/`) |
| --- | --- |
| `roundedPoly`, `bluePath`, `tealPath`, `BRAND`, `quadOf`, `cornerArc`, `sampleOf`, `plainRing`, `brandRing`, `dOf`, `piecePath` | `pieces.js` |
| `Z`, `B0`, `T0`, `P`, `IDS`, `bake`, `WB`/`WT`/`WR`/`WREST`, `warningPose`, `POSES`, `ATTEMPT_SPECS`, `buildAttempts`, `restPose`, `REST`, `RISE`, `atRest`, `raised`, `CONFIGS`, `PATTERNS`, `PLATES`, `SHINE` | `pieces.js` |
| `bez`, `E`, `lerp`, `lerpObj`, `clone`, `mixC`, `rgb` | `pieces.js` or a small `easing.js` (reuse `gui/motion/timing.js` if it already has cubic-bezier) |
| `polyOf`, `hullOf`, `HULL`, `SLACK`, `DOCK`, `trueOf`, `nearDist`, `segDist`, `inside`, `polyDist`, `segX`, `gap`, `gapPath`, `discGap` | `planner.js` (collision) |
| `lerpPose`, `curvePt`, `pieceAt`, `pathLen`, `pathCost`, `differs`, `perms`, `planPiece`, `planSequence`, `simulClear`, `spreadFor`, `slotsFor`, `OUT` | `planner.js` |
| `makeSvg`, `FX0`, `draw`, `mk`, `addOverlay`, `drawLoad` | `glyph.js` (renderer) |
| `animate`, `sleep`, `tweenTo`, `travelTo`, `moveTo`, `openTo`, `frameTo`, `colourTo`, `jump`, `nudge`, `standOff`, `seated`, `buildA`, `STRAIGHT`, `assemble`, `loadMesh`, `loadTexture`, `loadMaterial`, `LOADERS`, `impact`, `run`, and the `token` / `moving` / `colourTok` / `load` / `vb` state | `engine.js` (one engine instance per mounted glyph; one shared rAF clock) |
| `click` (WebAudio) | `gui/motion/foley.js` |
| `STATUS`, `ico`, `setStatus`, `sim`, button wiring, storyboard | Demo only. The storyboard is worth keeping as the Settings "Preview motion" panel. |

## Things to fix on the way in

1. **Fonts:** the page loads Inter from Google Fonts. The app has no font CDN;
   use the vendored font (D1).
2. **Global state:** `cur`, `cols`, `fx`, `token`, `moving`, `colourTok`, `load` and
   `vb` are page globals that drive four glyphs at once. Production needs one state per
   mounted glyph, ticked by one shared `requestAnimationFrame` loop.
3. **Drawing cost:** `draw()` rewrites every path's `d` attribute on every frame.
   Cache the path string per piece and only rebuild it when `w`, `h`, `taper`,
   `dx`, `k` or `m` change; move pieces with `transform` only.
4. **Redraw loop:** the page's `requestAnimationFrame` loop redraws all four glyphs
   on every frame, even when nothing is moving. Production schedules no frames for a
   settled glyph.
5. **Planning cost:** `planSequence` runs on the main thread: median 23 ms, p90 89 ms,
   and up to 146 ms for one move. Precompute the two Head and Ramp moves, the
   assemblies to and from Bench and the three outcome routes at idle
   (`requestIdleCallback`), and plan live only for unusual starting poses. The opening
   and the loaders plan nothing.
6. **Reduced motion toggle:** the button only sets a flag, so an animation already
   running carries on. In production a change takes effect as soon as the piece in
   flight lands (HANDOFF P2.4).
7. **Dead code:** `placeAttempt` is no longer used by the loop. Drop it.
8. **Not built yet:** the `info` state itself (the row is there as `REST`, on the
   storyboard and under the loaders), the Inline and Micro tiers (only Micro's green is
   in the page), the logo entrance at 32 px, Calm mode. The page frames only the row and
   the A at small sizes. A loader button starts a loader by name; production picks one
   from the surface (SPEC §7). Prototype these on the Settings preview first and show
   Thiago.
9. **Halo colour:** the prototype uses the CSS variable `--halo`, but the app already
   has `--halo: 2px` for focus rings (`gui/identity.css:102`), so name it `--glyph-halo`.
   Set it from the actual surface the glyph sits on (hosts already carry
   `data-krackle-surface`; rename that attribute).
10. **Test hook:** `window.__atelier` exposes internals to the check scripts.
   Keep an equivalent behind a test flag, not in shipped builds.

## Check scripts (`checks/`)

All three need Python with Playwright (`pip install playwright && playwright install chromium`).

- `planner_check.py <page>`: replays 400 seeded cycles through the planner, in the
  order the engine runs them, and reports how many moves stay fully clear. Prototype
  baseline: straight 108/108, open 3/3, spread 236/236, slots 217/236,
  regroup 176/244. It counts a move as not clear for even a slight graze, and
  crossings in the X are deliberate. Complete and the opening aren't planned, so they
  aren't counted. These figures don't compare with the old pack's, which used different
  pieces and six fits.
- `clearance_check.py <page>`: exact gaps on the drawn outlines, in every designed
  pose and on every frame of a fixed timeline, loaders included. It fails if a resting
  pose breaks its minimum. Prototype baseline of 1515 frames under 13.8u: tile-mesh 57,
  tile-disc 162, mesh-disc 168. Most of the last two are the X and leaving it, where
  the disc is pinned on the crossing, and the rest are Complete and the opening.
  Wrong-fit contact gaps are all 16u, and the row's are about 30u.
- `state_film.py <page> <out_dir>`: contact sheets of warning, success and error,
  for checking choreography by eye.

Port all three to run against the production module in Phase 2.
