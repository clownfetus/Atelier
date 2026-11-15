# Surface map

Every place Krackle shows today, where it's mounted, and what it becomes. File
references are from `main` at `eaf4ec8` (7 Nov 2026). **Re-run the greps at the
bottom before starting Phase 3**: line numbers drift.

## Moves to the new glyph (15)

| # | Surface | Mounted from | Krackle API today | Becomes | Tier |
| --- | --- | --- | --- | --- | --- |
| 1 | Export review stage | `gui/export-review.js:86` (ink-well), `:97` (stage) | `inkWell.mount`, `krackleStage.mount` | Glyph, full choreography. The hero placement. | Stage |
| 2 | Viewport loader | `gui/viewport.js:413` | `viewportLoader.mount` | Glyph: the mesh loader while the model loads (D16), error if it fails | Stage |
| 3 | Edit All import | `gui/motion/import-ink.js`, styled in `gui/identity.css` | import ink | Glyph: working while importing; finished count in text only | Stage |
| 4 | First-run setup | `gui/setup-wizard.js` `syncLine` (`setupCheck`, 72 px) | `setupCheck.mount` | One glyph: working while checks run, A once every row is valid, ! or X otherwise. It stands in for the logo's mark in the header (D18). The rows' blocks condense as each check passes, and a passed row has no glyph of its own. The drop and well have gone. | Inline |
| 5 | Header logo entrance | `gui/motion/logo-entrance-ui.js:55` | `logoEntrance.mount` | The A assembles once on launch in Full motion, then stays still (full colour, D6; SPEC §4.8, D8). Clicking the logo no longer replays it. | Inline |
| 6 | Export button and notifications | `gui/motion/export-feedback-ui.js:26` | `exportFeedback.mount` | Glyph. The install button's 28 px host is Micro (D12), toasts at 40 px are Inline | Inline / Micro |
| 7 | Material save | `gui/motion/material-save-ui.js:61`, `gui/motion/working-panels.js:339` | `materialSave.mount` | Glyph: the material loader while saving (D16) | Inline |
| 8 | Job toasts and Activity rows | `gui/job-tools.js:23`, `gui/mod-open.js:35`, `gui/setup-wizard.js:113` (passes `found`, covered by row 4 at P3.3), `gui/motion/surface-adapters.js:50`; `AtelierKrackleGlyph.toastIcon` at `gui/app.js:149`, `:201` | `krackleGlyph.mount` | Glyph. Micro keeps its jostle for every asset type (D16) | Micro |
| 9 | Empty states | `gui/app.js:494`, `gui/polish.js:325`, `gui/motion/empty-assets.js` | `emptyState.mount`, `emptyAssets.mount` | Still "at rest" pose (D4), no motion | Inline / Stage |
| 10 | Spinners | `gui/motion/krackle.css` (every `.spinner`) | CSS | Micro glyph in working | Micro |
| 11 | Settings → Try Krackle | `gui/motion/motion-preview.js` | preview | "Preview motion": all five states and the loaders on the production engine, at 16, 48 and 128 px | Stage |
| 12 | Model appearance loading (D10) | `gui/viewport-effects.js:56`, `gui/viewport-inspection.js:75` | energy band and reveal sweep | The texture loader in a corner, with the model staying in view (D16). Materials and rendering don't change | Inline |
| 13 | Setup-status check (D10) | `gui/motion/config-discovery.js`, `gui/app.js:3615` | animated scanner | The same glyph as row 4, driven by the real result. Its host is 88 px | Inline |
| 14 | Startup stage (D17) | `gui/motion/surface-adapters.js:22` | `krackleStage.mount` with the logo's silhouette | Working beside the counted progress bar, with no silhouette, so the A never forms here. The logo entrance still follows (D8). Calm and Off keep the still logo and the bar | Stage |
| 15 | Index failure (D17) | `gui/motion/surface-adapters.js:35` | `krackleStage.mount` | The X, with the notice's text unchanged | Stage |

## Additional approved placements

These reuse the finished motion system; the original migration inventory above stays historical.

