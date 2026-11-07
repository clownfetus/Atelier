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
| 4 | First-run setup | `gui/setup-wizard.js` `syncLine` (`setupCheck`, 72 px) | `setupCheck.mount` | One glyph: working while checks run, A once every row is valid, ! or X otherwise. The rows' blocks condense as each check passes, and the drop and well have gone (D18). The well was this surface's Stage-size host, so ask Thiago at P3.3 whether a larger glyph still has a place. | Stage |
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

## Retired (10)

| Surface | Where | Replacement |
| --- | --- | --- |
| Working panels (border charges) | `gui/motion/working-panels.js/.css` | Nothing; panels stay still while the glyph reports |
| Workflow gestures (arrive, trace, seal, release) | `gui/motion/workflow-krackle.js/.css`, `moment.js` | The existing Material easing tokens on plain transitions |
| Ink transfers and connected surfaces | `workflow.transfer`, `workflow-surfaces.js` | The Mod tray row enters with a plain 200 ms fade-and-rise. That's interface chrome, not the glyph, so invariant 2 doesn't apply. |
| Texture reconstruction (halftone dots) | `gui/motion/texture-reconstruction.js`, used from `gui/polish.js:136` | Plain image cross-fade (artwork must stay trustworthy) |
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
| Thumbnail loading (`gui/thumbnails.css:16`, D10) | A still tonal plate, and the image cross-fades in. No glyph |
| Cards being edited (`gui/polish.css:13`, `gui/app.js:651`, D10) | The preview stays whole beside the "Edited" marker. Edited materials show their saved colours as flat diagonal bands |
| Deleting a row (`gui/polish.js:144`, `gui/style.css:1519`, D10) | A plain 200 ms fade |
| HDR swatch ring (`gui/polish.js:303`, D10) | Stays, because it reports a material's intensity. Only its "bubble" name changes |
| Theme change (`gui/preferences.js:38`, D17) | A plain cross-fade of the page, 200 ms, in Full and Calm, as interface chrome. Off stays instant |
| Toast captions (`gui/motion/surfaces.css:10-22`, D17) | The theme's Card surface and text, with a left rule in the status colour and no comic shadow |
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
