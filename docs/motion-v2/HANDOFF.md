# Handoff: Atelier motion system v2

**Owner:** Thiago (design, every taste call) · **Builder:** Claude Code ·
**Repo:** `clownfetus/Atelier`, planned against `main` at `eaf4ec8` (7 Nov 2026)

## What this is

Atelier's animation language, Krackle (ink, bubbles, starbursts, splats), is
being replaced by a new identity: three opaque pieces (a blue texture tile, a
teal mesh block and a copper material disc) that physically come apart and try
to fit together while work runs, click into an A when a build succeeds, balance
into an exclamation mark on a warning, and cross into an X on failure.

The new system is fully designed and prototyped. Your job is to build it into
the app, swap every Krackle surface over, then delete Krackle.

## Read in this order

1. `SPEC.md`: the numbers and the ten invariants. Non-negotiable.
2. `reference/motion-prototype.html`: open it in a browser. This is the
   approved behaviour. When in doubt, match it.
3. `reference/PROTOTYPE_NOTES.md`: how the prototype's code maps onto modules,
   and what must change on the way in.
4. `DECISIONS.md`: the calls the bible and the app disagree on, or that Phase 0
   turned up. Phase 0 is getting them answered.
5. `SURFACE_MAP.md`: every Krackle surface, where it's mounted, what it becomes.
6. `../brand/Atelier_Brand_Bible_v1.2.pdf`: the visual identity, for context.
   Pages 9 and 10 cover motion.

The repo's own `docs/DESIGN_SYSTEM.md`, `docs/DEVELOPMENT.md` and
`gui/motion/README.md` describe the current system and how to run things.

## Working agreement

- **Branch:** `motion-v2` from `main`. Make one commit per task below, with a
  message that names the task id (for example `P2.3 tiers from host height`).
  Don't push, open PRs or merge unless Thiago asks.
- **Never touch:** the asset pipeline, project or sidecar formats, native tools,
  server routes, mod container formats, or how artwork and 3D models render.
  This is a presentation-layer change.
- **Keep the app working at every commit.** Krackle and the new glyph never
  appear on screen together in a commit you'd hand over. Hence the alias in
  Phase 3.
- **Stop and ask Thiago at every ⏸ checkpoint.** These are his taste calls; don't
  guess them. Show, don't describe: screenshots, a short screen recording, or
  the Settings preview.
- **Code style:** match the repo. Vanilla JS, classic scripts as IIFEs attaching
  to `window.AtelierMotion` (as `gui/motion/*.js` do), no build step, no new
  dependencies, CSS in its own file next to the script.
- **Copy:** British English. Status messages say what happened, to which asset,
  and what to do next: "Build complete. 3 assets exported." / "Mesh could not
  be read. Check hero_body.fbx exists and isn't locked." No exclamation marks,
  no emoji, no "Oops".

---

## Phase 0 · Decisions

- [x] **P0.1** Create branch `motion-v2`. Commit this pack as it is
  (`docs/motion-v2/`, `docs/brand/`, `CLAUDE.md`).
- [x] **P0.2** ⏸ Walk Thiago through `DECISIONS.md`. Record each answer and set its
  status to `confirmed`. Update `SPEC.md` wherever an answer differs from the
  recommendation.

**Gate:** every decision confirmed. Nothing in Phase 1 starts before this.

## Phase 1 · Foundations

- [ ] **P1.1 Type (D1).** Vendor Inter and Inter Display under
  `gui/vendor/inter/` (woff2, `OFL.txt`, a README matching
  `gui/vendor/instrument-sans/`), add them to `gui/vendor/THIRD_PARTY_NOTICES.md`,
  and update the `@font-face` rules and type tokens in `gui/tokens.css`. Only
  uppercase labels get letter-spacing (+9%). Remove Bricolage if D1 says so.
