# Local development and reliability checks

This branch includes the environment/baseline and critical reliability work, plus the Phase 2 Material 3 foundation. The application still uses Bottle, vanilla JavaScript, Three.js and pywebview. Project sidecars, Unreal paths and mod container formats are unchanged. See [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md) for theme, component, icon and artwork-cache decisions.

## This machine

The configured development directory is **`D:\AtelierDev\phase-0-1`**. It contains the native tools, a separate configuration, disposable projects, test exports, reports and screenshots. Its mods destination is `D:\AtelierDev\phase-0-1\test-mods`; it does not install into the game's mods folder. The existing `D:\Atelier` installation and projects were not edited.

From this repository in PowerShell:

```powershell
.\Start-AtelierDev.ps1 -DataDir 'D:\AtelierDev\phase-0-1'
# Open http://127.0.0.1:8767; Ctrl+C stops the browser-mode backend.

.\Start-AtelierDev.ps1 -Mode Desktop -DataDir 'D:\AtelierDev\phase-0-1'
```

Use one instance per data directory. Both browser and desktop modes support `-Port`; the default is 8767. An isolated desktop review can use `-Port 8778` alongside an installed application on 8767. Direct executable launches accept the equivalent `ATELIER_PORT` environment variable (1–65535). Desktop development mode enables developer tools. The source frontend is served with caching disabled, so reload after JavaScript/CSS changes; restart Python after backend changes.

`ATELIER_DATA_DIR` relocates configuration, projects, caches, exports, sets, logs and the desktop browser profile. GUI files still load from the source checkout. Without this variable, existing installations retain their original paths. Choose a normal local NTFS directory, preferably on the game's drive: the mesh tool uses hardlinks to a vanilla-only pak mirror. Codex's redirected Windows app-data storage rejected access to those hardlinks during testing; the directory above works.

## Recreate the environment

Use 64-bit Python 3.12 and Node.js (Node is needed by existing JavaScript regression tests, not by the application). On Windows the desktop shell also needs Microsoft Edge WebView2.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m playwright install chromium
.\Install-AtelierTools.ps1 -DataDir 'D:\AtelierDev\phase-0-1'
```

The installer script verifies release SHA-256 digests and extracts files without running AtelierSetup or changing registry/install settings. It preserves existing tool directories, keys and mappings. The full [Atelier 0.3.3 Windows bundle](https://github.com/clownfetus/Atelier/releases/tag/0.3.3) contains the fork's custom shader `retoc-rivals-cli`; the ordinary newer retoc release does **not** expose `dump-shaders` and `extract-shader`. Extraction uses the [maintained Inno Unpacker release](https://github.com/jrathlev/InnoUnpacker-Windows-GUI/releases/tag/ui_2_2_13). `tools-manifest.json` records installed binary hashes.

This machine additionally has the official Microsoft DXC 1.9.2609.5 tools, and AtelierMesh from the developer's [0.3.4 release bundle](https://github.com/clownfetus/Atelier/releases/tag/0.3.4). Native smoke checks verify the commands Atelier actually calls. Do not replace these tools based on version numbers alone.

For a fresh directory, use Atelier's Setup/Settings to select the game Paks folder, current mapping, Blender executable and a **development test-mods directory**. Keep native tools, AES keys, mappings, extracted game assets and local configuration out of Git. The source checkout contains none of those dependencies.

## Automated checks

```powershell
.\.venv\Scripts\python.exe tests/run_checks.py --report-dir 'D:\AtelierDev\phase-0-1\checks'
.\.venv\Scripts\python.exe tests/browser_smoke.py --report-dir 'D:\AtelierDev\phase-0-1\browser-checks'
node --check gui/app.js
node --check gui/viewport.js
.\.venv\Scripts\python.exe -m pip check
git diff --check
```

`run_checks.py` copies the source into a fresh temporary directory for each suite. It never reads the development tools or user projects. Native-dependent legacy cases therefore explicitly skip. Use `--suite test_reliability.py` for focused backend failure tests. Logs, package versions, timings and exit codes are saved with the report.

Browser checks run the real frontend and Bottle server in temporary app data. They use named fixtures for game browsing and native/network services, plus actual project HTTP requests. They exercise failed/partial saves, retry, editing while a save is in flight, project headers, stale preview responses and SSE errors. Test-only viewport access is injected into the intercepted module; production JavaScript has no test hooks. Screenshots cover both themes at 1024×768, 1280×800, 1400×900 and 1920×1080. The visual baseline uses `gui/index.html`, `gui/style.css` and `gui/app.js` from commit `2a3f4e2` with deterministic fixture data.

The Phase 2 checks additionally cover color-pair contrast, fonts/logo, large folder symbols, keyboard menus, theme persistence/OS changes/blocked storage, material draft preservation and reduced motion. Offline catalogue tests verify source parsing, exact ID/name matching, ambiguity, cache reuse and failed updates. These tests never crawl RivalSkins or download game artwork.

Use these report directories for the current phase:

```powershell
.\.venv\Scripts\python.exe tests/run_checks.py --report-dir 'D:\AtelierDev\phase-2\checks'
.\.venv\Scripts\python.exe tests/browser_smoke.py `
  --report-dir 'D:\AtelierDev\phase-2\browser-checks' `
  --mesh 'D:\AtelierDev\phase-0-1\native-checks\mesh\Marvel\Content\Marvel\Characters\1029\1029100\Meshes\10291\SK_10291_1029100.glb'
