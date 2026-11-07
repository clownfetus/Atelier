# Atelier motion

Atelier's motion is one glyph made of three opaque pieces: the texture tile (blue), the mesh block
(teal) and the material disc (copper), one for each kind of asset a modder edits. While work runs
they come apart and try to fit. On a real success they click into an A, on a warning they balance
into a `!`, and on a failure they cross into an X. The rules, including the ten invariants every
change must keep, are in `docs/motion-v2/SPEC.md`; the decisions behind them are in
`docs/motion-v2/DECISIONS.md`.

The glyph is presentation only. Application code owns project state, requests and results; the
glyph is told what happened and never decides it. A glyph that can't mount leaves its host's own
text and fallback icon in place, so the interface stays usable without it.

## The glyph

| File | Job |
| --- | --- |
| `assembly/pieces.js` | Geometry and poses: the mark's outlines, the fits, the row, Micro's small-mark poses, framing |
| `assembly/planner.js` | Clear routes between poses, planned in short slices, with common routes planned in idle time |
| `assembly/engine.js` | One engine per glyph on one shared clock: each state's choreography, tiers, Calm and Off |
| `assembly/glyph.js` | The renderer and the public API |
| `assembly/assembly.css` | The halo and the glyph's box |

`AtelierMotion.glyph.mount(host, {state, asset, size, reducedMotion, surface, still})` returns
`{set(state, {asset}), replay(), destroy(), state}`. States are `busy`, `info`, `success`,
`warning` and `error`. `asset` is `mesh`, `texture` or `material`, only with `busy`, and only when
the surface truly knows it. Call `success` only for a real `succeeded` result, never from a timer.
`surface` names the colour behind the glyph if it isn't the page background; `--glyph-halo` does
the same from CSS. `still` places a result without animating it. A glyph's `reducedMotion` is
fixed when it's mounted, so a caller that follows a change of motion setting mounts it again.

`AtelierMotion.glyph.entrance(host, {size, onDone})` is the header logo's entrance: once per launch,
in Full motion, while the window is visible. It ends on the still mark and then calls `onDone`.
Where it doesn't play, it mounts nothing, calls `onDone` at once and returns `null`.

The host gets `data-atelier-motion="glyph"` and `data-glyph-state`, `data-glyph-asset` and
`data-glyph-tier`. The tier comes from the host's height: Stage from 96 px, Inline from 32 px, Micro
below. Below 48 px, Working is the row with each piece nudging 1.5 px, because the moving fits need
the whole canvas and draw too small there; loaders still run from 32 px. A glyph's time stops while
it's off screen, while the document is hidden and once it has settled, and a settled glyph asks for
no frames. A state set meanwhile plays when the glyph comes back.

**Interruption (D7).** Status text and controls update the moment a result arrives. The glyph lets
the piece already in flight land (640 ms at most), then moves to the new state; cutting a move off
mid-flight makes the pieces pop. A busy state that follows the same busy state carries on, and a
result never animates twice. Only busy loops; results form once and hold still.

**Layers and fades.** The pieces always stack tile, mesh, disc. Nothing in the glyph fades or
dissolves, except the cross-fade that stands in for movement in Off and under OS reduced motion.

## Motion setting

Settings has a Motion dial: Full, Calm and Off. `AtelierMotionPolicy` (`../preferences.js`)
exposes `mode()`, `tier()` and `allows(n)` (Full is 3, Calm 1, Off 0) and sets
`data-motion-mode` on the root. OS reduced motion forces Off, and Settings says so beside the dial.
Calm keeps the shape and the colour of each result without the flourish; Off shows stills.

Settings also has Preview motion (`motion-preview.js`): real glyphs at 16, 48 and 128 px, the five
states, the three loaders and the logo's entrance. `AtelierFoley.click()` (`foley.js`) is the
optional success click, off by default. It plays at Stage and Inline in Full motion only, and
glyphs finishing together click once.

## Where the glyph appears

| File | Surface |
| --- | --- |
| `export-feedback-ui.js` / `.css` | The Build button and operation toasts. A result holds 1.8 s, then the button's icon comes back |
| `material-save-ui.js` / `.css` | The glyph beside a Save button while it runs, and its result in a toast |
| `toast-glyph.js` | A plain toast's icon becomes the small glyph, with the icon kept as the fallback |
| `spinner-glyph.js` / `.css` | Every `.spinner` is the Micro glyph, working; the plain ring in `style.css` shows only if it can't mount |
| `empty-glyph.js` / `.css` | The still glyph in empty places: the three pieces at rest, or the X when a place couldn't load |
| `empty-assets-ui.js` | The Mod tray's empty state, shown only when the application confirms the project is empty |
| `config-discovery.js` / `.css` | The setup-status check in Settings: the working glyph, Inline, while the request runs |
| `logo-entrance-ui.js` | The header logo's entrance on launch |
| `viewport-poster.js` | Model Studio opened from costume artwork: the artwork waits on the stage while the model decodes |
| `surface-adapters.js` | Startup beside the counted bar, the index failure notice and the update button in the topbar |
| `motion-preview.js` / `.css` | Settings: Preview motion |
| `../job-tools.js` | Activity rows: a glyph per job, kept across refreshes |
| `../mod-open.js` | Open a mod: a glyph per outcome row |
| `../viewport.js` | The 3D viewport's loader at Stage, on the dark stage |

`docs/motion-v2/SURFACE_MAP.md` lists every surface with its tier and states.

## Colour and timing

`inks.js` (`AtelierInks`) is the colour maths: sRGB fitting and CIELAB distance. `../theme.js` uses
it to fit `--charge` to the card surface and `--charge-raised` to raised surfaces, and sets
`data-glyph-surface` (dark or light) on the root. `charge.css` holds the unmeasured defaults and the
edited corner, a plain triangle in the charge colour on edited rows, cards and portraits.

`timing.js` loads after `tokens.css` and before the controllers. It exposes `AtelierMotion.ease`,
`AtelierMotion.beatMs` (from `--motion-beat`), `AtelierMotion.exitMs` and `AtelierMotion.springMs`.

## Continuity and polish

`AtelierMotion.polish.mount(host, {state, frames, duration})` (`../polish.js`) returns `setState`,
`destroy` and a completion promise. Replacing or removing a host cancels its previous effect; page
hide and reduced motion release active effects. View Transition names are transient and cleaned up
after completion or cancellation. The request or close a transition belongs to never waits for it.

## Checks

Each flag runs one part of `tests/browser_smoke.py --report-dir <folder>`:

| Flag | Covers |
| --- | --- |
| `--glyph-only` | Planner and clearance baselines, the glyph's promises and Preview motion, on the bare page in `tests/glyph_fixture.py` |
| `--assembly-only` | Glyph states, tiers and mounting rules in the app |
| `--glyph-surfaces-only` | Spinners, toasts, empty grids, Activity and the counted ring |
| `--working-panels-only` | Export, material save and the viewport loader, with their real hooks |
| `--surfaces-only` | Startup, the index failure notice, the update button and folder icons |
| `--inks-dial-only` | Charge fitting on every preset and the Motion dial |
| `--logo-only`, `--empty-assets-only` | The logo entrance and the Mod tray's empty state |
| `--polish-only`, `--retired-only` | Continuity, and that the retired surfaces stay gone |
| `--showcase-only` | Showcase views and the success click |

`tests/test_inks.py` runs the colour maths in Node. `tests/desktop_smoke.py` and
`tests/frozen_smoke.py` probe the glyph in WebView2 and in the frozen bundle.
