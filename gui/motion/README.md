# Motion inventory

Atelier's job feedback, ownership markers, empty states and brand moments speak
**Krackle**. Energy defines the silhouette; bubbles give it texture and movement;
at small sizes the silhouette survives with minimal texture. There are no outlines,
gradients or symbols: busy is a ring of dots a charge travels around; success is a
starburst; *completed with warnings* is a cracked ring whose broken chunk falls out
(the work finished, but something broke off); failure is a splat that drips. The
shapes give each outcome its personality; the text beside them says what happened.

Krackle is concentrated, not ambient. It appears for substantial job feedback
(export, import, saves, loading, Activity), restrained ownership markers (edited
rows), empty states and occasional showcase moments (the logo entrance, the first
export). Routine typing, hovering, pressing and theme changes stay responsive
without it, and chrome (toolbar, menus, form controls, category emblems) keeps its
Material Sharp glyphs. Artwork being edited stays visually trustworthy: Krackle
never textures a colour swatch or the material-inspection viewport.

Presentation owns artwork and animation lifecycle; application code owns project
state, requests and outcomes. The static interface remains usable when an optional
controller, image or animation API fails. No demo exporter, theme override or
simulated progress loop is part of the application.

**Interruption and ownership.** An animation is never entitled to finish its
performance. A real result replaces whatever is playing at once (mid-drop, mid-
coalesce or mid-loop), and readable status text and controls render immediately,
before the formation settles. A busy state that follows another busy state (a
destination check running straight into a build) continues the current animation
rather than dropping new ink. Only busy states loop; results animate once and hold
still, and a settled or hidden stage stops drawing. The large Krackle stage belongs
to the dialog the user has open (export review or edit import); other jobs that
finish or fail meanwhile report through their own toasts and Activity rows and
never take over that stage.

| Set | Production use | Slot / behavior |
| --- | --- | --- |
| Export feedback | Export button and notifications | 20px / 24px, charge ring, starburst, cracked ring, splat |
| Viewport loader | Existing 3D loading overlay | 72px, twelve-dot ring around a boiling ball; resting bubbles; KO splat |
| Folder flap | Generic folder cards | 76% of thumbnail, Krackle folder whose front panel tips open |
| Material save | Save-result notifications | 24px, swatch, charge ring, same result shapes |
| Logo entrance | Topbar brand | Existing 32px mark, one 320ms entrance with a bubble splash |
| Empty assets | Confirmed empty Edited Assets sidebar | 112px tray of bubbles, brief entrance then still |
| Texture reconstruction | Edited texture previews in the grid and sidebar | New pixels arrive through swelling halftone dots |
| Continuity / polish | Navigation, editors, menus, counters and confirmed operation feedback | `../continuity.js`, `../polish.js`; disposable snapshots, real outcomes only |
| Krackle glyph | Job toasts and Activity job rows | 16-24px, the same micro shapes for any job outcome |
| Empty state | Empty folder, no matches, failed folder load, no projects | 64px, bubbles drop in once |
| Krackle stage | Export review and edit import dialogs | 132-156px canvas particle formations |
| `krackle.css` | Every `.spinner`, progress bars, the Activity ring, import segments, edited rows | CSS only |

## Artwork source and rules

`scripts/krackle_art.py` draws every Krackle illustration once. It writes the
standalone `.svg` files here and the copies embedded in the controllers, in
`krackle.css` (spinner masks) and in `index.html` (`folder-flap-template`), so the
editable and embedded artwork cannot drift. Run it after any geometry change;
`python scripts/krackle_art.py --check` fails when a copy is stale and is part of
the browser checks.

- **Composition:** bubbles gather into one or two deliberate dark masses on the
  shadow side and thin into isolated satellites, leaving broad clean energy
  elsewhere. No bubble touches a silhouette's edge: in the stage a bubble may only
  sit on a dot at least one lattice step inside the shape, and its size is capped by
  that depth, so thin bands such as the ring keep a sparse centreline. Success stays
  mostly clean, a warning darkens the fracture and a failure carries one substantial
  mass, always with its outline intact. Highlights are crisp Paper specks (the
  charge crest swells and catches a few), never a soft glow or gradient.