.\Start-AtelierDev.ps1 -Mode Browser -Port 8770 -DataDir 'D:\AtelierDev\phase-0-1'
```

Open `http://127.0.0.1:8770`, switch the appearance selector, browse Characters and a skin folder, then open a material/3D preview and verify export controls. The isolated destination remains `test-mods`. Optional portrait metadata checks run in the background at launch; the image cache is independent of projects and exports. Cached artwork works offline; uncached artwork falls back to a symbol if unavailable. Restart Python after changes to the catalogue parser or browse routes.

## Native checks

```powershell
$env:ATELIER_DATA_DIR = 'D:\AtelierDev\phase-0-1'
.\.venv\Scripts\python.exe tests/native_smoke.py
.\.venv\Scripts\python.exe tests/desktop_smoke.py
```

`native_smoke.py` reads a small real game texture, creates a new disposable project, edits it, builds the `.pak/.ucas/.utoc` set, publishes to a test folder, compares hashes, unpacks it and checks texture format/dimensions. The game's global container is copied into the readback fixture so native tools can resolve script imports. Reports stay under `native-checks`. This is a pipeline smoke test; it does not establish every texture format, game patch, material, world or mesh as compatible.

`desktop_smoke.py` opens and closes a hidden WebView2 window. It checks the real asset browser, symbols, font, logo, both themes, active project and viewport module; its middleware suppresses update downloads and thumbnail prefetch. The Phase 2 run loaded 69 root entries and 156 symbols. The report is `desktop-smoke.json`.

AtelierMesh was also exercised on `Characters/1029/1029100/Meshes/10291/SK_10291_1029100`. To repeat Chromium rendering/disposal checks with that decoded file:

```powershell
.\.venv\Scripts\python.exe tests/browser_smoke.py `
  --report-dir 'D:\AtelierDev\phase-0-1\browser-checks' `
  --mesh 'D:\AtelierDev\phase-0-1\native-checks\mesh\Marvel\Content\Marvel\Characters\1029\1029100\Meshes\10291\SK_10291_1029100.glb'
```

This checks geometry rendering and resource disposal through three open/close cycles. Its material API is deliberately stubbed: the screenshot is a geometry preview, not evidence of material fidelity.

## Packaging

For a clean committed source checkout, [PACKAGING.md](PACKAGING.md) describes the
review-package script, matching source archive, file manifest, checksums and the
actual frozen-executable smoke test. The direct PyInstaller command below remains
available for local iteration.

```powershell
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm `
  --distpath 'D:\AtelierDev\phase-0-1\build\dist' `
  --workpath 'D:\AtelierDev\phase-0-1\build\work' Atelier.spec
```

The existing spec packages the GUI, vendor libraries and Blender scripts. Native tools remain external. Set `ATELIER_DATA_DIR` before launching the built executable to use the isolated tools/configuration. This command builds a local executable; it does not publish a release or run the installer.

