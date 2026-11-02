# Workspace shell review checkpoint

Implemented on `codex/friendly-workspace`, branched from `claude/krackle-ink-well` (`e9a120d`). Tasks 1 and 2 are complete. Task 3 stops after the Projects leading card and the page-mounted workspace, as requested. The Your mod dock, its Restore and Review & install controls, and new Phase 4 motion await layout review.

**Update, 2026-11-02:** the layout was approved and the Your mod dock is built (see "Your mod dock" below). New Phase 4 motion is still out of scope.

The direction is a familiar app with one clear next action: return to your project, or choose a hero and costume before naming anything. The full Library and its expert tools remain reachable. Colour edits keep the existing explicit Save changes action; no new autosave behaviour was introduced.

| Work | Main files | Result |
| --- | --- | --- |
| Task 1 | `atelier/config.py`, `atelier/web/routes.py`, `tests/test_usmap_builds.py` | Parse the highest versioned game-container build, warn about older active mappings, and bypass the update-check cooldown. Unknown builds stay silent. The warning explains the restart requirement. |
| Task 2 | `atelier/handlers/dye.py`, `atelier/web/routes.py`, `gui/viewport.js`, `tests/test_dye_preparation.py`, `tests/browser_smoke.py` | Cache immutable prepared sources, bounded to four entries and 128 MiB. File stamps include path, nanosecond modification time and size. Preview routes use PNG compression level 1; downloads retain their normal encoding. Hex changes and saved-colour restores bake immediately; picker drags retain debounce and stale-response guards. |
| Projects card | `atelier/project_meta.py`, `atelier/web/routes.py`, `gui/app.js`, `gui/index.html`, `gui/identity.css`, `tests/test_project_workspace.py` | Persist last-opened time separately from asset modification time. Lead with the latest project, or Start a recolour for an empty portfolio. Copies retain workspace state without inheriting opening recency. |
| Workspace mount | `gui/workspace.js`, `gui/workspace.css`, `gui/app.js`, `gui/index.html`, `gui/viewport.js`, `gui/viewport-inspection.js`, project metadata/routes, `tests/workspace_checks.py` | Mount the existing viewport as a page region with normal keyboard navigation. Retain its renderer and shared texture cache. Remember costume, model and colour set; infer a single costume for older projects, otherwise offer a chooser. Navigation respects unsaved drafts and hidden stages stop rendering. |

Every visible change has an entry under Unreleased in `CHANGELOG.md`. Existing browser tests were updated to enter Library using its visible navigation button after opening a project, including independent identity-test browser contexts. Their editor, export, motion and colour assertions remain in place.

**Validation**

- Mapping tests: `Ran 8 tests ... OK`; existing update-lifetime test: `Ran 1 test ... OK`.
- Dye tests: `Ran 7 tests ... OK`. Repeated bakes decode each source once, prepare once and match the uncached compositor pixel for pixel. Tests cover changed colours, edited/custom source changes, pristine originals, cache eviction, concurrent bakes and preview-only encoding. An AST comparison against the branch base confirms that the compositor arithmetic is unchanged.
- Workspace metadata tests: `Ran 4 tests ... OK`.
- Unit modules, excluding the five standalone scripts: `Ran 778 tests ... OK (skipped=2)`.
- Standalone scripts: Phase 1 `28 passed`; Phase 2 `18 passed`; Phase 3 `35 passed`; Phase 4 `47 passed, 2 skipped`; patch override `11 passed`. All report zero failures.
- Existing viewport (58 checks), working-panels (69 checks) and identity (33 checks) browser suites pass with zero page errors. The new workspace suite passes five grouped checks covering navigation, explicit-save, cancelled-navigation, colour-set persistence, empty-project and first-recolour behaviour.
- Full browser regression passes all 328 checks with zero page errors; the complete output is `_work/workspace-regression-full-20261102-final/results.json`.
- `git diff --check` passes.

The literal discovery command imports the standalone scripts and records their `SystemExit` calls as discovery errors. Its first sandboxed run also hit Windows temporary-directory cleanup errors and could not locate installed Chromium. Running unit modules separately outside that sandbox passed. Standalone scripts ran with a temporary data directory and UTF-8 enabled; the default Windows text encoding had initially failed Phase 3's Node input.

The stress fixture warms twenty distinct costume textures, then measures twenty more switches through that set: **one renderer, 23 live textures, 8 geometries, 20 cached textures, and zero additional texture downloads** throughout the measured pass. Per-skin geometry disposal continues. This distinguishes the intentional bounded cache from resource growth.

Review artifacts are in `_work/workspace-review-20261102-final/`: `projects-light.png`, `projects-empty.png`, `choose-costume.png`, `workspace-light-1400.png`, `workspace-dark-1400.png`, and both 1024-pixel workspace views. `skin-switch-stress.json` contains the measurements. Screenshots use generated fixture geometry, not decoded game models.

**Reference and limits**

The official [Modrinth app](https://modrinth.com/app) and [personalization article](https://modrinth.com/news/article/app-personalization/) informed the recent-work emphasis, clear primary actions, quiet layered surfaces and secondary placement of expert controls. Atelier retains its own Gesso, Lamp Black and Smalt palette, typography and portfolio artwork. The linked Claude prototype was inaccessible, so the implementation follows `WORKSPACE_PLAN.md` and `DESIGN_SYSTEM.md`.

Real game decoding, a real mapping download/restart, real-asset dye latency, installation into the game, and WebView2 GPU timing were not exercised. The under-400-ms target remains for the separate real-asset measurement. Browser validation uses Chromium, generated meshes, image fixtures and temporary project data. No new animation was added at this checkpoint.

## Your mod dock

| Work | Main files | Result |
| --- | --- | --- |
| Dock | `gui/workspace-dock.js`, `gui/workspace.css`, `gui/index.html`, `gui/app.js` (`AtelierModTray`) | A panel under the model lists the project's saved edits from the Mod tray's own data, sorted by costume then name, with the count drop. It keeps no list of its own. |
| Before → after | `atelier/web/browse.py` (`edited_colour_changes`), `/api/material_changes` | Material slots show the first changed colour, original then edited, matched by parameter name, with `+n` for further changes. Original reads are queued one at a time and cached per saved version. Texture slots show the edited preview. |
| Restore | `gui/workspace-dock.js`, `gui/viewport.js` (`reloadMaterials`, `label`) | Restore is the tray's Delete: confirm, project trash, Undo. The costume's colours reload afterwards and again after Undo. Unsaved colour drafts block Restore and point at Save changes. |
| Review & install | `gui/workspace-dock.js` | Opens the existing export review (`doInstallMod`), so draft guards, the overwrite check and `_install_to_mods` are unchanged. Disabled when nothing is selected for the mod. |

Deviations from `WORKSPACE_PLAN.md` Phase 1:

- **Grouped by costume, not part.** Named parts arrive with Phase 2's parts list. Slots use the viewport's own material labels ("Body" for `MI_Body`).
- **No saved dot.** Colour edits keep the explicit Save changes button, and the stage header already says "All changes saved", so the dock doesn't repeat it.
- **Selection stays in the Library's Mod tray.** The dock shows edits left out of the mod at reduced opacity, says how many go in, and points to the tray to change that.

Validation: `tests.test_project_workspace` (8 tests, 4 new for colour changes) passes, and `tests/browser_smoke.py --workspace-only` passes all six grouped checks, including a new one for the dock's listing, swatches, export review and Restore. Screenshots: `_work/dock-review/` (`workspace-with-dock-1400.png`, `dock-light.png`, `dock-dark.png`). Not exercised: real game materials, the native original read's latency, and installing into the game.