- [ ] **P1.2 Colour tokens (D2).** Add the roles in SPEC §2 to `tokens.css` as
  semantic tokens (`--atelier-texture`, `--atelier-mesh`, `--atelier-material`,
  `--status-complete`, `--status-warning`, `--status-error`, `--status-working`,
  plus the neutrals). Set `--studio-icon-texture`, `--studio-icon-mesh`,
  `--studio-icon-material` and the matching `EMBLEM_INKS` per SPEC §2. Every other
  category goes neutral per D2. Delete `--studio-texture`, `--studio-mesh` and
  `--studio-vfx`, and rewrite `tests/category_icon_checks.py:100` and
  `tests/surfaces_checks.py:152`. Keep the existing semantic error roles.
  Replace the folder artwork with `assets/emblems/` and apply the name rules in
  SPEC §3.5 (D9). Move the generator to `scripts/`, because P4.1 deletes
  `scripts/krackle_art.py`. It imports the mark, so port `assets/brand_mark_v2.py`
  to `scripts/brand_mark.py` in the same commit. Port the hue-holding colour fit from
  `AtelierKrackleInks.fit`, and update the tests that assert the old emblem markup
  or the dropped categories (`category_icon_checks.py`, `surfaces_checks.py`,
  `library_pins_checks.py`).
- [ ] **P1.3 Themes (D3).** In `gui/tokens.css` and `gui/theme.js`: apply the
  Atelier preset values in SPEC §2; the three piece colours are exempt from
  theming; expose the current surface colour for the halo; fit status hues for
  contrast while keeping hue. Move the warning lines at `gui/viewport.css:123` and
  `:243` to the warning colour. Atelier's accent is neutral, so where accent text
  is the only cue, add an underline or heavier weight. Point the `.at-identity` roles
  at the themed tokens and delete its pigments, per D13.
- [ ] **P1.4 Brand assets.** Replace `gui/brand/atelier-mark.svg/.png` with
  `docs/motion-v2/assets/atelier-mark.svg`; add `atelier-mark-small.svg` and the
  two wordmarks. Use these, not the drawing on bible v1.2 p.3 and p.4 (D14).
  `scripts/brand_mark.py` already holds the generator (P1.2). Regenerate `icon.png` and `icon.ico`, using the small mark for 16, 24 and
  32 px and the master for 48 px and up, on a Charcoal rounded square (bible
  p.12). Regenerate installer art through `scripts/installer_art.py`.
- [ ] **P1.5 Header logo (D6).** Full-colour mark and outlined wordmark, spaced as in
  D6, with the letters in the theme's text colour. Remove the monochrome filter from
  the header and the startup splash, and give the Library hero signature its own
  token. Check the header still fits at the 1100 px breakpoint. Replace the start
  page's lockup with the bible's, without RIVALS or the ink tagline, and update the
  tests that assert the old logo (`appearance_checks.py`, `logo_motion_checks.py`,
  `desktop_smoke.py`, `frozen_smoke.py`).
- [ ] **P1.6 Docs.** Update the colour, type and brand sections of
  `docs/DESIGN_SYSTEM.md`.
- [ ] **P1.7** ⏸ Screenshots of the library, an editor, Settings, the header, the
  project workspace, the Edit All import dialog, a project dialog, the mod-open dialog
  and the first-run setup page, in all six presets (Atelier, Darcula, Repak X, High contrast, Blueprint and
  Comic), light and dark, to Thiago. Include a hero with artwork tints in the
  Library and the viewer (D5).

**Gate:** library, editors and Settings read correctly in every preset, and the
existing contrast checks pass.

## Phase 2 · Engine

- [ ] **P2.1 Modules.** Port the prototype into `gui/motion/assembly/`:
  `pieces.js`, `planner.js`, `engine.js`, `glyph.js` (plus `assembly.css`).
  Follow `reference/PROTOTYPE_NOTES.md`: one engine per glyph, one shared rAF
  clock, cached paths, no globals. The tile and mesh outlines come from
  `assets/atelier-mark-pieces.json` (SPEC §3.2), generated with the mark. Include the
  opening and the three loaders (SPEC §4.1, §4.7).
- [ ] **P2.2 API.**
  `AtelierMotion.glyph.mount(host, {state, asset?, size?, reducedMotion?, surface?})` →
  `{set(state, {asset?}), replay(), destroy(), state}`. States: `busy`, `info`,
  `success`, `warning`, `error`. `asset` is `mesh`, `texture` or `material`, only
  with `busy`, and only when the surface truly knows it (SPEC §7, D16). Throw on a
  non-element host, exactly as `krackleGlyph.mount` does today. Set `aria-hidden` on the
  SVG; the status text next to it carries meaning. A glyph freshly mounted in `busy`
  starts in the row or a fit, and never shows an A first (SPEC §4.1).
- [ ] **P2.3 Tiers.** Pick Stage, Inline or Micro from the host's rendered
  height (`ResizeObserver`), per SPEC §5.