For Phase 2 use `D:\AtelierDev\phase-2\build\dist` and `D:\AtelierDev\phase-2\build\work`. The GUI directory is included recursively, so the local font, symbol paths, theme modules, logo and catalogue seed need no additional packaging rule. Downloaded portraits remain external cache files. A local Phase 2 executable was built successfully; this is separate from testing the installed application or an installer upgrade.

## Phase 2 evidence

- 178 regression checks passed; two native-tool cases explicitly skipped in the isolated runner.
- 14 Chromium workflow/design checks passed, including a real decoded GLB and repeated preview cleanup.
- Native WebView2 loaded the real index, local assets and synchronized light/dark/system controls.
- All 744 distinct artwork URLs in the seed downloaded and passed image validation in the development cache (about 70 MB); ordinary launches fetch images lazily.
- Live Characters and Magik skin browsing produced no uncaught JavaScript errors. Screenshots are under `D:\AtelierDev\phase-2\live-preview`; deterministic comparisons are under `browser-checks`.
- Syntax checks, dependency consistency and `git diff --check` passed.

The native export round-trip evidence from Phase 1 remains in `D:\AtelierDev\phase-0-1\native-checks`; this phase does not change encoding or container publication. No additional in-game compatibility claim is made.

## Export animation follow-up (15 October 2026)

The Gemini export animation is integrated in `gui/motion/` with scoped CSS and
classic scripts; no Python API, export payload or packaging rule changed. Run
`tests/browser_smoke.py --report-dir D:/AtelierDev/phase-2/export-motion-checks`
to include the seven new export-motion groups. They use fixture export responses,
including partial success and failed installation, and never build/copy a real
mod. Browser evidence is in
`D:/AtelierDev/phase-2/export-motion-agent-checks/results.json` (20 groups, no
uncaught page errors). The 35 Phase 3 checks and 26 reliability checks also
passed. Native WebView2 verified static busy/success poses, reduced motion and
cleanup; its report remains `D:/AtelierDev/phase-0-1/desktop-smoke.json`.

Refresh the running source preview to load the new scripts. An executable built
before this change must be rebuilt using the packaging command above. The
animation checks are separate from the earlier native export round trip and
in-game release verification.

## Viewport animation follow-up (15 October 2026)

The 3D preview loader now has a 72px footprint. Export feedback is 20px in buttons
and 24px in notifications. Nine new browser groups cover the actual viewport
lifecycle with controlled geometry and deferred responses: readiness before
materials finish, empty/error states, stale replies, close/reopen, blocked
navigation, optional-script failures, reduced motion and cleanup.

The combined browser run passed **30 groups**, including a real decoded GLB and
three open/close disposal cycles. Results and desktop-size screenshots are in
`D:/AtelierDev/phase-2/viewport-motion-checks`. Native WebView2 verified the 72px
size, loading/empty/error/ready static states and teardown. Normal-zoom screenshots
of the source interface are in `D:/AtelierDev/phase-2/viewport-motion`; the loading
request is deliberately held by a browser fixture for these captures.

```powershell
.\.venv\Scripts\python.exe tests/browser_smoke.py `
  --report-dir 'D:\AtelierDev\phase-2\viewport-motion-checks' `
  --mesh 'D:\AtelierDev\phase-0-1\native-checks\mesh\Marvel\Content\Marvel\Characters\1029\1029100\Meshes\10291\SK_10291_1029100.glb'
```

This is a frontend-only change. Python endpoints, model decoding, materials and
mod formats are unchanged. The source preview is updated; the earlier packaged
executable does not include these motion changes until rebuilt.

## Folder animation follow-up (15 October 2026)

The Gemini folder flap is integrated as scoped CSS and an inline SVG template.
Generic folders open on hover/keyboard focus, including failed portrait fallbacks;
loaded portraits, category icons and asset previews keep their existing behavior.
The slot remains approximately 102px, with about 90px painted width. No backend
endpoint, mod format or additional runtime dependency changed.

```powershell
.\.venv\Scripts\python.exe tests/browser_smoke.py `
  --report-dir 'D:\AtelierDev\phase-2\folder-motion-checks'
.\.venv\Scripts\python.exe tests/run_checks.py `
  --suite test_phase3.py --suite test_reliability.py `
  --report-dir 'D:\AtelierDev\phase-2\folder-regression-checks'