- **Inks:** a formation uses one energy ink (two at most while one state hands over
  to the next). Bubbles and glints are not inks: bubbles are holes that show the
  surface behind (`--krackle-hole`, ink black on dark surfaces, the surface or button
  colour on light ones) and glints are a small fixed Paper highlight.
- **Colour:** energy uses Atelier's semantic tokens through the `--krackle-*`
  variables in `krackle.css`, so every palette, including custom palettes, keeps its
  tested contrast. Any future skin-derived accent and its clash guard change only
  interface accents, never an asset's colour values.
- **Sizes:** at 48px and below glyphs are drawn by hand rather than sampled from a
  formation; the large stage keeps its dots about 8px on screen.

## Continuity and polish lifecycle

`AtelierMotion.polish.mount(host, {state, frames, duration})` returns `setState`,
`destroy` and a completion promise. Replacing or removing a host cancels its
previous effect; page hide and forced/OS reduced motion release active effects.
View Transition names are transient and cleaned after completion or cancellation.
The actual request/close is independent of the visual completion. Dialogs retain
plain CSS exits when discrete transitions are supported; older engines close
immediately. Existing save/export controllers also follow the shared motion policy.

The optional first-export color burst requires a confirmed successful export and
real selected-preview colors, persists its one-time flag locally, and becomes
static chips with reduced motion. Logo replay is an explicit click/keyboard
action. The loader's artwork tint remains contrast-corrected on its fixed surround.

Browser coverage: `tests/browser_smoke.py --polish-only --report-dir <folder>`.
Native coverage: `tests/desktop_smoke.py --fixtures` with isolated
`ATELIER_DATA_DIR`; its `polish` report checks static lifecycle, operation identity,
collation, segments, preferences and the actual native launch/title-bar bridge.

# Texture reconstruction

`texture-reconstruction.js` exposes `AtelierTextureReconstruction.refresh(image,
src, {project})`, `disposeWithin(container)` and `clear()`. Only edit notifications
and successful Replace Texture actions call it; ordinary browsing and initial
imports do not animate. Grid and sidebar refreshes use the same project-bound
edited PNG URL and wait for the real image load before starting.

The updated image remains underneath a temporary, non-interactive canvas. Its
pixels arrive through a 45° halftone screen (about 14 dots across a tile, 8 in the
compact sidebar): each dot swells from nothing, outward from the centre, until the
dots overlap into the finished image, settling in about 640ms/430ms. The wipe swap
sends the same swelling dots across the old preview from left to right. Rectangular maps retain contain fit and transparency. At most four
canvases animate concurrently; offscreen, hidden and reduced-motion views update
statically. Repeated saves replace the previous effect. Navigation, list redraw,
project changes, failed reads, missing canvas support and page hide release the
temporary layers. Presentation does not write textures or delay image requests.

`tests/texture_reconstruction_checks.py` covers actual image arrival, external
save and replacement integration, exact final pixels, repeated saves, reduced
motion, optional component failures and abandoned project/grid updates. Run the
focused browser checks with `tests/browser_smoke.py --texture-reconstruction-only
--report-dir _work/texture-reconstruction-checks`.

# Export feedback

Lifecycle adapted from the user's Gemini export feedback controller (15 October
2026); the artwork is now Krackle. Idle is a drop of ink above a tray of energy.
Busy is the six-dot charge ring: each dot swells and shows a bubble as the charge
passes, clockwise, every 1040ms. Success pops a starburst (420ms) with four flecks
thrown out; completed-with-warnings stamps a cracked ring and drops its chunk,
which bounces twice (620ms); failure squeezes to a point, bursts into a splat with
satellites and a drip, and leaves one dazed bubble circling to rest (about 1.4s,
decorative; the toast text is already there). The SVG is the editable static
resting vector; the controller embeds the same geometry, both generated by
`scripts/krackle_art.py`. CSS uses Atelier's semantic colour tokens.

## Ownership and integration