| Surface | Mounted from | Behaviour |
| --- | --- | --- |
| Add custom asset | `gui/add-asset.js` | Inline texture, mesh or material loader beside the preparation status, from the selected asset type |
| Bulk review and save | `gui/bulk-edit.js` | The rolling disc follows the review job's own current/total. Uncounted review uses the working glyph. Saving materials uses the material loader; mixed, VFX and curve batches use general working |
| Workspace: Your mod | `gui/workspace-dock.js` | New saves and Undo seat into their slots; changed saves reseat. Restore folds an inert departing copy. Refreshes and selection changes stay still |
| Quick Preview | `gui/library-tools.js` | The loaded image opens downwards from its top edge, using the existing reveal timing |
| Pinned folders | `gui/library-pins.js` | A newly pinned chip settles; an unpinned chip folds away. Initial display, filtering, catalogue updates and unchanged repaints do not replay the effect |
| Material editor work | `gui/app.js` (`editorWorking`) | Beside Save: the texture loader while a custom texture uploads or textures bake or pack for download; the material loader while the material is replaced or reset. Requests that overlap in one editor share its glyph until the last one ends |
| Other editors' resets | `gui/app.js` | Curve, VFX, level and text Reset show the working glyph beside Save, as their saves already do |
| Texture export options | `gui/app.js` (`saveTexOpts`) | The texture loader beside Save while the options save. The footer keeps the badge's height, so it doesn't jump |
| Recolour texture | `gui/viewport-recolour.js` | The texture loader beside the status while a recolour saves. It ends when the "Replace edited texture?" question opens; the replacing save shows its own. Previews during a drag stay text only |
| Replace mesh | `gui/mesh-edit.js` | The mesh loader beside the status while the `mesh-replace` job runs, with Add custom asset's lifecycle |
| Process S maps | `gui/s-maps.js` | A Mod tray progress row with the texture loader from planning to the result. Planning hands to processing without restarting it. The result stays the existing toast |
| Assembly View textures | `gui/assembly.js` | Each texture thumbnail opens downwards from its top edge once loaded, as library thumbnails do |
| Dye preview | `gui/app.js` (`_dyeShow`) | The preview opens downwards over its plate when the editor opens or Dyed and Region map switch. Live colour changes swap in place; a repaint of the same picture stays still |
| Activity rows | `gui/job-tools.js` | A job that starts while Activity is open seats into the list: the slot opens, the row snaps in, its glyph squashes at the impact (Full only) and the text wipes in. Opening the panel, progress repaints, closed refreshes and project changes stay still |
| Region highlight | `gui/style.css` (`matflash`) | Finding a region holds the highlight, then folds it back into the row's left edge in 190 ms instead of fading it. Off shows no highlight, as before |
| Costume glow | `gui/viewport.css` | Model Studio's skin glow opens downwards from its top edge when the colour is known and folds back up when it goes, instead of fading |
| Folder pin button | `gui/library-pins.css` | On hover or focus the pin unfolds downwards like a pop-up (280 ms, 6 px) and folds back up (190 ms), instead of fading |
| Upscaled artwork | `gui/catalogue-art.js` | When the sharper copy of the Library banner's art or Model Studio's skin card finishes while the art is on screen, it opens downwards over the original from its top edge, with the image swap an edited texture uses. A copy that was already waiting, or that arrives while the art is still opening, swaps in at once |

These placements use the shared Full/Calm/Off policy, including OS reduced motion. They never
form a success glyph themselves. Busy mounts are disposed when the operation ends, its dialog
is hidden or its project is no longer current. A reopened dialog resumes its existing operation.

## Retired (10)

| Surface | Where | Replacement |
| --- | --- | --- |
| Working panels (border charges) | `gui/motion/working-panels.js/.css` | Nothing; panels stay still while the glyph reports |
| Workflow gestures (arrive, trace, seal, release) | `gui/motion/workflow-krackle.js/.css`, `moment.js` | The existing Material easing tokens on plain transitions |
| Ink transfers and connected surfaces | `workflow.transfer`, `workflow-surfaces.js` | A Mod tray row clicks in like a glyph piece (P4b.6, `seat()` in `polish.js`): the slot opens and the thumbnail seats with Complete's snap, recoil and rest. It never fades. |
| Texture reconstruction (halftone dots) | `gui/motion/texture-reconstruction.js`, used from `gui/polish.js:136` | The new picture opens down over the old one from its top edge (P4b.7). Nothing is blended, so artwork stays trustworthy |
| Folder flap | `gui/app.js:722`, inline SVG at `gui/index.html:1020` | Static folder icon in its category colour |
| Contextual pigments | `gui/motion/krackle-context.js` (`AtelierMotion.energy`) | Nothing (D5) |
| Project ink (D10) | `gui/motion/project-ink.js`: not loaded, and nothing calls it | Nothing. Delete it in P4.1 |
| First-export moment (D17) | `gui/polish.js:194` (`.export-color-moment`) | Nothing. Complete is the celebration |
| Selection count bubble (D17) | `#sel-count::before` in `gui/motion/surfaces.css` | Nothing. The count stays |
| Dot lattice (D17) | `.k-screen`, `--screen-dot`, `gui/polish.js:324` | Nothing. Empty states sit on the plain surface |