$env:ATELIER_DATA_DIR = 'D:\AtelierDev\phase-0-1'
.\.venv\Scripts\python.exe tests/desktop_smoke.py
```

The combined browser run passed **34 groups**, including five folder groups for
eligibility/fallbacks, native navigation and keyboard input, pointer media/reduced
motion, both-theme sizing/clipping, and grid replacement. Screenshots and results
are in the browser report directory above, with no uncaught page errors. The 35
Phase 3 and 26 reliability checks passed. WebView2 confirmed the 101.83px folder
slot, static pose and reduced-motion styles; keyboard checks run in Chromium
because the native smoke window is hidden. JavaScript syntax, matching standalone
and inline SVG geometry, and `git diff --check` passed.

Refresh the source preview to see the animation. The previously packaged EXE
still requires a rebuild. This run did not repeat the earlier real-GLB decoding
check or perform in-game testing.

## Material-save animation follow-up (15 October 2026)

The Gemini save feedback now uses a 24px notification icon (about 21.5px painted
width), with a 240ms success reveal and static reduced-motion states. Both material
save paths report actual outcomes: intensity persistence warnings, failed requests,
partial viewport saves and newer dirty edits never receive an unconditional check.
The current `Saving…` text stays in place; no optional busy toast is added.

The dialog now captures its editor/project/submitted values before awaiting a
save, ignores duplicate in-flight Save clicks and keeps edits made during that
request open. Late responses cannot close or relabel a later editor. Viewport
completion releases its saving guard independently of stale-view detection while
keeping local status updates scoped to the originating view. Requests, payloads,
project headers, intensity persistence and mod formats are unchanged.

```powershell
.\.venv\Scripts\python.exe tests/browser_smoke.py `
  --report-dir 'D:\AtelierDev\phase-2\material-save-motion-checks'
.\.venv\Scripts\python.exe tests/run_checks.py `
  --suite test_phase3.py --suite test_reliability.py `
  --report-dir 'D:\AtelierDev\phase-2\material-save-regression-checks'
$env:ATELIER_DATA_DIR = 'D:\AtelierDev\phase-0-1'
.\.venv\Scripts\python.exe tests/desktop_smoke.py
```

The combined browser suite passed **41 groups**, with seven material-save groups
covering real frontend save hooks through intercepted responses, exact payloads,
project capture, retries, retained drafts, stale responses, notification failures,
safe text, fallback artwork, reduced motion, visibility and animation cleanup.
Additional stale-generation/project assertions passed in the focused material-save
run. No uncaught page errors were recorded. Current-interface light/dark screenshots
and results are in the browser report directory. These fixtures do not save real
materials or write game/mod output.

All **35 Phase 3 and 26 reliability checks** passed. Native WebView2 verified 24px
saving/success/warning/error static states and disposal; its report remains
`D:/AtelierDev/phase-0-1/desktop-smoke.json`. JavaScript syntax and diff whitespace
checks passed. Refresh the source preview for the changes; the packaged EXE has
not been rebuilt. The earlier real-GLB check was not repeated for this notification
change; in-game compatibility remains a separate release check.

## Asset-library feedback follow-up (15 October 2026)

Weapons folders now use a full-size crossed-swords symbol. Thirteen dedicated
icon color roles distinguish types in both themes, including home shortcut icons.
Folder pin controls and the context menu add persistent browser-profile shortcuts
above the home grid without changing project metadata or export selection.

The reported Storm thumbnails were already cached. Search rebuilt unimported
texture cards without assigning their image URLs; missed SSE and canceled batches
could also leave loading indicators indefinitely. `gui/thumbnails.js` now owns
each grid's image reads, bounded status recovery, failures and cleanup. Cached
images display immediately, slow reads are not restarted on every poll, and failed
previews expose a retry action. Image reads have a 30-second bound; queued work is
checked every two seconds for up to three minutes while its grid remains active.

