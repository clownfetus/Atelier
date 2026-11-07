# Reading the prototype

`motion-prototype.html` is the approved behaviour, not production code. It's
one self-contained page: demo UI on top, everything else in one `<script>`. Open
it in a browser to see every state (buttons: Working, Complete, Warning, Error,
Brand mark, Simulate build or failure, Reduced motion, Light UI, Sound).

## Where each part should go

| Prototype section / functions | Production module (`gui/motion/assembly/`) |
| --- | --- |
| `roundedPoly`, `bluePath`, `tealPath` | `pieces.js` |
| `Z`, `B0`, `T0`, `P`, `IDS`, `bake`, `WB`/`WT`/`WR`/`WREST`, `warningPose`, `POSES`, `ATTEMPT_SPECS`, `buildAttempts` | `pieces.js` |
| `bez`, `E`, `lerp`, `lerpObj`, `clone`, `mixC`, `rgb` | `pieces.js` or a small `easing.js` (reuse `gui/motion/timing.js` if it already has cubic-bezier) |
| `polyOf`, `segDist`, `inside`, `polyDist`, `segX`, `gap` | `planner.js` (collision) |
| `lerpPose`, `curvePt`, `pieceAt`, `pathLen`, `pathCost`, `differs`, `perms`, `planPiece`, `planSequence`, `simulClear`, `spreadFor`, `slotsFor`, `OUT` | `planner.js` |
| `makeSvg`, `FX0`, `draw` | `glyph.js` (renderer) |
| `animate`, `sleep`, `tweenTo`, `travelTo`, `colourTo`, `jump`, `nudge`, `assemble`, `impact`, `run`, and the `token` / `moving` / `colourTok` state | `engine.js` (one engine instance per mounted glyph; one shared rAF clock) |
| `click` (WebAudio) | `gui/motion/foley.js` |
| `STATUS`, `ico`, `setStatus`, `sim`, button wiring, storyboard | Demo only. The storyboard is worth keeping as the Settings "Preview motion" panel. |

## Things to fix on the way in

1. **Fonts:** the page loads Inter from Google Fonts. The app has no font CDN;
   use the vendored font (D1).
2. **Global state:** `cur`, `cols`, `fx`, `token`, `moving` and `colourTok` are
   page globals that drive four glyphs at once. Production needs one state per
   mounted glyph, ticked by one shared `requestAnimationFrame` loop.
3. **Drawing cost:** `draw()` rewrites every path's `d` attribute on every frame.
   Cache the path string per piece and only rebuild it when `w`, `h`, `taper`,
   `dx` or `k` change; move pieces with `transform` only.
4. **Planning cost:** `planSequence` runs on the main thread, taking up to 70 ms
   per move. Precompute the six fits' routes and the three outcome routes at
   idle (`requestIdleCallback`), and plan live only for unusual starting poses.
5. **Dead code:** `placeAttempt` is no longer used by the loop. Drop it.
6. **Not built yet:** the `info` "at rest" pose (D4), the Inline and Micro tiers,
   Calm mode. Prototype these on the Settings preview first and show Thiago.
7. **Halo colour:** the prototype uses the CSS variable `--halo`. In the app,
   set it from the actual surface the glyph sits on (hosts already carry
   `data-krackle-surface`; rename that attribute).
8. **Test hook:** `window.__atelier` exposes internals to the check scripts.
   Keep an equivalent behind a test flag, not in shipped builds.

## Check scripts (`checks/`)

Both need Python with Playwright (`pip install playwright && playwright install chromium`).

- `planner_check.py <page>`: replays 400 cycles through the planner and reports
  how many moves stay fully clear. Prototype baseline: spread 400/400,
  slots about 385/400, regroup about 350/400. Crossings in the X are deliberate.
- `state_film.py <page> <out_dir>`: contact sheets of warning, success and error,
  for checking choreography by eye.

Port both to run against the production module in Phase 2.