- `export-feedback.js` provides `AtelierMotion.exportFeedback.mount(emptyHost,
  {state, reducedMotion})`. Its handle supports `setState`, `replay`,
  `setReducedMotion` and idempotent `destroy`. It owns only its inline SVG,
  animation effects and lifecycle listeners. There are no API or storage calls.
- States are `idle`, `busy`, `success`, `warning`, `error`. The busy loop is
  indeterminate (1040ms); terminal transitions are one-shots of 420ms to about
  1.4s, released when they finish. Both OS
  reduced motion and the forced `reduce` setting select static poses. Hidden
  documents stop loops, resuming only still-busy work. Unavailable/throwing WAAPI
  degrades to static artwork. Finished effects are released; detached/replaced
  hosts and duplicate mounts dispose old instances.
- `export-feedback-ui.js` mounts the button and each export toast separately.
  `begin(button, project)` returns a result callback guarded by operation and
  project. Only the latest operation can update/reset that button. After 1800ms
  the static download icon returns; this timer never gates another export.
- Toast removal, timeout and click share one cleanup path. Hover pauses terminal
  toast dismissal. Text is inserted with `textContent`; dynamic filenames and
  backend errors never become SVG/HTML markup. Existing non-export toasts keep
  their previous behavior.
- `_runInstall` starts motion after validation/overwrite confirmation and maps
  actual results: clean completion -> success; client/server skipped items,
  missing mods folder or built-but-not-installed -> warning; build/network
  failure -> error. Detailed skipped-item messages retain their 16-second
  duration. Requests, payloads, project headers and button availability remain
  under the existing application logic. Optional presentation failures fall
  back to existing notifications without changing the export result.

`../export-review.js` adds the review/result surface around this existing
feedback. It lists included/excluded changes, uses indeterminate build progress
and preserves the latest result for the session. Application guards reject stale
project/selection/settings snapshots and material/viewport drafts or active saves.
The destination conflict check has a timeout; builds are never automatically
retried or cancelled by presentation. Built-but-not-copied results expose the
exported files separately from installation failure. `tests/export_review_checks.py`
uses intercepted responses to check these contracts without writing a mod.

## Checks

`tests/export_motion_checks.py` runs through `tests/browser_smoke.py` with real
frontend functions and intercepted export responses. It covers lifecycle,
reduced motion, visibility, unsupported animation, outcomes, rapid operations,
project changes and toast disposal. No game/mod output is written by these
fixtures. `tests/desktop_smoke.py` also checks static states and destruction in
native WebView2. In-game compatibility is a separate release check.

# 3D viewport loader

Lifecycle adapted from the user's Gemini viewport loader controller (15 October
2026); the artwork is now Krackle and shares geometry with `viewport-loader.svg`.
Loading coalesces twelve dots out of the centre around a ball of energy (220ms),
then the charge travels the ring while the ball bobs, its bubbles boil out of step
and three loose bubbles drift. Empty drains the ball away: the ring fades and three
bubbles drop to the floor and bounce. Error squeezes and bursts into a dripping
splat, then three dazed bubbles circle above it and slow to a stop; the existing
message and controls appear immediately.

The user requested clearly visible animation sizes. The loader occupies **72px**
(a 48-unit viewBox with approximately 48px outer framing on screen), compared to
the supplied 44px demo. Export feedback is **20px** in the button and **24px** in
toasts. Fixed dimensions prevent layout movement during state changes.

`AtelierMotion.viewportLoader.mount(emptyHost, {state, reducedMotion})` returns the
same `setState`, `replay`, `setReducedMotion`, `destroy` handle shape. It extends
the existing namespace without replacing export feedback. States are `idle`,
`loading`, `ready`, `empty` and `error`; replay only repeats loading assembly.
The 220ms assembly transitions into the 1200ms charge loop. These are
indeterminate decoration, not a percentage or model progress measurement.
Ready cancels immediately; empty settles in about 640ms and error in about 1.6s. Finished effects are
released, duplicate mounts destroy their predecessor, and a partial WAAPI failure
cancels all effects and selects a static pose for that instance. OS/forced reduced
motion and hidden-document behavior are handled explicitly.