The Python pipeline deduplicates shared-cache jobs across clients, limits active
batches, publishes validated PNGs atomically, emits `thumb_failed` as well as the
existing `thumb_ready`, and reserves the cache against Reset Data while running.
POST `/api/prefetch_thumbs` retains `ok`, `cached` and `count`, adding `pending`,
`failed`, `missing` and `errors`; optional `retry: true` bypasses its 30-second
failure cooldown. POST `/api/thumb_status` accepts the same `game_rels` list and
returns a read-only snapshot. `/api/thumb` retains shared-thumbnail-first, then
project-PNG priority and supports the existing `_project` context. No new runtime
dependency, import/export format or material-save payload was introduced.

```powershell
.\.venv\Scripts\python.exe tests/browser_smoke.py `
  --report-dir 'D:\AtelierDev\phase-2\library-feedback-checks'
.\.venv\Scripts\python.exe tests/run_checks.py `
  --suite test_thumbnails.py --suite test_phase3.py --suite test_reliability.py `
  --report-dir 'D:\AtelierDev\phase-2\library-feedback-regressions'
$env:ATELIER_DATA_DIR = 'D:\AtelierDev\phase-0-1'
.\.venv\Scripts\python.exe tests/desktop_smoke.py
```

Validation passed: **54 browser groups**, **8 thumbnail + 35 Phase 3 + 26 reliability
checks**, native WebView2 smoke, syntax and diff checks. Browser coverage includes
pin persistence/keyboard/search/storage failures, category colors/sizing, cached
previews after search, missed SSE, decode errors/retry, slow and hung image reads,
and abandoned requests. Backend decoder/extractor failures use controlled fixtures.

The live isolated server at port 8770 was restarted with these routes. Read-only
inspection confirmed all **36 Storm / Goddess of Thunder texture previews** load
with no visible spinners, including the reported normal map after filtering and
clearing search. Both-theme screenshots and measurements are in
`D:/AtelierDev/phase-2/library-feedback-live`. Preview screenshots use temporary
browser-profile pins; they do not populate the user's own home shortcuts.
The packaged EXE was not rebuilt; in-game compatibility was not retested.

## Professional studio styling (15 October 2026)

The visual refinement uses flatter asset cards, neutral charcoal/cool-grey
surfaces, muted but distinct category colors, 13px left-aligned names and compact
6–12px corner roles across controls, panels and dialogs. The toolbar is 56px.
Two-line name slots keep grid rows consistent; full text remains searchable,
available to assistive technology and in the existing hover title. Previews remain
134px within 156px cards, and category icon slots remain about 102px. Artwork is
not tinted, filtered or reduced.

Whole-card press scaling, portrait hover zoom, button shape changes and the 3D
button's hover lift were removed. Folder-flap interaction and functional loader,
save and export animations remain. Pins, project cards, sidebar empty states,
material segments and viewport actions share the restrained control styling.
This pass changes presentation only; Python routes, project data, mod formats and
frontend action handlers are unchanged.

```powershell
.\.venv\Scripts\python.exe tests/browser_smoke.py `
  --report-dir 'D:\AtelierDev\phase-2\studio-refinement-checks'
$env:ATELIER_DATA_DIR = 'D:\AtelierDev\phase-0-1'
.\.venv\Scripts\python.exe tests/desktop_smoke.py
```

All **54 browser groups** and the native WebView2 smoke passed. The browser suite
covers both themes at four desktop sizes, category
contrast, keyboard navigation, pins, previews, material drafts and functional
motion. Preview-size and stable press-geometry assertions extend those checks.
Live library screenshots and measurements are in
`D:/AtelierDev/phase-2/studio-refinement`; home, skin, texture, folder and material
views were inspected in both themes. The material dialog uses read-only fixture
responses, and screenshot pins live only in a temporary browser profile.
Category colors measure at least **4.54:1 light / 4.98:1 dark** against their
thumbnail surfaces. The live Storm folder still displays all 36 texture previews.
Refresh the source preview at port 8770. The packaged executable is not rebuilt.

## Sharp icons and framed cards (15 October 2026)

The static icon family now uses locally vendored Material Symbols Sharp, fill 0.
All 72 compatibility aliases remain. Compact controls use 24px optical artwork
at weight 400; 15 large asset aliases use 48px artwork at weight 300. Characters,
VFX, materials, textures, UI and plugins now use a hero mask, bolt, layers,
hatching, panel grid and chip. Source URLs and hashes record both optical sizes.
The generic folder uses official closed/open outlines with the existing keyboard,
pointer and reduced-motion behavior. Other functional motion components retain
their existing artwork and lifecycle.

