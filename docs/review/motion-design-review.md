# Motion design review: Krackle and studio motion

Date: 18 October 2026. Base: `claude/jolly-lamport-a8bc3d` at `6aee64b` (Wave 4b).
Scope: `gui/motion/` and the motion tokens in `gui/tokens.css` / `gui/style.css`, plus
the neighbouring motion each animation plays next to (`polish.js`, `continuity.css`,
`preferences.js`, `surface-adapters.js`, `app.js` call sites).

**Status: proposals 1–5 are implemented on this branch. Proposals 6–10 remain proposals.** Each
implemented item ends with an "Implemented" note that records any deviation from the proposal.
The four required browser smoke modes (`--surfaces-only`, `--inks-dial-only`, `--polish-only`,
`--texture-reconstruction-only`) pass in Edge, and `polish_checks.py` now also asserts the toast exit
and the settled empty state.

## Method

The `motion-design` skill is enabled on the user's claude.ai account, but it is not
installed in the Claude Code session that ran this review, so its text could not be
loaded. The review applies the same principles directly:

- Timing follows frequency and distance. Things that fire often are short; large or
  far-travelling things take longer.
- Easing: decelerate into a rest pose, accelerate out of view, and stay linear for time
  and progress.
- Disney principles adapted for UI: anticipation, follow-through, squash and stretch,
  staging (one hero per event) and slow-in/slow-out.
- Entrances take longer than exits, and every exit exists.
- Visible rhythm: indicators shown together share a tempo.

The Krackle constraints in `gui/motion/README.md` were treated as fixed: solid energy
with punched bubbles, no outlines, gradients or symbols; AtelierMotionPolicy tiers 3/1/0
with OS reduced motion forcing Off; one large stage at a time (`moment.js`); particle
frames under the 8 ms median; inks at 3:1; and the four browser smoke modes kept green.

Durations and easings below are the values in the code. Where a keyframed effect also
has a timing-level easing, the *actual* landing time of each keyframe was computed
numerically (bisection on the cubic-bezier; see the appendix). Findings come from
reading the code and the computed curves, not from screen recordings. No browser run
was needed because nothing changed.

## Verdict

Yes, the principles can improve the animations. The gains are mostly in
**choreography and easing, not new effects**. Krackle's shapes, inks and tier gates are
in good shape. Five issues stand out:

1. One export outcome plays up to five success animations at once.
2. An entrance replays on every keystroke.
3. Overshoot keyframes are eased twice, so their anticipation lasts about 60 ms.
4. Decorative tails and the brand entrance still play in Calm.
5. Toasts have no exit.

## Ranked proposals

Ranked by user impact: how often the motion is seen × how noticeable the problem is.

### 1. One export, one hero (choreography): highest impact

**Problem.** When an export finishes with the review dialog open (the main path),
`_runInstall` (`gui/app.js:2698-2704`) runs all of the following in the same task:

- It removes the busy toast instantly (`t?.remove()`).
- It plays the install button's result pop behind the overlay blur (`finishFeedback`,
  `export-feedback-ui.js:45`).
- It creates a **new** toast. That toast slides in (200 ms) above the dialog
  (`#toast-area` z-index 300 vs `.export-review-overlay` 210) and pops its own 420 ms
  starburst.
- It asks for the first-export colour burst (`AtelierPolish.exported()`).

Then `AtelierExportReview.finish` pops the 156 px stage starburst. While the build
runs, the dialog already shows three busy voices for one job: the stage ring, the
indeterminate `<progress>` (`export-review.js:267`) and the busy toast's ring. The
topbar Activity ring and the button ring behind the blur make five.

This breaks staging. The stage is the hero and owns the moment, and the README's rule
that a busy state "continues the current animation" is lost when the toast is replaced
rather than resolved. Separately, the first-export burst calls
`moment.claim('first-export', 3)` (`polish.js:148`) while the stage still owns the
moment. `moment.js:8` refuses it, so **in the review flow the first-export burst never
plays**, and because the flag is set only after a successful claim, it retries on every
export.

**Proposal.**