`viewport.js` owns this persistent host's lifetime. `clearModel()` destroys the
old animation; both open paths mount after clearing/capturing the new generation.
Successful geometry hides and destroys the loader before background materials
start. Empty/error states preserve their existing messages. Stale successes and
failures do not touch the current loader. A denied `canLeave()` leaves it intact.
Callers must explicitly destroy before removing/replacing a loader host; unlike
short-lived export toasts, this component needs no DOM-wide observer.

The static fallback uses bundled Material box/error symbols rather than an
animated spinner, so absent scripts or failed presentation cannot imply that an
empty/failed load is still working. Mount/state failures restore this fallback
without changing decoding, project headers, API requests, cameras or materials.
No new dependencies are needed. Fixed dark-surface accent/error colors remain
legible when the surrounding application is in light mode.

`tests/viewport_motion_checks.py` is run by `tests/browser_smoke.py`. It exercises
the actual viewport functions using controlled Three.js geometry and API responses:
fast readiness, deferred materials, empty/error results, late geometry disposal,
rapid reopening, close/save guards, optional-script failures, animation lifecycle,
and 72px rendering at two desktop sizes in both themes. The optional `--mesh`
browser run additionally loads a real previously decoded GLB. The native desktop
smoke checks static states, dimensions and teardown in WebView2.

# Folder flap

The interaction was initially adapted from the user's Gemini folder flap
(15 October 2026). The artwork is now a Krackle folder: back and front panels of
energy in the folder colour, a bubbly top edge on the front panel, and one composed
mass of bubbles punched through to the tile in the lower right.

`folder-flap.svg` is the editable static vector. Its geometry is also embedded in
`index.html`'s `folder-flap-template`, avoiding an extra request per folder or a
JavaScript animation controller. Keep these copies in sync when changing artwork.
`app.js`'s `renderCardIcon` clones the template only for generic folder icons;
missing templates fall back to the existing Material symbol. The same helper runs
after failed portrait requests, whose original `thumbnail` property remains set.
Loaded hero/skin portraits, category symbols, asset previews and their fallbacks
keep their existing rendering. The inline SVG has no IDs, events or external
references, and the icon adapter leaves it alone.

Scoped CSS tips the front panel open (a skew and squash from its base, 220ms with a
small overshoot) on fine-pointer hover or keyboard `:focus-visible`, returning in
150ms. Hover adds no particles.
Focus retains the open pose after the
pointer leaves. Coarse pointers have no hover pose. OS/forced reduced motion
selects immediate static poses. The existing native button owns clicks, Enter,
focus outlines and press feedback; Space uses the library preview shortcut when
one is available, otherwise native folder activation. No animation controller,
timers or cleanup hooks
are added. Replacing a grid automatically cancels its CSS transitions.

The existing 76% icon sizing is applied once: a **~102px SVG slot** in a 134px
thumbnail, with **~90px painted width** and no clipping in either pose. Both paths
inherit the existing theme-aware folder color. SVG opacity attributes leave the
closed folder visible when motion CSS is missing.

`tests/folder_motion_checks.py`, invoked by `tests/browser_smoke.py`, covers
eligibility, image fallbacks, actual navigation, keyboard/pointer behavior,
reduced motion, touch media queries, dimensions in both themes and grid rebuilds.
Native WebView2 checks the static SVG size and reduced-motion styles; keyboard
behavior is tested in Chromium because the native smoke window is hidden.

# Material-save feedback

Lifecycle adapted from the user's Gemini material save controller (15 October
2026); the artwork is now Krackle and shares geometry with `material-save.svg`.
Idle is a swatch: a ball of energy shaded by bubbles, with a glint. Saving runs the
charge ring around a small pulsing swatch. Results use the same starburst, cracked
ring (saved, with something lost such as intensity metadata) and splat as export
feedback. The glyph is decoration beside the save message, never the material's
own colour.

