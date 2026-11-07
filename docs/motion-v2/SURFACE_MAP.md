# Surface map

Every place Krackle shows today, where it's mounted, and what it becomes. File
references are from `main` at `eaf4ec8` (7 Nov 2026). **Re-run the greps at the
bottom before starting Phase 3**: line numbers drift.

## Moves to the new glyph (11)

| # | Surface | Mounted from | Krackle API today | Becomes | Tier |
| --- | --- | --- | --- | --- | --- |
| 1 | Export review stage | `gui/export-review.js:86` (ink-well), `:97` (stage) | `inkWell.mount`, `krackleStage.mount` | Glyph, full choreography. The hero placement. | Stage |
| 2 | Viewport loader | `gui/viewport.js:413` | `viewportLoader.mount` | Glyph: working while the model loads, error if it fails | Stage |
| 3 | Edit All import | `gui/motion/import-ink.js`, styled in `gui/identity.css` | import ink | Glyph: working while importing; finished count in text only | Stage |
| 4 | First-run setup | `gui/setup-wizard.js:160` (`setupDrop`, 240 px), `:176` (`setupCheck`, 72 px) | `setupDrop.mount`, `setupCheck.mount` | One glyph: working while checks run, A once every row is valid, ! or X otherwise. Biggest first impression. | Stage |
| 5 | Header logo entrance | `gui/motion/logo-entrance-ui.js:55` | `logoEntrance.mount` | The A assembles once on launch, then stays still (full colour, D6) | Inline |
| 6 | Export button and notifications | `gui/motion/export-feedback-ui.js:26` | `exportFeedback.mount` | Glyph | Inline / Micro |
| 7 | Material save | `gui/motion/material-save-ui.js:61`, `gui/motion/working-panels.js:339` | `materialSave.mount` | Glyph | Inline |
| 8 | Job toasts and Activity rows | `gui/job-tools.js:23`, `gui/mod-open.js:35`, `gui/setup-wizard.js:113`, `gui/motion/surface-adapters.js:50` | `krackleGlyph.mount` | Glyph | Micro |
| 9 | Empty states | `gui/app.js:494`, `gui/polish.js:325`, `gui/motion/empty-assets.js` | `emptyState.mount`, `emptyAssets.mount` | Still "at rest" pose (D4), no motion | Inline / Stage |
| 10 | Spinners | `gui/motion/krackle.css` (every `.spinner`) | CSS | Micro glyph in working | Micro |
| 11 | Settings → Try Krackle | `gui/motion/motion-preview.js` | preview | "Preview motion": all five states on the production engine, at 16, 48 and 128 px | Stage |

## Retired (6)

| Surface | Where | Replacement |
| --- | --- | --- |
| Working panels (border charges) | `gui/motion/working-panels.js/.css` | Nothing; panels stay still while the glyph reports |
| Workflow gestures (arrive, trace, seal, release) | `gui/motion/workflow-krackle.js/.css`, `moment.js` | The existing Material easing tokens on plain transitions |
| Ink transfers and connected surfaces | `workflow.transfer`, `workflow-surfaces.js` | The Mod tray row enters with a plain 200 ms fade-and-rise. That's interface chrome, not the glyph, so invariant 2 doesn't apply. |
| Texture reconstruction (halftone dots) | `gui/motion/texture-reconstruction.js`, used from `gui/polish.js:136` | Plain image cross-fade (artwork must stay trustworthy) |
| Folder flap | `gui/app.js:722`, inline SVG at `gui/index.html:1020` | Static folder icon in its category colour |
| Contextual pigments | `gui/motion/krackle-context.js` (`AtelierMotion.energy`) | Nothing (D5) |

## Changed in place (3)

| Surface | Change |
| --- | --- |
| Progress bars (`krackle.css`) | Paper on Surface; filled only from counted steps; no bar when nothing is countable |
| Viewport poster (`gui/motion/viewport-poster.js`) | Kept: it moves the hero artwork itself, not ink. Remove any Krackle ink it uses. |
| Formation sounds (`gui/motion/foley.js`, `#settings-foley`) | Becomes "Motion sounds": the success click only (SPEC §6), off by default, Full only |

## Shared infrastructure to keep

- `AtelierMotionPolicy` (`gui/preferences.js:31`): Full/Calm/Off and OS reduced
  motion. The new engine reads it; don't duplicate it.
- `#settings-motion` and `#setup-motion-dial`: same controls, same storage.
- `gui/motion/timing.js` easing tokens, if still used by non-Krackle code;
  check before deleting.

## Greps to re-run before Phase 3 and Phase 4

```sh
grep -rn "AtelierMotion\." gui --include=*.js | grep -v "^gui/motion/"   # 19 files on eaf4ec8
grep -rln "krackle\|Krackle" gui tests scripts docs                     # must be empty after Phase 4
grep -n "motion/" gui/index.html                                        # script and style includes
```