At the user's request, asset cards again enclose previews and labels in a bordered
surface with 10px corners, superseding the transparent resting cards above.
The 134px previews, approximately 102px icon slots and category colors remain in
both themes. No backend, project format or action handler changes are part of this
follow-up.

```powershell
.\.venv\Scripts\python.exe tests/browser_smoke.py `
  --report-dir 'D:\AtelierDev\phase-2\sharp-icons-checks'
$env:ATELIER_DATA_DIR = 'D:\AtelierDev\phase-0-1'
.\.venv\Scripts\python.exe tests/desktop_smoke.py
```

All **54 browser groups** and native WebView2 smoke passed. Syntax and whitespace
checks passed. Live home and nested-folder views were reviewed in both themes;
all 36 Storm texture previews still loaded without page errors. Screenshots and
live measurements are in `D:/AtelierDev/phase-2/sharp-icons`; automated results
are in `D:/AtelierDev/phase-2/sharp-icons-checks/results.json`. The native report
is `D:/AtelierDev/phase-0-1/desktop-smoke.json`. Refresh the source preview at port
8770; the packaged executable has not been rebuilt.

## Folder coverage and motion polish (15 October 2026)

The new shared `gui/folder-icons.js` registry gives animation, audio/cues, maps,
lights and the remaining known engine/editor folder categories dedicated Sharp
symbols. All 67 folder entries currently returned by the live root browser are
covered. Unknown custom names and numeric hero/skin folders retain the generic
folder fallback; portraits still take priority. Full-name matching avoids changing
an unrelated folder merely because its name contains a category word.

Cards and home shortcuts share the registry. Existing v1 generic shortcuts gain
their current icon without changing storage shape, label, path or ordering. The
established home grouping stays independent of icon coverage. The icon bundle
has 98 aliases including all previous 72, with 41 large optical variants. There
are 22 theme-aware color families; related technical subtypes share a family.
Framed 156px cards, 134px previews and approximately 102px category slots remain.

Export, material-save and viewport feedback received geometry-only polish: square
tray/arrow, clipped-corner save cartridge, crisp outcomes and right-angle viewport
brackets. Standalone and embedded SVG geometry match. Controller lifecycle logic,
states, durations, slots, API calls and result handling are unchanged. The folder
animation already used the Sharp outlines from the previous pass.

```powershell
.\.venv\Scripts\python.exe tests/browser_smoke.py `
  --report-dir 'D:\AtelierDev\phase-2\folder-category-checks'
$env:ATELIER_DATA_DIR = 'D:\AtelierDev\phase-0-1'
.\.venv\Scripts\python.exe tests/desktop_smoke.py
```

All **54 browser groups** and native WebView2 smoke passed. The category checks
cover 39 icon types, all 22 color families at 4.5:1 or better in both themes,
large previews, 18px shortcut artwork, matching boundaries and old-pin upgrades.
The generic-folder tests use explicit unknown folder fixtures, independently of
the installed game's categories. Syntax, geometry consistency and whitespace
checks passed. Reports/screenshots are in `D:/AtelierDev/phase-2/folder-category-checks`
and `D:/AtelierDev/phase-2/folder-category-icons`; the latter includes motion state
contact sheets. Live reference captures use a read-only empty-sidebar response
fixture; they do not clear project assets. The packaged EXE is not rebuilt.

The six-set motion inventory now includes the supplied logo entrance and empty
Edited Assets artwork alongside export, viewport, folder and material-save
feedback. Their production files and guarded adapters are in `gui/motion/`;
[its README](gui/motion/README.md) records lifecycle and fallback contracts.
The earlier web-upload packs remain handoff/reference files, not runtime assets.
The validation counts above describe the earlier four-set run only.

## Library, material and export workflow upgrades (15 October 2026)

`gui/library-tools.js` adds current-folder name/ID/path search, type and edited
status filters, natural/type/edited sorting and four thumbnail sizes. Sort/size
persist locally; navigation clears transient filters. Arrow/Home/End movement,
Enter, parent/history shortcuts and Space/P previews preserve normal editing
actions. Preview requests do not import assets. Edit All uses the same visible
texture set. Nested home pins retain their paths while displaying hero/skin/folder
context instead of ambiguous final-folder names.

