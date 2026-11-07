# Decisions (Phase 0)

The brand bible (v1.2) and the current app disagree on these points. Each has a
recommended answer. **None is confirmed yet.** Phase 0 is: show this file to
Thiago, record his answer in the *Decision* line, set *Status* to `confirmed`,
and only then start Phase 1. Where an answer differs from the recommendation,
follow the answer and update `SPEC.md` to match.

---

## D1 · Typeface

- **Today:** Roboto (UI) and Bricolage Grotesque at 80% width (titles), both
  vendored under `gui/vendor/` and declared in `gui/tokens.css`.
- **Bible:** Inter for UI, Inter Display for large sizes. Letter-spacing only on
  uppercase labels.
- **Recommended:** move to Inter + Inter Display, vendored locally (SIL OFL, no
  CDN). Remove Bricolage. Keep Roboto only if Inter fails a layout check.
- **Decision:** _pending_
- **Status:** open

## D2 · Category colours

- **Today:** 13 muted category hues in `tokens.css` (`--studio-icon-*`,
  `--studio-texture`, `--studio-mesh`). Texture is teal `#3f6872`, mesh brown
  `#795b48`, material green `#4b6b55`.
- **Bible:** texture blue `#6C98CA`, mesh teal `#5AAA9A`, material copper
  `#DF8F6B`. These name asset types and nothing else.
- **Recommended:** adopt the three bible hues for texture, mesh and material.
  Re-pick the other 10 categories (folder, character, UI, VFX, curve, text,
  nameplate, plugin, weapon, unknown) so none sits within 25° of hue of the
  three category colours or of the status hues (see SPEC.md).
- **Decision:** _pending_
- **Status:** open

## D3 · Themes and custom palettes

- **Today:** Atelier, Darcula and Repak X presets, each light and dark, plus up
  to 24 custom palettes (`gui/theme.js`, storage key `atelier.appearance` v2).
  `theme.js` already derives text and accents for ≥ 4.5:1 contrast.
- **Recommended:** the mark's three colours never change with the theme. The
  glyph's halo always equals the surface it sits on. Status hues keep their hue
  and `theme.js` adjusts only their lightness for contrast, keeping each at
  least 30° of hue from the user's accent. The bible's Charcoal / Surface /
  Paper / Mist / Guide become the dark variant of the Atelier preset.
- **Decision:** _pending_
- **Status:** open

## D4 · The `info` state (neutral, cancelled)

- **Today:** a neutral Krackle glyph for notices and cancelled jobs.
- **Bible:** no neutral state (only working, complete, warning, error).
- **Recommended:** "at rest": the three pieces side by side in a row, category
  colours, still. Never the A (the A is reserved for success).
- **Decision:** _pending_
- **Status:** open

## D5 · Costume-coloured effects

- **Today:** `gui/motion/krackle-context.js` tints effects with the current
  hero's or costume's colours (`AtelierMotion.energy`).
- **Recommended:** retire it. It breaks "colour means asset type". Hero artwork
  keeps its own colours; the motion system stays out of them.
- **Decision:** _pending_
- **Status:** open

## D6 · Header logo

- **Today:** Krackle A mark, monochrome (black in light, white in dark), from
  `gui/brand/atelier-mark.svg` via `scripts/brand_mark.py`.
- **Bible:** the mark never changes colour; the wordmark follows the theme.
- **Recommended:** full-colour mark, wordmark in Paper (dark) or Ink (light).
- **Decision:** _pending_
- **Status:** open

## D7 · Interruption

- **Today (`gui/motion/README.md`):** "An animation is never entitled to finish
  its performance. A real result replaces whatever is playing at once."
- **New rule (tested and agreed in the prototype):** status text and controls
  still update immediately. The glyph lets the piece already in flight land
  (≤ 640 ms), then moves to the new state. Cutting a move off mid-flight is
  what produced the visible pop Thiago rejected.
- **Recommended:** adopt the new rule and rewrite that README paragraph.
- **Decision:** _pending_
- **Status:** open