`AtelierMotion.materialSave.mount(emptyHost, {state, reducedMotion})` returns the
same `setState`, `replay`, `setReducedMotion`, `destroy` handle shape as the other
components. States are `idle`, `saving`, `success`, `warning`, `error`. The icon
occupies **24px**, with about **22px** painted width. Success pops in 420ms, warning
drops its chunk in 620ms and error splats in about 1.4s. Saving has an optional 960ms loop, but actual
save hooks retain their existing `Saving…` text and use only completion toasts.

Direct terminal mounts animate once; identical states do not replay. Finite
effects and their finish callbacks are released. OS/forced reduced motion and
hidden documents cancel motion; only genuinely busy work resumes. Missing,
throwing or partially failing WAAPI cancels all effects and leaves static CSS
artwork. State validation excludes inherited object properties. Duplicate mounts
destroy the prior instance; callers explicitly destroy before removing hosts.

`material-save-ui.js` provides the save-only `AtelierMaterialSaveFeedback.toast`.
It creates a 24px static fallback beside the motion host, inserts dynamic messages
with `textContent`, and returns the exact toast element. Its `remove()`, click and
timeout paths share idempotent disposal. Hover pauses expiry. Failed mounting
leaves the fallback visible; cleanup errors cannot prevent removal. The existing
toast area's live-region behavior is retained. No DOM-wide observer is added.
`app.js`'s no-throw `toastMaterialSave` boundary falls back to escaped generic
notifications if the optional presentation helper fails or is absent.

The material dialog captures its editor, project, material name and exact submitted
payload before awaiting persistence. Duplicate Save clicks on that editor share
the in-flight guard. A late result cannot close or relabel another editor/project.
If colors, scalars or intensity metadata change during the request, the newer
draft remains open with qualified warning feedback. Clean saves close immediately;
the toast plays independently. Missing intensity persistence uses warning artwork
and retains the explanatory message. Failed requests retain the draft and inline
error. Other callers of `_warnIntenLost` are unchanged.

Viewport saving preserves its existing per-material requests, submitted snapshot,
project header, draft comparisons and retry behavior. Any failed material yields
the original warning/counts; successful submissions with newer dirty edits get
qualified warning feedback. Completion releases the singleton saving guard even
if the view is stale. Editor-local status/controls update only for the originating
view, and an old project's notification identifies that project. Non-save `note`
calls and the Save button's text/count/disabled behavior are preserved.

No Python API, payload fields, intensity persistence rules, model rendering or mod
formats change. `tests/material_save_motion_checks.py` exercises the controllers
and real save hooks with intercepted responses through `tests/browser_smoke.py`.
The native desktop smoke checks 24px static states and disposal in WebView2.

# Logo entrance

`logo-entrance.js`, `.css` and `.svg` adapt the supplied Gemini entrance without
redrawing the Atelier mark. The controller uses the caller's unchanged PNG inside
an inline SVG and exposes `AtelierMotion.logoEntrance.mount(emptyHost, options)`.
States are `settled` and `entering`; the handle provides the common state/replay/
reduced-motion/destroy methods and a `ready` promise. The entrance fades from
0.58 opacity and translates 2px over 320ms while six charge bubbles pop out from
behind the mark and fade inside the slot; settling cancels them with the entrance. The topbar keeps its existing 32px
slot, avoiding layout movement or an enlarged startup splash.

`logo-entrance-ui.js` owns a single document-start attempt. It keeps the original
image visible until both controller/image readiness succeed, then exchanges equal
slots in one task. Missing scripts, load failure, hidden startup, reduced motion
or unavailable animation keep the static mark. Startup never waits for the motion;
theme changes, project changes and ordinary renders do not replay it. Page teardown
destroys its effects/listeners and restores the caller-owned fallback.

# Empty Edited Assets

`empty-assets.js`, `.css` and `.svg` keep the supplied Gemini controller's
lifecycle with Krackle artwork: a tray of energy holding four loose accent bubbles,
a drop of ink waiting above it and halftone registration dots in the corners.
Scoped selectors override the sidebar's ordinary small-icon size only for this
illustration. `AtelierMotion.emptyAssets.mount(emptyHost, options)` accepts
`settled` and `entering`; the entrance stamps the tray up, drops the bubbles in one
after another with a bounce and swings the drop in, finishing in about 480ms, with
no idle loop.
Reduced motion, hidden/offscreen hosts or unavailable animation settle statically.
Duplicate mounts and explicit destroy release owned effects/listeners/observers.

