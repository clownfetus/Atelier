# Motion inventory

The six supplied animation sets have scoped production assets in this directory.
Presentation owns artwork and animation lifecycle; application code owns project
state, requests and outcomes. The static interface remains usable when an optional
controller, image or animation API fails. No demo exporter, theme override or
simulated progress loop is part of the application.

| Set | Production use | Slot / behavior |
| --- | --- | --- |
| Export feedback | Export button and notifications | 20px / 24px, actual busy/result states |
| Viewport loader | Existing 3D loading overlay | 72px, indeterminate while model work runs |
| Folder flap | Generic folder cards | 76% of thumbnail, closed/open outlines |
| Material save | Save-result notifications | 24px, actual persistence result |
| Logo entrance | Topbar brand | Existing 32px mark, one 320ms entrance |
| Empty assets | Confirmed empty Edited Assets sidebar | 112px technical tray, brief entrance then still |

# Export feedback

Adapted from the user's Gemini files `export_feedback_production_controller.js`,
`export_feedback_production_styles.md`, `export_feedback_standalone_svg.md` and
`export_feedback_self_contained_preview.html` (15 October 2026). The downloaded
preview and integration notes are reference material; their simulated exporter,
theme overrides and demo controls are not application code.

The download/tray geometry derives from Google Material Symbols Rounded under
Apache 2.0; retain the [bundled license](../vendor/material-symbols/LICENSE) and
upstream attribution. The SVG is the editable static resting vector; the
controller embeds the same geometry so startup needs no fetch or external SVG
resource. It adds separate success, warning and error groups. Update both files
if the artwork changes. CSS uses Atelier's existing semantic color tokens.

The studio polish squares the tray, payload and arrow, sharpens check/error
strokes and uses a pointed warning triangle with quieter tonal fills. This is
an Atelier adaptation of the original artwork, not an unmodified official Sharp
glyph. The embedded and standalone geometry remain identical; animation states,
timings and application integration are unchanged.

## Ownership and integration

- `export-feedback.js` provides `AtelierMotion.exportFeedback.mount(emptyHost,
  {state, reducedMotion})`. Its handle supports `setState`, `replay`,
  `setReducedMotion` and idempotent `destroy`. It owns only its inline SVG,
  animation effects and lifecycle listeners. There are no API or storage calls.
- States are `idle`, `busy`, `success`, `warning`, `error`. The busy loop is
  indeterminate (1040ms); terminal transitions finish within 240ms. Both OS
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

Adapted from the user's Gemini `viewport_loader_production_controller.js`,
`viewport_loader_production_styles.md`, `viewport_loader_standalone_svg.svg` and
`viewport_loader_self_contained_preview.html` (15 October 2026). Preserve the
Material Symbols attribution in the source; the corner framing references that
visual family. The standalone SVG and embedded controller markup share geometry.
Demo simulations and token overrides are excluded from the application.

The studio polish replaces rounded bracket corners with right angles and uses
sharp wireframe joins, preserving the original 72px slot and assembly/loading
timing. Circular progress and empty/error indicators keep their meaning.

The user requested clearly visible animation sizes. The loader occupies **72px**
(a 48-unit viewBox with approximately 48px outer framing on screen), compared to
the supplied 44px demo. Export feedback is **20px** in the button and **24px** in
toasts. Fixed dimensions prevent layout movement during state changes.

`AtelierMotion.viewportLoader.mount(emptyHost, {state, reducedMotion})` returns the
same `setState`, `replay`, `setReducedMotion`, `destroy` handle shape. It extends
the existing namespace without replacing export feedback. States are `idle`,
`loading`, `ready`, `empty` and `error`; replay only repeats loading assembly.
The 220ms assembly transitions into five synchronized 1200ms effects. These
are indeterminate decoration, not a percentage or model progress measurement.
Ready cancels immediately; empty/error settle in 180ms. Finished effects are
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

The interaction was initially adapted from the user's Gemini
`folder_flap_standalone_svg.md` and `folder_flap_production_styles.md`
(15 October 2026). The supplied HTML preview and integration notes were references;
demo controls, fixtures and layout overrides are excluded. The current artwork
replaces the filled pocket with official Google Material Symbols Sharp `folder`
and `folder_open` paths at optical size 48, weight 300, fill 0. Both sources are
recorded in `../vendor/material-symbols/sources.json`; retain the bundled
Apache 2.0 license and SVG attribution.

`folder-flap.svg` is the editable static vector. Its geometry is also embedded in
`index.html`'s `folder-flap-template`, avoiding an extra request per folder or a
JavaScript animation controller. Keep these copies in sync when changing artwork.
`app.js`'s `renderCardIcon` clones the template only for generic folder icons;
missing templates fall back to the existing Material symbol. The same helper runs
after failed portrait requests, whose original `thumbnail` property remains set.
Loaded hero/skin portraits, category symbols, asset previews and their fallbacks
keep their existing rendering. The inline SVG has no IDs, events or external
references, and the icon adapter leaves it alone.

Scoped CSS crossfades closed/open outlines, with a 1px open-pose lift, in 180ms on
fine-pointer hover or keyboard `:focus-visible`, returning in 150ms.
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

Adapted from the user's Gemini `material_save_production_controller.js`,
`material_save_production_styles.md` and `material_save_standalone_svg.md`
(15 October 2026). The supplied self-contained preview and integration notes are
references, not application code. Keep the Material Symbols Rounded attribution
and bundled Apache 2.0 license. The standalone SVG and embedded controller markup
share geometry; update both if changing artwork.

The studio polish gives the cartridge a clipped corner and square shutter, with
crisp check/error strokes and a pointed warning triangle. Quiet tonal fills and
circular progress/outcome rings remain. Sizes, states, lifecycle and save hooks
are unchanged; retain the original attribution for this adapted artwork.

`AtelierMotion.materialSave.mount(emptyHost, {state, reducedMotion})` returns the
same `setState`, `replay`, `setReducedMotion`, `destroy` handle shape as the other
components. States are `idle`, `saving`, `success`, `warning`, `error`. The icon
occupies **24px**, with about **21.5px** painted width. Success draws the check in
240ms; warning/error settle in 210ms. Saving has an optional 960ms loop, but actual
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
0.58 opacity and translates 2px over 320ms. The topbar keeps its existing 32px
slot, avoiding layout movement or an enlarged startup splash.

`logo-entrance-ui.js` owns a single document-start attempt. It keeps the original
image visible until both controller/image readiness succeed, then exchanges equal
slots in one task. Missing scripts, load failure, hidden startup, reduced motion
or unavailable animation keep the static mark. Startup never waits for the motion;
theme changes, project changes and ordinary renders do not replay it. Page teardown
destroys its effects/listeners and restores the caller-owned fallback.

# Empty Edited Assets

`empty-assets.js`, `.css` and `.svg` adapt the supplied Gemini technical tray.
Retain the source's Material Design Icons/Apache 2.0 attribution. The 112px SVG
uses sharp guides and a tray/deck with restrained tonal fill. Scoped selectors
override the sidebar's ordinary small-icon size only for this illustration.
`AtelierMotion.emptyAssets.mount(emptyHost, options)` accepts `settled` and
`entering`; its brief layered entrance finishes within 340ms and has no idle loop.
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