## Changed in place (13)

| Surface | Change |
| --- | --- |
| Start page lockup (`.at-proj-lockup` in `gui/index.html`) | The bible's lockup, without RIVALS or the ink tagline (D6). Done in P1.5. |
| Progress bars (`krackle.css`) | Paper on Surface; filled only from counted steps; no bar when nothing is countable |
| Viewport poster (`gui/motion/viewport-poster.js`) | Kept: it moves the hero artwork itself, not ink. Remove any Krackle ink it uses. |
| Formation sounds (`gui/motion/foley.js`, `#settings-foley`) | Becomes "Motion sounds": the success click only (SPEC §6), off by default, Full only |
| Showcase backdrop (`gui/motion/showcase-art.js`, D10) | Neutral gradient only, with the dots and burst gone. Exported Showcase images change |
| Thumbnail loading (`gui/thumbnails.css:16`, D10) | A still tonal plate, and the image opens downwards over it (P4b.7). No glyph, no fade |
| Cards being edited (`gui/polish.css:13`, `gui/app.js:651`, D10) | The preview stays whole beside the "Edited" marker. Edited materials show their saved colours as flat diagonal bands |
| Deleting a row (`gui/polish.js:144`, `gui/style.css:1519`, D10) | The row folds back into its left edge, then its slot closes (P4b.7). No fade |
| HDR swatch ring (`gui/polish.js:303`, D10) | Stays, because it reports a material's intensity. Only its "bubble" name changes |
| Theme change (`gui/preferences.js:38`, D17) | The new theme opens down over the old one from the window's top edge, 400 ms, in Full and Calm, as interface chrome (P4b.7). Off stays instant |
| Toast captions (`gui/motion/surfaces.css:10-22`, D17) | The theme's Card surface and text, with a left rule in the status colour and no comic shadow. It unfolds upwards from its bottom edge and folds back down (P4b.7), never fading |
| Pop-ups: dialogs, editors, image preview, menus, tooltips, search results, Model Studio menus, the update button (P4b.7) | Each unfolds out of the edge it belongs to (280 ms, 6px, no overshoot) and folds back into it (190 ms). Nothing fades except a dialog's dimmed backdrop. Off and reduced motion cut. `continuity.css`, `AtelierMotion.unfold`/`fold` |
| Toast repeat count (`gui/motion/surfaces.css`, `gui/app.js:191`, D17) | Always a number, such as "×3" |
| Texture drop target (`.card.k-texture-pool`, `gui/app.js:4294`, D17) | A plain outline in the theme's text colour |

## Shared infrastructure to keep

- `AtelierMotionPolicy` (`gui/preferences.js:31`): Full/Calm/Off and OS reduced
  motion. The new engine reads it; don't duplicate it.
- `#settings-motion` and `#setup-motion-dial`: same controls, same storage.
- `gui/motion/timing.js` easing tokens, if still used by non-Krackle code;
  check before deleting.

## Greps to re-run before Phase 3 and Phase 4

```sh
grep -rnE "AtelierMotion\??\." gui --include=*.js | grep -v "^gui/motion/"   # includes the AtelierMotion?. callers
git grep -il krackle -- . ':!CHANGELOG.md' ':!docs/release-*' ':!docs/discord-*' ':!docs/announcements' ':!docs/*-verification-*.json' ':!docs/*checkpoint*' ':!docs/review' ':!docs/motion-v2'   # must be empty after Phase 4 (D11)
grep -n "motion/" gui/index.html                                        # script and style includes
```