The material editor groups colors, dye regions and scalars, marks unsaved values,
and compares against either the last saved project values or pristine game data.
The new GET `/api/material_original` reads original values without resetting the
project. Reference-value/revert controls change the draft; game reset remains a
separate action. The viewport adds saved-color swatches and unsaved counts.

`gui/export-review.js` reviews included/excluded changes and destination settings.
Project/selection/settings snapshots are rechecked at confirmation, overwrite and
retry. Material and viewport draft/save guards return focus to their editor.
`AtelierViewport.hasPendingEdits()` is a side-effect-free query;
`focusPendingEdits()` does not ask to discard. The existing build endpoint supplies
no percentage, so progress is indeterminate. Its window can be hidden/reopened;
the latest full result remains available for the session. Partial copy failure
retains the built-file result. Retries are manual and recheck overwrite conflicts.
Existing Python save/export payloads, project headers, sidecars and mod formats
are unchanged. Restart the source backend for the new comparison route.

```powershell
.\.venv\Scripts\python.exe tests/browser_smoke.py `
  --report-dir 'D:\AtelierDev\workflow-upgrades\browser-checks'
.\.venv\Scripts\python.exe tests/run_checks.py `
  --suite test_material_original.py --suite test_reliability.py --suite test_phase3.py --suite test_thumbnails.py `
  --report-dir 'D:\AtelierDev\workflow-upgrades\backend-checks'