| Step | Where | Before | After |
| --- | --- | --- | --- |
| a | `gui/app.js:2698`, `:2704`, `:2733-2735` | `t?.remove()`, then a new `toastExportFeedback(...)` | `t.resolve(message, outcome, 5000)` when `t?.resolve` exists. The same toast's ring hands over through the existing 140 ms busy fade (`export-feedback.js:296-301`). The current path stays as the fallback. The 16 s skipped-items toast stays separate. |
| b | `export-feedback-ui.js:28` `begin`, `:51` `toast`; `app.js:2685-2686` | Button and toast glyphs animate while the dialog's stage owns the job | `_runInstall` passes `{quiet: !!review}`. Quiet mounts use `reducedMotion: 'reduce'`, so the ring and result render as static poses. The stage alone moves. Unrelated jobs keep their animated toasts (README: they "report through their own toasts"). |
| c | `gui/export-review.css` (new rule) | `<progress>` (1040 ms, 4 px steps) runs under the stage ring (1.43 s) | `:root[data-krackle=full] .export-review-modal:has([data-atelier-motion=krackle-stage][data-am-state=busy]:not([data-am-micro=true])) progress:not([value])` visually clipped, as `surfaces.css:32` already does for the launch splash. It stays in the accessibility tree, and in Calm/Off or a refused stage it stays visible. |
| d | `polish.js:142-160` | Burst is refused while the stage owns the moment and never plays in the review flow | Queue the colours and play the burst from `#install-btn` when the review overlay closes, after its 120 ms exit, when the button is visible again. It still claims tier 3 once per session. |

**Constraints.** No ink or particle changes. The stage keeps the moment. Off is
unchanged. **Tests:** `export_motion_checks.py:180-182` expects one `.toast.success`
containing `Exported: <name>`, which still holds after (a). `polish_checks.py` operation
toasts already use `resolve` in place.

**Implemented.** (a) as proposed, through a `settle()` helper in `_runInstall`. (b) is a
`quiet(state)` predicate rather than a fixed flag, because the user can hide the dialog
mid-build. `AtelierExportReview.staging(state)` is true when the stage is mounted, not in
micro mode, and the tier is Full; for `busy` it also requires the dialog to be open.
`export-review.js` dispatches `atelier:export-review` when the dialog opens or closes, and
`export-feedback-ui.js` re-reads the predicate, so a hidden dialog lets the toast ring move
again. Calm keeps the micro pops, because its stage is still. (c) as proposed. (d) waits for
`atelier:export-review` to report the close, then retries the claim up to five times at
150 ms, because the stage releases the moment only after its hidden-dialog observer fires.

### 2. The "No matches" empty state replays on every keystroke (frequency)

**Problem.** In folder scope, typing in the search box runs `applyLibraryView` on each
input (`app.js:678-680` → `:653-655`). That rebuilds the grid. While results stay at
zero, `buildGrid` rewrites `#empty-state` (`app.js:465-471`), and
`AtelierPolish.empty` (`polish.js:183-194`) mounts a new `emptyState`, whose `mount`
calls `enter()` (`empty-state.js:122`). The three bubbles restart their 460 ms bounce,
with 60 ms + 70 ms per-bubble delays, on every key. The project search empty state
(`app.js:4116`) follows the same path. The README's own rules say routine typing stays
plain with "no per-keystroke effect", and that returning to the same empty state stays
settled (the rule `empty-assets-ui.js` already follows).

**Proposal.** Remember the last empty key (`kind` + title) on the host container.

| Where | Before | After |
| --- | --- | --- |
| `polish.js:183-194` | Every rebuild enters | When the previous empty state in that container had the same key, mount settled: `emptyState.mount(krackle, {kind, reducedMotion: 'reduce'})`. Clear the key when cards render or navigation changes. |
| Result | Bounce restarts per key | Bounces once on the first zero-result keystroke. Stays still while typing continues at zero. Bounces again only after results return and then vanish. |

**Tests:** `krackle_motion_checks.py:76-90` checks kinds and fallbacks, not replay,
so they still hold.

**Implemented.** The key (`kind|title`) is kept per container in `polish.js`. Its existing
MutationObserver forgets the key as soon as the container shows anything else (cards, the
loading pose), so navigating to another empty folder still enters. `polish_checks.py` types
into folder-scope search: the first zero-result keystroke has 3 entrance effects, the next
has 0, and after results return and vanish again it has 3.

### 3. Overshoot keyframes are eased twice (easing, anticipation)

**Problem.** The burst, splat, ring, satellite, drip and logo-splash effects put
`easing: 'cubic-bezier(0.2, 0, 0, 1)'` on the **whole** effect while their keyframes
already encode an overshoot. The strong ease-out compresses every offset toward the
start: 80% of the progress is spent in the first 40% of the time. The keyframe
segments themselves stay linear, so velocity snaps at each keyframe instead of easing
into the peak. Measured landing times:

| Effect (duration) | Keyframe | Intended | Actual |
| --- | --- | --- | --- |
| Success burst (420 ms) | peak 1.24 @ .52 / rebound .95 @ .76 | 218 / 319 ms | **87 / 150 ms** |
| Burst bubble (420 ms) | appears @ .42 / 1.35 @ .72 | 176 / 302 ms | 72 / 136 ms |
| Error splat (520 ms) | squeeze .26 @ .20 / burst 1.2 @ .52 | 104 / 270 ms | **58 / 108 ms** |
| Error satellites (560 ms) | release @ .24 / 1.2 @ .60 | 134 / 336 ms | 68 / 138 ms |
| Error drip (640 ms) | starts @ .45 / 1.15 @ .82 | 288 / 525 ms | 116 / 269 ms |
| Warning ring (380 ms) | impact .93 @ .42 / 1.03 @ .70 | 160 / 266 ms | **65 / 117 ms** |
| Logo splash (280 ms) | peak @ .45 | 126 ms | 51 ms |

The splat's 58 ms squeeze, its anticipation, falls entirely under the 140 ms busy-ring
fade, so it is never seen. The warning ring lands at 65 ms, but the chunk (correctly
built with linear timing and per-keyframe easing) is released at 186 ms, so the cause
(impact) and the effect (chunk falls) are 120 ms apart. The rest of the time is creep:
the burst covers its last 5% over ~270 ms.

The codebase already has the right pattern: the info drop (`krackle-glyph.js:116-122`),
the warning chunk and every bounce use `easing: 'linear'` with per-keyframe easing.
This proposal applies that pattern everywhere.

**Proposal.** Set timing `easing: 'linear'` and give each keyframe its own easing.
Use cubic-beziers rather than CSS `linear()` springs, because WebKitGTK support for
`linear()` is unverified.

| Effect | Before | After |
| --- | --- | --- |
| Success burst | 420 ms, timing (.2,0,0,1); offsets 0 / .52 / .76 / 1 | 380 ms linear; 0 → .38 (144 ms) scale 1.24 with (.2,0,0,1) into the peak; .38 → .66 (250 ms) scale .95 with (.45,0,.55,1); .66 → 1 scale 1 with (.45,0,.55,1). Bubble: hold to .36, 1.35 at .64 with (.2,0,0,1), then 1. Flecks: 420 ms linear, out to .55 with (.2,0,0,1), fade .55 → 1 with (.55,0,1,.45). |
| Error splat | 520 ms, timing (.2,0,0,1); squeeze @ .20 | 520 ms linear; 0 → .22 (114 ms) squeeze to .26 with (.45,0,.55,1), so the squeeze now coincides with the ring collapsing; .22 → .48 burst to 1.2 with (.2,0,0,1); .48 → .72 .95 with (.45,0,.55,1); .72 → 1 settle with (.2,0,0,1). Satellites release at .26. |
| Error drip | 640 ms, decelerating overall | Hold to .45, extend to 1.15 at .80 with **(.55,0,1,.45)** (a drip accelerates as it falls), then settle with (.2,0,0,1). |
| Warning ring + chunk | Ring 380 ms eased (impact 65 ms); chunk held to .30 of 620 ms (186 ms) | Ring 380 ms linear; 0 → .30 (114 ms) stamp to .93 with (.55,0,1,.45) (accelerate into impact); → .60 1.03 with (.2,0,0,1); → 1 with (.45,0,.55,1). Chunk offsets `[0, .18, .56, .70, .84, .92, 1]`, released at 112 ms, the moment of impact. |
| Logo splash | 280 ms, timing (.2,0,0,1), 6 ms stagger | 280 ms linear; out to .45 with (.2,0,0,1), then shrink and fade with (.55,0,1,.45); stagger 6 → 24 ms (6 ms is below one 60 Hz frame). |

**Where.** Each outcome is implemented three times:

- `export-feedback.js:208-283` (burst 209, bubble 215, flecks 221-229, ring 234,
  chunk 241, splat 254, satellites 261-270, drip 271-276)
- `material-save.js:216-300` (burst 235, flecks 249, ring 257, chunk 264, splat 274,
  drip 291)
- `krackle-glyph.js:124-174`

The same timing-level pattern also appears in:

- `empty-state.js:77-98` (tray, splat, satellites, drip)
- `viewport-loader.js:251-255` (sphere), `:297-318` (splat, satellites, drip)
- `empty-assets.js:227-233` (tray overshoot lands at 74 ms, not 180), `:254-261` (drop)
- `logo-entrance.js:290-299`

A shared `outcomeFrames()` helper would make this one change instead of three.

**Constraints.** Durations stay the same or get shorter, the poses don't change, and
there are no particles. Off is unchanged.