- [ ] **P2.4 Policy.** Read `AtelierMotionPolicy` (`gui/preferences.js:31`) for
  Full, Calm and Off, and honour OS reduced motion. Stop drawing when a glyph is
  off screen (`IntersectionObserver`), hidden (`document.hidden`) or settled: a
  settled glyph schedules no animation frames at all. A change to the Motion setting
  or to OS reduced motion takes effect on a running animation: the piece in flight
  lands (at most 640 ms), then the glyph follows the new setting. Test this.
- [ ] **P2.5 Precompute.** Plan the two Head and Ramp moves, the assemblies to and from
  Bench and the routes into the three outcomes in `requestIdleCallback` after start-up;
  plan live only for unusual starting poses. The opening needs no plan. A live plan took
  up to 146 ms in the prototype, on the main thread, so it needs a time budget.
- [ ] **P2.6 Sound.** The success click (SPEC §6) in `gui/motion/foley.js`.
  Rename the setting "Motion sounds"; keep its storage key.
- [ ] **P2.7 Preview.** Add "Preview motion" to Settings, replacing Try Krackle
  (`motion-preview.js`) if it's still there: five state buttons and the three loaders, driving glyphs at 16, 48
  and 128 px side by side, on the production engine.
- [ ] **P2.8** ⏸ Design the parts that aren't in the prototype: the Inline and Micro
  tiers, the per-shape framing at small sizes (SPEC §5), the logo entrance at 32 px
  (SPEC §4.8), and Calm mode, loaders included. Thiago also signs off the row's size and
  spacing (D4, D16), which the prototype has. Check every state and loader at 24 and 32
  px, and on light backgrounds, where the material's light may soften the disc's edge.
  Show them in the preview, then get Thiago's sign-off.
- [ ] **P2.9 Tests.**
  - `tests/assembly_planner_checks.py`, ported from `reference/checks/planner_check.py`
    and run against the preview. It fails if fully-clear moves drop below the
    prototype baseline.
  - `tests/assembly_clearance_checks.py`, ported from
    `reference/checks/clearance_check.py`: resting gaps on the drawn outlines stay at
    their minimums (every wrong fit and the row at least 14u), and no piece overlaps
    another while Working or a loader runs, after the opening.
  - `tests/assembly_state_checks.py`: success never fires without a
    `succeeded` result; a result arriving mid-move, or during a loader, lands within
    640 ms; only `busy` loops; busy after busy carries on; layer order never changes;
    text updates before the glyph settles; the A returns to category colours after
    success, except at Micro; a settled glyph schedules no frames; the logo entrance
    runs once, in Full only, and never turns green or clicks; a glyph mounted in `busy`
    never shows an A; a loader only runs when a surface names its asset type, and hands
    over only on a real event.
  - A `--glyph-only` flag in `tests/browser_smoke.py`. (`--assembly-only` already
    belongs to the Assembly workspace.)

**Gate:** Preview motion runs all five states and the loaders at all three sizes; film strips
(`reference/checks/state_film.py`) match the prototype; 30 Micro glyphs cost
under 2 ms of script per frame in WebView2; a live plan never blocks the main thread
for over 50 ms; settled glyphs cost nothing per frame.

## Phase 3 · Swap surfaces

- [ ] **P3.1 Alias.** Point `AtelierMotion.krackleGlyph.mount` at
  `AtelierMotion.glyph.mount`. Same states, same handle shape, so every caller
  listed in `SURFACE_MAP.md` row 8 switches with no change. Cover
  `AtelierKrackleGlyph.toastIcon` too (`gui/app.js:149`, `:201`), which doesn't go
  through that mount.
- [ ] **P3.2 to P3.11.** One surface per task and commit, in this order:
  export review (P3.2), first-run setup (P3.3), viewport loader (P3.4),
  material save (P3.5), Edit All import (P3.6), export button and notifications
  (P3.7), header logo entrance (P3.8), empty states (P3.9), spinners and
  progress bars (P3.10), Settings preview wiring (P3.11). Follow
  `SURFACE_MAP.md` for each.
- [ ] **P3.12 Retire.** Stop mounting the six retired surfaces (working panels,
  workflow gestures, ink transfers, halftone reconstruction, folder flap,
  contextual pigments). Swap in the replacements from the map. Leave the files
  in place for now.
- [ ] **P3.12b Surfaces from D10 and D17.** One commit each: model appearance loading,
  setup-status check, Showcase backdrop, thumbnail loading, cards being edited, deleting
  a row, startup stage, index failure, first-export moment, theme change, toast captions,
  toast repeat count, selection count, texture drop target and dot lattice. Follow
  `SURFACE_MAP.md`. Don't change how materials or models render.