$env:ATELIER_DATA_DIR = 'D:\AtelierDev\phase-0-1'
.\.venv\Scripts\python.exe tests/desktop_smoke.py
```

The browser runner includes `library_workflow_checks.py`,
`material_workflow_checks.py` and `export_review_checks.py`. These use temporary
projects and intercepted writes to exercise filters, persistence, keyboard focus,
read-only previews, draft comparisons, stale operations and export recovery.
`test_material_original.py` covers the original-data boundary independently.
The final combined run passed 75 browser check groups with no uncaught page errors,
including `empty_assets_motion_checks.py` and `logo_motion_checks.py`. The four
Python suites above passed 77 tests. JavaScript syntax, the DOM smoke and whitespace
checks passed. Native WebView2 loaded the real library and verified all six motion
components, their sizes, reduced-motion states and cleanup. Reports are in
`D:/AtelierDev/workflow-upgrades/{browser-checks,backend-checks}` and
`D:/AtelierDev/phase-0-1/desktop-smoke.json`.

A separate live check loaded all 36 Storm/Goddess of Thunder textures, opened a
project-image preview and read 10 original material colors plus 24 scalars. Hashes
of all eight files in the isolated development projects were unchanged. Both-theme
screenshots and results are in `D:/AtelierDev/workflow-upgrades/live-checks`.
The source server on port 8770 was restarted for the new comparison route. No
real mod was exported or installed during these checks; in-game compatibility and
the packaged EXE rebuild remain separate release work.

## Contribution packaging (15 October 2026)

Release preparation adds the reproducible [package script](PACKAGING.md), vendor
and runtime license notices, and the actual frozen-executable smoke. It also fixes
two thumbnail-status/Windows-path races and adds an opt-in desktop port override
without changing the normal port or data layout. The complete Python runner passes
202 tests, with two native-dependent cases explicitly skipped. Chromium passes
76 groups including a real decoded GLB; the frozen WebView2 smoke passes four
UI/backend groups with no page errors. The source/output reports are under
`D:/AtelierDev/release-candidate-2026-10-15/`; archive manifests identify the exact
source revision. The earlier per-phase counts above describe those earlier runs.

## Review and follow-up

See [RELIABILITY.md](RELIABILITY.md) for the fixes, evidence, API compatibility and remaining limitations. Before release, manually validate representative texture/material/dye, VFX/curve/text, world, Blender, protected-mod and repatch workflows with a supported game version. In-game verification remains a separate release gate.

## Native export, managed jobs and bulk editing (15 October 2026)

Activity now tracks imports, exports, repatches and bulk reviews/saves by project.
The desktop waits for managed work during close. A cancellable job stops its own
native child processes and discards private staging; once publication starts,
cancellation is disabled and shutdown waits for the file transaction to finish.
Restart marks unfinished jobs as interrupted, recovers publication journals in
configured output folders and removes owned private workspaces where possible.
Interrupted work is never resubmitted automatically. Inputs and passwords are not
stored in the job journal; terminal results remain available in Activity.

The optional `background: true` field on import/export/repatch requests returns a
job ID. Existing requests retain synchronous export/repatch behavior and legacy
import status. `GET /api/jobs`, `GET /api/jobs/<id>` and
`POST /api/jobs/<id>/cancel` use the same originating-project header as edits.
Restart Python to register these new routes; refreshing CSS/JS alone is insufficient.

Bulk VFX / curves offers selected edited assets or the filtered current folder.
Multiply can target color RGB, alpha or all channels/scalars; replacing RGB keeps
alpha. Curve times/interpolation/weights stay intact, with slopes scaled alongside
values or zeroed for constant RGB replacement. Niagara edits retain their export
indices and LUT dimensions. MPCs are visibly labelled as global. Reviews use a
temporary project copy, expire after 15 minutes and never write project edits.
Applying rejects any stale target before changing a file. A durable project-local
journal rolls back a failed/interrupted batch before subsequent project access.
Intensity metadata changes join that transaction; other export settings remain.

Real native verification exposed a pre-existing zero-scalar bug: changing a
material parameter omitted as zero retained its old unversioned header and
produced an unreadable export. Edited parameters now rebuild only their owning
header, preserving untouched nested headers. The same helper covers MPC defaults.

Validation for this follow-up:

- **225 Python checks passed**, with the two legacy native cases explicitly
  skipped by the isolated runner. Reports: `_work/native-jobs-bulk/backend-complete`.
- **81 Chromium groups passed**, including real decoded mesh rendering and three
  disposal cycles. The final UI changes also passed the focused real-HTTP bulk/job
  suite. Reports: `_work/native-jobs-bulk/browser-final` and `browser-latest`.
- A real hidden WebView2 close cancelled an owned child and persisted its final
  job state before process exit: `_work/native-jobs-bulk/desktop-final`.
- Storm `MI_1031306_Equip_01`: a changed `BaseTint`, zero-to-nonzero `AOIntensity`,
  painted 2048-square DXT1 texture and neutral 2048-square DXT5 ColorID survived
  build, isolated installation and unpack/decode. Material texture references,
  formats, dimensions, zero mask alpha and existing project hashes matched.
  This also ran through the managed native-child path with a persisted success
  result. Report: `D:/AtelierDev/native-jobs-bulk-2026-10-15/material-dye-managed`.
- A real `C_1032_6_601`, `MPC_1015_6_001` and `NS_103100_Body_01` passed bulk save,
  native export and readback of curve keys/tangents, MPC parameters and every
  changed Niagara LUT. Source projects and isolated installation hashes matched.
  Report: `D:/AtelierDev/native-jobs-bulk-2026-10-15/bulk-native-final`.
- JavaScript syntax, DOM smoke, dependency consistency and whitespace checks pass.

Repeat the focused and native checks with fresh report directories:

```powershell
.\.venv\Scripts\python.exe tests/browser_smoke.py --jobs-bulk-only --report-dir _work/jobs-browser
.\.venv\Scripts\python.exe tests/window_job_smoke.py --report-dir _work/jobs-desktop
$env:ATELIER_DATA_DIR = 'D:\AtelierDev\phase-0-1'
.\.venv\Scripts\python.exe tests/native_material_dye.py --report-dir 'D:\AtelierDev\new-material-check'
.\.venv\Scripts\python.exe tests/native_bulk_smoke.py --report-dir 'D:\AtelierDev\new-bulk-check'
```

All native installation checks target report-local `test-mods`, never live game
mods. These are storage/pipeline checks, not an in-game visual certification.
Managed job locks remain process-local: concurrent instances need separate data
directories. Legacy untracked callers and shader-index background work are not
converted into managed jobs. Repatch's optional import-into-project mode becomes
uncancellable when its legacy project writes start; it is not a bulk-save
transaction. No new packaged executable or installer was produced in this pass.