**Implemented** in all seven files listed above, with the values in the table. One
deviation: the logo splash is 240 ms with a 16 ms stagger, not 280 ms with 24 ms. The
entrance cancels the splash when its 320 ms ends, and a 24 ms stagger would have cut the
last bubble short. The material-save swatch pulse (`material-save.js:208-212`) is a
symmetric loop, not an overshoot, and was left as it is.

### 4. Calm should keep the state change and drop the decoration (tiers)

**Problem.** Calm means tier 1, and `data-motion` stays `full` (`preferences.js:14`).
The micro controllers only check the Off query (`export-feedback.js:98-100`,
`krackle-glyph.js`, `empty-state.js:43`, `logo-entrance.js:245-250`), so in Calm they
play exactly as in Full. That includes:

- the error glyph's **1.1 s dazed-bubble orbit** after a 260 ms delay, so an error
  keeps moving for ~1.36 s;
- the success flecks;
- the **logo entrance with its bubble splash** (`logo-entrance-ui.js:7` checks only
  Off).

The README classes the logo entrance as a showcase moment, and Calm's own setting text
reads "Calm keeps small responses and still formations".

| Where | Before | After |
| --- | --- | --- |
| `logo-entrance-ui.js:7` | `reduced()` = Off only | Also true when `!AtelierMotionPolicy.allows(2)`. Calm keeps the static mark; replay is Full only. |
| Dazed orbit: `export-feedback.js:277-282`, `material-save.js:297-299`, `krackle-glyph.js:175-185` | Plays in Calm | Runs only when `allows(2)`. In Calm the splat settles in ≤ 640 ms. |
| Success flecks: `export-feedback.js:221-229`, `material-save.js:247-255`, `krackle-glyph.js:134-142` | Play in Calm | Only when `allows(2)`. The burst itself still pops in Calm. |

**Tests:** `inks_dial_checks.py:87-92` and `surfaces_checks.py:51-111` check stage sleep
and Calm drop behaviour. Neither asserts the logo or glyph tails in Calm.

**Implemented** with one change to the proposal: only the automatic startup entrance is
Full-only (`showcase()` in `logo-entrance-ui.js`). Clicking the mark still replays in Calm,
because that is an explicit request. Flecks and the dazed orbit run only when
`allows(2)`, in all three outcome controllers.

### 5. Toasts need an exit (asymmetry)

**Problem.** Toasts enter over 200 ms with a 10 px rise using the generic `ease`
(`style.css:626`, `:633`). They leave with **no exit**: `el.remove()` at `app.js:124`,
`:145-170`, `export-feedback-ui.js:74-80` and `material-save-ui.js`. A 300 px Paper
card vanishing in one frame is the most visible hard cut in routine use. If the
removed toast is not the top one, the toasts above it drop by its height plus the 8 px
gap at once.

| Where | Before | After |
| --- | --- | --- |
| `style.css:626` | `toastIn .2s ease` | `toastIn var(--studio-motion-standard) var(--studio-easing)`, which keeps 200 ms. |
| Shared exit helper used by the four removal paths | 0 ms | 120 ms opacity → 0 plus `translateY(4px)` with `cubic-bezier(.3,0,1,1)` (accelerate out). Mark the toast `inert` at once, then remove it on finish. No exit under Off (`polish.css:69`). |

**Constraints.** The contrast dip during the fade is transient, the same treatment as
the hover transitions in the card-ink handover. **Tests:** `polish_checks.py:113-114`
waits 1050 ms after `mouseleave` for a 1000 ms toast and asserts it is gone. With a
120 ms exit, removal lands at ~1070-1120 ms, so that wait needs about +150 ms. Raising
the wait is the safer fix; shortening the exit below ~50 ms would leave the hard cut
mostly in place. Flagged for the user's call.

**Implemented** as `AtelierPolish.leave(el, done)`, used by all four removal paths. The toast
leaves `#toast-area` at once, so the live region, collation, the stack and every `#toast-area`
selector stay truthful. The same element then fades for 120 ms in an inert,
`aria-hidden` layer just before `#toast-area`. It drops `role`, `toast-timed` and
`data-operation-state`, and keeps its caption ink inline. Export and material-save glyphs stop
their effects at dismissal and hold their still pose until the fade ends; they are not
swapped for the fallback icon. Instead of a longer wait, `polish_checks.py:113-116` now checks
that the toast has left `#toast-area` at 1050 ms, then waits for the faded copy to go.
For the same reason, the Undo locators in `trust_checks.py` are scoped to
`#toast-area .toast-undo`. A copy that is still fading is inert and `aria-hidden`, but a global
CSS selector still matches it, which tripped Playwright's strict mode. Off removes toasts
outright.

### 6. Hold the viewport loader for fast loads (timing)