`empty-assets-ui.js` follows authoritative imported-asset responses, after the
application's project/request-generation checks. Loading, stale responses and
failed requests cannot establish emptiness. Filtering a nonempty project's sidebar
to zero matches does not show the tray. Each project enters on first confirmed
emptiness or a genuine nonempty-to-empty transition; ordinary sidebar rerenders,
search, theme changes and returning to the same empty state stay settled.
The adapter disposes before replacing its host and hides the static package
fallback only after successful mounting. Text and export controls remain owned
by the sidebar, not the animation.

## Entrance validation contract

Check both themes, reduced motion, hidden startup, image/WAAPI failures, repeated
mount/unmount, equal brand bounds, visible 112px tray bounds and absence of idle
effects. Confirm that project loading/failure/search cannot replay or falsely
trigger empty-state motion, and that no new API/project writes are introduced.
Run the combined browser suite and native smoke before claiming end-to-end
integration; asset presence and the older four-set test counts alone are not
validation of these two adapters.

Saved-preview swaps pass the mode 'wipe' to AtelierTextureReconstruction.refresh.
The controller retains a small previous-preview snapshot until the real image
loads, then wipes to the new pixels over 320ms. Alpha, contain fit and lifecycle
cleanup remain intact. Block assembly remains the default for direct consumers.

The viewport's existing render lifecycle also owns its 420ms wireframe/shaded
clipping sweep, 150ms linear colour and texture blends, and 260ms camera framing.
`viewport-effects.js` owns disposable display variants and bounded optional bloom
targets. Model/project replacement and close release these resources; the hidden
viewer stops rendering. Reduced motion selects the final shaded colours and
camera position immediately. No additional idle loop or automatic standing-idle
playback is introduced. Browser and native viewer checks include rendering,
interruption, alpha captures and target disposal. Native automation intercepts
only the final download click to inspect real encoded bytes before an OS dialog.

# Krackle glyphs, empty states and the stage

`krackle-glyph.js` (`AtelierMotion.krackleGlyph`) renders the micro shapes for job
outcomes: `busy`, `info` (a drop), `success`, `warning` and `error`.
Operation toasts (`toastSpinner(...)`) are owned by the export-feedback set, which
charges and then resolves into the same result shapes. When that controller is
absent, `AtelierKrackleGlyph.toastIcon(toast, type)` swaps the resolved toast's icon
for a glyph instead; the original icon stays in the slot as the fallback and
removing the toast destroys the glyph. Ordinary informational and warning toasts
keep their Material icons, because "warning" in those messages also covers cautions
and failures. Activity job rows show a 16px glyph beside each state label,
animating only when that job's state changes; a job that succeeded with skipped
items is labelled "Succeeded with warnings", the only place its cracked ring
appears.

`empty-state.js` (`AtelierMotion.emptyState`) supplies the art for
`AtelierPolish.empty`: an empty folder or project list (a tray with two bubbles
dropped in), no matches (three loose bubbles bounce to the floor) and a failed
folder load (a splat). Titles and descriptions stay authoritative; a failed mount
keeps the original outline drawing.