- [ ] **P3.13 Interruption (D7).** Update the surfaces that replaced animations
  instantly on a result, so the move in flight lands first and the text
  updates immediately.
- [ ] **P3.14** ⏸ Recording of a full walk-through to Thiago: launch with indexing,
  first-run setup, change the theme, open a hero, edit a material and save, export with success, with warnings and
  with failure, cancel a job, and an empty folder.

**Gate:** no visible Krackle anywhere in the running app. Confirm by
walk-through and by a smoke-run DOM check that no Krackle class or element is
ever created.

## Phase 4 · Remove Krackle

- [ ] **P4.1** Delete the Krackle files in `gui/motion/` (everything not used
  by the new system), their `<script>` and `<link>` lines in `gui/index.html`,
  `scripts/krackle_art.py`, and the folder-flap SVG in `index.html`.
- [ ] **P4.2** Delete or rewrite the 15 Krackle test files
  (`context_ink_checks.py`, `empty_assets_motion_checks.py`,
  `export_motion_checks.py`, `folder_motion_checks.py`, `ink_flow_checks.py`,
  `ink_well_checks.py`, `inks_dial_checks.py`, `krackle_inks_checks.js`,
  `krackle_motion_checks.py`, `logo_motion_checks.py`,
  `material_save_motion_checks.py`, `test_krackle_inks.py`,
  `viewport_motion_checks.py`, `workflow_motion_checks.py`,
  `working_panels_checks.py`) and their `browser_smoke.py` flags. Clear the Krackle
  references in `category_icon_checks.py`, `fluid_work_checks.py`, `frozen_smoke.py`,
  `library_pins_checks.py`, `polish_checks.py`, `showcase_checks.py`,
  `surfaces_checks.py` and `trust_checks.py` as well.
- [ ] **P4.3** Remove the alias; rename callers to `AtelierMotion.glyph.mount`.
  Rename `data-krackle-surface` to `data-glyph-surface`, `data-krackle`
  (`gui/preferences.js:15` and the CSS) and the `--krackle-*` tokens.
- [ ] **P4.4** Rewrite `gui/motion/README.md` for the new system, including the
  D7 interruption rule. Update `docs/DESIGN_SYSTEM.md`, the Krackle notes in
  `docs/DEVELOPMENT.md`, and `docs/WORKSPACE_PLAN.md`. Clear `README.md:77`,
  `images/README.md`, `packaging/Atelier.iss:72` and `CLAUDE.md`. Remove
  `images/krackle-examples.png` and its entry in `images/screenshots.json`, and capture
  its replacement in P5.2.

**Gate (D11):** these both return nothing, because history stays as it was written;
every suite passes on Windows (WebView2) and the Linux AppImage.

```sh
git grep -il krackle -- . ':!CHANGELOG.md' ':!docs/release-*' ':!docs/discord-*' ':!docs/announcements' ':!docs/*-verification-*.json' ':!docs/*checkpoint*' ':!docs/review' ':!docs/motion-v2'
git ls-files | grep -i krackle | grep -vE '^(docs/review|docs/motion-v2)/'
```

## Phase 5 · Release

- [ ] **P5.1** ⏸ Thiago's timing pass on the real app. Tune only the durations
  and easing in one place (`pieces.js` or `easing.js`); don't touch the invariants.
- [ ] **P5.2** Release screenshots (`scripts/release_screenshots.py`; any change to
  `gui/` makes line 31 reject `images/screenshots.json` until they're recaptured), README
  "What's new", a `CHANGELOG.md` *Unreleased* entry, `docs/release-<version>.md`
  and a Discord draft in the style of `docs/discord-1.1.3.md`. Include one line
  on the category colour change.
- [ ] **P5.3** ⏸ Thiago approves the notes and the version number. Follow
  `docs/automatic-releases.md`. Don't publish anything yourself.

## Definition of done

- Every surface in `SURFACE_MAP.md` is in its new state.
- All ten invariants in SPEC §1 hold, with tests covering 2, 5, 6, 7 and 9.
- No Krackle code, assets, tests or docs remain outside history (D11).
- The Full, Calm, Off and OS reduced-motion settings each behave per SPEC §5.
- Thiago has signed off P1.7, P2.8, P3.14 and P5.1.