**Problem.** `startViewportLoader` (`viewport.js:335-345`) mounts the loader and starts
the 220 ms coalesce straight away (`viewport-loader.js:244-255`). Ready cancels at once
(README). A model that resolves in ~100-200 ms therefore flashes a few frames of dots
and ball before the model's own 420 ms sweep. That is a "flash of loading", and the
sweep is the real entrance.

| Where | Before | After |
| --- | --- | --- |
| `viewport-loader.js:249`, `:255` (assembly) | Delay `k * 6` ms; sphere starts at 0 | Add 150 ms to every assembly delay with `fill: 'backwards'` (dots stay invisible). Mounting stays immediate, so the static box fallback never shows. Empty and error stay immediate. |

**Tests:** `viewport_motion_checks.py:187-192` ("fast geometry immediately") checks
that the model reveals; that is unaffected. This suite is outside the four required
modes but should stay green.

### 7. One busy tempo (rhythm)

**Problem.** Busy loops run at 960 ms (`material-save.js:19`), 1040 ms (spinner,
Activity ring, glyph, export feedback, indeterminate progress), 1200 ms
(`viewport-loader.js:21`) and 1429 ms (stage head at 0.7 rev/s,
`krackle-stage.js:275`). The textures differ too: the CSS rings tick
(`steps(6)`), the WAAPI rings glide and the bar steps 4 px at 11.5 fps. In the export
dialog the stage and the progress bar beat against each other at an 11:8 ratio.

| Where | Before | After |
| --- | --- | --- |
| `tokens.css` | none | `--krackle-beat: 1040ms`. JS reads the same constant. |
| `krackle-stage.js:275` | `tau * 0.7 * TAU` (1.43 s/rev) | `tau * (1000 / 2080) * TAU`: two beats per revolution (0.48 rev/s). It is calmer at 156 px and locks to the small rings. |
| `material-save.js:19` | 960 ms | 1040 ms |
| `viewport-loader.js:21` | 1200 ms | 1040 ms ring; keep bob, boil and drift as multiples of the beat. |

This item is lower once 1c lands, because the progress bar then hides behind a drawing
stage. CPU cost is unchanged (only the head speed changes).

### 8. Logo entrance: no dip, and one brand moment at startup (staging)

**Problem.** The static mark is fully visible. `logo-entrance-ui.js:43` swaps it, in
one task, for the entrance, which starts at **opacity 0.58** and 2 px low
(`logo-entrance.js:15-16`). The logo blinks to 58% before it rises, at startup and on
every replay click. In Full, while containers index, the 224 px launch formation draws
the same mark at the same moment (`surface-adapters.js:19`, tier 3 `launch`), so two
brand moments compete.

| Where | Before | After |
| --- | --- | --- |
| `logo-entrance.js:364-378` | Opacity .58 → 1, translateY 2 → 0 px, 320 ms eased | Opacity stays 1. Squash-stretch stamp: `translateY(1px) scale(1.04,.94)` → `scale(.98,1.02)` @ .45 with (.2,0,0,1) → `none` with (.45,0,.55,1), 320 ms, linear timing. |
| `logo-entrance-ui.js:63-65` | Plays at document start | When the launch formation is drawing, hold and play on `AtelierSurfaces.startupDone()`. The splash leaves and the topbar mark "receives" the ink. |
| `logo-entrance.css:75-84` | Unused `am-logo-entrance-reveal` keyframes | Remove. |

### 9. Exits accelerate and point where gravity points (craft)

| Where | Before | After |
| --- | --- | --- |
| Trash drain `polish.js:119`, `:124` | Snapshot clips `inset(0 0 100% 0)` (collapses **upward**) while the dots fall down; both use the decelerating (.2,0,0,1) | `inset(100% 0 0 0)` (the row sinks with its bubbles); dots use (.55,0,1,.45). `play()` (`polish.js:23`) gains an optional easing argument. 300 ms is kept. |
| Export button revert `export-feedback-ui.js:47` | After 1800 ms the glyph is destroyed and the download icon snaps back | 120 ms opacity crossfade before `destroy`. |
| Glyph busy → result `krackle-glyph.js:99-124` | The ring hard-cuts to the result (CSS state selectors) | Reuse export feedback's 140 ms fade plus scale .7 (`export-feedback.js:296-301`) so Activity rows hand over the same way. |
| Determinate width `style.css:596`, `:1191` | `width .3s ease`, which restarts a slow-start curve on every update | `width 200ms linear`: steady between updates, no stutter. |

### 10. Token and housekeeping cleanup (system)