`krackle-stage.js` (`AtelierMotion.krackleStage`) is the full particle language
from the Krackle prototype, ported to plain Canvas 2D without p5.js. `mount(host,
{state, size, reducedMotion})` accepts `idle`, `busy`, `success`, `warning` and
`error`. A fresh busy starts as a drop of ink that splashes into a puddle and is
drawn out into a charging ring of comic-sized dots; results pop into a starburst
with a ripple, crack the ring so its chunk falls, or squeeze and burst into a
knocked-out splat with three dazed bubbles. Ink merging uses a blur-and-threshold
canvas filter where available and falls back to separate haloed bubbles when
unsupported or slow (WebKitGTK). Settled results stop the frame loop
(`data-am-sleeping="true"`), and an IntersectionObserver stops a stage whose
dialog is hidden. Hidden documents pause; reduced motion jumps to each formation.
`mount` throws without canvas, so callers keep their static progress UI. The export
review shows a 156px stage while checking and building, then the result formation
(cancelled exports hide it) under a heading that names the outcome ("Mod exported
with warnings"); long reports scroll inside the dialog so the heading and actions
stay visible. The edit import dialog shows a 132px stage while open.

`krackle.css` restyles existing feedback rather than adding new effects: every
`.spinner` becomes the six-dot charge ring, whose crest counts round dot by dot;
the update download bar is energy with drifting bubbles and an ink-blob leading
edge; indeterminate `<progress>` runs dots along the bar; the Activity ring is six
dots that fill clockwise with progress; import results are one dot per asset; the
first-export colour moment throws the skin's colours as bubbles; edited sidebar
rows keep their accent corner with a single bubble. Every loop stops under OS or
Atelier reduced motion (`[data-motion=reduce]`).

Typing, dialog backdrops and material inspection stay plain. Full allows a brief
primary-button pop and a bubble theme wave; Calm/Off skip both. Category
emblems remain Material Sharp pending D4 approval. Swatch interiors and dye /
texture previews keep their exact content; HDR energy stays outside the swatch.

`tests/krackle_motion_checks.py` (via `tests/browser_smoke.py`) covers the spinner,
job toast glyphs and fallbacks, empty states, the stage's sleep, hidden-dialog and
cleanup behaviour and the Activity ring, and fails if the generated artwork is
stale.

Wave 2 adds a 300 ms deletion drain to the existing inert sidebar snapshots.
Snapshots contain no live asset identifiers, are noninteractive and never delay
the delete request or rendering. Loose bubbles stay within a 48 px micro host;
OS/Atelier reduced motion skips the drain. Detached snapshots and their effects
are disposed after completion. Undo itself is ordinary focusable UI, with the
existing hover-paused toast timer.

First-run validation uses `krackleGlyph` at 24 px beside the step heading. A
validation change destroys the previous mount; it does not decorate input fields
or delay Next. The first-run and Settings dials share Full/Calm/Off preferences.

Viewport `canLeave` and `close` now return promises. Every dependent action awaits
them before clearing geometry or changing skin. A cancelled answer retains the
draft, loaded geometry and loader; export's public pending-edit guard still
focuses Save without offering to discard anything.

Search typing remains plain. A completed empty global result may show three
decorative bubbles, with no per-keystroke effect. A new query aborts the old
request; Escape and navigation dispose its popover. Roster filtering, card focus
and Continue do not wait for animation. Portrait accents stay behind artwork,
and costume opening follows the actual mesh lookup with a folder fallback.

Wave 4a fixes outcome inks by measured surface luminance, independently of the
palette's semantic UI colours. Success uses Paper on dark surfaces and Ink with
Paper holes on light ones. Charge/Rift alone can follow sampled hero/skin art.
`krackle-inks.js` is pure sRGB: fitting guarantees 3:1 contrast; CIE76 distances
use CIELAB with a consistent D65 reference white (not CSS's D50 `lab()`). The
guard reserves outcome inks, nudges the smallest colour distance within 45°,
then tries other sampled colours and a full hue turn. Pink moves toward magenta;
gold/amber toward orange. Manual colours can retain a CLASH warning. SHIFTED
explains automatic changes in Settings. Primary buttons and the dark model
loader fit against their own surfaces.

`AtelierMotionPolicy.tier()` returns 3/1/0 for Full/Calm/Off; `allows(tier)` is
the shared gate. Legacy system/reduce values migrate to full/off. OS reduced
motion always forces Off. `query()` and `data-motion` retain their old contract;
`data-krackle` exposes the effective dial. Calm keeps micro responses but stops
particle frames on a still formation. Off keeps static feedback.

`AtelierMotion.moment.claim(kind,tier)` returns an idempotent release or null.
Only one Tier 2/3 formation owns the screen; refused stages render a hand-drawn
48 px glyph. Export review, edit import and the model loader release ownership
on completion, hiding or disposal. A Tier 3 kind can claim only once per page
session. Result states interrupt work immediately. Theme changes repaint still
formations without replaying a result. Tests cover the colour guard, every
palette, migration, OS overrides, stopped frames and competing stage ownership.

Wave 4b adds the local OFL Latin Bricolage display face, empty-space `.k-screen`,
Paper caption toasts, Mod tray corners and real Build drop. All existing toast
APIs, live regions and hover-paused timers remain. Repeat badges show up to five
bubbles, then a number. The update drop opens the existing offer/notice; it never
blocks input. Container progress drives index formations and a once-per-launch
A sampled from the original PNG. Calm/Off retain the plain launch splash. Index
failures show the KO result beside the original explanation and Settings action.

Texture drops upload `File` bytes through `replaceTextureFromFile`, the same
project-scoped FormData path as Replace with Image. Success uses the existing
texture refresh/reconstruction. Calm/Off keep the final preview without particles.
Cancelled Activity glyphs drain once; replaced rows dispose their controllers.
The empty-project drop starts the original creation dialog immediately. All
transient button/project bubbles release on hiding, policy changes and teardown.

Category candidates are generated at 24 and 102 px by `krackle_art.py`; review
HTML and both-theme PNG sheets live in `docs/review/wave-4b`. The hidden local
`atelier.experimentalKrackleEmblems=1` flag is for review only and defaults off.
Control glyphs keep Material Sharp. D4 remains a user decision.

Particle rendering uses preallocated circle command buffers, linked per integer
ink key, and native `beginPath` batches. Path2D has no reset method, so reusing
Path2D instances would accumulate geometry (see the WHATWG Canvas path API).
The merge guard measures RAF intervals against the observed refresh baseline;
14 ms of sustained excess disables merging. An absolute 14 ms threshold would
disable it even on an idle 60 Hz display. `perf()` reports sampled CPU costs and
frame intervals; `surfaces_checks.py` logs the median and verifies the 8 ms ceiling
plus a simulated slow-frame fallback. No Linux WebKitGTK result is claimed.

Wave 4c adds explicit Inspect/Showcase controls. `viewport-inspection.js` creates
one shared nearest-filtered toon ramp and disposable per-source toon variants.
Only display draws use them. A `try/finally` restores every source material object
and the grid; originals, textures, colours, alpha and editable drafts stay intact.
Reopening a model resets to Inspect. `showcase-art.js` draws a still 45° screen
and composed burst behind the model for the explicit mode and its captures.
The normal viewport RAF owns all 3D drawing; there is no second animation loop.

`AtelierViewport.captureModPoster(context)` refuses another project/skin, pending
edits or an unready model. It returns a clean Showcase canvas with camera/render
settings restored even on failure. `AtelierModCards.mount` is optional result UI:
it uses that capture, a labelled catalogue fallback, or no card. Result resets
abort old image/version work and revoke download URLs. Counts use completed
applied entries (`mod-card-data.js`), not the selected list. Packaging summaries
do not count as assets. Explicit custom-texture counts and dye-off masks do.
Warning cards include a crack/skipped count; failure has no card. Footer text is
always on Paper, and the build date survives reopening the last result. Clipboard
failure explains Save PNG; no optional card failure changes the export result.
`/api/app_info` is a local read of the bundled version, with no release request.

`AtelierFoley.play(drop|pop|splat)` is called only by an owned, visible Full
formation transition. Settings stores `atelier.foley` locally, default off.
WebAudio is initialized by an enabled pointer gesture. Oscillators/noise and gain
envelopes last 90–140 ms. Hiding, changing policy or disabling sounds cancels
active sources before suspending, so no old sound resumes later. Page teardown
closes the context. Unavailable or blocked WebAudio fails silently.

`showcase_checks.py` checks render-time toon use, exact material restoration,
capture camera/error restoration, all dial modes, silent audio gates, real card
counts/actions and failed builds. `test_mod_cards.py` checks the pure report/context
logic; frontend HTTP tests check local build identity. All are in the full suites.