- `style.css:180`: `.card { transition: border-color .15s, background .15s }` is dead.
  `style.css:1426-1427` overrides it with 120 ms. Remove it so the handover notes'
  ".15s" matches reality.
- `polish.css:17`: the `.card.imported:hover` box-shadow changes without a transition
  while the border eases. Add `box-shadow` to the 120 ms list.
- `folder-flap.css:63-64`: `[data-reduced-motion="reduce"]` is never set. Forced Off is
  already covered by `polish.css:69`. Remove the selector.
- Stray `ease` curves: toast in (`style.css:626`), overlay (`continuity.css:33`), grid
  out (`continuity.css:23`), rolling digits (`polish.css:43`). Add
  `--studio-easing-exit: cubic-bezier(.3,0,1,1)` and `--studio-motion-exit: 120ms`
  next to `tokens.css:92-94`, and use them.
- `EASE_STANDARD`, `EASE_FALL` and `EASE_RISE` are duplicated in six controllers.
  Expose one `AtelierMotion.ease` table.
- README drift: Empty Edited Assets says "about 480ms", but the last bubble ends at
  ~625 ms (205 ms delay + 420 ms).
- Texture wipe on alpha textures: the canvas paints a flat `--bg3`
  (`texture-reconstruction.css:12`), while the thumb shows a checkerboard
  (`polish.css:28-30`). For 320 ms the transparent areas go flat, then snap back.
  Use `background: inherit`.

### Lower-priority craft notes

- **Bounce timing.** The bounce keyframes (`empty-state.js:24-29`,
  `empty-assets.js:244-249`, the warning chunk) rebound to 22% and 6% of the drop
  height, but give those bounces 36% and 14% of the timeline. Constant gravity needs
  about 47% and 24%, so the bounces look hurried. Retime only if 3 is accepted.
- **Rolling counter direction.** The counter always rolls up (`polish.css:45`).
  Rolling down for decreasing counts would encode direction. It is low value.

## Animation inventory

Tiers: **F**ull / **C**alm / **O**ff. OS reduced motion forces Off
(`preferences.js:9`). Off stops every CSS animation and transition through
`polish.css:69`, and JS controllers read `AtelierMotionPolicy.query()`.

### Busy loops

| Animation | Where | Duration · easing | Fires | Enter / exit | Neighbours | F · C · O |
| --- | --- | --- | --- | --- | --- | --- |
| `.spinner` charge ring | `krackle.css:56-73` | 1040 ms `steps(6, end)` ∞ (a count, 173 ms per dot) | Any busy control; frequent | Loop; removed instantly | Activity ring at the same tempo; WAAPI rings share the period but glide | ✓ · ✓ · static crest at top |
| Activity ring, indeterminate | `krackle.css:141-162` | 1040 ms `steps(6)` | While jobs run | Loop | Topbar; visible during export builds | ✓ · ✓ · static |
| Determinate bar | `krackle.css:86-109`, `style.css:596` | Bubbles drift 1600 ms linear ∞; width 300 ms `ease` | Downloads, imports | n/a | n/a | ✓ · ✓ · static, width jumps |
| Indeterminate `<progress>` | `krackle.css:112-130` | 1040 ms `steps(12)`: big dots jump 4 px every 87 ms | Startup, export build | n/a | Sits under the 156 px stage in export review | ✓ · ✓ · plain bar (`polish.css:71`) |
| Export / glyph busy ring | `export-feedback.js:183-204`, `krackle-glyph.js:103-113` | 1040 ms linear; crest peaks at 10% and dots stagger 173 ms | Every export and job toast | Fades in over 120 ms after the drop (Full) | Toast, button and stage at once (item 1) | ✓ · ✓ · static crest |
| Install-button falling drop | `export-feedback.js:322-327` | 420 ms (.55,0,1,.45), squash `scale(1.3,.5)` at 94% | Each export | n/a | Behind the review overlay blur | ✓ · – · – |
| Material saving loop | `material-save.js:183-210` | 960 ms linear plus 960 ms swatch pulse (.2,0,0,1) | Optional; real saves don't use it | n/a | n/a | ✓ · ✓ · static |
| Viewport loader | `viewport-loader.js:20-25`, `:175-255` | Coalesce 220 ms (.2,0,0,1) + 6 ms/dot; ring 1200 ms linear; bob 1200 ms (.42,0,.58,1); boil 900-1116 ms; drift 2400 ms | Every model open | No show-delay; ready cancels instantly (item 6) | Model's 420 ms sweep and 260 ms framing follow | ✓ claims tier 2 (refused → 48 px glyph) · static · static |
| Stage busy | `krackle-stage.js:17`, `:275`, `:392-458` | Drop 420 ms, splash to 1.05 s; head 0.7 rev/s (1.43 s); springs ω ≈ 9.5 rad/s, ζ = 0.6 (≈ 9% overshoot, ≈ 0.7 s settle at stiffness 1) | Export review, edit import, startup indexing | A fresh busy drops ink; busy → busy continues | `<progress>` below, busy toast above (items 1, 7) | ✓ claims · still formation · still |

### Results

| Animation | Where | Duration · easing | Fires | Enter / exit | Neighbours | F · C · O |
| --- | --- | --- | --- | --- | --- | --- |
| Success starburst | `export-feedback.js:208-230`, `material-save.js:235-255`, `krackle-glyph.js:124-142` | 420 ms with timing (.2,0,0,1): peak at 87 ms, rebound at 150 ms; flecks 460 ms | Every successful job | Holds; button reverts by hard cut at 1800 ms | Toast, button, stage and Activity together | ✓ · ✓ · static |
| Warning cracked ring | `export-feedback.js:232-250` and twins | Ring 380 ms eased (impact at 65 ms); chunk 620 ms linear with fall/rise per keyframe, released at 186 ms | Partial results | Holds | Same | ✓ · ✓ · static |
| Error splat | `export-feedback.js:252-283` and twins | Splat 520 ms (squeeze 58 ms, peak 108 ms); satellites 560; drip 640; dazed orbit 1100 ms at 260 ms with quadratic slow-down, ≈ 1.36 s total | Failures | Holds | Same | ✓ · ✓ (with orbit) · static |
| Info drop | `krackle-glyph.js:116-122` | 420 ms linear timing; fall (.55,0,1,.45), rise (0,.55,.45,1), squash 1.12 × .84 | Update drop, empty projects | n/a | n/a | ✓ · ✓ · static |
| Busy → result handoff | `export-feedback.js:296-301` | 140 ms (.2,0,0,1) fade plus scale .7 | Each export result | n/a | Missing from the glyph (item 9) | ✓ · ✓ · instant |
| Loader outcomes | `viewport-loader.js:270-335` | Empty: 520 ms bounce + 60 ms/bubble; error: 520/560/680 ms + orbit 1300 ms at 300 ms (≈ 1.6 s); moment released after 1.5 s / 3.3 s | Empty or failed loads | Message renders at once | n/a | ✓ · static · static |
| Stage results | `krackle-stage.js:18`, `:343-349`, `:396-418` | Success gathers 180 ms, then kick and ripple; warning stamps over 80-420 ms and drops over 300-950 ms (bounce); error squeezes 160 ms, then kicks; orbit from 0.5 s; sleeps after 1.5 / 1.5 / 3.3 s | Export review results | The result replaces whatever was playing at once | Toast pops at the same moment (item 1) | ✓ · still · still |

### Entrances, brand and surfaces

| Animation | Where | Duration · easing | Fires | Enter / exit | Neighbours | F · C · O |
| --- | --- | --- | --- | --- | --- | --- |
| Logo entrance | `logo-entrance.js:13-16`, `:287-299`, `:364-378` | 320 ms (.2,0,0,1), opacity .58 → 1, 2 px rise; six bubbles 280 ms, peaking at 51 ms, 6 ms stagger | Once per launch plus replay click | Starts *below* the already-visible static mark (item 8) | The Full launch formation draws the same mark at the same time | ✓ · ✓ (item 4) · static |
| Empty Edited Assets | `empty-assets.js:219-261` | Tray 300 ms (overshoot lands at 74 ms); guides 260 ms; bubbles 420 ms at 40 + 55 ms each (ends ≈ 625 ms); drop 360 ms at 120 ms | First confirmed emptiness per project | Entrance only; no idle loop | n/a | ✓ · ✓ · static |
| Grid empty states | `empty-state.js:71-101` | Tray 280 ms; splat 520 ms; bubbles 460 ms at 60 + 70 ms each | Empty folder, no matches, failed load, no projects | **Replays on each rebuild, including every keystroke** (item 2) | n/a | ✓ · ✓ · static |
| Texture wipe | `texture-reconstruction.js:63-110`; caller `app.js:2309` | 320 ms; front eases out cubically; 0.35-width growth band | Every edited-texture refresh | Old preview underneath; canvas removed at the end | Grid and sidebar copies run together | ✓ · static · static |
| Folder flap | `folder-flap.css:25-52` | Open 220 ms `--krackle-pop` (≈ 10% overshoot, peak ≈ 130 ms); close 150 ms (.2,0,0,1); back panel 180 ms | Every folder hover or focus | Open slower than close ✓ | Card background/border at 120 ms | ✓ · ✓ · instant (`folder-flap.css:55-61` for OS) |
| Theme wave | `preferences.js:38-56` | 240 ms (.2,0,0,1) clip-path; 80% of the radius is covered by ~96 ms | Theme pick | n/a | Claims tier 2 | ✓ · – · – |
| Primary-button pop | `surface-adapters.js:49-59` | 8 dots, 200 ms (.2,0,0,1), 28 × 22 px | Each primary click | n/a | Coincides with dialog opens and the stage drop | ✓ · – · – |
| Project fall / update drop | `surface-adapters.js:39-47`, `:60-70` | Fall 420 ms (.55,0,1,.45) to `scale(1.2,.6)`; drop-in 260 ms (.2,0,0,1) | Rare | n/a | n/a | Fall F only; drop F + C |
| First-export colours | `polish.js:142-160` | 460 ms (.2,0,0,1), up to 6 dots | Once | n/a | **Refused while the review stage owns the moment** (item 1d) | ✓ (tier 3) · – · – |
| Trash drain | `polish.js:110-125` | 300 ms (.2,0,0,1); snapshot clips upward; dots fall 12-22 px decelerating | Each delete | Exit only | Undo toast enters | ✓ · ✓ · none |

### Studio chrome (tokens: `--studio-motion-fast` 120 ms, `--studio-motion-standard` 200 ms, `--studio-easing` (.2,0,0,1), `tokens.css:92-94`)

| Animation | Where | Duration · easing | Fires | Enter / exit | Neighbours | F · C · O |
| --- | --- | --- | --- | --- | --- | --- |
| Card hover / press | `style.css:1426-1427` (overrides `:180`), `:186`, `:209` | 120 ms (.2,0,0,1) on background, border, colour; imported box-shadow untransitioned | Constant | Symmetric | Folder flap 220 ms; raised charge switches instantly (≥ 3:1 on both surfaces) | ✓ · ✓ · instant |
| Hero portrait fade | `style.css:207-208` | 200 ms (.2,0,0,1) | Thumbnail load | Fade in only | n/a | ✓ · ✓ · instant |
| Toast | `style.css:626-633`; timer bar `polish.css:37-40` | In 200 ms `ease`, 10 px; timer linear; **out 0 ms** | Very frequent | 200 / 0 (item 5) | Siblings jump on removal | ✓ · ✓ · none |
| Dialog | `style.css:1424-1425`, `continuity.css:32-37` | Panel 200 ms (.2,0,0,1), 4 px; backdrop 120 ms `ease` in and out | Frequent | 200 / 120 ✓ | n/a | ✓ · ✓ · none |
| Library navigation | `continuity.css:22-28` | Old view out 120 ms `ease`; new view in 160 ms (.2,0,0,1), ± 8 px by direction; shared elements 200 ms | Every navigation | 120 / 160 ✓ | n/a | ✓ · ✓ · none |
| Rolling counter | `polish.css:42-45`, `polish.js:31-45` | 160 ms `ease`; always rolls up | Per filter keystroke | n/a | n/a | ✓ · ✓ · none |
| Repeat badge | `app.js:157` | 120 ms (.2,0,0,1), scale .85 → 1 | Repeated toasts | n/a | n/a | ✓ · ✓ · none |

## Considered and rejected

- **Pulsing the busy crest under Off or reduced motion** to avoid a frozen-looking
  ring. Off is defined as "Stills only". The static crest plus the status text is the
  contract.
- **CSS `linear()` spring easings.** They express overshoot well, but WebKitGTK support
  is unverified. Per-keyframe cubic-beziers (item 3) get the same result everywhere.
- **Softening results with glow or gradient follow-through.** Krackle forbids gradients
  and glows.
- **More ripple particles in the stage success.** That would spend the 8 ms frame
  budget for little gain. The stage's spring physics (ζ = 0.6) and 180 ms anticipation
  are already sound.
- **Slowing the theme wave.** It is a routine action, and ~100 ms of effective reveal
  keeps theme changes responsive, which the README asks for.

## Appendix: how the actual timings were computed

For a WAAPI effect with keyframe offsets and a timing-level `easing`, the progress at
time *t* is `ease(t / duration)`. Keyframes interpolate linearly in that progress. For
`cubic-bezier(.2,0,0,1)`, y(s) = 3s² − 2s³ and x(s) = 0.6 s (1 − s)² + s³. Each
offset *o* was solved for y(s) = *o* by bisection, and x(s) × duration gives the
landing time. Reference points: 40% of the time gives 80% progress, and 60% of the
time gives 93%.
